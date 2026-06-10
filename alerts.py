"""
Alarm tarama motoru.
- Tüm kullanıcıların aktif alarmlarını tek geçişte değerlendirir
- Aynı sembol için veriler cache'lenir (N kullanıcı = 1 istek)
- Senkron çalışır; main.py asyncio.to_thread ile çağırır
"""
import logging
from datetime import datetime, timezone, timedelta

import config
import users
import strategy
import yahoo_client
from telegram_handler import (
    fmt_price, fmt_pct, fmt_num, chg_emoji, base_sym, interval_label,
)

log = logging.getLogger(__name__)


def _cooldown_ok(al: dict) -> bool:
    lf = al.get("last_fired")
    if not lf:
        return True
    try:
        last = datetime.fromisoformat(lf)
    except ValueError:
        return True
    return datetime.now(timezone.utc) - last >= timedelta(
        minutes=config.RSI_ALERT_COOLDOWN_MIN)


def scan():
    """Döner: [(chat_id, mesaj), ...]. Tetiklenen alarmların state'ini günceller."""
    results = []
    quote_cache = {}
    rsi_cache = {}
    dirty = False

    for cid, u in users.DATA["users"].items():
        if not u.get("settings", {}).get("notif", True):
            continue
        st = u.get("settings", config.DEFAULT_SETTINGS)

        for al in u.get("alerts", []):
            if not al.get("active"):
                continue
            sym = al["symbol"]
            t = al["type"]

            if sym not in quote_cache:
                quote_cache[sym] = yahoo_client.get_quote(sym)
            quote = quote_cache[sym]
            if not quote:
                continue

            now_str = (f"Şu an: *{fmt_price(quote['price'], quote['currency'])}* "
                       f"{chg_emoji(quote['chg_pct'])} {fmt_pct(quote['chg_pct'])} (bugün)")

            if t in ("price_above", "price_below"):
                hit = (quote["price"] >= al["value"] if t == "price_above"
                       else quote["price"] <= al["value"])
                if hit:
                    al["active"] = False
                    al["last_fired"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
                    dirty = True
                    direction = "hedefin üstüne çıktı" if t == "price_above" else "hedefin altına indi"
                    results.append((cid,
                        f"🎯 *{base_sym(sym)}* {direction}!\n"
                        f"Hedef: {fmt_num(al['value'])}\n{now_str}\n\n"
                        f"_Bu alarm tamamlandı ve kapatıldı._"))

            else:  # rsi_low / rsi_high
                if not _cooldown_ok(al):
                    continue
                key = (sym, st["interval"], st["rsi_period"])
                if key not in rsi_cache:
                    chart = yahoo_client.fetch_chart(sym, st["interval"])
                    rsi_cache[key] = (strategy.rsi(chart["closes"], st["rsi_period"])
                                      if chart else None)
                r = rsi_cache[key]
                if r is None:
                    continue

                fired = False
                if t == "rsi_low" and r <= st["rsi_low"]:
                    fired = True
                    msg = (f"🟢 *{base_sym(sym)}* aşırı satım bölgesinde!\n"
                           f"RSI({st['rsi_period']}, {interval_label(st['interval'])}): "
                           f"*{fmt_num(r, 1)}* (eşik {st['rsi_low']})\n{now_str}")
                elif t == "rsi_high" and r >= st["rsi_high"]:
                    fired = True
                    msg = (f"🔴 *{base_sym(sym)}* aşırı alım bölgesinde!\n"
                           f"RSI({st['rsi_period']}, {interval_label(st['interval'])}): "
                           f"*{fmt_num(r, 1)}* (eşik {st['rsi_high']})\n{now_str}")
                if fired:
                    al["last_fired"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
                    dirty = True
                    results.append((cid, msg))

    if dirty:
        users.save_async()
    return results
