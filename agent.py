import os
import http.server
import socketserver
import threading
import asyncio
import re
import httpx
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
from openai import OpenAI

# Dummy server to bypass Render port check
def start_dummy_server():
    port = int(os.environ.get("PORT", 10000))
    handler = http.server.SimpleHTTPRequestHandler
    try:
        with socketserver.TCPServer(("", port), handler) as httpd:
            httpd.serve_forever()
    except Exception as e:
        print(f"Dummy server exception: {e}")

threading.Thread(target=start_dummy_server, daemon=True).start()

# ==========================================
# 1. CONFIGURATION & ENVIRONMENT SETUP
# ==========================================
client = OpenAI(
    base_url="https://router.huggingface.co/v1",
    api_key=os.environ.get("EXPLABS_API_KEY")
)

WEBSITE_URL = os.environ.get("WEBSITE_URL", "https://your-site.vercel.app")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_REPO = os.environ.get("GITHUB_REPO")  # Format: "user/repo"
TARGET_FILE = os.environ.get("TARGET_FILE", "index.html")

HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json",
    "User-Agent": "Autonomous-Patching-Agent"
}

# ==========================================
# 2. UTILITY & CLEANING FUNCTIONS
# ==========================================
def extract_clean_code(ai_output: str) -> str:
    """Removes markdown code block formatting if returned by the AI model."""
    clean_text = re.sub(r"^```[a-zA-Z]*\n", "", ai_output)
    clean_text = re.sub(r"\n```$", "", clean_text)
    return clean_text.strip()

# ==========================================
# 3. ASYNC GITHUB HELPER FUNCTIONS
# ==========================================
async def get_github_file_async():
    """Fetch current file content and its SHA hash asynchronously."""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{TARGET_FILE}"
    async with httpx.AsyncClient() as httpx_client:
        try:
            response = await httpx_client.get(url, headers=HEADERS, timeout=15.0)
            if response.status_code == 200:
                data = response.json()
                import base64
                content = base64.b64decode(data['content']).decode('utf-8')
                return content, data['sha']
        except Exception as e:
            print(f"Error fetching from GitHub: {e}")
    return None, None

async def update_github_file_async(new_content, sha, commit_message):
    """Push updated file content directly to GitHub repo asynchronously."""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{TARGET_FILE}"
    import base64
    encoded_content = base64.b64encode(new_content.encode('utf-8')).decode('utf-8')
    payload = {
        "message": commit_message,
        "content": encoded_content,
        "sha": sha
    }
    async with httpx.AsyncClient() as httpx_client:
        try:
            response = await httpx_client.put(url, headers=HEADERS, json=payload, timeout=15.0)
            return response.status_code in [200, 201]
        except Exception as e:
            print(f"Error pushing to GitHub: {e}")
            return False

# ==========================================
# 4. SELF-HEALING WATCHDOG AGENT
# ==========================================
async def auto_healing_watchdog(app):
    """Monitors site health asynchronously using httpx."""
    while True:
        try:
            async with httpx.AsyncClient() as httpx_client:
                res = await httpx_client.get(WEBSITE_URL, timeout=10.0)
                status_code = res.status_code
        except httpx.RequestError as exc:
            status_code = f"Connection Error ({type(exc).__name__})"

        if status_code != 200:
            try:
                await app.bot.send_message(
                    chat_id=TELEGRAM_CHAT_ID,
                    text=f"⚠️ **Watchdog Alert:** Site error detected (Status: {status_code}). Initiating Auto-Fix..."
                )
                
                current_code, sha = await get_github_file_async()
                if current_code and sha:
                    prompt = f"The website returned error: {status_code}. Fix any broken HTML/JS code in:\n{current_code}"
                    
                    # Offload the blocking OpenAI API call to an executor thread
                    loop = asyncio.get_running_loop()
                    completion = await loop.run_in_executor(
                        None,
                        lambda: client.chat.completions.create(
                            model="Qwen/Qwen2.5-Coder-32B-Instruct",
                            messages=[
                                {"role": "system", "content": "You are a code repairing agent. Output ONLY the raw updated code. Absolutely no text explanations, markdown tags, or backticks."},
                                {"role": "user", "content": prompt}
                            ]
                        )
                    )
                    
                    raw_patched = completion.choices[0].message.content
                    patched_code = extract_clean_code(raw_patched)
                    
                    success = await update_github_file_async(
                        patched_code, sha, f"Auto-Patch applied by AI Agent for {status_code}"
                    )
                    if success:
                        await app.bot.send_message(
                            chat_id=TELEGRAM_CHAT_ID,
                            text="🛠️ **Auto-Patch Success!** Fixed code pushed to GitHub. Deployment restarting..."
                        )
                    else:
                        await app.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text="❌ Failed to update GitHub repository.")
            except Exception as loop_err:
                print(f"Error within self-healing process: {loop_err}")

        await asyncio.sleep(300)  # Check every 5 minutes

# ==========================================
# 5. MANUAL COMMAND HANDLING VIA TELEGRAM
# ==========================================
async def handle_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_prompt = update.message.text
    chat_id = update.effective_chat.id
    
    await context.bot.send_message(chat_id=chat_id, text="🔍 **Step 1:** Request received. Fetching source code from GitHub...")
    current_code, sha = await get_github_file_async()
    
    if not current_code:
        await context.bot.send_message(chat_id=chat_id, text="❌ Could not fetch file from GitHub. Check environment credentials.")
        return
        
    await context.bot.send_message(chat_id=chat_id, text="🧠 **Step 2:** Generating updates with AI Agent...")
    try:
        loop = asyncio.get_running_loop()
        completion = await loop.run_in_executor(
            None,
            lambda: client.chat.completions.create(
                model="Qwen/Qwen2.5-Coder-32B-Instruct",
                messages=[
                    {"role": "system", "content": "You are an AI developer. Update the code according to request. Output raw updated code only. No explanations, no markdown blocks."},
                    {"role": "user", "content": f"Existing Code:\n{current_code}\n\nUser Request:\n{user_prompt}"}
                ]
            )
        )
        
        raw_code = completion.choices[0].message.content
        new_code = extract_clean_code(raw_code)
        
        await context.bot.send_message(chat_id=chat_id, text="⚙️ **Step 3:** Committing and pushing changes directly to GitHub...")
        success = await update_github_file_async(new_code, sha, f"Telegram command update: {user_prompt[:30]}")
        
        if success:
            await context.bot.send_message(chat_id=chat_id, text="🚀 **Finished!** Changes pushed to GitHub. Auto-deployment triggered.")
        else:
            await context.bot.send_message(chat_id=chat_id, text="❌ Failed to commit changes to GitHub.")
    except Exception as e:
        await context.bot.send_message(chat_id=chat_id, text=f"❌ Error during execution: {e}")

# ==========================================
# 6. ENTRY POINT
# ==========================================
async def post_init(application):
    asyncio.create_task(auto_healing_watchdog(application))

if __name__ == "__main__":
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    app = ApplicationBuilder().token(bot_token).post_init(post_init).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_user_command))
    
    print("Autonomous Patching Agent is running.")
    app.run_polling()
