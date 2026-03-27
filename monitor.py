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
    
    # 1. Complianz eklentisinin kendi 'Tümünü Kabul Et' sınıfı
    try:
        btn = page.locator('.cmplz-accept').first
        if btn.is_visible(timeout=2000):
            btn.click(force=True)
            log("Complianz 'Tümünü Kabul Et' (.cmplz-accept) butonuna basıldı.")
            page.wait_for_timeout(2000)
            return True
    except Exception:
        pass

    # 2. İçinde 'Accept' geçen ama 'necessary' GEÇMEYEN genel arama
    buttons = page.locator("button, .cookie-btn, a.cc-allow")
    for i in range(buttons.count()):
        try:
            btn = buttons.nth(i)
            text = btn.inner_text().strip().lower()
            
            if ("accept" in text or "allow" in text) and "necessary" not in text:
                if btn.is_visible():
                    btn.click(force=True)
                    log(f"Genel Cookie Butonu ('{text}') basıldı.")
                    page.wait_for_timeout(2000)
                    return True
        except Exception:
            pass

    log("Cookie popup bulunamadı.")
    return False

def html5_email_valid(page):
    email_input = page.locator('input[type="email"]').first
    return email_input.evaluate("(el) => el.checkValidity()")

def get_actual_response_message(page) -> str:
    try:
        response_locator = page.locator('.wpcf7-response-output')
        if response_locator.count() > 0 and response_locator.first.is_visible():
            return response_locator.first.inner_text().strip()
    except Exception as e:
        log(f"Mesaj okunurken hata: {e}")

    return "Ekranda herhangi bir geri dönüş mesajı tespit edilemedi."

def build_email_html(result: dict) -> str:
    details_html = "".join(f"<li>{item}</li>" for item in result["details"])

    return f"""
    <html>
      <body>
        <h2>MobiVisor Submit Monitor Sonucu</h2>
        <p><b>Zaman:</b> {result["timestamp"]}</p>
        <p><b>Son Durum:</b> {result["status"]}</p>

        <h3>Kontroller</h3>
        <ul>
          <li><b>Cookie accepted:</b> {result["cookie_accepted"]}</li>
          <li><b>Email valid:</b> {result["email_valid"]}</li>
        </ul>

        <h3>Detaylar (Her Deneme Sonucu)</h3>
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
        # xvfb ile çalışırken bot olduğumuzu belli etmemek için gerçekçi User-Agent ekliyoruz
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080}
        )
        page = context.new_page()

        try:
            log("Site açılıyor...")
            page.goto(URL, timeout=60000)
            page.wait_for_load_state("domcontentloaded")
            page.wait_for_timeout(2000)

            # COOKIE ONAYI
            result["cookie_accepted"] = accept_cookies_if_present(page)

            # ---------------------------------------------------------
            # EN KRİTİK NOKTA: Çerez onayından sonra SİTEYİ YENİLE
            # ---------------------------------------------------------
            if result["cookie_accepted"]:
                log("Cookie onaylandı! Spam tokenlarının yenilenmesi için sayfa TEKRAR YÜKLENİYOR...")
                page.reload(wait_until="domcontentloaded")
                page.wait_for_timeout(3000) # Yenilenme sonrası bekleme

            # Formu bulabilmek için kaydır
            page.mouse.wheel(0, 1500)
            page.wait_for_timeout(1000)

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
            if not result["email_valid"]:
                result["status"] = "invalid_email"
                result["details"].append("❌ Email geçersiz.")
                return result

            log("Form gönderme döngüsü başlıyor...")

            final_message = "Hiçbir mesaj alınamadı."
            max_attempts = 5 # Sayfa yenilendiği için 5 deneme bile çok fazla, ilkinde geçmeli

            for i in range(max_attempts):
                log(f"{i+1}. kez butona basılıyor...")
                
                submit_button.click(force=True)
                page.wait_for_timeout(4000) # AJAX'ın gitmesi ve yanıtın ekrana basılması için 4 saniye

                actual_message = get_actual_response_message(page)
                log(f"Sitede Yazan Mesaj: {actual_message}")
                
                result["details"].append(f"<b>Deneme {i+1}:</b> {actual_message}")

                # Başarı kontrolü
                if "Thank you" in actual_message or "successfully" in actual_message or "has been sent" in actual_message:
                    final_message = "SUCCESS: " + actual_message
                    log("✅ Form başarıyla gönderildi!")
                    break
                
                # Hata durumu
                elif "spam" in actual_message or "cookie" in actual_message:
                    log("Spam/Cookie hatası alındı. Formun resetlenmesi bekleniyor...")
                    page.wait_for_timeout(1500)
                    final_message = "ERROR: " + actual_message
                else:
                    final_message = "UNKNOWN: " + actual_message

            # SONUÇ
            result["status"] = final_message
            return result

        except Exception as e:
            result["status"] = "exception"
            result["details"].append(f"❌ HATA: {e}")
            log(f"❌ HATA: {e}")
            return result

        finally:
            context.close()
            browser.close()

def main():
    log("DEBUG: GITHUB MONITOR SURUMU CALISIYOR (Sayfa Yenilemeli Kesin Çözüm)")

    result = run_test(
        name_value="Test User",
        email_value="test@example.com",
        message_value=f"Automated check - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )

    log(f"DEBUG RESULT: {result['status']}")

    short_status = (result['status'][:40] + '...') if len(result['status']) > 40 else result['status']
    subject = f"MobiVisor Submit: {short_status}"
    
    html = build_email_html(result)
    send_email(subject, html)

if __name__ == "__main__":
    main()