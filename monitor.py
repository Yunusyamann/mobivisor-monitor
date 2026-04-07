import os
from datetime import datetime
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

# Formun bulunduğu sayfanın tam linki (Görsel Türkçe olduğu için /tr/ veya iletişim sayfası linkini yazabilirsin)
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

def build_email_html(result: dict) -> str:
    details_html = "".join(f"<li>{item}</li>" for item in result["details"])

    return f"""
    <html>
      <body>
        <h2>MobiVisor Submit Monitor Sonucu (Gelişmiş API)</h2>
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

    session = requests.Session()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": URL,
        "Connection": "keep-alive",
    }

    try:
        log("1. AŞAMA: Form sayfasına bağlanılıyor...")
        response = session.get(URL, headers=headers, timeout=30)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        form = soup.find('form', class_=lambda c: c and 'wpcf7-form' in c)
        
        if not form:
            result["status"] = "form_missing"
            result["details"].append("Sitede form altyapısı bulunamadı.")
            log("❌ Form bulunamadı.")
            return result

        log("2. AŞAMA: Form eylem adresi ve tokenlar çekiliyor...")
        payload = {}
        
        # Sitenin kendi form gönderim URL'sini dinamik olarak alıyoruz (REST API'yi zorlamak yerine)
        action_url = form.get("action")
        if action_url:
            submit_url = urljoin(URL, action_url)
        else:
            submit_url = URL
            
        log(f"Hedef Gönderim URL'si: {submit_url}")

        # Tüm gizli güvenlik tokenlarını al (_wpcf7, _wpnonce vs.)
        for hidden in form.find_all('input', type='hidden'):
            name = hidden.get('name')
            value = hidden.get('value', '')
            if name:
                payload[name] = value

        # GÖRSELDEKİ ALANLARI DOLDURMA KISMI
        # İsim alanı (Genelde text tipindedir)
        name_input = form.find('input', type='text')
        if name_input and name_input.get('name'):
            payload[name_input.get('name')] = name_value

        # E-posta alanı
        email_input = form.find('input', type='email')
        if email_input and email_input.get('name'):
            payload[email_input.get('name')] = email_value

        # Mesaj alanı
        textarea = form.find('textarea')
        if textarea and textarea.get('name'):
            payload[textarea.get('name')] = message_value

        # Formun arka planda asenkron işlenmesi için CF7 bayrağı
        payload['_wpcf7_is_ajax_call'] = '1'

        log("3. AŞAMA: Form verileri gönderiliyor...")
        
        api_headers = headers.copy()
        api_headers["Accept"] = "application/json, text/javascript, */*; q=0.01"
        api_headers["X-Requested-With"] = "XMLHttpRequest"

        post_response = session.post(submit_url, data=payload, headers=api_headers, timeout=30)
        
        try:
            json_resp = post_response.json()
            api_status = json_resp.get("status", "unknown")
            api_message = json_resp.get("message", "Mesaj okunamadı")
            
            result["details"].append(f"<b>Sunucu Yanıt Durumu:</b> {api_status}")
            result["details"].append(f"<b>Sunucu Mesajı:</b> {api_message}")
            log(f"Sunucu Yanıtı: [{api_status}] {api_message}")

            if api_status == "mail_sent":
                result["status"] = "SUCCESS"
                result["details"].append("✅ Form başarıyla iletildi.")
            elif api_status == "spam":
                result["status"] = "SPAM_BLOCKED"
                result["details"].append("❌ İstek spam filtresine takıldı.")
            elif api_status == "validation_failed":
                result["status"] = "VALIDATION_ERROR"
                result["details"].append("❌ Form alanları eksik veya hatalı.")
            else:
                result["status"] = f"UNKNOWN: {api_status}"

        except ValueError:
            # EĞER JSON DÖNMEZSE, GELEN HTML/HATA SAYFASINI GÖSTER
            raw_text = post_response.text.strip()
            preview = raw_text[:300] + "..." if len(raw_text) > 300 else raw_text
            
            result["status"] = f"HTTP_{post_response.status_code}_ERROR"
            result["details"].append(f"❌ Sunucu JSON yerine düz metin/HTML döndürdü (Kod: {post_response.status_code}).")
            result["details"].append(f"<pre>{preview}</pre>")
            
            log(f"❌ JSON hatası. HTTP Kodu: {post_response.status_code}")
            log(f"Gelen Yanıt (Özet): {preview}")

        return result

    except Exception as e:
        result["status"] = "exception"
        result["details"].append(f"❌ HATA: {str(e)}")
        log(f"❌ HATA: {e}")
        return result

def main():
    log("DEBUG: GITHUB MONITOR SURUMU CALISIYOR (Dinamik Hedefli API)")

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