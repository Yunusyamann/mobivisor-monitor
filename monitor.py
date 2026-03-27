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

def text_exists(page, text: str, timeout=2000):
    try:
        page.get_by_text(text, exact=False).first.wait_for(state="visible", timeout=timeout)
        return True
    except Exception:
        return False

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

def evaluate_result(page):
    if text_exists(page, "Please enter an email address."):
        return "invalid_email"

    if text_exists(page, "You need to accept cookies before send form message."):
        return "cookie_error"

    if text_exists(page, "Submission was referred to as spam"):
        return "spam_error"

    if text_exists(page, "There was an error sending your message"):
        return "general_error"

    if (
        text_exists(page, "Thank you") or
        text_exists(page, "successfully") or
        text_exists(page, "Your message has been sent")
    ):
        return "success"

    return "unknown"

def build_email_html(result: dict) -> str:
    details_html = "".join(f"<li>{item}</li>" for item in result["details"])

    return f"""
    <html>
      <body>
        <h2>MobiVisor Submit Monitor Sonucu</h2>
        <p><b>Zaman:</b> {result["timestamp"]}</p>
        <p><b>Durum:</b> {result["status"]}</p>

        <h3>Kontroller</h3>
        <ul>
          <li><b>Cookie accepted:</b> {result["cookie_accepted"]}</li>
          <li><b>Email valid:</b> {result["email_valid"]}</li>
        </ul>

        <h3>Detaylar</h3>
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
        # ÖNEMLİ: xvfb kullanılacağı için headless=False bırakıldı
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

            final_result = "unknown"
            max_attempts = 10

            # İSTEDİĞİN 10 KERELİK DÖNGÜ (1 saniye arayla)
            for i in range(max_attempts):
                log(f"{i+1}. tıklama yapılıyor...")
                
                submit_button.click()
                page.wait_for_timeout(1000)  # 1 saniye bekle

                current_result = evaluate_result(page)
                log(f"Sonuç: {current_result}")

                # başarılıysa dur
                if current_result == "success":
                    final_result = current_result
                    break

                final_result = current_result
                if i < max_attempts - 1:
                     result["details"].append(f"Deneme {i + 1}: {current_result} alındı, tekrar deneniyor.")

            # SONUÇ
            result["status"] = final_result
            result["details"].append(f"Submit son durum: {final_result}")

            if final_result == "success":
                result["details"].append("Form başarıyla gönderildi.")
                log("✅ TEST PASS")
            elif final_result == "spam_error":
                result["details"].append("❌ SPAM filtresine takıldı")
                log("❌ SPAM filtresine takıldı")
            elif final_result == "general_error":
                result["details"].append("❌ Genel hata alındı")
                log("❌ Genel hata alındı")
            elif final_result == "cookie_error":
                 result["details"].append("❌ Cookie problemi")
                 log("❌ Cookie problemi")
            else:
                result["details"].append("⚠️ Belirsiz durum")
                log("⚠️ Belirsiz durum")

            return result

        except Exception as e:
            result["status"] = "exception"
            result["details"].append(f"❌ HATA: {e}")
            log(f"❌ HATA: {e}")
            return result

        finally:
            browser.close()

def main():
    log("DEBUG: GITHUB MONITOR SURUMU CALISIYOR (10 Deneme, xvfb uyumlu)")

    result = run_test(
        name_value="Test User",
        email_value="test@example.com",
        message_value=f"Automated check - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )

    log(f"DEBUG RESULT: {result['status']}")

    subject = f"MobiVisor submit sonucu: {result['status']}"
    html = build_email_html(result)
    send_email(subject, html)

if __name__ == "__main__":
    main()