"""
Otomatik AL/SAT sinyal motoru — LOT BİRİKTİRME mantığı.
- Sinyal modu açık kullanıcıların TÜM watchlist'i taranır
- strategy.check_signal eski OKX botunun crossover + filtre mantığını uygular
- POZİSYON MANTIĞI (kullanıcının isteği):
    • Her AL sinyali     → +1 lot topla (🟢 bildir, toplam lot artar)
    • İlk SAT sinyali     → biriken TÜM lotları sat (🔴 bildir, lot=0)
    • SAT + lot yok       → tepkisiz (asla short açmaz)
- Aynı mum için sinyal bir kez işlenir (last_ts ile spam önleme)
- Durum: signal_state[sym] = {"lots": int, "last_ts": <bar timestamp>}
- Senkron çalışır; main.py asyncio.to_thread ile çağırır

Not: BIST'te açığa satış bireysel olarak yoktur; SAT = elindeki lotları kapatmak.
"""
import logging

import users
import strategy
import yahoo_client
from telegram_handler import (
    fmt_price, fmt_pct, fmt_num, chg_emoji, base_sym, interval_label,
)

log = logging.getLogger(__name__)


def _format_signal(sym, sig, quote, interval, is_buy: bool, lots: int) -> str:
    if is_buy:
        title = "🟢 *AL Sinyali*"
        action = f"_+1 lot topla → toplam *{lots} lot*. Midas'tan 1 lot al._"
    else:
        title = "🔴 *SAT Sinyali — Tüm Lotları Kapat*"
        action = f"_Biriken *{lots} lotun tamamını* sat. Pozisyonu kapat._"

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
    """Döner: [(chat_id, mesaj), ...]. signal_state'i (lots/last_ts) günceller."""
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
            if not isinstance(state, dict):
                state = {}
            lots = state.get("lots", 0)
            bar_ts = sig["bar_ts"]

            # Bu mum daha önce değerlendirildiyse atla (spam önleme)
            if state.get("last_ts") == bar_ts:
                continue

            is_buy = None
            if sig["side"] == "long":
                lots += 1
                sig_state[sym] = {"lots": lots, "last_ts": bar_ts}
                dirty = True
                is_buy = True
            else:  # short sinyali
                if lots > 0:
                    sig_state[sym] = {"lots": 0, "last_ts": bar_ts}
                    dirty = True
                    is_buy = False
                else:
                    # Pozisyon yok → short açma; ama mumu işlenmiş say
                    sig_state[sym] = {"lots": 0, "last_ts": bar_ts}
                    dirty = True
                    continue

            if sym not in quote_cache:
                quote_cache[sym] = yahoo_client.get_quote(sym)
            shown_lots = lots if is_buy else state.get("lots", 0)
            results.append((cid,
                            _format_signal(sym, sig, quote_cache[sym], interval,
                                           is_buy, shown_lots)))

    if dirty:
        users.save_async()
    return results
