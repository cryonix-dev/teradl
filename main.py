import os
import html
import time
import logging
import requests
import threading
import asyncio
import signal
import sys
from urllib.parse import quote_plus
from aiohttp import web
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN not set.")

TERADL_PATTERN = "https://teradl.tiiny.io/?key=RushVx&link={link}"
COOLDOWN_SECONDS = 15
HTTP_TIMEOUT = 20
WEB_PORT = int(os.environ.get("PORT", 8080))
WEB_HOST = "0.0.0.0"
KEEPALIVE_SECRET = os.environ.get("KEEPALIVE_SECRET")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

start_time = time.time()
last_user_activity = None
last_ping = None
user_cooldown = {}

def build_api_url(shared_link: str) -> str:
    return TERADL_PATTERN.format(link=quote_plus(shared_link))

def parse_json(data):
    results = []
    arr = data.get("data") or []
    for item in arr:
        title = item.get("title") or "Unknown File"
        download = item.get("download")
        size = item.get("size") or ""
        if download:
            results.append((title, download, size))
    return results

def _require_token(request):
    if KEEPALIVE_SECRET:
        token = request.query.get("token")
        return token == KEEPALIVE_SECRET
    return True

async def handle_ping(request):
    global last_ping
    if not _require_token(request):
        return web.json_response({"ok": False}, status=403)
    last_ping = time.time()
    return web.json_response({"ok": True, "timestamp": last_ping})

async def handle_health(request):
    if not _require_token(request):
        return web.json_response({"ok": False}, status=403)
    now = time.time()
    return web.json_response({
        "ok": True,
        "uptime": int(now - start_time),
        "pid": os.getpid(),
        "last_user_activity": int(last_user_activity) if last_user_activity else None,
        "last_ping": int(last_ping) if last_ping else None
    })

def run_keepalive_server_in_thread(host: str, port: int):
    app = web.Application()
    app.router.add_get("/ping", handle_ping)
    app.router.add_get("/health", handle_health)
    async def index(req):
        return web.Response(text="OK")
    app.router.add_get("/", index)
    def _run():
        web.run_app(app, host=host, port=port)
    t = threading.Thread(target=_run, daemon=True)
    t.start()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Send me a Terabox link.\n— Powered by @Regnis"
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Just send a Terabox share link.\n— Powered by @Regnis"
    )

async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global last_user_activity
    last_user_activity = time.time()
    user = update.effective_user
    if not user:
        return
    user_id = user.id
    now = time.time()
    last = user_cooldown.get(user_id, 0)
    if now - last < COOLDOWN_SECONDS:
        remaining = int(COOLDOWN_SECONDS - (now - last))
        await update.message.reply_text(f"Slow down. Try again in {remaining}s.\n— Powered by @Regnis")
        return
    user_cooldown[user_id] = now
    text = (update.message.text or "").strip()
    if not text:
        await update.message.reply_text("Invalid link.\n— Powered by @Regnis")
        return
    if "teradl.tiiny.io" in text:
        api_url = text
    else:
        api_url = build_api_url(text)
    info_msg = await update.message.reply_text("Fetching…")
    try:
        resp = requests.get(api_url, timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        await info_msg.edit_text(f"Error: {e}\n— Powered by @Regnis")
        return
    items = parse_json(data)
    if not items:
        await info_msg.edit_text("No downloadable items.\n— Powered by @Regnis")
        return
    lines = []
    for title, link, size in items:
        safe_title = html.escape(title)
        safe_link = html.escape(link)
        line = f'<a href="{safe_link}">{safe_title}</a>'
        if size:
            line += f" — {html.escape(size)}"
        lines.append(line)
    lines.append("")
    lines.append("— Powered by @Regnis")
    final = "\n".join(lines)
    try:
        await info_msg.edit_text("Done.")
    except:
        pass
    await update.message.reply_text(final, parse_mode="HTML", disable_web_page_preview=True)

def main():
    run_keepalive_server_in_thread(WEB_HOST, WEB_PORT)
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))
    app.run_polling()

def _exit(signum, frame):
    sys.exit(0)

signal.signal(signal.SIGTERM, _exit)
signal.signal(signal.SIGINT, _exit)

if __name__ == "__main__":
    main()
