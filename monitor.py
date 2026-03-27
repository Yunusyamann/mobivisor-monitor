import os
from datetime import datetime
from playwright.sync_api import sync_playwright
import requests

URL = "https://www.mobivisor.de/en/"

RESEND_API_KEY = os.getenv("RESEND_API_KEY")
MAIL_FROM = os.getenv("MAIL_FROM")
MAIL_TO = os.getenv("MAIL_TO")

# "true" ise form submit edilir, değilse sadece health-check yapılır
SUBMIT_FORM = os.getenv("SUBMIT_FORM", "false").lower() == "true"


def log(msg: str):
    print(msg, flush=True)


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


def text_exists(page, text: str, timeout=4000) -> bool:
    try:
        page.get_by_text(text, exact=False).first.wait_for(state="visible", timeout=timeout)
        return True
    except Exception:
        return False


def accept_cookies(page) -> bool:
    buttons = page.locator("button")
    count = buttons.count()

    for i in range(count):
        try:
            btn = buttons.nth(i)
            text = btn.inner_text().strip()

            if ("Accept" in text or "accept" in text) and btn.is_visible():
                btn.click()
                page.wait_for_timeout(1500)
                return True
        except Exception:
            pass

    return False


def safe_is_visible(locator) -> bool:
    try:
        return locator.is_visible()
    except Exception:
        return False


def safe_fill(locator, value: str) -> bool:
    try:
        locator.fill(value)
        return True
    except Exception:
        return False


def html5_email_valid(page) -> bool:
    try:
        email_input = page.locator('input[type="email"]').first
        return email_input.evaluate("(el) => el.checkValidity()")
    except Exception:
        return False


def detect_submit_result(page) -> str:
    # Önce belirgin hata durumları
    if text_exists(page, "Please enter an email address."):
        return "invalid_email"

    if text_exists(page, "You need to accept cookies before send form message."):
        return "cookie_error"

    if text_exists(page, "Submission was referred to as spam"):
        return "spam_error"

    if text_exists(page, "There was an error sending your message"):
        return "general_error"

    # Başarı durumları
    if (
        text_exists(page, "Thank you")
        or text_exists(page, "Your message has been sent")
        or text_exists(page, "successfully")
    ):
        return "success"

    return "unknown_after_submit"


def run():
    result = {
        "status": "unknown",
        "details": [],
        "cookie_accepted": False,
        "name_visible": False,
        "email_visible": False,
        "message_visible": False,
        "send_visible": False,
        "fill_name_ok": False,
        "fill_email_ok": False,
        "fill_message_ok": False,
        "email_valid": False,
        "submit_performed": False,
        "submit_result": "not_attempted",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        try:
            log("DEBUG: MONITOR CALISIYOR")
            page.goto(URL, timeout=60000)
            page.wait_for_load_state("domcontentloaded")
            page.wait_for_timeout(3000)

            page.mouse.wheel(0, 2500)
            page.wait_for_timeout(1000)

            result["cookie_accepted"] = accept_cookies(page)
            page.wait_for_timeout(1000)

            name_input = page.locator('input[type="text"]').first
            email_input = page.locator('input[type="email"]').first
            message_input = page.locator("textarea").first
            send_button = page.get_by_role("button", name="Send").first

            result["name_visible"] = safe_is_visible(name_input)
            result["email_visible"] = safe_is_visible(email_input)
            result["message_visible"] = safe_is_visible(message_input)
            result["send_visible"] = safe_is_visible(send_button)

            if not result["name_visible"]:
                result["details"].append("Name input görünmüyor.")
            if not result["email_visible"]:
                result["details"].append("Email input görünmüyor.")
            if not result["message_visible"]:
                result["details"].append("Message textarea görünmüyor.")
            if not result["send_visible"]:
                result["details"].append("Send butonu görünmüyor.")

            if not (
                result["name_visible"]
                and result["email_visible"]
                and result["message_visible"]
                and result["send_visible"]
            ):
                result["status"] = "form_missing"
                return result

            result["fill_name_ok"] = safe_fill(name_input, "Monitor Bot")
            result["fill_email_ok"] = safe_fill(email_input, "test@example.com")
            result["fill_message_ok"] = safe_fill(
                message_input,
                f"Form health check - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )

            if not result["fill_name_ok"]:
                result["details"].append("Name alanına yazılamadı.")
            if not result["fill_email_ok"]:
                result["details"].append("Email alanına yazılamadı.")
            if not result["fill_message_ok"]:
                result["details"].append("Message alanına yazılamadı.")

            result["email_valid"] = html5_email_valid(page)
            if not result["email_valid"]:
                result["details"].append("Email HTML5 validation'dan geçmedi.")

            if not (
                result["fill_name_ok"]
                and result["fill_email_ok"]
                and result["fill_message_ok"]
                and result["email_valid"]
            ):
                result["status"] = "form_fill_problem"
                return result

            # Buraya kadar health-check başarılı
            result["status"] = "healthy"
            result["details"].append("Form alanları bulundu ve başarıyla dolduruldu.")

            # İstenirse gerçek submit yapılır
            if SUBMIT_FORM:
                result["submit_performed"] = True
                result["details"].append("Submit testi başlatıldı.")

                send_button.click()
                page.wait_for_timeout(6000)

                submit_result = detect_submit_result(page)
                result["submit_result"] = submit_result

                if submit_result == "success":
                    result["details"].append("Form başarıyla gönderildi.")
                    result["status"] = "submit_success"
                elif submit_result == "invalid_email":
                    result["details"].append("Form gönderilemedi: email geçersiz.")
                    result["status"] = "submit_failed"
                elif submit_result == "cookie_error":
                    result["details"].append("Form gönderilemedi: cookie hatası.")
                    result["status"] = "submit_failed"
                elif submit_result == "spam_error":
                    result["details"].append("Form gönderilemedi: spam filtresine takıldı.")
                    result["status"] = "submit_failed"
                elif submit_result == "general_error":
                    result["details"].append("Form gönderilemedi: genel hata mesajı döndü.")
                    result["status"] = "submit_failed"
                else:
                    result["details"].append("Form submit edildi ancak sonuç net tespit edilemedi.")
                    result["status"] = "submit_unknown"

            return result

        except Exception as e:
            result["status"] = "down"
            result["details"].append(f"{type(e).__name__}: {e}")
            return result

        finally:
            browser.close()


def build_email_html(result: dict) -> str:
    details_html = "".join(f"<li>{detail}</li>" for detail in result["details"])

    return f"""
    <html>
      <body>
        <h2>MobiVisor Form Monitor Sonucu</h2>
        <p><b>Zaman:</b> {result["timestamp"]}</p>
        <p><b>Durum:</b> {result["status"]}</p>
        <p><b>Submit yapıldı mı:</b> {result["submit_performed"]}</p>
        <p><b>Submit sonucu:</b> {result["submit_result"]}</p>

        <h3>Kontroller</h3>
        <ul>
          <li><b>Cookie accepted:</b> {result["cookie_accepted"]}</li>
          <li><b>Name visible:</b> {result["name_visible"]}</li>
          <li><b>Email visible:</b> {result["email_visible"]}</li>
          <li><b>Message visible:</b> {result["message_visible"]}</li>
          <li><b>Send visible:</b> {result["send_visible"]}</li>
          <li><b>Fill name ok:</b> {result["fill_name_ok"]}</li>
          <li><b>Fill email ok:</b> {result["fill_email_ok"]}</li>
          <li><b>Fill message ok:</b> {result["fill_message_ok"]}</li>
          <li><b>Email valid:</b> {result["email_valid"]}</li>
        </ul>

        <h3>Detaylar</h3>
        <ul>
          {details_html}
        </ul>
      </body>
    </html>
    """


def main():
    log("DEBUG: YENI MONITOR SURUMU CALISIYOR")
    log(f"DEBUG: SUBMIT_FORM={SUBMIT_FORM}")

    result = run()

    log(f"DEBUG RESULT: {result['status']}")
    log(str(result))

    subject = f"Monitor sonucu: {result['status']}"
    html = build_email_html(result)

    send_email(subject, html)


if __name__ == "__main__":
    main()