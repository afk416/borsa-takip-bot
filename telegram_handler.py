"""
Borsa Takip Bot - Telegram UI (çok kullanıcılı)
- Her kullanıcı kendi Telegram'ından kendi listesini/alarmını/portföyünü yönetir
- Reply keyboard ana menü + inline butonlar (alt akışlar)
"""
import json
import asyncio
import logging
import urllib.parse
from datetime import datetime, timezone

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton, BotCommand,
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    filters, ContextTypes,
)

import config
import users
import strategy
import yahoo_client

log = logging.getLogger(__name__)

_app: Application = None

BTN_PRICES    = "📊 Fiyatlar"
BTN_RSI       = "📈 RSI Tarama"
BTN_PORTFOLIO = "💼 Portföyüm"
BTN_WATCHLIST = "⭐ Listem"
BTN_ALERTS    = "🔔 Alarmlarım"
BTN_ADD       = "➕ Hisse Ekle"
BTN_SETTINGS  = "⚙️ Ayarlar"
BTN_HELP      = "❓ Yardım"


# ============================================================
# YARDIMCILAR
# ============================================================
def main_menu_keyboard():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(BTN_PRICES),    KeyboardButton(BTN_RSI)],
            [KeyboardButton(BTN_PORTFOLIO), KeyboardButton(BTN_WATCHLIST)],
            [KeyboardButton(BTN_ALERTS),    KeyboardButton(BTN_ADD)],
            [KeyboardButton(BTN_SETTINGS),  KeyboardButton(BTN_HELP)],
        ],
        resize_keyboard=True,
    )


def fmt_num(x, digits: int = 2) -> str:
    """Türkçe sayı formatı: 1.234,56"""
    s = f"{x:,.{digits}f}"
    return s.replace(",", "§").replace(".", ",").replace("§", ".")


def cur_suffix(currency: str) -> str:
    return {"TRY": "₺", "USD": "$", "EUR": "€"}.get(currency, f" {currency}")


def fmt_price(price, currency: str) -> str:
    digits = 2 if price >= 1 else 4
    return f"{fmt_num(price, digits)}{cur_suffix(currency)}"


def fmt_pct(pct) -> str:
    if pct is None:
        return "—"
    sign = "+" if pct >= 0 else "-"
    return f"%{sign}{fmt_num(abs(pct))}"


def chg_emoji(pct) -> str:
    if pct is None:
        return "▪️"
    return "🔺" if pct > 0 else ("🔻" if pct < 0 else "▪️")


def md_escape(text: str) -> str:
    for ch in ("*", "_", "`", "["):
        text = text.replace(ch, "")
    return text


def base_sym(symbol: str) -> str:
    """Görüntüleme adı: THYAO.IS -> THYAO, AAPL -> AAPL"""
    return symbol[:-3] if symbol.endswith(".IS") else symbol


def tr_float(text: str):
    """'250', '250.75' veya '1.250,75' gibi girdileri float'a çevirir."""
    t = text.strip().replace("₺", "").replace("$", "").replace(" ", "")
    try:
        if "," in t:
            t = t.replace(".", "").replace(",", ".")
        return float(t)
    except ValueError:
        return None


def interval_label(key: str) -> str:
    return yahoo_client.INTERVALS.get(key, yahoo_client.INTERVALS["gunluk"])[2]


def build_chart_url(title: str, closes, up: bool) -> str:
    """quickchart.io ile mini fiyat grafiği URL'si."""
    data = [round(float(c), 4) for c in closes[-60:]]
    color = "#22c55e" if up else "#ef4444"
    chart_config = {
        "type": "line",
        "data": {
            "labels": list(range(len(data))),
            "datasets": [{
                "label": title,
                "data": data,
                "fill": False,
                "borderColor": color,
                "backgroundColor": color,
                "borderWidth": 2,
                "pointRadius": 0,
            }],
        },
        "options": {
            "plugins": {"legend": {"display": False},
                        "title": {"display": True, "text": title}},
            "scales": {"x": {"display": False}},
        },
    }
    encoded = urllib.parse.quote(json.dumps(chart_config, separators=(",", ":")))
    return f"https://quickchart.io/chart?w=600&h=300&bkg=white&c={encoded}"


async def gate(update: Update):
    """Kullanıcıyı kaydet; erişim kodu gerekiyorsa kontrol et.
    Yetkili ise user dict, değilse None döner (mesajı kendisi atar)."""
    chat = update.effective_chat
    tg_user = update.effective_user
    user = users.get_or_create(
        chat.id,
        name=(tg_user.full_name if tg_user else ""),
        username=(tg_user.username if tg_user else ""),
    )
    if user["authorized"]:
        return user

    text = (update.message.text or "").strip() if update.message else ""
    if text and text == config.ACCESS_CODE:
        user["authorized"] = True
        users.save_async()
        await update.message.reply_text(
            "✅ Erişim onaylandı, hoş geldin!\n\n"
            "➕ *Hisse Ekle* ile takip listeni oluşturarak başlayabilirsin.",
            parse_mode="Markdown", reply_markup=main_menu_keyboard(),
        )
        return None
    if update.message:
        await update.message.reply_text(
            "🔒 Bu botu kullanmak için erişim kodu gerekli.\n"
            "Kodu mesaj olarak gönder."
        )
    return None


# ============================================================
# KOMUTLAR
# ============================================================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await gate(update)
    if not user:
        return
    await update.message.reply_text(
        "📈 *Borsa Takip Bot'a hoş geldin!*\n\n"
        "BIST ve ABD hisselerini takip et, fiyat & RSI alarmları kur, "
        "portföyünün kâr/zararını izle — hepsi Telegram'dan.\n\n"
        "🔹 Hisse aramak için sembolü yaz: örn `THYAO` veya `AAPL`\n"
        "🔹 ➕ *Hisse Ekle* ile popüler BIST hisselerinden seç\n"
        "🔹 🔔 Alarm kur, fiyat hedefe gelince bildirim al\n\n"
        "_Veriler Yahoo Finance'ten gelir, BIST ~15 dk gecikmelidir._\n"
        "_Yatırım tavsiyesi değildir._",
        parse_mode="Markdown", reply_markup=main_menu_keyboard(),
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await gate(update)
    if not user:
        return
    await update.message.reply_text(
        "❓ *Nasıl kullanılır?*\n\n"
        "*Hisse arama:* sembolü direkt yaz → `THYAO`, `ASELS`, `AAPL`\n"
        "BIST için sadece sembol yeterli, ABD hisseleri de çalışır.\n\n"
        "*Komutlar:*\n"
        "/ekle SEMBOL — takip listesine ekle\n"
        "/sil SEMBOL — listeden çıkar\n"
        "/fiyat SEMBOL — anlık fiyat + grafik\n\n"
        "*Menü:*\n"
        f"{BTN_PRICES} — listendeki hisselerin anlık fiyatları\n"
        f"{BTN_RSI} — listendeki hisselerin RSI taraması\n"
        f"{BTN_PORTFOLIO} — elindeki hisseler + kâr/zarar\n"
        f"{BTN_ALERTS} — fiyat ve RSI alarmların\n"
        f"{BTN_SETTINGS} — RSI periyodu, eşikler, zaman dilimi\n\n"
        "*Alarmlar:*\n"
        "📈/📉 Fiyat alarmı: hedef fiyata gelince 1 kez bildirir, kapanır\n"
        "🟢/🔴 RSI alarmı: aşırı satım/alım bölgesine girince bildirir "
        "(aynı hisse için en erken 4 saatte bir)\n\n"
        "*📡 Otomatik AL/SAT Sinyali:*\n"
        f"{BTN_SETTINGS} → *AL/SAT Sinyalini Aç* dersen, listendeki TÜM hisseler "
        "otomatik taranır (alarm kurmana gerek yok):\n"
        "🟢 *AL* — RSI seçtiğin moda göre yukarı kesişince\n"
        "🔴 *SAT* — RSI aşağı kesişince (elindekinden çıkış)\n"
        "Her sinyalde RSI + ATR'a göre önerilen 🛑 Stop / 🎯 Hedef gelir. "
        "Aynı mum için sinyal bir kez gönderilir.\n\n"
        "*Sinyal modları (Ayarlar'dan seç):*\n"
        "• *Crossover* — RSI, aşırı satım/alım eşiğini keser\n"
        "• *RSI 50 Cross* — RSI 50 çizgisini keser\n"
        "• *RSI EMA Cross* — RSI kendi EMA'sını keser\n"
        "*Filtreler:* Hacim (düşük hacimli sinyali eler) ve Volatilite "
        "(yatay/durgun hisseyi eler) — Ayarlar'dan açıp kapatabilirsin.\n"
        "İşlemi Midas'tan elle yaparsın (bot otomatik alım-satım YAPMAZ).\n\n"
        "_Bu bot herkese açık — arkadaşların da kendi Telegram'ından "
        "/start diyerek kendi listesini kurabilir._",
        parse_mode="Markdown", reply_markup=main_menu_keyboard(),
    )


async def cmd_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await gate(update)
    if not user:
        return
    if not context.args:
        await update.message.reply_text("Kullanım: `/ekle THYAO`", parse_mode="Markdown")
        return
    await add_to_watchlist(update.effective_chat.id, user, context.args[0])


async def cmd_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await gate(update)
    if not user:
        return
    if not context.args:
        await update.message.reply_text("Kullanım: `/sil THYAO`", parse_mode="Markdown")
        return
    q = context.args[0].strip().upper()
    matches = [s for s in user["watchlist"] if s == q or base_sym(s) == q]
    if not matches:
        await update.message.reply_text(f"❌ `{q}` listende yok.", parse_mode="Markdown")
        return
    for m in matches:
        user["watchlist"].remove(m)
    users.save_async()
    await update.message.reply_text(f"🗑 *{q}* listenden çıkarıldı.", parse_mode="Markdown")


async def cmd_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await gate(update)
    if not user:
        return
    if not context.args:
        await update.message.reply_text("Kullanım: `/fiyat THYAO`", parse_mode="Markdown")
        return
    await lookup_and_show(update, user, context.args[0])


async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_chat.id) != str(config.ADMIN_CHAT_ID):
        return
    all_users = users.DATA["users"]
    total_alerts = sum(len([a for a in u.get("alerts", []) if a.get("active")])
                       for u in all_users.values())
    recent = sorted(all_users.items(), key=lambda kv: kv[1].get("created", ""),
                    reverse=True)[:5]
    lines = [f"👥 Kullanıcı: *{len(all_users)}*",
             f"🔔 Aktif alarm: *{total_alerts}*", "",
             "*Son katılanlar:*"]
    for cid, u in recent:
        uname = f"@{u['username']}" if u.get("username") else cid
        lines.append(f"• {md_escape(u.get('name') or '?')} ({md_escape(uname)}) — "
                     f"{len(u.get('watchlist', []))} hisse")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_chat.id) != str(config.ADMIN_CHAT_ID):
        return
    if not context.args:
        await update.message.reply_text("Kullanım: `/duyuru mesaj`", parse_mode="Markdown")
        return
    msg = "📢 *Duyuru*\n\n" + " ".join(context.args)
    sent = 0
    for cid in list(users.DATA["users"].keys()):
        try:
            await _app.bot.send_message(chat_id=int(cid), text=msg, parse_mode="Markdown")
            sent += 1
        except Exception:
            pass
    await update.message.reply_text(f"✅ {sent} kullanıcıya gönderildi.")


# ============================================================
# WATCHLIST İŞLEMLERİ
# ============================================================
async def add_to_watchlist(chat_id, user, query: str, reply_to=None):
    """Sembolü çözümleyip listeye ekler, sonucu mesajla bildirir."""
    if len(user["watchlist"]) >= config.MAX_WATCHLIST:
        await _send(chat_id, f"⚠️ Liste dolu (max {config.MAX_WATCHLIST}). Önce bir hisse çıkar.")
        return
    quote = await asyncio.to_thread(yahoo_client.resolve_symbol, query)
    if not quote:
        await _send(chat_id,
                    f"❌ `{query.upper()}` bulunamadı.\n"
                    "BIST sembolü (örn `THYAO`) veya ABD sembolü (örn `AAPL`) dene.")
        return
    sym = quote["symbol"]
    users.remember_symbol(quote)
    if sym in user["watchlist"]:
        await _send(chat_id, f"ℹ️ *{base_sym(sym)}* zaten listende.")
        return
    user["watchlist"].append(sym)
    users.save_async()
    await _send(chat_id,
                f"⭐ *{base_sym(sym)}* ({md_escape(quote['name'])}) listene eklendi.\n"
                f"Şu an: {fmt_price(quote['price'], quote['currency'])} "
                f"{chg_emoji(quote['chg_pct'])} {fmt_pct(quote['chg_pct'])}")


async def show_prices(update: Update, user):
    wl = user["watchlist"]
    if not wl:
        await update.message.reply_text(
            f"Liste boş. {BTN_ADD} ile hisse ekle veya sembol yaz (örn `THYAO`).",
            parse_mode="Markdown")
        return
    msg = await update.message.reply_text("📊 Fiyatlar alınıyor...")
    lines = ["📊 *Fiyatlar*\n"]
    for sym in wl:
        quote = await asyncio.to_thread(yahoo_client.get_quote, sym)
        if not quote:
            lines.append(f"▪️ *{base_sym(sym)}* — veri alınamadı")
            continue
        lines.append(f"{chg_emoji(quote['chg_pct'])} *{base_sym(sym)}*  "
                     f"{fmt_price(quote['price'], quote['currency'])}  "
                     f"({fmt_pct(quote['chg_pct'])})")
    lines.append("\n_Detay için hisseye sembolüyle bakabilirsin (örn THYAO yaz)._")
    await msg.edit_text("\n".join(lines), parse_mode="Markdown")


async def show_rsi_scan(update: Update, user):
    wl = user["watchlist"]
    if not wl:
        await update.message.reply_text(
            f"Liste boş. Önce {BTN_ADD} ile hisse ekle.", parse_mode="Markdown")
        return
    st = user["settings"]
    msg = await update.message.reply_text("📈 RSI hesaplanıyor...")
    lines = [f"📈 *RSI Taraması* — {interval_label(st['interval'])}, "
             f"RSI({st['rsi_period']})\n"]
    for sym in wl:
        chart = await asyncio.to_thread(yahoo_client.fetch_chart, sym, st["interval"])
        if not chart:
            lines.append(f"▪️ *{base_sym(sym)}* — veri alınamadı")
            continue
        r = strategy.rsi(chart["closes"], st["rsi_period"])
        if r is None:
            lines.append(f"▪️ *{base_sym(sym)}* — yetersiz veri")
            continue
        if r <= st["rsi_low"]:
            tag = " → 🟢 *aşırı satım*"
        elif r >= st["rsi_high"]:
            tag = " → 🔴 *aşırı alım*"
        else:
            tag = ""
        lines.append(f"{'🟢' if r <= st['rsi_low'] else ('🔴' if r >= st['rsi_high'] else '⚪')} "
                     f"*{base_sym(sym)}*  RSI {fmt_num(r, 1)}{tag}")
    await msg.edit_text("\n".join(lines), parse_mode="Markdown")


async def show_watchlist(update: Update, user):
    wl = user["watchlist"]
    if not wl:
        await update.message.reply_text(
            f"⭐ Listen boş. {BTN_ADD} ile başla!", parse_mode="Markdown")
        return
    rows, row = [], []
    for sym in wl:
        row.append(InlineKeyboardButton(base_sym(sym), callback_data=f"s:show:{sym}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    await update.message.reply_text(
        f"⭐ *Takip Listen* ({len(wl)} hisse)\n"
        "Detay ve işlemler için hisseye dokun:",
        parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(rows))


async def show_add_menu(update: Update, user):
    rows, row = [], []
    for sym in config.POPULAR_BIST:
        row.append(InlineKeyboardButton(sym, callback_data=f"s:pop:{sym}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    await update.message.reply_text(
        "➕ *Hisse Ekle*\n\n"
        "Popüler BIST hisselerinden seç veya sembolü direkt yaz:\n"
        "• BIST: `THYAO`, `SISE`, `HEKTS` ...\n"
        "• ABD: `AAPL`, `NVDA`, `TSLA` ...",
        parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(rows))


# ============================================================
# HİSSE KARTI
# ============================================================
async def lookup_and_show(update: Update, user, query: str):
    msg = await update.message.reply_text("🔍 Aranıyor...")
    quote = await asyncio.to_thread(yahoo_client.resolve_symbol, query)
    if not quote:
        await msg.edit_text(
            f"❌ `{query.upper()}` bulunamadı.\n"
            "BIST için sembol yeterli (örn `THYAO`), ABD için `AAPL` gibi.",
            parse_mode="Markdown")
        return
    users.remember_symbol(quote)
    await msg.delete()
    await show_symbol_card(update.effective_chat.id, user, quote)


async def show_symbol_card(chat_id, user, quote: dict):
    sym = quote["symbol"]
    st = user["settings"]
    chart = await asyncio.to_thread(yahoo_client.fetch_chart, sym, st["interval"])

    rsi_line = ""
    closes = None
    if chart:
        closes = chart["closes"]
        r = strategy.rsi(closes, st["rsi_period"])
        if r is not None:
            zone = ("🟢 aşırı satım" if r <= st["rsi_low"]
                    else ("🔴 aşırı alım" if r >= st["rsi_high"] else "⚪ nötr"))
            rsi_line = (f"\n📈 RSI({st['rsi_period']}, {interval_label(st['interval'])}): "
                        f"*{fmt_num(r, 1)}* {zone}")

    caption = (
        f"*{base_sym(sym)}* — {md_escape(quote['name'])}\n"
        f"💰 *{fmt_price(quote['price'], quote['currency'])}*  "
        f"{chg_emoji(quote['chg_pct'])} {fmt_pct(quote['chg_pct'])} (bugün)"
        f"{rsi_line}"
    )

    in_list = sym in user["watchlist"]
    buttons = [
        [
            InlineKeyboardButton("➖ Listemden Çıkar" if in_list else "⭐ Listeme Ekle",
                                 callback_data=f"s:{'rm' if in_list else 'add'}:{sym}"),
            InlineKeyboardButton("🔔 Alarm Kur", callback_data=f"a:new:{sym}"),
        ],
        [InlineKeyboardButton("💼 Portföye Ekle", callback_data=f"p:start:{sym}")],
    ]
    markup = InlineKeyboardMarkup(buttons)

    if closes and len(closes) >= 2:
        up = closes[-1] >= closes[0]
        url = build_chart_url(f"{base_sym(sym)} ({interval_label(st['interval'])})",
                              closes, up)
        try:
            await _app.bot.send_photo(chat_id=chat_id, photo=url, caption=caption,
                                      parse_mode="Markdown", reply_markup=markup)
            return
        except Exception as e:
            log.warning(f"Grafik gönderilemedi ({sym}): {e}")
    await _app.bot.send_message(chat_id=chat_id, text=caption,
                                parse_mode="Markdown", reply_markup=markup)


# ============================================================
# ALARMLAR
# ============================================================
def alert_desc(al: dict, user: dict) -> str:
    b = base_sym(al["symbol"])
    t = al["type"]
    if t == "price_above":
        return f"📈 {b} ≥ {fmt_num(al['value'])}"
    if t == "price_below":
        return f"📉 {b} ≤ {fmt_num(al['value'])}"
    if t == "rsi_low":
        return f"🟢 {b} RSI ≤ {user['settings']['rsi_low']} (aşırı satım)"
    return f"🔴 {b} RSI ≥ {user['settings']['rsi_high']} (aşırı alım)"


async def show_alerts(update: Update, user):
    active = [a for a in user["alerts"] if a.get("active")]
    rows = [[InlineKeyboardButton(f"🗑 {alert_desc(a, user)}",
                                  callback_data=f"a:del:{a['id']}")]
            for a in active]
    rows.append([InlineKeyboardButton("➕ Yeni Alarm", callback_data="a:ask")])
    text = (f"🔔 *Alarmların* ({len(active)} aktif)\n"
            "Silmek için alarma dokun." if active
            else "🔔 Aktif alarmın yok.\nYeni alarm kurmak için butona dokun "
                 "veya bir hisse kartından *Alarm Kur*'u kullan.")
    await update.message.reply_text(text, parse_mode="Markdown",
                                    reply_markup=InlineKeyboardMarkup(rows))


def alert_type_menu(sym: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📈 Fiyat ÜSTÜNE çıkınca", callback_data=f"a:t:pa:{sym}")],
        [InlineKeyboardButton("📉 Fiyat ALTINA inince",  callback_data=f"a:t:pb:{sym}")],
        [InlineKeyboardButton("🟢 RSI aşırı satıma girince", callback_data=f"a:t:rl:{sym}")],
        [InlineKeyboardButton("🔴 RSI aşırı alıma girince",  callback_data=f"a:t:rh:{sym}")],
    ])


# ============================================================
# PORTFÖY
# ============================================================
async def show_portfolio(update: Update, user):
    pf = user["portfolio"]
    rows = [[InlineKeyboardButton("➕ Pozisyon Ekle", callback_data="p:add")]]
    if not pf:
        await update.message.reply_text(
            "💼 *Portföyün boş.*\n\n"
            "Midas'ta (veya başka aracı kurumda) aldığın hisseleri buraya girersen "
            "anlık kâr/zararını takip ederim.\n\n"
            "Eklemek için butona dokun, sonra şu formatta yaz:\n"
            "`THYAO 10 230,50`  →  _10 adet, 230,50₺ maliyet_",
            parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(rows))
        return

    msg = await update.message.reply_text("💼 Hesaplanıyor...")
    lines = ["💼 *Portföyüm*\n"]
    totals = {}   # currency -> [maliyet, güncel]
    for sym, pos in pf.items():
        quote = await asyncio.to_thread(yahoo_client.get_quote, sym)
        b = base_sym(sym)
        if not quote:
            lines.append(f"▪️ *{b}* — veri alınamadı")
            continue
        qty, cost = pos["qty"], pos["cost"]
        cur = quote["currency"]
        value_now = qty * quote["price"]
        value_cost = qty * cost
        pnl = value_now - value_cost
        pnl_pct = (pnl / value_cost * 100) if value_cost else 0
        t = totals.setdefault(cur, [0.0, 0.0])
        t[0] += value_cost
        t[1] += value_now
        emoji = "🟢" if pnl >= 0 else "🔴"
        sign = "+" if pnl >= 0 else ""
        lines.append(
            f"{emoji} *{b}* — {fmt_num(qty, 0 if qty == int(qty) else 2)} adet\n"
            f"   Maliyet {fmt_price(cost, cur)} → Şu an {fmt_price(quote['price'], cur)}\n"
            f"   K/Z: {sign}{fmt_num(pnl)}{cur_suffix(cur)} ({fmt_pct(pnl_pct)})"
        )
    lines.append("")
    for cur, (vc, vn) in totals.items():
        pnl = vn - vc
        sign = "+" if pnl >= 0 else ""
        pct = (pnl / vc * 100) if vc else 0
        lines.append(f"*Toplam ({cur}):* {fmt_num(vn)}{cur_suffix(cur)}  "
                     f"K/Z {sign}{fmt_num(pnl)}{cur_suffix(cur)} ({fmt_pct(pct)})")

    for sym in pf:
        rows.append([InlineKeyboardButton(f"🗑 {base_sym(sym)} pozisyonunu sil",
                                          callback_data=f"p:rm:{sym}")])
    await msg.edit_text("\n".join(lines), parse_mode="Markdown",
                        reply_markup=InlineKeyboardMarkup(rows))


async def handle_portfolio_input(update: Update, user, text: str):
    """'THYAO 10 230,50' formatını işler."""
    parts = text.split()
    if len(parts) != 3:
        await update.message.reply_text(
            "Format: `SEMBOL ADET MALİYET`\nÖrnek: `THYAO 10 230,50`",
            parse_mode="Markdown")
        return False
    qty = tr_float(parts[1])
    cost = tr_float(parts[2])
    if qty is None or cost is None or qty <= 0 or cost <= 0:
        await update.message.reply_text("❌ Adet ve maliyet sayı olmalı. Örnek: `THYAO 10 230,50`",
                                        parse_mode="Markdown")
        return False
    quote = await asyncio.to_thread(yahoo_client.resolve_symbol, parts[0])
    if not quote:
        await update.message.reply_text(f"❌ `{parts[0].upper()}` bulunamadı.",
                                        parse_mode="Markdown")
        return False
    users.remember_symbol(quote)
    sym = quote["symbol"]
    pf = user["portfolio"]
    if sym in pf:
        old = pf[sym]
        total_qty = old["qty"] + qty
        avg = (old["qty"] * old["cost"] + qty * cost) / total_qty
        pf[sym] = {"qty": total_qty, "cost": round(avg, 4)}
        note = f"\n_(Mevcut pozisyonla birleştirildi: {fmt_num(total_qty, 0)} adet, " \
               f"ort. maliyet {fmt_num(avg)})_"
    else:
        pf[sym] = {"qty": qty, "cost": cost}
        note = ""
    user["pending"] = None
    users.save_async()
    await update.message.reply_text(
        f"✅ *{base_sym(sym)}* portföye eklendi: {fmt_num(qty, 0)} adet @ {fmt_num(cost)}{note}\n\n"
        f"{BTN_PORTFOLIO} ile kâr/zararı görebilirsin.",
        parse_mode="Markdown")
    return True


# ============================================================
# AYARLAR
# ============================================================
def settings_text(user) -> str:
    st = user["settings"]
    return (
        "⚙️ *Ayarların*\n\n"
        f"RSI Periyot: *{st['rsi_period']}*\n"
        f"RSI Smooth (EMA): *{st.get('rsi_smooth', 1)}*\n"
        f"Aşırı Satım eşiği: *{st['rsi_low']}*\n"
        f"Aşırı Alım eşiği: *{st['rsi_high']}*\n"
        f"Zaman Dilimi: *{interval_label(st['interval'])}*\n"
        f"Sinyal Modu: *{st.get('signal_mode', 'Crossover')}*\n"
        f"Hacim Filtresi: *{'Açık ✅' if st.get('vol_filter') else 'Kapalı'}*\n"
        f"Volatilite Filtresi: *{'Açık ✅' if st.get('range_filter') else 'Kapalı'}*\n"
        f"Bildirimler: *{'Açık 🔔' if st['notif'] else 'Kapalı 🔕'}*\n"
        f"Otomatik AL/SAT Sinyali: *{'Açık 📡' if st.get('signals') else 'Kapalı'}*\n\n"
        "_RSI eşikleri hem taramada hem alarmlarda hem de AL/SAT sinyalinde kullanılır._\n"
        "_AL/SAT sinyali açıkken listendeki hisseler otomatik taranır; seçtiğin moda "
        "göre crossover olunca, hacim ve volatilite filtrelerinden geçen sinyaller "
        "(ATR'a göre Stop/Hedef'le birlikte) bildirilir._"
    )


def settings_keyboard(user) -> InlineKeyboardMarkup:
    st = user["settings"]

    def opt_row(prefix, options, current, fmt=str):
        return [InlineKeyboardButton(("✅ " if o == current else "") + fmt(o),
                                     callback_data=f"c:{prefix}:{o}")
                for o in options]

    rows = [
        opt_row("rp", [7, 14, 21], st["rsi_period"]),
        opt_row("rs", [1, 3, 5], st.get("rsi_smooth", 1)),
        opt_row("rl", [20, 25, 30, 35], st["rsi_low"]),
        opt_row("rh", [65, 70, 75, 80], st["rsi_high"]),
        opt_row("int", list(yahoo_client.INTERVALS.keys()), st["interval"],
                fmt=interval_label),
        [InlineKeyboardButton(("✅ " if m == st.get("signal_mode", "Crossover") else "") + m,
                              callback_data=f"c:mode:{i}")
         for i, m in enumerate(config.SIGNAL_MODES)],
        [InlineKeyboardButton(
            "📊 Hacim Filtresi: " + ("Açık ✅" if st.get("vol_filter") else "Kapalı"),
            callback_data="c:volf:x")],
        [InlineKeyboardButton(
            "📈 Volatilite Filtresi: " + ("Açık ✅" if st.get("range_filter") else "Kapalı"),
            callback_data="c:rangef:x")],
        [InlineKeyboardButton(
            "🔕 Bildirimleri Kapat" if st["notif"] else "🔔 Bildirimleri Aç",
            callback_data="c:notif:x")],
        [InlineKeyboardButton(
            "📡 AL/SAT Sinyalini Kapat" if st.get("signals") else "📡 AL/SAT Sinyalini Aç",
            callback_data="c:signals:x")],
    ]
    # satır başlıkları
    rows[0].insert(0, InlineKeyboardButton("RSI:",    callback_data="c:noop:x"))
    rows[1].insert(0, InlineKeyboardButton("Smooth:", callback_data="c:noop:x"))
    rows[2].insert(0, InlineKeyboardButton("Alt:",    callback_data="c:noop:x"))
    rows[3].insert(0, InlineKeyboardButton("Üst:",    callback_data="c:noop:x"))
    return InlineKeyboardMarkup(rows)


async def show_settings(update: Update, user):
    await update.message.reply_text(settings_text(user), parse_mode="Markdown",
                                    reply_markup=settings_keyboard(user))


# ============================================================
# SERBEST METİN
# ============================================================
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await gate(update)
    if not user:
        return
    text = (update.message.text or "").strip()
    if not text:
        return

    # 1) Bekleyen çok adımlı akış var mı?
    pending = user.get("pending")
    if pending:
        action = pending.get("a")
        if action == "alarm_val":
            value = tr_float(text)
            if value is None or value <= 0:
                await update.message.reply_text(
                    "❌ Geçerli bir fiyat yaz (örn `250` veya `250,75`).",
                    parse_mode="Markdown")
                return
            sym = pending["sym"]
            atype = "price_above" if pending["t"] == "pa" else "price_below"
            al = users.add_alert(user, sym, atype, value)
            user["pending"] = None
            users.save_async()
            await update.message.reply_text(
                f"✅ Alarm kuruldu: {alert_desc(al, user)}\n"
                "_Hedef gerçekleşince bildirim alacaksın (alarm 1 kez çalışır)._",
                parse_mode="Markdown")
            return
        if action == "alarm_sym":
            user["pending"] = None
            quote = await asyncio.to_thread(yahoo_client.resolve_symbol, text)
            if not quote:
                await update.message.reply_text(f"❌ `{text.upper()}` bulunamadı.",
                                                parse_mode="Markdown")
                return
            users.remember_symbol(quote)
            await update.message.reply_text(
                f"🔔 *{base_sym(quote['symbol'])}* için alarm türünü seç:",
                parse_mode="Markdown",
                reply_markup=alert_type_menu(quote["symbol"]))
            return
        if action == "port_add":
            await handle_portfolio_input(update, user, text)
            return
        user["pending"] = None   # tanınmayan pending'i temizle

    # 2) Ana menü butonları
    if text == BTN_PRICES:
        await show_prices(update, user)
    elif text == BTN_RSI:
        await show_rsi_scan(update, user)
    elif text == BTN_PORTFOLIO:
        await show_portfolio(update, user)
    elif text == BTN_WATCHLIST:
        await show_watchlist(update, user)
    elif text == BTN_ALERTS:
        await show_alerts(update, user)
    elif text == BTN_ADD:
        await show_add_menu(update, user)
    elif text == BTN_SETTINGS:
        await show_settings(update, user)
    elif text == BTN_HELP:
        await cmd_help(update, context)
    else:
        # 3) Sembol araması
        await lookup_and_show(update, user, text)


# ============================================================
# CALLBACK'LER
# ============================================================
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    chat_id = update.effective_chat.id
    user = users.get_or_create(chat_id)
    if not user["authorized"]:
        await q.answer("🔒 Önce erişim kodunu gir.", show_alert=True)
        return

    data = q.data or ""
    parts = data.split(":")
    ns = parts[0]

    try:
        # ---- Hisse işlemleri ----
        if ns == "s":
            action, payload = parts[1], parts[2]
            if action == "show":
                await q.answer()
                quote = await asyncio.to_thread(yahoo_client.get_quote, payload)
                if quote:
                    users.remember_symbol(quote)
                    await show_symbol_card(chat_id, user, quote)
                else:
                    await _send(chat_id, f"❌ {base_sym(payload)} için veri alınamadı.")
            elif action in ("add", "pop"):
                await q.answer("Ekleniyor...")
                await add_to_watchlist(chat_id, user, payload)
            elif action == "rm":
                if payload in user["watchlist"]:
                    user["watchlist"].remove(payload)
                    users.save_async()
                await q.answer(f"➖ {base_sym(payload)} çıkarıldı", show_alert=False)
                await _send(chat_id, f"🗑 *{base_sym(payload)}* listenden çıkarıldı.")

        # ---- Alarm işlemleri ----
        elif ns == "a":
            action = parts[1]
            if action == "new":
                sym = parts[2]
                await q.answer()
                await _send(chat_id, f"🔔 *{base_sym(sym)}* için alarm türünü seç:",
                            markup=alert_type_menu(sym))
            elif action == "ask":
                await q.answer()
                user["pending"] = {"a": "alarm_sym"}
                users.save_async()
                await _send(chat_id,
                            "Hangi hisse için alarm kuralım? Sembolü yaz (örn `THYAO`):")
            elif action == "t":
                t, sym = parts[2], parts[3]
                active = [a for a in user["alerts"] if a.get("active")]
                if len(active) >= config.MAX_ALERTS:
                    await q.answer(f"⚠️ Alarm limiti dolu (max {config.MAX_ALERTS})",
                                   show_alert=True)
                    return
                if t in ("pa", "pb"):
                    await q.answer()
                    user["pending"] = {"a": "alarm_val", "t": t, "sym": sym}
                    users.save_async()
                    direction = "üstüne çıkınca" if t == "pa" else "altına inince"
                    quote = await asyncio.to_thread(yahoo_client.get_quote, sym)
                    now_line = (f"\nŞu anki fiyat: *{fmt_price(quote['price'], quote['currency'])}*"
                                if quote else "")
                    await _send(chat_id,
                                f"📍 *{base_sym(sym)}* fiyatı hangi değerin {direction} "
                                f"haber vereyim?{now_line}\n\nHedef fiyatı yaz (örn `250,75`):")
                else:
                    atype = "rsi_low" if t == "rl" else "rsi_high"
                    al = users.add_alert(user, sym, atype)
                    await q.answer("✅ Alarm kuruldu")
                    await _send(chat_id,
                                f"✅ Alarm kuruldu: {alert_desc(al, user)}\n"
                                f"_Kontrol sıklığı ~{config.CHECK_INTERVAL // 60} dk; aynı hisse "
                                f"için en erken {config.RSI_ALERT_COOLDOWN_MIN // 60} saatte bir bildirir._")
            elif action == "del":
                aid = int(parts[2])
                before = len(user["alerts"])
                user["alerts"] = [a for a in user["alerts"] if a["id"] != aid]
                if len(user["alerts"]) < before:
                    users.save_async()
                    await q.answer("🗑 Alarm silindi")
                    active = [a for a in user["alerts"] if a.get("active")]
                    rows = [[InlineKeyboardButton(f"🗑 {alert_desc(a, user)}",
                                                  callback_data=f"a:del:{a['id']}")]
                            for a in active]
                    rows.append([InlineKeyboardButton("➕ Yeni Alarm", callback_data="a:ask")])
                    try:
                        await q.edit_message_reply_markup(InlineKeyboardMarkup(rows))
                    except Exception:
                        pass
                else:
                    await q.answer("Alarm zaten silinmiş")

        # ---- Portföy ----
        elif ns == "p":
            action = parts[1]
            if action == "add":
                await q.answer()
                user["pending"] = {"a": "port_add"}
                users.save_async()
                await _send(chat_id,
                            "💼 Pozisyonu şu formatta yaz:\n"
                            "`SEMBOL ADET MALİYET`\n\n"
                            "Örnek: `THYAO 10 230,50`")
            elif action == "start":
                sym = parts[2]
                await q.answer()
                user["pending"] = {"a": "port_add"}
                users.save_async()
                await _send(chat_id,
                            f"💼 *{base_sym(sym)}* için adet ve maliyeti yaz:\n"
                            f"`{base_sym(sym)} ADET MALİYET`\n\n"
                            f"Örnek: `{base_sym(sym)} 10 230,50`")
            elif action == "rm":
                sym = parts[2]
                if sym in user["portfolio"]:
                    del user["portfolio"][sym]
                    users.save_async()
                    await q.answer(f"🗑 {base_sym(sym)} silindi")
                    await _send(chat_id, f"🗑 *{base_sym(sym)}* portföyünden silindi.")
                else:
                    await q.answer("Zaten silinmiş")

        # ---- Ayarlar ----
        elif ns == "c":
            key = parts[1]
            st = user["settings"]
            if key == "noop":
                await q.answer()
                return
            if key == "rp":
                st["rsi_period"] = int(parts[2])
            elif key == "rs":
                st["rsi_smooth"] = int(parts[2])
            elif key == "rl":
                st["rsi_low"] = int(parts[2])
            elif key == "rh":
                st["rsi_high"] = int(parts[2])
            elif key == "int":
                st["interval"] = parts[2]
            elif key == "mode":
                st["signal_mode"] = config.SIGNAL_MODES[int(parts[2])]
            elif key == "volf":
                st["vol_filter"] = not st.get("vol_filter", True)
            elif key == "rangef":
                st["range_filter"] = not st.get("range_filter", True)
            elif key == "notif":
                st["notif"] = not st["notif"]
            elif key == "signals":
                st["signals"] = not st.get("signals", False)
                if not st["signals"]:
                    user["signal_state"] = {}   # kapatınca baseline sıfırlansın
            users.save_async()
            await q.answer("✅ Kaydedildi")
            try:
                await q.edit_message_text(settings_text(user), parse_mode="Markdown",
                                          reply_markup=settings_keyboard(user))
            except Exception:
                pass

    except Exception as e:
        log.error(f"Callback hatası ({data}): {e}", exc_info=True)
        try:
            await q.answer("❌ Bir hata oluştu")
        except Exception:
            pass


# ============================================================
# GÖNDERİM YARDIMCILARI
# ============================================================
async def _send(chat_id, text: str, markup=None):
    try:
        await _app.bot.send_message(chat_id=chat_id, text=text,
                                    parse_mode="Markdown", reply_markup=markup)
    except Exception as e:
        log.error(f"Mesaj gönderilemedi ({chat_id}): {e}")


async def send_to(chat_id, text: str):
    """Alarm döngüsünün kullandığı bildirim fonksiyonu."""
    await _send(int(chat_id), text)


# ============================================================
# BOT KURULUMU
# ============================================================
async def register_bot_commands(app):
    commands = [
        BotCommand("start",    "Ana menü"),
        BotCommand("fiyat",    "Hisse fiyatı (örn /fiyat THYAO)"),
        BotCommand("ekle",     "Listeye hisse ekle"),
        BotCommand("sil",      "Listeden hisse çıkar"),
        BotCommand("yardim",   "Nasıl kullanılır?"),
    ]
    await app.bot.set_my_commands(commands)


def build_application() -> Application:
    global _app
    app = Application.builder().token(config.TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start",  cmd_start))
    app.add_handler(CommandHandler("help",   cmd_help))
    app.add_handler(CommandHandler("yardim", cmd_help))
    app.add_handler(CommandHandler("ekle",   cmd_add))
    app.add_handler(CommandHandler("sil",    cmd_remove))
    app.add_handler(CommandHandler("fiyat",  cmd_price))
    app.add_handler(CommandHandler("admin",  cmd_admin))
    app.add_handler(CommandHandler("duyuru", cmd_broadcast))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    _app = app
    return app
