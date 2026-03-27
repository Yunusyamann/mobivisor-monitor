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


def text_exists(page, text: str, timeout=2000) -> bool:
    try:
        page.get_by_text(text, exact=False).first.wait_for(state="visible", timeout=timeout)
        return True
    except Exception:
        return False


def accept_cookies_if_present(page) -> bool:
    log("Cookie popup kontrol ediliyor...")

    # 1. YÖNTEM: Popüler eklentilerin spesifik "Tümünü Kabul Et" buton ID/Class'ları
    known_selectors = [
        "#borlabs-cookie-btn-accept-all",      # Borlabs
        ".borlabs-cookie-btn-accept-all",
        "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll", # Cookiebot
        ".cm-btn-accept-all",                  # Complianz
        "#cookie_action_close_header",         # Cookie Law Info
        "button[data-cookiefirst-action='accept']",
        ".cookie-btn-accept",
        "a.cc-allow"
    ]

    for selector in known_selectors:
        try:
            btn = page.locator(selector).first
            if btn.is_visible(timeout=1000):
                # JS ile tıklayarak engelleri bypass et
                btn.evaluate("node => node.click()")
                page.wait_for_timeout(3000)
                log(f"Cookie CSS seçicisi ({selector}) ile kesin olarak kabul edildi.")
                return True
        except Exception:
            pass

    # 2. YÖNTEM: Kesin metin eşleşmesi
    primary_texts = ["Accept All", "Allow all", "Alle akzeptieren", "Tümünü Kabul Et"]
    for text in primary_texts:
        try:
            btn = page.get_by_text(text, exact=True).first
            if btn.is_visible(timeout=1000):
                btn.evaluate("node => node.click()")
                page.wait_for_timeout(3000)
                log(f"Cookie '{text}' metni ile kabul edildi.")
                return True
        except Exception:
            pass

    # 3. YÖNTEM: Sadece "Necessary" İÇERMEYEN accept butonları
    try:
        buttons = page.locator("button, a")
        count = buttons.count()
        for i in range(count):
            try:
                btn = buttons.nth(i)
                btn_text = btn.inner_text().strip().lower()
                
                if "accept" in btn_text or "allow" in btn_text or "akzeptieren" in btn_text:
                    # Gerekli çerez butonlarını KESİNLİKLE atla
                    if "necessary" in btn_text or "essential" in btn_text or "nur" in btn_text:
                        continue
                        
                    if btn.is_visible():
                        btn.evaluate("node => node.click()")
                        page.wait_for_timeout(3000)
                        log(f"Cookie akıllı genel aramayla ({btn_text}) kabul edildi.")
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
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--start-maximized"
            ]
        )
        
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080}
        )
        
        page = context.new_page()

        try:
            log("Site açılıyor...")
            page.goto(URL, timeout=60000)
            page.wait_for_load_state("networkidle") # Sitenin tam yüklenmesini bekle
            page.wait_for_timeout(2000)

            # COOKIE YÖNETİMİ
            page.mouse.wheel(0, 2500)
            page.wait_for_timeout(1000)
            result["cookie_accepted"] = accept_cookies_if_present(page)

            # Çerezlerin kaydedilip kaydedilmediğini görmek için log ekledik
            cookies = context.cookies()
            log(f"Mevcut tarayıcı çerezi sayısı: {len(cookies)}")

            # Formu bulabilmek için sayfayı aşağı kaydır
            page.mouse.wheel(0, 1500)
            page.wait_for_timeout(1000)

            # FORM ELEMANLARINI BUL
            name_input = page.locator('input[type="text"]').first
            email_input = page.locator('input[type="email"]').first
            message_input = page.locator('textarea').first
            submit_button = page.get_by_role("button", name="Send").first

            if not submit_button.is_visible():
                result["status"] = "form_missing"
                result["details"].append("Eksik form elemanı.")
                return result

            log("Form dolduruluyor (Gerçek insan simülasyonu)...")
            # fill() yerine type() kullanıyoruz ki bot algılaması düşsün
            name_input.type(name_value, delay=50)
            email_input.type(email_value, delay=50)
            message_input.type(message_value, delay=50)

            result["email_valid"] = html5_email_valid(page)
            log(f"Email validity: {result['email_valid']}")

            if not result["email_valid"]:
                result["status"] = "invalid_email"
                result["details"].append("Email HTML5 validation'dan geçmedi.")
                return result

            log("Form gönderme döngüsü başlıyor...")

            submit_result = "unknown"

            for i in range(3):
                log(f"{i+1}. tıklama yapılıyor...")
                # Zorla JS tıklaması
                submit_button.evaluate("node => node.click()")
                page.wait_for_timeout(2500)  # Tıklama sonrası 2.5 saniye bekle

                current_result = evaluate_result(page)
                log(f"Sonuç: {current_result}")

                if current_result == "success":
                    submit_result = current_result
                    break
                
                submit_result = current_result
                if i < 2:
                    result["details"].append(f"Deneme {i + 1}: {current_result} alındı, tekrar deneniyor.")
                    # Hata alındığında hafifçe kaydır ve bekle
                    page.mouse.wheel(0, 100)
                    page.wait_for_timeout(1000)

            # SONUÇLARI KAYDET
            result["status"] = submit_result
            result["details"].append(f"Submit son durum: {submit_result}")

            if submit_result == "success":
                result["details"].append("Form başarıyla gönderildi.")
                log("✅ TEST PASS")
            else:
                result["details"].append(f"Form gönderilemedi: 3 deneme sonucunda {submit_result} aşılamadı.")
                log(f"❌ {submit_result}")

            return result

        except Exception as e:
            result["status"] = "exception"
            result["details"].append(f"{type(e).__name__}: {e}")
            log(f"❌ HATA: {e}")
            return result

        finally:
            context.close()
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