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


def text_exists(page, text: str, timeout=4000) -> bool:
    try:
        page.get_by_text(text, exact=False).first.wait_for(state="visible", timeout=timeout)
        return True
    except Exception:
        return False


def accept_cookies_if_present(page) -> bool:
    log("Cookie popup kontrol ediliyor...")

    # Öncelikle "Tümünü Kabul Et" tarzı, form eklentilerini tamamen açan butonları arayalım
    primary_texts = ["Accept All", "Accept all", "Allow all", "Allow All Cookies", "Alle akzeptieren", "Tümünü Kabul Et"]
    
    for text in primary_texts:
        try:
            btn = page.get_by_role("button", name=text, exact=False).first
            if btn.is_visible(timeout=1500):
                btn.click()
                page.wait_for_timeout(3000)
                log(f"Cookie '{text}' butonu ile tam olarak kabul edildi.")
                return True
        except Exception:
            pass

    # Bulunamazsa daha genel "accept" veya "akzeptieren" içeren ilk görünür butonu arayalım
    buttons = page.locator("button")
    try:
        count = buttons.count()
        for i in range(count):
            try:
                btn = buttons.nth(i)
                btn_text = btn.inner_text().strip().lower()
                if ("accept" in btn_text or "allow" in btn_text or "akzeptieren" in btn_text) and btn.is_visible():
                    btn.click()
                    page.wait_for_timeout(3000)
                    log(f"Cookie genel aramasıyla ({btn_text}) kabul edildi.")
                    return True
            except Exception:
                continue
    except Exception:
        pass

    log("Cookie popup bulunamadı veya işlem yapılamadı.")
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
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        try:
            log("Site açılıyor...")
            page.goto(URL, timeout=60000)
            page.wait_for_load_state("domcontentloaded")
            page.wait_for_timeout(2000)

            # COOKIE
            result["cookie_accepted"] = accept_cookies_if_present(page)

            # Formu bulabilmek için sayfayı aşağı kaydır
            page.mouse.wheel(0, 3000)
            page.wait_for_timeout(1000)

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

            max_attempts = 3
            submit_result = "unknown"

            for attempt in range(max_attempts):
                log(f"Form gönderiliyor... (Deneme {attempt + 1}/{max_attempts})")
                submit_button.click()
                
                # Sitenin formu işleyip sonucu ekrana basması için bekleme süresi
                page.wait_for_timeout(6000)

                submit_result = evaluate_result(page)
                
                # Hem spam hem de cookie hatalarında tekrar deneme mantığı
                if submit_result in ["spam_error", "cookie_error"]:
                    if attempt < max_attempts - 1:
                        log(f"{submit_result} alındı. 2 saniye beklenip tekrar butona basılacak...")
                        result["details"].append(f"Deneme {attempt + 1}: {submit_result} alındı, tekrar deneniyor.")
                        page.wait_for_timeout(2000)
                        continue
                    else:
                        log("Maksimum deneme sayısına ulaşıldı.")
                
                # Başarılıysa veya artık son denemeyse döngüyü kır
                break

            result["status"] = submit_result
            result["details"].append(f"Submit son durum: {submit_result}")

            if submit_result == "success":
                result["details"].append("Form başarıyla gönderildi.")
            elif submit_result in ["spam_error", "cookie_error"]:
                result["details"].append(f"Form gönderilemedi: {max_attempts} deneme sonucunda {submit_result} aşılamadı.")
            elif submit_result == "general_error":
                result["details"].append("Form gönderilemedi: genel hata alındı.")
            elif submit_result == "unknown":
                result["details"].append("Submit yapıldı ancak sonuç net belirlenemedi.")

            return result

        except Exception as e:
            result["status"] = "exception"
            result["details"].append(f"{type(e).__name__}: {e}")
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