import os
import time
from datetime import datetime
from playwright.sync_api import sync_playwright
import requests

URL = "https://www.mobivisor.de/en/"

# Ortam değişkenleri (GitHub Secrets'tan gelecek)
RESEND_API_KEY = os.getenv("RESEND_API_KEY")
MAIL_FROM = os.getenv("MAIL_FROM")
MAIL_TO = os.getenv("MAIL_TO")

def log(msg: str):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def send_email(subject: str, html: str):
    if not RESEND_API_KEY or not MAIL_FROM or not MAIL_TO:
        log("E-posta ayarları eksik, e-posta gönderilmeyecek.")
        return

    response = requests.post(
        "https://api.resend.com/emails",
        headers={
            "Authorization": f"Bearer {RESEND_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "from": MAIL_FROM,
            "to": [MAIL_TO],
            "subject": subject,
            "html": html,
        },
        timeout=30,
    )

    log(f"MAIL STATUS CODE: {response.status_code}")
    if response.status_code >= 300:
        log(f"MAIL RESPONSE: {response.text}")

def accept_cookies_if_present(page):
    log("Cookie popup kontrol ediliyor...")
    buttons = page.locator("button")
    for i in range(buttons.count()):
        try:
            btn = buttons.nth(i)
            text = btn.inner_text()
            if "Accept" in text or "accept" in text:
                if btn.is_visible():
                    btn.click()
                    page.wait_for_timeout(1500)
                    log("Cookie kabul edildi.")
                    return True
        except Exception:
            pass

    log("Cookie popup bulunamadı.")
    return False

def html5_email_valid(page):
    email_input = page.locator('input[type="email"]').first
    return email_input.evaluate("(el) => el.checkValidity()")

# --- YENİ EKLENEN FONKSİYON: Gerçek Mesajı Yakalar ---
def get_actual_response_message(page) -> str:
    try:
        # Form mesajlarının çıktığı genel div class'ı (CF7)
        response_locator = page.locator('.wpcf7-response-output')
        
        if response_locator.count() > 0 and response_locator.first.is_visible():
            return response_locator.first.inner_text().strip()
        
        # Eğer yukarıdaki class yoksa, sayfadaki 'alert' veya bildirim rolü taşıyan bir şey arayalım
        alert_locator = page.locator('[role="alert"]')
        if alert_locator.count() > 0 and alert_locator.first.is_visible():
            return alert_locator.first.inner_text().strip()
            
    except Exception as e:
        log(f"Mesaj okunurken hata: {e}")

    return "Ekranda herhangi bir geri dönüş mesajı tespit edilemedi."

def build_email_html(result: dict) -> str:
    details_html = "".join(f"<li>{item}</li>" for item in result["details"])

    return f"""
    <html>
      <body>
        <h2>MobiVisor Submit Monitor Sonucu (Gerçek Mesaj Yakalama)</h2>
        <p><b>Zaman:</b> {result["timestamp"]}</p>
        <p><b>Son Mesaj (Durum):</b> {result["status"]}</p>

        <h3>Kontroller</h3>
        <ul>
          <li><b>Cookie accepted:</b> {result["cookie_accepted"]}</li>
          <li><b>Email valid:</b> {result["email_valid"]}</li>
        </ul>

        <h3>Detaylar (Her Denemede Ekranda Yazan Metin)</h3>
        <ul>
          {details_html}
        </ul>
      </body>
    </html>
    """

def run_test(name_value: str, email_value: str, message_value: str) -> dict:
    result = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": "unknown",
        "cookie_accepted": False,
        "email_valid": False,
        "details": [],
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()

        try:
            log("Site açılıyor...")
            page.goto(URL)
            page.wait_for_load_state("domcontentloaded")
            page.wait_for_timeout(2000)

            page.mouse.wheel(0, 2500)

            # COOKIE
            result["cookie_accepted"] = accept_cookies_if_present(page)

            page.mouse.wheel(0, 1500)

            # FORM ELEMANLARI
            name_input = page.locator('input[type="text"]').first
            email_input = page.locator('input[type="email"]').first
            message_input = page.locator('textarea').first
            submit_button = page.get_by_role("button", name="Send").first

            if not submit_button.is_visible():
                result["status"] = "form_missing"
                result["details"].append("Eksik form elemanı.")
                return result

            log("Form dolduruluyor...")
            name_input.fill(name_value)
            email_input.fill(email_value)
            message_input.fill(message_value)

            result["email_valid"] = html5_email_valid(page)
            log(f"Email validity: {result['email_valid']}")

            if not result["email_valid"]:
                result["status"] = "invalid_email"
                result["details"].append("❌ Email geçersiz, test durduruldu.")
                return result

            log("Form gönderme döngüsü başlıyor...")

            final_message = "Hiçbir mesaj alınamadı."
            max_attempts = 10

            for i in range(max_attempts):
                log(f"{i+1}. tıklama yapılıyor...")
                
                submit_button.click()
                page.wait_for_timeout(1000)  # 1 saniye bekle

                # Sitenin arayüzündeki asıl mesajı okuyoruz
                actual_message = get_actual_response_message(page)
                log(f"Sitede Yazan Mesaj: {actual_message}")
                
                result["details"].append(f"<b>Deneme {i+1}:</b> {actual_message}")

                # Mesaj başarılı içeriyorsa döngüyü kır
                if "Thank you" in actual_message or "successfully" in actual_message or "has been sent" in actual_message:
                    final_message = actual_message
                    log("✅ Başarı mesajı yakalandı, durduruluyor.")
                    break

                final_message = actual_message

            # SONUÇ
            result["status"] = final_message
            result["details"].append(f"<br><b>Submit son durum:</b> {final_message}")

            return result

        except Exception as e:
            result["status"] = "exception"
            result["details"].append(f"❌ HATA: {e}")
            log(f"❌ HATA: {e}")
            return result

        finally:
            browser.close()

def main():
    log("DEBUG: GITHUB MONITOR SURUMU CALISIYOR (Gerçek Mesaj Okuma)")

    result = run_test(
        name_value="Test User",
        email_value="test@example.com",
        message_value=f"Automated check - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )

    log(f"DEBUG RESULT: {result['status']}")

    # E-posta başlığında durum çok uzun olmasın diye ilk 30 karakteri alıyoruz
    short_status = (result['status'][:30] + '...') if len(result['status']) > 30 else result['status']
    subject = f"MobiVisor Submit: {short_status}"
    
    html = build_email_html(result)
    send_email(subject, html)

if __name__ == "__main__":
    main()