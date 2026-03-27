import os
import time
from datetime import datetime
from playwright.sync_api import sync_playwright
import requests

URL = "https://www.mobivisor.de/en/"

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
            text = btn.inner_text().strip()
            
            if "Accept" in text or "accept" in text:
                if btn.is_visible():
                    btn.click()
                    log("Cookie 'Accept' butonuna basıldı. Sitenin algılaması bekleniyor...")
                    # Çerezin tarayıcıya işlenmesi için yeterli bekleme süresi
                    page.wait_for_timeout(2500) 
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
        # CF7'nin asıl mesaj kutusu
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
        # xvfb kullandığımız için headless=False
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()

        try:
            log("Site açılıyor...")
            page.goto(URL, timeout=60000)
            page.wait_for_load_state("domcontentloaded")
            page.wait_for_timeout(2000)

            page.mouse.wheel(0, 2500)
            page.wait_for_timeout(1000)

            # COOKIE ONAYI
            result["cookie_accepted"] = accept_cookies_if_present(page)

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
            max_attempts = 5 # 5 deneme fazlasıyla yeterli olacaktır

            for i in range(max_attempts):
                log(f"{i+1}. kez butona basılıyor...")
                
                # Tıklamayı garantiye al
                submit_button.click(force=True)
                
                # ÖNEMLİ: Formun sunucuya gidip yanıt dönmesi (AJAX) için tam 4 saniye bekle.
                # Önceki kodlarda bu süre çok kısa olduğu için form kilitli kalıyordu.
                page.wait_for_timeout(4000) 

                actual_message = get_actual_response_message(page)
                log(f"Sitede Yazan Mesaj: {actual_message}")
                
                result["details"].append(f"<b>Deneme {i+1}:</b> {actual_message}")

                # İkinci görseldeki BAŞARI MESAJI kontrolü
                if "Thank you" in actual_message or "successfully" in actual_message or "has been sent" in actual_message:
                    final_message = "SUCCESS: " + actual_message
                    log("✅ Form başarıyla gönderildi!")
                    break
                
                # Eğer spam hatasıysa (Birinci görsel), formun sıfırlanması için 1 saniye daha bekle ve tekrarla
                elif "spam" in actual_message or "cookie" in actual_message:
                    log("Spam/Cookie hatası alındı (Beklenen durum). Formun resetlenmesi bekleniyor...")
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
            browser.close()

def main():
    log("DEBUG: GITHUB MONITOR SURUMU CALISIYOR (AJAX Beklemeli Tam Çözüm)")

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