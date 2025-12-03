import os, html, time, logging, requests, threading, sys
from urllib.parse import quote_plus, urlparse, parse_qs
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN not set")

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
    if not isinstance(data, dict):
        return results
    arr = data.get("data") or data.get("items") or []
    if not isinstance(arr, list):
        return results
    for item in arr:
        if not isinstance(item, dict):
            continue
        title = item.get("title") or item.get("name") or "Unknown File"
        download = item.get("download") or item.get("url") or item.get("link")
        size = item.get("size") or item.get("filesize") or ""
        if isinstance(download, str) and (download.startswith("http://") or download.startswith("https://")):
            results.append((str(title), download, str(size)))
    return results

def _require_token_qs(path_qs):
    if not KEEPALIVE_SECRET:
        return True
    qs = parse_qs(urlparse(path_qs).query)
    token_vals = qs.get("token") or []
    return (token_vals and token_vals[0] == KEEPALIVE_SECRET)

class _SimpleHandler(BaseHTTPRequestHandler):
    def _send_json(self, payload, status=200):
        data = (str(payload).replace("'", '"')).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/ping":
            if not _require_token_qs(self.path):
                self._send_json({"ok": False, "error": "invalid token"}, status=403)
                return
            global last_ping
            last_ping = int(time.time())
            self._send_json({"ok": True, "timestamp": last_ping})
            return
        if path == "/health":
            if not _require_token_qs(self.path):
                self._send_json({"ok": False, "error": "invalid token"}, status=403)
                return
            now = int(time.time())
            self._send_json({
                "ok": True,
                "uptime": int(now - start_time),
                "pid": os.getpid(),
                "last_user_activity": int(last_user_activity) if last_user_activity else None,
                "last_ping": int(last_ping) if last_ping else None,
                "time": now
            })
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")

def run_keepalive_server_in_thread(host: str, port: int):
    server = HTTPServer((host, port), _SimpleHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    logger.info("Keep-alive server started on %s:%s", host, port)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Send me a Terabox link.\n— Powered by @Regnis")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Send a Terabox share link and I'll return a clean direct download link.\n— Powered by @Regnis")

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
    logger.info("Bot started (polling)...")
    app.run_polling()

if __name__ == "__main__":
    main()
