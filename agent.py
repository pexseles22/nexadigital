import os
import asyncio
import requests
import base64
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
from openai import OpenAI

# ==========================================
# 1. CONFIGURATION & ENVIRONMENT SETUP
# ==========================================
client = OpenAI(
    base_url="https://api.experientiallabs.ai/v1",
    api_key=os.environ.get("EXPLABS_API_KEY")
)

WEBSITE_URL = os.environ.get("WEBSITE_URL", "https://your-site.vercel.app")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")        # Personal Access Token from GitHub
GITHUB_REPO = os.environ.get("GITHUB_REPO")          # Example: "pexseles22/nexadigital"
TARGET_FILE = os.environ.get("TARGET_FILE", "index.html")


# ==========================================
# 2. GITHUB HELPER FUNCTIONS
# ==========================================
def get_github_file():
    """Fetch current file content and its SHA hash from GitHub repository."""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{TARGET_FILE}"
    headers = {"Authorization": f"bearer {GITHUB_TOKEN}"}
    response = requests.get(url, headers=headers)
    
    if response.status_code == 200:
        data = response.json()
        content = base64.b64decode(data['content']).decode('utf-8')
        return content, data['sha']
    return None, None

def update_github_file(new_content, sha, commit_message):
    """Push updated file content directly to GitHub repo to trigger auto-redeploy."""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{TARGET_FILE}"
    headers = {"Authorization": f"bearer {GITHUB_TOKEN}"}
    
    encoded_content = base64.b64encode(new_content.encode('utf-8')).decode('utf-8')
    payload = {
        "message": commit_message,
        "content": encoded_content,
        "sha": sha
    }
    
    response = requests.put(url, headers=headers, json=payload)
    return response.status_code == 200


# ==========================================
# 3. SELF-HEALING WATCHDOG AGENT
# ==========================================
async def auto_healing_watchdog(app):
    """Monitors site health. If down, fetches code, fixes it with AI, and pushes patch to GitHub."""
    while True:
        try:
            res = requests.get(WEBSITE_URL, timeout=10)
            
            # If site has crashed or returned server error (e.g. status != 200)
            if res.status_code != 200:
                await app.bot.send_message(
                    chat_id=TELEGRAM_CHAT_ID, 
                    text=f"⚠️ **Watchdog Alert:** Site error detected (Status: {res.status_code}). Initiating Auto-Fix..."
                )
                
                # Step A: Fetch current code from GitHub
                current_code, sha = get_github_file()
                
                if current_code and sha:
                    # Step B: Ask AI to fix the error in the code
                    prompt = f"The website returned HTTP error {res.status_code}. Fix any broken HTML/JS code in this file:\n\n{current_code}"
                    completion = client.chat.completions.create(
                        model="claude-opus-5-fast",
                        messages=[
                            {"role": "system", "content": "You are a code repairing agent. Output ONLY valid updated raw code without markdown wrappers."},
                            {"role": "user", "content": prompt}
                        ]
                    )
                    patched_code = completion.choices[0].message.content.strip()
                    
                    # Step C: Commit fix to GitHub
                    success = update_github_file(patched_code, sha, f"Auto-Patch applied by AI Agent for HTTP {res.status_code}")
                    
                    if success:
                        await app.bot.send_message(
                            chat_id=TELEGRAM_CHAT_ID, 
                            text="🛠️ **Auto-Patch Success!** Fixed code pushed to GitHub. Deployment restarting..."
                        )
                    else:
                        await app.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text="❌ Failed to update GitHub repository.")
                
        except Exception as err:
            await app.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=f"🚨 **Critical Crash:** {err}")
            
        await asyncio.sleep(300) # Check every 5 minutes


# ==========================================
# 4. MANUAL COMMAND HANDLING VIA TELEGRAM
# ==========================================
async def handle_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processes manual requests from user: updates code and commits directly to GitHub."""
    user_prompt = update.message.text
    chat_id = update.effective_chat.id

    await context.bot.send_message(chat_id=chat_id, text="🔍 **Step 1:** Request received. Fetching source code from GitHub...")
    
    current_code, sha = get_github_file()
    
    if not current_code:
        await context.bot.send_message(chat_id=chat_id, text="❌ Could not fetch file from GitHub. Check GITHUB_TOKEN and GITHUB_REPO.")
        return

    await context.bot.send_message(chat_id=chat_id, text="🧠 **Step 2:** Generating updates with AI Agent...")
    
    try:
        completion = client.chat.completions.create(
            model="claude-opus-5-fast",
            messages=[
                {"role": "system", "content": "You are an AI developer. Update the user code according to request. Output updated raw code only."},
                {"role": "user", "content": f"Existing Code:\n{current_code}\n\nUser Request:\n{user_prompt}"}
            ]
        )
        new_code = completion.choices[0].message.content.strip()

        await context.bot.send_message(chat_id=chat_id, text="⚙️ **Step 3:** Committing and pushing changes directly to GitHub...")
        
        success = update_github_file(new_code, sha, f"Updated via Telegram command: {user_prompt[:30]}")
        
        if success:
            await context.bot.send_message(chat_id=chat_id, text="🚀 **Finished!** Changes pushed to GitHub. Vercel/Render will auto-deploy now.")
        else:
            await context.bot.send_message(chat_id=chat_id, text="❌ Failed to commit changes to GitHub.")

    except Exception as e:
        await context.bot.send_message(chat_id=chat_id, text=f"❌ Error during execution: {e}")


# ==========================================
# 5. ENTRY POINT
# ==========================================
async def post_init(application):
    """Start background auto-healing loop."""
    asyncio.create_task(auto_healing_watchdog(application))

if __name__ == "__main__":
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    app = ApplicationBuilder().token(bot_token).post_init(post_init).build()
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_user_command))
    
    print("Autonomous Patching Agent is running.")
    app.run_polling()
