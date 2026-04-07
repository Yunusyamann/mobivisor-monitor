import os
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
    if response.status_code >= 300:
        log(f"MAIL RESPONSE: {response.text}")

def accept_cookies_if_present(page):
    log("Cookie popup kontrol ediliyor...")
    try:
        # Complianz eklentisinin 'Tümünü Kabul Et' butonu
        btn = page.locator('.cmplz-accept').first
        if btn.is_visible(timeout=3000):
            btn.click(force=True)
            log("Cookie 'Tümünü Kabul Et' butonuna basıldı.")
            page.wait_for_timeout(2000) # JS'in çerezi işlemesi için bekle
            return True
    except Exception:
        pass
    log("Cookie popup bulunamadı veya zaten kabul edilmiş.")
    return False

def get_actual_response_message(page) -> str:
    try:
        response_locator = page.locator('.wpcf7-response-output')
        if response_locator.count() > 0 and response_locator.first.is_visible():
            return response_locator.first.inner_text().strip()
    except Exception:
        pass
    return "Ekranda herhangi bir geri dönüş mesajı tespit edilemedi."

def build_email_html(result: dict) -> str:
    details_html = "".join(f"<li>{item}</li>" for item in result["details"])
    return f"""
    <html>
      <body>
        <h2>MobiVisor Submit Monitor Sonucu (HardyPress JS Simülasyonu)</h2>
        <p><b>Zaman:</b> {result["timestamp"]}</p>
        <p><b>Son Durum:</b> {result["status"]}</p>
        <h3>Kontroller</h3>
        <ul>
          <li><b>Cookie accepted:</b> {result["cookie_accepted"]}</li>
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
        "details": [],
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False) # Xvfb sanal ekranı ile çalışacak
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080}
        )
        page = context.new_page()

        try:
            log("Site açılıyor...")
            page.goto(URL, timeout=60000)
            page.wait_for_load_state("networkidle")
            
            result["cookie_accepted"] = accept_cookies_if_present(page)

            # Ekranda formun olduğu yere kaydır
            page.mouse.wheel(0, 1000)
            page.wait_for_timeout(1000)

            # EKRAN GÖRÜNTÜSÜNDEN ALINAN KESİN ALAN ADLARI
            name_input = page.locator('input[name="your-name"]').first
            email_input = page.locator('input[name="your-email"]').first
            message_input = page.locator('textarea[name="your-message"]').first
            submit_button = page.locator('input[type="submit"], button.wpcf7-submit').first

            if not submit_button.is_visible():
                result["status"] = "form_missing"
                result["details"].append("Eksik form elemanı.")
                return result

            log("Form dolduruluyor...")
            name_input.fill(name_value)
            email_input.fill(email_value)
            message_input.fill(message_value)

            log("Form gönderme döngüsü başlıyor (JavaScript'i uyandırma stratejisi)...")
            final_message = "Hiçbir mesaj alınamadı."
            max_attempts = 5 

            for i in range(max_attempts):
                log(f"{i+1}. kez butona basılıyor...")
                
                # Tıkla ve JavaScript'in yanıt dönmesini bekle
                submit_button.click(force=True)
                page.wait_for_timeout(3500) 

                actual_message = get_actual_response_message(page)
                log(f"Sitede Yazan Mesaj: {actual_message}")
                result["details"].append(f"<b>Deneme {i+1}:</b> {actual_message}")

                if "Thank you" in actual_message or "successfully" in actual_message or "has been sent" in actual_message:
                    final_message = "SUCCESS: " + actual_message
                    log("✅ Form başarıyla gönderildi!")
                    break
                
                # Eğer spam veya cookie derse, form JS'i kendini sıfırlayana kadar bekle ve LÜTFEN TEKRAR TIKLA
                elif "spam" in actual_message or "cookie" in actual_message:
                    log("Spam/Cookie hatası alındı. İkinci tıklama için bekleniyor...")
                    page.wait_for_timeout(2000)
                    final_message = "ERROR: " + actual_message
                else:
                    final_message = "UNKNOWN: " + actual_message
                    page.wait_for_timeout(2000)

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
    log("DEBUG: GITHUB MONITOR SURUMU CALISIYOR (HardyPress JS Simülasyonu)")

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