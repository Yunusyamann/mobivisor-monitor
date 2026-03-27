import os
from datetime import datetime
import requests
from bs4 import BeautifulSoup

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

def build_email_html(result: dict) -> str:
    details_html = "".join(f"<li>{item}</li>" for item in result["details"])

    return f"""
    <html>
      <body>
        <h2>MobiVisor Submit Monitor Sonucu (API Yöntemi)</h2>
        <p><b>Zaman:</b> {result["timestamp"]}</p>
        <p><b>Son Durum:</b> {result["status"]}</p>

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
        "details": [],
    }

    # Tarayıcı gibi davranmak için Session ve Header ayarları
    session = requests.Session()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Connection": "keep-alive",
    }

    try:
        log("1. AŞAMA: Sitenin altyapısına bağlanılıyor...")
        response = session.get(URL, headers=headers, timeout=30)
        response.raise_for_status()
        
        # Siteyi tarayıp Contact Form 7'yi buluyoruz
        soup = BeautifulSoup(response.text, 'html.parser')
        form = soup.find('form', class_=lambda c: c and 'wpcf7-form' in c)
        
        if not form:
            result["status"] = "form_missing"
            result["details"].append("Sitede form altyapısı (wpcf7) bulunamadı.")
            log("❌ Form bulunamadı.")
            return result

        log("2. AŞAMA: Form gizli güvenlik tokenları (nonce) çekiliyor...")
        payload = {}
        
        # Formun içindeki tüm gizli alanları (ID, versiyon, güvenlik tokenları) al
        for hidden in form.find_all('input', type='hidden'):
            name = hidden.get('name')
            value = hidden.get('value', '')
            if name:
                payload[name] = value

        form_id = payload.get('_wpcf7')
        if not form_id:
            result["status"] = "id_missing"
            result["details"].append("Form ID'si çıkarılamadı.")
            return result

        log(f"Form ID bulundu: {form_id}")

        # Dinamik olarak sitedeki form alanlarının 'name' değerlerini bulup doldur
        text_inputs = form.find_all('input', type='text')
        if text_inputs:
            payload[text_inputs[0].get('name')] = name_value

        email_inputs = form.find_all('input', type='email')
        if email_inputs:
            payload[email_inputs[0].get('name')] = email_value

        textareas = form.find_all('textarea')
        if textareas:
            payload[textareas[0].get('name')] = message_value

        # Arka plan (AJAX) isteği atacağımızı WordPress'e bildiriyoruz
        payload['_wpcf7_is_ajax_call'] = '1'

        log("3. AŞAMA: Form API üzerinden arka planda gönderiliyor...")
        
        # WordPress Contact Form 7 REST API Endpoint'i
        api_url = f"https://www.mobivisor.de/wp-json/contact-form-7/v1/contact-forms/{form_id}/feedback"
        
        # Fetch isteği atıyormuşuz gibi ek başlıklar
        api_headers = headers.copy()
        api_headers["Accept"] = "application/json, text/javascript, */*; q=0.01"
        api_headers["X-Requested-With"] = "XMLHttpRequest"

        post_response = session.post(api_url, data=payload, headers=api_headers, timeout=30)
        
        # JSON yanıtını çözümle
        try:
            json_resp = post_response.json()
            api_status = json_resp.get("status", "unknown")
            api_message = json_resp.get("message", "Mesaj okunamadı")
            
            result["details"].append(f"<b>API Yanıt Durumu:</b> {api_status}")
            result["details"].append(f"<b>API Mesajı:</b> {api_message}")
            log(f"Sunucu Yanıtı: [{api_status}] {api_message}")

            if api_status == "mail_sent":
                result["status"] = "SUCCESS"
                result["details"].append("✅ API üzerinden form başarıyla iletildi.")
            elif api_status == "spam":
                result["status"] = "SPAM_BLOCKED"
                result["details"].append("❌ API isteği spam filtresine takıldı.")
            elif api_status == "validation_failed":
                result["status"] = "VALIDATION_ERROR"
                result["details"].append("❌ Form alanları doğrulamadan geçemedi.")
            else:
                result["status"] = f"UNKNOWN: {api_status}"

        except ValueError:
            result["status"] = "json_error"
            result["details"].append(f"Sunucu JSON döndürmedi. HTTP Kodu: {post_response.status_code}")
            log("❌ Sunucu JSON yanıtı vermedi.")

        return result

    except Exception as e:
        result["status"] = "exception"
        result["details"].append(f"❌ HATA: {str(e)}")
        log(f"❌ HATA: {e}")
        return result

def main():
    log("DEBUG: GITHUB MONITOR SURUMU CALISIYOR (API & BACKEND YÖNTEMİ)")

    result = run_test(
        name_value="Test User",
        email_value="test@example.com",
        message_value=f"Automated API check - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )

    log(f"NİHAİ SONUÇ: {result['status']}")

    short_status = (result['status'][:40] + '...') if len(result['status']) > 40 else result['status']
    subject = f"MobiVisor API Submit: {short_status}"
    
    html = build_email_html(result)
    send_email(subject, html)

if __name__ == "__main__":
    main()