import os
import requests
import json
import time
import base64
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"NexaAgent is online!")

def run_dummy_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), SimpleHandler)
    server.serve_forever()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

# اسم المستودع الصحيح
REPO_NAME = os.getenv("GITHUB_REPO", "pexseles/nexadigital")
FILE_PATH = "index.html"

def send_telegram_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=10)
    except Exception as e:
        print("Telegram send error:", e)

def get_latest_message(offset=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    params = {"timeout": 30, "offset": offset}
    try:
        response = requests.get(url, params=params, timeout=35).json()
        if response.get("ok") and response.get("result"):
            return response["result"]
    except Exception as e:
        print("Telegram fetch error:", e)
    return []

def get_github_file():
    url = f"https://api.github.com/repos/{REPO_NAME}/contents/{FILE_PATH}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    res = requests.get(url, headers=headers).json()
    if "content" not in res:
        raise Exception(f"GitHub Error: {res.get('message', 'فشل الوصول للمستودع')}")
    content = base64.b64decode(res["content"]).decode("utf-8")
    return content, res["sha"]

def update_github_file(new_content, sha, commit_message):
    url = f"https://api.github.com/repos/{REPO_NAME}/contents/{FILE_PATH}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    encoded_content = base64.b64encode(new_content.encode("utf-8")).decode("utf-8")
    data = {
        "message": commit_message,
        "content": encoded_content,
        "sha": sha
    }
    res = requests.put(url, headers=headers, json=data)
    return res.status_code == 200

def generate_new_html(current_html, prompt):
    models = ["gemini-1.5-flash", "gemini-2.0-flash"]
    full_prompt = f"You are a web developer. Modify the following HTML code according to this instruction: '{prompt}'. Return ONLY the updated full HTML code without any markdown formatting or explanation.\n\nCurrent HTML:\n{current_html}"
    payload = {"contents": [{"parts": [{"text": full_prompt}]}]}
    headers = {'Content-Type': 'application/json'}

    errors = []
    for model_name in models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={GEMINI_API_KEY}"
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=20)
            res = response.json()
            if 'candidates' in res and res['candidates']:
                text = res['candidates'][0]['content']['parts'][0]['text']
                return text.replace("```html", "").replace("```", "").strip(), None
            else:
                err_msg = res.get("error", {}).get("message", json.dumps(res))
                errors.append(f"{model_name}: {err_msg}")
        except Exception as e:
            errors.append(f"{model_name}: {str(e)}")
    return None, " | ".join(errors)

def main():
    print("[INFO] NexaAgent service starting...")
    threading.Thread(target=run_dummy_server, daemon=True).start()
    
    offset = None
    while True:
        try:
            updates = get_latest_message(offset)
            for update in updates:
                offset = update["update_id"] + 1
                message = update.get("message", {})
                text = message.get("text")
                chat_id = message.get("chat", {}).get("id")

                if text and chat_id:
                    send_telegram_message(chat_id, "⏳ جاري معالجة طلبك وتحديث الموقع...")
                    try:
                        current_html, sha = get_github_file()
                        updated_html, err = generate_new_html(current_html, text)
                        if updated_html:
                            success = update_github_file(updated_html, sha, f"Auto update: {text[:30]}")
                            if success:
                                send_telegram_message(chat_id, "✅ تم تعديل الموقع ونشره بنجاح على Vercel!")
                            else:
                                send_telegram_message(chat_id, "❌ حدث خطأ أثناء التحديث على GitHub.")
                        else:
                            send_telegram_message(chat_id, f"❌ فشل الذكاء الاصطناعي.\nالتفاصيل: {err}")
                    except Exception as e:
                        print("Execution error:", e)
                        send_telegram_message(chat_id, f"❌ خطأ في النظام: {str(e)}")
        except Exception as e:
            print("Main loop error:", e)
        time.sleep(2)

if __name__ == "__main__":
    main()
