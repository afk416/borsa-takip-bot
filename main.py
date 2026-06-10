"""
Borsa Takip Bot - Ana giriş noktası (Webhook mode)
- Telegram WEBHOOK kullanılır (polling değil) → conflict olmaz
- Render Web Service: Flask + Telegram webhook + arka planda alarm döngüsü
"""
import asyncio
import logging
import os
import threading
from datetime import datetime
from flask import Flask, request, jsonify
from telegram import Update

import config
import users
import alerts
import signals
import telegram_handler

# ============================================================
# LOGGING
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("main")

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
logging.getLogger("werkzeug").setLevel(logging.WARNING)

# Gist'ten kullanıcı verilerini yükle
users.load()

# ============================================================
# FLASK
# ============================================================
flask_app = Flask(__name__)

_loop: asyncio.AbstractEventLoop = None
_telegram_app = None
_running = True


@flask_app.route("/")
def home():
    return {
        "status": "running",
        "users":  len(users.DATA["users"]),
        "time":   datetime.utcnow().isoformat(),
    }


@flask_app.route("/health")
def health():
    return {"ok": True}


@flask_app.route("/webhook", methods=["POST"])
def telegram_webhook():
    """Telegram, update'leri buraya POST eder."""
    if _telegram_app is None or _loop is None:
        return jsonify({"error": "bot not ready"}), 503
    try:
        data = request.get_json(force=True)
        update = Update.de_json(data, _telegram_app.bot)
        asyncio.run_coroutine_threadsafe(
            _telegram_app.process_update(update), _loop,
        )
        return jsonify({"ok": True})
    except Exception as e:
        log.error(f"Webhook hatası: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


# ============================================================
# ALARM DÖNGÜSÜ
# ============================================================
async def alert_loop():
    log.info("🔔 Alarm kontrol döngüsü başladı")
    await asyncio.sleep(15)   # bot otursun
    while _running:
        try:
            triggered = await asyncio.to_thread(alerts.scan)
            for chat_id, text in triggered:
                await telegram_handler.send_to(chat_id, text)
            if triggered:
                log.info(f"🔔 {len(triggered)} alarm tetiklendi")
        except Exception as e:
            log.error(f"Alarm döngüsü hatası: {e}", exc_info=True)

        try:
            sigs = await asyncio.to_thread(signals.scan)
            for chat_id, text in sigs:
                await telegram_handler.send_to(chat_id, text)
            if sigs:
                log.info(f"📡 {len(sigs)} AL/SAT sinyali gönderildi")
        except Exception as e:
            log.error(f"Sinyal döngüsü hatası: {e}", exc_info=True)

        await asyncio.sleep(config.CHECK_INTERVAL)


async def keep_alive_loop():
    """Render free tier uyumasın diye kendi public URL'ine ping (her 10 dk)."""
    public_url = os.environ.get("RENDER_EXTERNAL_URL")
    if not public_url:
        log.info("RENDER_EXTERNAL_URL yok, self-ping devre dışı")
        return
    import requests as _req
    health_url = public_url.rstrip("/") + "/health"
    while _running:
        try:
            _req.get(health_url, timeout=10)
        except Exception as e:
            log.debug(f"Self-ping hatası: {e}")
        await asyncio.sleep(600)


# ============================================================
# ASYNCIO ARKA PLAN THREAD'İ
# ============================================================
async def async_main():
    global _telegram_app

    _telegram_app = telegram_handler.build_application()
    await _telegram_app.initialize()
    await _telegram_app.start()

    try:
        await telegram_handler.register_bot_commands(_telegram_app)
    except Exception as e:
        log.warning(f"Bot komutları kaydedilemedi: {e}")

    public_url = os.environ.get("RENDER_EXTERNAL_URL") or os.environ.get("PUBLIC_URL")
    if public_url:
        webhook_url = f"{public_url.rstrip('/')}/webhook"
        try:
            await _telegram_app.bot.delete_webhook(drop_pending_updates=True)
            await _telegram_app.bot.set_webhook(
                url=webhook_url,
                drop_pending_updates=True,
                allowed_updates=["message", "callback_query"],
            )
            log.info(f"✅ Webhook kuruldu: {webhook_url}")
        except Exception as e:
            log.error(f"Webhook kurulamadı: {e}")
    else:
        log.warning("⚠️ RENDER_EXTERNAL_URL yok, webhook kurulamaz (lokal test modu)")

    asyncio.create_task(alert_loop())
    asyncio.create_task(keep_alive_loop())

    log.info(f"✅ Bot çalışıyor — {len(users.DATA['users'])} kayıtlı kullanıcı")

    while _running:
        await asyncio.sleep(60)


def run_async_loop():
    global _loop
    _loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_loop)
    _loop.run_until_complete(async_main())


# ============================================================
# ANA
# ============================================================
def main():
    if not config.TELEGRAM_TOKEN:
        log.error("❌ TELEGRAM_TOKEN env var eksik!")
        return

    bg_thread = threading.Thread(target=run_async_loop, daemon=True)
    bg_thread.start()
    log.info("🚀 Asyncio loop başlatıldı")

    port = int(os.environ.get("PORT", 10000))
    log.info(f"🌐 Flask başlatılıyor (port {port})")
    flask_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
