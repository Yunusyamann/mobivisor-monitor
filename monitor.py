import os
from datetime import datetime
from playwright.sync_api import sync_playwright
import requests

print("DEBUG: YENI HEALTH-CHECK SURUMU CALISIYOR", flush=True)

URL = "https://www.mobivisor.de/en/"

RESEND_API_KEY = os.getenv("RESEND_API_KEY")
MAIL_FROM = os.getenv("MAIL_FROM")
MAIL_TO = os.getenv("MAIL_TO")

def log(msg):
    print(msg, flush=True)

def send_email(subject, html):
    requests.post(
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

def accept_cookies(page):
    buttons = page.locator("button")
    for i in range(buttons.count()):
        try:
            btn = buttons.nth(i)
            text = btn.inner_text()
            if "Accept" in text or "accept" in text:
                if btn.is_visible():
                    btn.click()
                    page.wait_for_timeout(1500)
                    return True
        except Exception:
            pass
    return False

def run():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()

        try:
            page.goto(URL, timeout=60000)
            page.wait_for_load_state("domcontentloaded")
            page.wait_for_timeout(3000)

            page.mouse.wheel(0, 2500)
            accept_cookies(page)
            page.wait_for_timeout(1000)

            name_input = page.locator('input[type="text"]').first
            email_input = page.locator('input[type="email"]').first
            msg_input = page.locator('textarea').first
            send_button = page.get_by_role("button", name="Send").first

            if not name_input.is_visible():
                return "form_missing"
            if not email_input.is_visible():
                return "form_missing"
            if not msg_input.is_visible():
                return "form_missing"
            if not send_button.is_visible():
                return "form_missing"

            name_input.fill("Monitor Bot")
            email_input.fill("test@example.com")
            msg_input.fill("Form health check")

            return "healthy"

        except Exception as e:
            return f"down: {type(e).__name__}: {e}"

        finally:
            browser.close()

def main():
    result = run()
    print("DEBUG RESULT:", result, flush=True)
    log(result)

    if result != "healthy":
        send_email(
            subject=f"Monitor sonucu: {result}",
            html=f"<b>Durum:</b> {result}<br>{datetime.now()}"
        )

if __name__ == "__main__":
    main()