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


# Timeout süresi manuel kodundaki gibi 2000 yapıldı
def text_exists(page, text: str, timeout=2000) -> bool:
    try:
        page.get_by_text(text, exact=False).first.wait_for(state="visible", timeout=timeout)
        return True
    except Exception:
        return False


# Cookie fonksiyonu başarılı olan manuel kodunla birebir aynı yapıldı
def accept_cookies_if_present(page) -> bool:
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


def html5_email_valid(page) -> bool:
    email_input = page.locator('input[type="email"]').first
    return email_input.evaluate("(el) => el.checkValidity()")


def evaluate_result(page) -> str:
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
        # Sunucuda (GitHub vb.) çalıştığı için headless=True
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        try:
            log("Site açılıyor...")
            page.goto(URL, timeout=60000)
            page.wait_for_load_state("domcontentloaded")
            page.wait_for_timeout(2000)

            # COOKIE (Manuel koddaki gibi tekerleği biraz kaydırıyoruz)
            page.mouse.wheel(0, 2500)
            result["cookie_accepted"] = accept_cookies_if_present(page)

            # Formu bulabilmek için sayfayı aşağı kaydır
            page.mouse.wheel(0, 1500)

            # FORM ELEMANLARINI BUL
            name_input = page.locator('input[type="text"]').first
            email_input = page.locator('input[type="email"]').first
            message_input = page.locator('textarea').first
            submit_button = page.get_by_role("button", name="Send").first

            if not name_input.is_visible():
                result["status"] = "form_missing"
                result["details"].append("Name alanı görünmüyor.")
                return result

            if not email_input.is_visible():
                result["status"] = "form_missing"
                result["details"].append("Email alanı görünmüyor.")
                return result

            if not message_input.is_visible():
                result["status"] = "form_missing"
                result["details"].append("Message alanı görünmüyor.")
                return result

            if not submit_button.is_visible():
                result["status"] = "form_missing"
                result["details"].append("Send butonu görünmüyor.")
                return result

            log("Form dolduruluyor...")
            name_input.fill(name_value)
            email_input.fill(email_value)
            message_input.fill(message_value)

            result["email_valid"] = html5_email_valid(page)
            log(f"Email validity: {result['email_valid']}")

            if not result["email_valid"]:
                result["status"] = "invalid_email"
                result["details"].append("Email HTML5 validation'dan geçmedi.")
                return result

            log("Form gönderme döngüsü başlıyor...")

            # ASIL İSTEDİĞİN DÖNGÜ KISMI (Manuel koda göre birebir uyarlandı)
            submit_result = "unknown"

            for i in range(3):
                log(f"{i+1}. tıklama yapılıyor...")
                submit_button.click()
                page.wait_for_timeout(2000)  # Tam 2 saniye bekle

                current_result = evaluate_result(page)
                log(f"Sonuç: {current_result}")

                # başarılıysa dur
                if current_result == "success":
                    submit_result = current_result
                    break
                
                submit_result = current_result
                if i < 2:
                    result["details"].append(f"Deneme {i + 1}: {current_result} alındı, tekrar deneniyor.")

            # SONUÇLARI KAYDET
            result["status"] = submit_result
            result["details"].append(f"Submit son durum: {submit_result}")

            if submit_result == "success":
                result["details"].append("Form başarıyla gönderildi.")
                log("✅ TEST PASS")
            elif submit_result in ["spam_error", "cookie_error"]:
                result["details"].append(f"Form gönderilemedi: 3 deneme sonucunda {submit_result} aşılamadı.")
                log(f"❌ {submit_result}")
            elif submit_result == "general_error":
                result["details"].append("Form gönderilemedi: genel hata alındı.")
                log("❌ Genel hata alındı")
            elif submit_result == "unknown":
                result["details"].append("Submit yapıldı ancak sonuç net belirlenemedi.")
                log("⚠️ Belirsiz durum")

            return result

        except Exception as e:
            result["status"] = "exception"
            result["details"].append(f"{type(e).__name__}: {e}")
            log(f"❌ HATA: {e}")
            return result

        finally:
            browser.close()


def main():
    log("DEBUG: GITHUB MONITOR SURUMU CALISIYOR")

    result = run_test(
        name_value="Test User",
        email_value="test@example.com",
        message_value=f"Automated check - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
    )

    log(f"DEBUG RESULT: {result['status']}")
    log(str(result))

    subject = f"MobiVisor submit sonucu: {result['status']}"
    html = build_email_html(result)
    send_email(subject, html)


if __name__ == "__main__":
    main()