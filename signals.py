"""
Otomatik AL/SAT sinyal motoru.
- Sinyal modu açık kullanıcıların TÜM watchlist'i taranır (alarm kurmaya gerek yok)
- strategy.check_signal eski OKX botunun crossover + filtre mantığını uygular
- Aynı bar için aynı sinyal iki kez gönderilmez: signal_state[sym] = {"ts","side"}
- Senkron çalışır; main.py asyncio.to_thread ile çağırır

Not: BIST'te açığa satış bireysel olarak pratikte yapılamaz; "SAT sinyali"
elindeki pozisyondan çıkış / kâr al anlamındadır, açığa satış değil.
"""
import logging

import config
import users
import strategy
import yahoo_client
from telegram_handler import (
    fmt_price, fmt_pct, fmt_num, chg_emoji, base_sym, interval_label,
)

log = logging.getLogger(__name__)


def _format_signal(sym, sig, quote, interval) -> str:
    is_long = sig["side"] == "long"
    title = "🟢 *AL Sinyali*" if is_long else "🔴 *SAT Sinyali*"

    price_line = ""
    if quote:
        price_line = (f"\n💰 {fmt_price(quote['price'], quote['currency'])} "
                      f"{chg_emoji(quote['chg_pct'])} {fmt_pct(quote['chg_pct'])}")

    cur = quote["currency"] if quote else ""
    sltp = ""
    if sig.get("sl") and sig.get("tp"):
        sltp = (f"\n🛑 Stop: {fmt_price(sig['sl'], cur)}   "
                f"🎯 Hedef: {fmt_price(sig['tp'], cur)}")

    extras = []
    if sig.get("vol_ratio"):
        extras.append(f"Hacim ×{fmt_num(sig['vol_ratio'])}")
    if sig.get("range_pct"):
        extras.append(f"Volatilite %{fmt_num(sig['range_pct'])}")
    extra_line = f"\n📊 {' · '.join(extras)}" if extras else ""

    return (
        f"{title} — *{base_sym(sym)}*\n"
        f"Mod: {sig['mode']} · RSI({interval_label(interval)}): *{fmt_num(sig['rsi'], 1)}*"
        f"{price_line}"
        f"{sltp}"
        f"{extra_line}\n\n"
        f"_Otomatik sinyal — işlemi Midas'tan elle yapmalısın. "
        f"Stop/Hedef ATR'a göre önerilir. Yatırım tavsiyesi değildir._"
    )


def scan():
    """Döner: [(chat_id, mesaj), ...]. signal_state'i günceller."""
    results = []
    chart_cache = {}    # (sym, interval) -> chart
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
        interval = st.get("interval", "gunluk")

        for sym in wl:
            ckey = (sym, interval)
            if ckey not in chart_cache:
                chart_cache[ckey] = yahoo_client.fetch_chart(sym, interval)
            chart = chart_cache[ckey]
            if not chart:
                continue

            sig = strategy.check_signal(chart, st)
            if not sig:
                continue

            # Aynı barın aynı yönlü sinyalini tekrar gönderme (spam önleme)
            last = sig_state.get(sym)
            if not isinstance(last, dict):
                last = None
            if last and last.get("ts") == sig["bar_ts"] and last.get("side") == sig["side"]:
                continue
            sig_state[sym] = {"ts": sig["bar_ts"], "side": sig["side"]}
            dirty = True

            if sym not in quote_cache:
                quote_cache[sym] = yahoo_client.get_quote(sym)
            results.append((cid, _format_signal(sym, sig, quote_cache[sym], interval)))

    if dirty:
        users.save_async()
    return results
