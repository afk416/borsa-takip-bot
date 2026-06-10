"""
Otomatik AL/SAT sinyal motoru — LONG-ONLY mantık.
- Sinyal modu açık kullanıcıların TÜM watchlist'i taranır
- strategy.check_signal eski OKX botunun crossover + filtre mantığını uygular
- POZİSYON MANTIĞI (kullanıcının isteği):
    • AL sinyali + pozisyon YOK  → 🟢 AL bildir, pozisyona "girildi" say
    • AL sinyali + zaten pozisyonda → sessiz (tekrar AL deme)
    • SAT sinyali + pozisyonda    → 🔴 SAT bildir (TÜM alımları kapat), pozisyon kapandı
    • SAT sinyali + pozisyon YOK  → HİÇBİR ŞEY (asla short açmaz)
- Durum kullanıcı kaydında: signal_state[sym] = {"in_pos": bool}
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


def _format_signal(sym, sig, quote, interval, is_buy: bool) -> str:
    if is_buy:
        title = "🟢 *AL Sinyali*"
        action = "_Pozisyona girmeyi değerlendirebilirsin._"
    else:
        title = "🔴 *SAT Sinyali — Tüm Alımları Kapat*"
        action = "_AL sinyaliyle girdiğin pozisyondan çıkış. Elindekini sat._"

    price_line = ""
    if quote:
        price_line = (f"\n💰 {fmt_price(quote['price'], quote['currency'])} "
                      f"{chg_emoji(quote['chg_pct'])} {fmt_pct(quote['chg_pct'])}")

    cur = quote["currency"] if quote else ""
    sltp = ""
    if is_buy and sig.get("sl") and sig.get("tp"):
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
        f"{action}\n"
        f"_İşlemi Midas'tan elle yapmalısın. Yatırım tavsiyesi değildir._"
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

            state = sig_state.get(sym)
            in_pos = bool(state.get("in_pos")) if isinstance(state, dict) else False

            is_buy = None
            if sig["side"] == "long":
                if in_pos:
                    continue            # zaten pozisyonda → tekrar AL gönderme
                is_buy = True
                sig_state[sym] = {"in_pos": True}
            else:  # short sinyali
                if not in_pos:
                    continue            # pozisyon yok → short AÇMA, sessiz geç
                is_buy = False
                sig_state[sym] = {"in_pos": False}

            dirty = True
            if sym not in quote_cache:
                quote_cache[sym] = yahoo_client.get_quote(sym)
            results.append((cid,
                            _format_signal(sym, sig, quote_cache[sym], interval, is_buy)))

    if dirty:
        users.save_async()
    return results
