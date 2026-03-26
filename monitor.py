import json
import os
from datetime import datetime
from playwright.sync_api import sync_playwright
import requests

URL = "https://www.mobivisor.de/en/"
STATE_FILE = "state.json"

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
    )

def text_exists(page, text):
    try:
        page.get_by_text(text).first.wait_for(timeout=2000)
        return True
    except:
        return False

def accept_cookies(page):
    buttons = page.locator("button")
    for i in range(buttons.count()):
        try:
            btn = buttons.nth(i)
            if "Accept" in btn.inner_text():
                btn.click()
                page.wait_for_timeout(1500)
                return
        except:
            pass

def evaluate(page):
    if text_exists(page, "spam"):
        return "spam"
    if text_exists(page, "error"):
        return "error"
    if text_exists(page, "Thank"):
        return "success"
    return "unknown"

def run():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()

        page.goto(URL)
        page.wait_for_timeout(3000)

        page.mouse.wheel(0, 2500)
        accept_cookies(page)

        name = page.locator('input[type="text"]').first
        email = page.locator('input[type="email"]').first
        msg = page.locator('textarea').first
        btn = page.get_by_role("button", name="Send").first

        name.fill("Monitor Bot")
        email.fill("test@example.com")
        msg.fill("Automated test")

        # 🔥 3 defa bas
        for _ in range(3):
            btn.click()
            page.wait_for_timeout(2000)

        result = evaluate(page)

        browser.close()
        return result

def main():
    result = run()
    log(result)

    send_email(
        subject=f"Monitor sonucu: {result}",
        html=f"<b>Durum:</b> {result}<br>{datetime.now()}"
    )

if __name__ == "__main__":
    main()
