"""
Otomatik AL/SAT sinyal motoru (eski OKX botundaki Crossover mantığı).
- Sinyal modu açık kullanıcıların TÜM watchlist'i taranır (alarm kurmaya gerek yok)
- Her hisse için son RSI bölgesi (low/mid/high) kullanıcı kaydında tutulur
- Sinyal yalnızca BÖLGE GEÇİŞİNDE üretilir (sürekli tekrar etmez):
    AL  : RSI aşırı satımdan (low) yukarı, eşiğin üstüne döndüğünde → toparlanma
    SAT : RSI aşırı alımdan (high) aşağı, eşiğin altına döndüğünde → zayıflama
- İlk taramada baseline kurulur, sinyal üretilmez (yanlış ilk sinyali önler)
- Senkron çalışır; main.py asyncio.to_thread ile çağırır
"""
import logging

import users
import strategy
import yahoo_client
from telegram_handler import (
    fmt_price, fmt_pct, fmt_num, chg_emoji, base_sym, interval_label,
)

log = logging.getLogger(__name__)


def _zone(rsi_val: float, low: int, high: int) -> str:
    if rsi_val <= low:
        return "low"
    if rsi_val >= high:
        return "high"
    return "mid"


def scan():
    """Döner: [(chat_id, mesaj), ...]. signal_state'i günceller."""
    results = []
    rsi_cache = {}      # (sym, interval, period) -> rsi
    quote_cache = {}    # sym -> quote
    dirty = False

    for cid, u in users.DATA["users"].items():
        st = u.get("settings", {})
        if not st.get("signals") or not st.get("notif", True):
            continue
        wl = u.get("watchlist", [])
        if not wl:
            continue

        sig_state = u.setdefault("signal_state", {})
        low, high = st.get("rsi_low", 30), st.get("rsi_high", 70)
        period, interval = st.get("rsi_period", 14), st.get("interval", "gunluk")

        for sym in wl:
            key = (sym, interval, period)
            if key not in rsi_cache:
                chart = yahoo_client.fetch_chart(sym, interval)
                rsi_cache[key] = (strategy.rsi(chart["closes"], period)
                                  if chart else None)
            r = rsi_cache[key]
            if r is None:
                continue

            new_zone = _zone(r, low, high)
            prev_zone = sig_state.get(sym)
            sig_state[sym] = new_zone
            dirty = True

            if prev_zone is None or prev_zone == new_zone:
                continue   # baseline veya bölge değişmedi → sinyal yok

            signal = None
            if prev_zone == "low" and new_zone == "mid":
                signal = ("🟢 *AL Sinyali*", "aşırı satımdan yukarı döndü")
            elif prev_zone == "high" and new_zone == "mid":
                signal = ("🔴 *SAT Sinyali*", "aşırı alımdan aşağı döndü")
            if not signal:
                continue

            if sym not in quote_cache:
                quote_cache[sym] = yahoo_client.get_quote(sym)
            quote = quote_cache[sym]
            price_line = ""
            if quote:
                price_line = (f"\n💰 {fmt_price(quote['price'], quote['currency'])} "
                              f"{chg_emoji(quote['chg_pct'])} {fmt_pct(quote['chg_pct'])}")

            title, reason = signal
            results.append((cid,
                f"{title} — *{base_sym(sym)}*\n"
                f"RSI({period}, {interval_label(interval)}): *{fmt_num(r, 1)}* ({reason})"
                f"{price_line}\n\n"
                f"_Otomatik sinyal — işlemi Midas'tan elle yapmalısın. "
                f"Yatırım tavsiyesi değildir._"))

    if dirty:
        users.save_async()
    return results
