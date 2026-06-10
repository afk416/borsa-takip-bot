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
    ReplyKeyboardMarkup, KeyboardButton, BotCommand, ForceReply,
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    filters, ContextTypes,
)

import config
import users
import strategy
import yahoo_client
import tv_client

log = logging.getLogger(__name__)

_app: Application = None

BTN_RSI       = "📈 RSI Tarama"
BTN_PORTFOLIO = "💼 Portföyüm"
BTN_WATCHLIST = "⭐ Listem"
BTN_ALERTS    = "🔔 Alarmlarım"
BTN_ADD       = "➕ Hisse Ekle"
BTN_SETTINGS  = "⚙️ İndikatör Ayarları"
BTN_SUMMARY   = "🧾 İşlem Özeti"
BTN_HELP      = "❓ Yardım"

MENU_BUTTONS = {BTN_RSI, BTN_PORTFOLIO, BTN_WATCHLIST,
                BTN_ADD, BTN_SETTINGS, BTN_SUMMARY, BTN_HELP}


# ============================================================
# YARDIMCILAR
# ============================================================
def main_menu_keyboard():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(BTN_RSI),       KeyboardButton(BTN_WATCHLIST)],
            [KeyboardButton(BTN_PORTFOLIO), KeyboardButton(BTN_ADD)],
            [KeyboardButton(BTN_SETTINGS),  KeyboardButton(BTN_SUMMARY)],
            [KeyboardButton(BTN_HELP)],
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


async def _cancel_pending(user, chat_id):
    """Bekleyen akışı iptal eder ve sorulan mesajı (varsa) Telegram'dan siler."""
    pending = user.get("pending")
    user["pending"] = None
    users.save_async()
    if pending and pending.get("prompt_msg_id"):
        try:
            await _app.bot.delete_message(chat_id=chat_id,
                                          message_id=pending["prompt_msg_id"])
        except Exception:
            pass


async def gate(update: Update, clear_pending: bool = False):
    """Kullanıcıyı kaydet; erişim kodu gerekiyorsa kontrol et.
    Yetkili ise user dict, değilse None döner (mesajı kendisi atar).
    clear_pending=True: komutlarda bekleyen akışı iptal eder (kullanıcı takılmasın)."""
    chat = update.effective_chat
    tg_user = update.effective_user
    user = users.get_or_create(
        chat.id,
        name=(tg_user.full_name if tg_user else ""),
        username=(tg_user.username if tg_user else ""),
    )
    if user["authorized"]:
        if clear_pending and user.get("pending"):
            await _cancel_pending(user, chat.id)
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
    user = await gate(update, clear_pending=True)
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
    user = await gate(update, clear_pending=True)
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
        f"{BTN_RSI} — listendeki hisselerin RSI taraması\n"
        f"{BTN_PORTFOLIO} — elindeki hisseler + kâr/zarar\n"
        f"{BTN_SETTINGS} — RSI periyodu, eşikler, zaman dilimi\n\n"
        "*📡 Otomatik AL/SAT Sinyali:*\n"
        f"{BTN_SETTINGS} → *AL/SAT Sinyalini Aç* dersen, listendeki TÜM hisseler "
        "otomatik taranır:\n"
        "🟢 *AL* — her sinyalde *+1 lot* topla (üst üste AL gelirse lot birikir), "
        "grafikle birlikte bildirilir\n"
        "🔴 *SAT* — ilk SAT'ta biriken *tüm lotları* sat, pozisyonu kapat\n"
        "_Pozisyon yokken SAT gelirse bot tepkisiz kalır — asla açığa satış yapmaz._\n"
        "AL sinyalinde RSI + ATR'a göre önerilen 🛑 Stop / 🎯 Hedef gelir.\n\n"
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
    user = await gate(update, clear_pending=True)
    if not user:
        return
    if not context.args:
        await update.message.reply_text("Kullanım: `/ekle THYAO`", parse_mode="Markdown")
        return
    await add_to_watchlist(update.effective_chat.id, user, context.args[0])


async def cmd_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await gate(update, clear_pending=True)
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
    user = await gate(update, clear_pending=True)
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


async def show_rsi_scan(update: Update, user):
    wl = user["watchlist"]
    if not wl:
        await update.message.reply_text(
            f"Liste boş. Önce {BTN_ADD} ile hisse ekle.", parse_mode="Markdown")
        return
    st = user["settings"]
    msg = await update.message.reply_text("📈 RSI hesaplanıyor...")
    lines = ["📈 *RSI Taraması*\n"]
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


def _collect_quotes(symbols):
    """Senkron — birden çok hissenin quote'unu toplar (to_thread ile çağrılır)."""
    return {s: yahoo_client.get_quote(s) for s in symbols}


def _wl_label(sym, quote) -> str:
    """Grid butonu etiketi: 'THYAO 🔺%1,8' (isim + günlük değişim)."""
    b = base_sym(sym)
    if not quote or quote.get("chg_pct") is None:
        return b
    pct = quote["chg_pct"]
    return f"{b}  {chg_emoji(pct)}%{fmt_num(abs(pct), 1)}"


def watchlist_markup(wl, quotes, edit_mode: bool) -> InlineKeyboardMarkup:
    """Hisseleri 2 sütunlu grid olarak dizer (üstte isim + altında % değişim)."""
    rows, row = [], []
    for sym in wl:
        label = _wl_label(sym, quotes.get(sym))
        if edit_mode:
            row.append(InlineKeyboardButton("❌ " + label, callback_data=f"wl:rm:{sym}"))
        else:
            row.append(InlineKeyboardButton(label, callback_data=f"s:show:{sym}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    if edit_mode:
        rows.append([InlineKeyboardButton("✅ Bitti", callback_data="wl:done")])
    else:
        rows.append([
            InlineKeyboardButton("➕ Hisse Ekle", callback_data="wl:add"),
            InlineKeyboardButton("🗑 Hisse Çıkar", callback_data="wl:edit"),
        ])
        rows.append([InlineKeyboardButton("📊 Liste Analizi", callback_data="wl:analiz")])
    return InlineKeyboardMarkup(rows)


def watchlist_title(wl, edit_mode: bool) -> str:
    if edit_mode:
        return "🗑 *Hisse Çıkar*\nÇıkarmak istediğin hisseye dokun:"
    return (f"⭐ *Takip Listen* ({len(wl)} hisse)\n"
            "Detay için hisseye dokun · alttan ekle/çıkar:")


async def show_watchlist(update: Update, user):
    wl = user["watchlist"]
    if not wl:
        await update.message.reply_text(
            f"⭐ Listen boş.\n{BTN_ADD} ile veya sembol yazarak (örn `THYAO`) başla!",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("➕ Hisse Ekle", callback_data="wl:add")]]))
        return
    msg = await update.message.reply_text("⭐ Liste yükleniyor...")
    quotes = await asyncio.to_thread(_collect_quotes, wl)
    await msg.edit_text(watchlist_title(wl, False), parse_mode="Markdown",
                        reply_markup=watchlist_markup(wl, quotes, False))


async def refresh_watchlist_message(q, user, edit_mode: bool):
    """Callback'ten gelen grid'i yerinde günceller."""
    wl = user["watchlist"]
    if not wl:
        await q.edit_message_text(
            "⭐ Listen boş.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("➕ Hisse Ekle", callback_data="wl:add")]]))
        return
    quotes = await asyncio.to_thread(_collect_quotes, wl)
    try:
        await q.edit_message_text(watchlist_title(wl, edit_mode), parse_mode="Markdown",
                                  reply_markup=watchlist_markup(wl, quotes, edit_mode))
    except Exception:
        pass


async def show_add_menu(chat_id):
    rows, row = [], []
    for sym in config.POPULAR_BIST:
        row.append(InlineKeyboardButton(sym, callback_data=f"s:pop:{sym}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    await _send(chat_id,
                "➕ *Hisse Ekle*\n\n"
                "Popüler BIST hisselerinden seç ya da sembolü direkt yaz:\n"
                "• BIST: `THYAO`, `SISE`, `HEKTS` ...\n"
                "• ABD: `AAPL`, `NVDA`, `TSLA` ...",
                markup=InlineKeyboardMarkup(rows))


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
        [InlineKeyboardButton("➖ Listemden Çıkar" if in_list else "⭐ Listeme Ekle",
                              callback_data=f"s:{'rm' if in_list else 'add'}:{sym}")],
        [InlineKeyboardButton("💼 Portföye Ekle", callback_data=f"p:add1:{sym}")],
        [InlineKeyboardButton("📊 Analiz Et", callback_data=f"an:{sym}")],
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
def _pos_metrics(pos, quote) -> dict:
    qty, cost = pos["qty"], pos["cost"]
    price = quote["price"]
    value_now  = qty * price
    value_cost = qty * cost
    pnl = value_now - value_cost
    return {
        "qty": qty, "cost": cost, "price": price, "cur": quote["currency"],
        "value_now": value_now, "value_cost": value_cost, "pnl": pnl,
        "pnl_pct": (pnl / value_cost * 100) if value_cost else 0.0,
    }


def _qty_fmt(qty) -> str:
    return fmt_num(qty, 0 if qty == int(qty) else 2)


async def build_portfolio_view(user):
    """Portföy ana ekranı: her hisse grid butonu (🟢/🔴 isim + K/Z%)."""
    pf = user["portfolio"]
    if not pf:
        text = ("💼 *Portföyün boş.*\n\n"
                "Midas'ta (veya başka aracı kurumda) aldığın hisseleri buraya girersen "
                "anlık kâr/zararını takip ederim.")
        markup = InlineKeyboardMarkup(
            [[InlineKeyboardButton("➕ Yeni Pozisyon Ekle", callback_data="p:new")]])
        return text, markup

    quotes = await asyncio.to_thread(_collect_quotes, list(pf.keys()))
    rows, row, totals = [], [], {}
    for sym, pos in pf.items():
        q = quotes.get(sym)
        if not q:
            label = f"▪️ {base_sym(sym)}"
        else:
            m = _pos_metrics(pos, q)
            t = totals.setdefault(m["cur"], [0.0, 0.0])
            t[0] += m["value_cost"]
            t[1] += m["value_now"]
            emoji = "🟢" if m["pnl"] >= 0 else "🔴"
            sign = "+" if m["pnl_pct"] >= 0 else ""
            label = f"{emoji} {base_sym(sym)}  {sign}{fmt_num(m['pnl_pct'], 1)}%"
        row.append(InlineKeyboardButton(label, callback_data=f"p:show:{sym}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("➕ Yeni Pozisyon Ekle", callback_data="p:new")])

    lines = ["💼 *Portföyüm*\n"]
    for cur, (vc, vn) in totals.items():
        pnl = vn - vc
        sign = "+" if pnl >= 0 else ""
        pct = (pnl / vc * 100) if vc else 0
        emoji = "🟢" if pnl >= 0 else "🔴"
        lines.append(f"{emoji} *Toplam ({cur}):* {fmt_num(vn)}{cur_suffix(cur)} · "
                     f"K/Z {sign}{fmt_num(pnl)}{cur_suffix(cur)} ({fmt_pct(pct)})")
    lines.append("\n_Detay ve işlem için hisseye dokun._")
    return "\n".join(lines), InlineKeyboardMarkup(rows)


async def build_position_detail(user, sym):
    """Hisse detayı: adet/maliyet/şimdi/KZ kutucukları + Ekle/Sat."""
    pos = user["portfolio"].get(sym)
    if not pos:
        return None, None
    quote = await asyncio.to_thread(yahoo_client.get_quote, sym)
    if not quote:
        return f"❌ {base_sym(sym)} verisi alınamadı.", InlineKeyboardMarkup(
            [[InlineKeyboardButton("‹ Portföy", callback_data="p:back")]])
    m = _pos_metrics(pos, quote)
    emoji = "🟢" if m["pnl"] >= 0 else "🔴"
    sign = "+" if m["pnl"] >= 0 else ""
    rows = [
        [InlineKeyboardButton(f"📦 Adet: {_qty_fmt(m['qty'])}", callback_data="p:noop"),
         InlineKeyboardButton(f"💵 Maliyet: {fmt_price(m['cost'], m['cur'])}",
                              callback_data="p:noop")],
        [InlineKeyboardButton(f"📈 Şimdi: {fmt_price(m['price'], m['cur'])}",
                              callback_data="p:noop"),
         InlineKeyboardButton(f"{emoji} K/Z: {sign}{fmt_num(m['pnl_pct'], 1)}%",
                              callback_data="p:noop")],
        [InlineKeyboardButton("➕ Ekle", callback_data=f"p:add1:{sym}"),
         InlineKeyboardButton("💸 Sat", callback_data=f"p:sell:{sym}")],
        [InlineKeyboardButton("‹ Portföy", callback_data="p:back")],
    ]
    text = (f"*{base_sym(sym)}* — {md_escape(quote['name'])}\n"
            f"Toplam değer: *{fmt_price(m['value_now'], m['cur'])}*  "
            f"({sign}{fmt_num(m['pnl'])}{cur_suffix(m['cur'])} · {fmt_pct(m['pnl_pct'])})")
    return text, InlineKeyboardMarkup(rows)


def build_sell_menu(user, sym):
    """Satış oranı menüsü: %15 / %25 / %50 / %75 / %100."""
    pos = user["portfolio"].get(sym)
    if not pos:
        return None, None
    rows = [
        [InlineKeyboardButton(f"%{p}", callback_data=f"p:sp:{sym}:{p}")
         for p in (15, 25, 50, 75)],
        [InlineKeyboardButton("💯 Tümünü Sat (%100)", callback_data=f"p:sp:{sym}:100")],
        [InlineKeyboardButton("‹ Geri", callback_data=f"p:show:{sym}")],
    ]
    text = (f"💸 *{base_sym(sym)}* — ne kadarını satıyorsun?\n"
            f"Elinde *{_qty_fmt(pos['qty'])}* adet var. Oran seç:")
    return text, InlineKeyboardMarkup(rows)


async def show_portfolio(update: Update, user):
    msg = await update.message.reply_text("💼 Hesaplanıyor...")
    text, markup = await build_portfolio_view(user)
    await msg.edit_text(text, parse_mode="Markdown", reply_markup=markup)


def apply_sell(user, sym, pct: int, sell_price=None, currency=""):
    """Pozisyonun pct%'ini satar. Satılan adedi döner (yoksa None).
    Gerçekleşen K/Z (kullanıcının maliyetine göre) closed_trades'e kaydedilir."""
    pos = user["portfolio"].get(sym)
    if not pos:
        return None
    qty, cost = pos["qty"], pos["cost"]
    sold = qty if pct >= 100 else qty * pct / 100.0

    if sell_price:   # gerçekleşen işlem kaydı (kullanıcının maliyetiyle)
        user.setdefault("closed_trades", []).append({
            "sym":      sym,
            "qty":      round(sold, 6),
            "cost":     cost,            # kullanıcının girdiği maliyet
            "sell":     sell_price,
            "pnl":      (sell_price - cost) * sold,
            "currency": currency,
        })

    if pct >= 100:
        del user["portfolio"][sym]
    else:
        pos["qty"] = round(qty - sold, 6)
    users.save_async()
    return sold


async def handle_portfolio_new(update: Update, user, text: str):
    """'THYAO 10 230,50' → yeni/ek pozisyon."""
    parts = text.split()
    if len(parts) != 3:
        await update.message.reply_text(
            "Format: `SEMBOL ADET MALİYET`\nÖrnek: `THYAO 10 230,50`",
            parse_mode="Markdown")
        return
    quote = await asyncio.to_thread(yahoo_client.resolve_symbol, parts[0])
    if not quote:
        await update.message.reply_text(f"❌ `{parts[0].upper()}` bulunamadı.",
                                        parse_mode="Markdown")
        return
    users.remember_symbol(quote)
    await _apply_add(update, user, quote["symbol"], parts[1], parts[2])


async def handle_portfolio_add_one(update: Update, user, sym, text: str):
    """Belli hisseye 'ADET MALİYET' ekler."""
    parts = text.split()
    if len(parts) != 2:
        await update.message.reply_text(
            "Format: `ADET MALİYET`\nÖrnek: `10 230,50`", parse_mode="Markdown")
        return
    await _apply_add(update, user, sym, parts[0], parts[1])


async def _apply_add(update, user, sym, qty_s, cost_s):
    qty = tr_float(qty_s)
    cost = tr_float(cost_s)
    if qty is None or cost is None or qty <= 0 or cost <= 0:
        await update.message.reply_text("❌ Adet ve maliyet sayı olmalı. Örn: `10 230,50`",
                                        parse_mode="Markdown")
        return
    pf = user["portfolio"]
    if sym in pf:
        old = pf[sym]
        total_qty = old["qty"] + qty
        avg = (old["qty"] * old["cost"] + qty * cost) / total_qty
        pf[sym] = {"qty": round(total_qty, 6), "cost": round(avg, 4)}
        note = (f"\n_(Birleştirildi: {_qty_fmt(total_qty)} adet, "
                f"ort. maliyet {fmt_num(avg)})_")
    else:
        pf[sym] = {"qty": qty, "cost": cost}
        note = ""
    user["pending"] = None
    users.save_async()
    text, markup = await build_position_detail(user, sym)
    await update.message.reply_text(
        f"✅ *{base_sym(sym)}* eklendi: {_qty_fmt(qty)} adet @ {fmt_num(cost)}{note}",
        parse_mode="Markdown")
    if text:
        await _send(update.effective_chat.id, text, markup=markup)


# ============================================================
# AYARLAR
# ============================================================
def settings_text(user) -> str:
    st = user["settings"]
    return (
        "⚙️ *İndikatör Ayarların*\n\n"
        "📐 *İndikatör*\n"
        f"RSI Periyot: *{st['rsi_period']}*\n"
        f"RSI Smooth (EMA): *{st.get('rsi_smooth', 1)}*\n"
        f"Aşırı Satım (LOW): *{st['rsi_low']}*\n"
        f"Aşırı Alım (HIGH): *{st['rsi_high']}*\n"
        f"Zaman Dilimi: *{interval_label(st['interval'])}*\n"
        f"Sinyal Modu: *{st.get('signal_mode', 'Crossover')}*\n\n"
        "📊 *Hacim Filtresi*\n"
        f"Aktif: *{'✅' if st.get('vol_filter') else '❌'}* · "
        f"MA Pencere: *{st.get('vol_ma_len', 20)}* · "
        f"Çarpan: *{st.get('vol_mult', 1.0)}x*\n\n"
        "📈 *Volatilite Filtresi*\n"
        f"Aktif: *{'✅' if st.get('range_filter') else '❌'}* · "
        f"Pencere: *{st.get('range_len', 20)}* mum · "
        f"Min Range: *%{st.get('min_range', 0.1)}*\n\n"
        "🔔 *Genel*\n"
        f"Analiz Sayımı: *{'İşlem bazlı 🔄' if st.get('analysis_mode') == 'islem' else 'Lot bazlı 🛒'}*\n"
        f"Bildirimler: *{'Açık 🔔' if st['notif'] else 'Kapalı 🔕'}*\n"
        f"Otomatik AL/SAT Sinyali: *{'Açık 📡' if st.get('signals') else 'Kapalı'}*\n\n"
        "_Crossover olunca, hacim ve volatilite filtrelerinden geçen sinyaller "
        "ATR'a göre Stop/Hedef'le birlikte bildirilir._"
    )


def settings_keyboard(user) -> InlineKeyboardMarkup:
    st = user["settings"]

    def opt_row(prefix, options, current, fmt=str):
        return [InlineKeyboardButton(("✅ " if o == current else "") + fmt(o),
                                     callback_data=f"c:{prefix}:{o}")
                for o in options]

    rows = [
        # — İNDİKATÖR —
        opt_row("rp", [7, 14, 21, 28], st["rsi_period"]),
        opt_row("rs", [1, 3, 5], st.get("rsi_smooth", 1)),
        opt_row("rl", [20, 25, 30, 35], st["rsi_low"]),
        opt_row("rh", [70, 75, 78, 80], st["rsi_high"]),
        opt_row("int", list(yahoo_client.INTERVALS.keys()), st["interval"],
                fmt=interval_label),
        [InlineKeyboardButton(("✅ " if m == st.get("signal_mode", "Crossover") else "") + m,
                              callback_data=f"c:mode:{i}")
         for i, m in enumerate(config.SIGNAL_MODES)],
        # — HACİM FİLTRESİ —
        [InlineKeyboardButton(
            "📊 Hacim Filtresi: " + ("Açık ✅" if st.get("vol_filter") else "Kapalı ❌"),
            callback_data="c:volf:x")],
        opt_row("vml", [10, 20, 30, 50], st.get("vol_ma_len", 20)),
        opt_row("vmu", [1.0, 1.2, 1.5, 2.0], st.get("vol_mult", 1.0), fmt=lambda x: f"{x}x"),
        # — VOLATİLİTE FİLTRESİ —
        [InlineKeyboardButton(
            "📈 Volatilite Filtresi: " + ("Açık ✅" if st.get("range_filter") else "Kapalı ❌"),
            callback_data="c:rangef:x")],
        opt_row("rfl", [10, 20, 30, 50], st.get("range_len", 20)),
        opt_row("mrp", [0.1, 0.3, 0.5, 1.0], st.get("min_range", 0.1), fmt=lambda x: f"%{x}"),
        # — ANALİZ —
        [InlineKeyboardButton(
            "📐 Analiz Sayımı: " + ("İşlem bazlı 🔄" if st.get("analysis_mode") == "islem"
                                     else "Lot bazlı 🛒"),
            callback_data="c:amode:x")],
        # — GENEL —
        [InlineKeyboardButton(
            "🔕 Bildirimleri Kapat" if st["notif"] else "🔔 Bildirimleri Aç",
            callback_data="c:notif:x")],
        [InlineKeyboardButton(
            "📡 AL/SAT Sinyalini Kapat" if st.get("signals") else "📡 AL/SAT Sinyalini Aç",
            callback_data="c:signals:x")],
    ]
    # satır başlıkları (ilk butona etiket ekle)
    labels = {0: "RSI:", 1: "Smooth:", 2: "Alt:", 3: "Üst:",
              7: "MA:", 8: "Çarpan:", 10: "Pencere:", 11: "MinR:"}
    for idx, lbl in labels.items():
        rows[idx].insert(0, InlineKeyboardButton(lbl, callback_data="c:noop:x"))
    return InlineKeyboardMarkup(rows)


async def show_settings(update: Update, user):
    await update.message.reply_text(settings_text(user), parse_mode="Markdown",
                                    reply_markup=settings_keyboard(user))


async def show_trade_summary(update: Update, user):
    """Kapatılan (satılan) işlemlerin özeti — kullanıcının girdiği maliyetlere göre.
    Analiz Sayımı ayarına uyar: lot bazlı (her satış) / işlem bazlı (hisse bazında net)."""
    closed = user.get("closed_trades", [])
    if not closed:
        await update.message.reply_text(
            "🧾 *İşlem Özeti*\n\nHenüz kapatılan işlem yok.\n"
            "Portföyden bir pozisyonu *Sat* ile kapattığında, gerçekleşen kâr/zararın "
            "(senin girdiğin maliyete göre) burada özetlenir.",
            parse_mode="Markdown")
        return

    is_cycle = user["settings"].get("analysis_mode", "lot") == "islem"

    # Para birimi bazında topla. İşlem bazlı: aynı hissenin satışları 1 işlem (net).
    by_cur = {}   # currency -> {"used","pnl","win","loss"}
    if is_cycle:
        groups = {}   # (currency, sym) -> {"used","pnl"}
        for t in closed:
            g = groups.setdefault((t["currency"], t["sym"]), {"used": 0.0, "pnl": 0.0})
            g["used"] += t["cost"] * t["qty"]
            g["pnl"]  += t["pnl"]
        for (cur, _sym), g in groups.items():
            c = by_cur.setdefault(cur, {"used": 0.0, "pnl": 0.0, "win": 0, "loss": 0})
            c["used"] += g["used"]
            c["pnl"]  += g["pnl"]
            c["win" if g["pnl"] >= 0 else "loss"] += 1
    else:
        for t in closed:
            cur = t["currency"]
            c = by_cur.setdefault(cur, {"used": 0.0, "pnl": 0.0, "win": 0, "loss": 0})
            c["used"] += t["cost"] * t["qty"]
            c["pnl"]  += t["pnl"]
            c["win" if t["pnl"] >= 0 else "loss"] += 1

    mod = "İşlem bazlı" if is_cycle else "Lot bazlı"
    lines = ["🧾 *İşlem Özeti* — kapatılan işlemler",
             f"_Sayım: {mod} · senin girdiğin maliyetlere göre_\n"]
    for cur, c in by_cur.items():
        oran = (c["pnl"] / c["used"] * 100) if c["used"] else 0
        emoji = "🟢" if c["pnl"] >= 0 else "🔴"
        sign = "+" if c["pnl"] >= 0 else ""
        lines.append(f"*{cur}*")
        lines.append(f"💵 Toplam kullanılan: {fmt_num(c['used'])}{cur_suffix(cur)}")
        lines.append(f"🟢 Karlı işlem: {c['win']}")
        lines.append(f"🔴 Zararlı işlem: {c['loss']}")
        lines.append(f"{emoji} Kar/Zarar: {sign}{fmt_num(c['pnl'])}{cur_suffix(cur)} "
                     f"({fmt_pct(oran)})\n")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


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

    # Menü butonuna/komuta basıldıysa bekleyen akışı iptal et (kullanıcı takılmasın)
    pending = user.get("pending")
    if pending and (text.startswith("/") or text in MENU_BUTTONS):
        await _cancel_pending(user, update.effective_chat.id)
        pending = None

    # 1) Bekleyen çok adımlı akış var mı?
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
        if action == "port_new":
            await handle_portfolio_new(update, user, text)
            return
        if action == "port_one":
            await handle_portfolio_add_one(update, user, pending["sym"], text)
            return
        user["pending"] = None   # tanınmayan pending'i temizle

    # 2) Ana menü butonları
    if text == BTN_RSI:
        await show_rsi_scan(update, user)
    elif text == BTN_PORTFOLIO:
        await show_portfolio(update, user)
    elif text == BTN_WATCHLIST:
        await show_watchlist(update, user)
    elif text == BTN_ADD:
        await show_add_menu(update.effective_chat.id)
    elif text == BTN_SETTINGS:
        await show_settings(update, user)
    elif text == BTN_SUMMARY:
        await show_trade_summary(update, user)
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

        # ---- Analiz (backtest) ----
        elif ns == "an":
            sym = parts[1]
            await q.answer("📊 Analiz başlıyor...")
            await analyze_symbol(chat_id, user, sym)

        elif ns == "an2":      # zaman dilimi değiştir (mesajı yerinde günceller)
            sym, ikey = parts[1], parts[2]
            await q.answer("📊 Yeniden hesaplanıyor...")
            await analyze_symbol(chat_id, user, sym, interval_key=ikey,
                                 edit_message=q.message)

        # ---- Liste (grid) düzenleme ----
        elif ns == "wl":
            action = parts[1]
            if action == "add":
                await q.answer()
                await show_add_menu(chat_id)
            elif action == "edit":
                await q.answer("🗑 Çıkarma modu")
                await refresh_watchlist_message(q, user, edit_mode=True)
            elif action == "done":
                await q.answer("✅ Tamam")
                await refresh_watchlist_message(q, user, edit_mode=False)
            elif action == "rm":
                sym = parts[2]
                if sym in user["watchlist"]:
                    user["watchlist"].remove(sym)
                    user.get("signal_state", {}).pop(sym, None)
                    users.save_async()
                    await q.answer(f"❌ {base_sym(sym)} çıkarıldı")
                else:
                    await q.answer("Zaten yok")
                await refresh_watchlist_message(q, user, edit_mode=True)
            elif action == "analiz":
                await q.answer("📊 Liste analiz ediliyor...")
                await analyze_watchlist(chat_id, user)

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
                await ask(user, chat_id,
                          "Hangi hisse için alarm kuralım? Sembolü yaz (örn `THYAO`):",
                          {"a": "alarm_sym"}, placeholder="THYAO")
            elif action == "t":
                t, sym = parts[2], parts[3]
                active = [a for a in user["alerts"] if a.get("active")]
                if len(active) >= config.MAX_ALERTS:
                    await q.answer(f"⚠️ Alarm limiti dolu (max {config.MAX_ALERTS})",
                                   show_alert=True)
                    return
                if t in ("pa", "pb"):
                    await q.answer()
                    direction = "üstüne çıkınca" if t == "pa" else "altına inince"
                    quote = await asyncio.to_thread(yahoo_client.get_quote, sym)
                    now_line = (f"\nŞu anki fiyat: *{fmt_price(quote['price'], quote['currency'])}*"
                                if quote else "")
                    await ask(user, chat_id,
                              f"📍 *{base_sym(sym)}* fiyatı hangi değerin {direction} "
                              f"haber vereyim?{now_line}\n\nHedef fiyatı yaz (örn `250,75`):",
                              {"a": "alarm_val", "t": t, "sym": sym}, placeholder="250,75")
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
            if action == "noop":
                await q.answer()
            elif action == "back":
                await q.answer()
                text, markup = await build_portfolio_view(user)
                await q.edit_message_text(text, parse_mode="Markdown", reply_markup=markup)
            elif action == "show":
                sym = parts[2]
                await q.answer()
                text, markup = await build_position_detail(user, sym)
                if not text:
                    text, markup = await build_portfolio_view(user)
                await q.edit_message_text(text, parse_mode="Markdown", reply_markup=markup)
            elif action == "sell":
                sym = parts[2]
                await q.answer()
                text, markup = build_sell_menu(user, sym)
                if not text:
                    await q.answer("Pozisyon yok", show_alert=True)
                else:
                    await q.edit_message_text(text, parse_mode="Markdown", reply_markup=markup)
            elif action == "sp":      # satış uygula: p:sp:SYM:PCT
                sym, pct = parts[2], int(parts[3])
                pos = user["portfolio"].get(sym)
                quote = await asyncio.to_thread(yahoo_client.get_quote, sym) if pos else None
                sold = apply_sell(user, sym, pct,
                                  sell_price=(quote["price"] if quote else None),
                                  currency=(quote["currency"] if quote else ""))
                if sold is None:
                    await q.answer("Pozisyon yok", show_alert=True)
                else:
                    await q.answer(f"💸 %{pct} satıldı")
                    note = ""
                    if quote:
                        note = (f"\nSatış değeri ≈ "
                                f"{fmt_price(sold * quote['price'], quote['currency'])}")
                    await _send(chat_id,
                                f"💸 *{base_sym(sym)}* — %{pct} satıldı "
                                f"({_qty_fmt(sold)} adet).{note}\n"
                                f"_İşlemi Midas'tan gerçekleştirmeyi unutma._")
                    text, markup = await build_portfolio_view(user)
                    await q.edit_message_text(text, parse_mode="Markdown", reply_markup=markup)
            elif action == "new":     # yeni pozisyon (sembollü)
                await q.answer()
                await ask(user, chat_id,
                          "💼 Yeni pozisyon — şu formatta yaz:\n`SEMBOL ADET MALİYET`\n"
                          "Örnek: `THYAO 10 230,50`",
                          {"a": "port_new"}, placeholder="THYAO 10 230,50")
            elif action == "add1":    # belli hisseye ekle
                sym = parts[2]
                await q.answer()
                await ask(user, chat_id,
                          f"➕ *{base_sym(sym)}* — eklenecek adet ve maliyeti yaz:\n"
                          f"`ADET MALİYET`\nÖrnek: `10 230,50`",
                          {"a": "port_one", "sym": sym}, placeholder="10 230,50")

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
            elif key == "vml":
                st["vol_ma_len"] = int(parts[2])
            elif key == "vmu":
                st["vol_mult"] = float(parts[2])
            elif key == "rangef":
                st["range_filter"] = not st.get("range_filter", True)
            elif key == "rfl":
                st["range_len"] = int(parts[2])
            elif key == "mrp":
                st["min_range"] = float(parts[2])
            elif key == "amode":
                st["analysis_mode"] = "lot" if st.get("analysis_mode") == "islem" else "islem"
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


async def ask(user, chat_id, text: str, pending: dict, placeholder: str = None):
    """Soru sorar (ForceReply ile klavye açılır), bekleyen akışı kaydeder.
    Sorulan mesajın id'si pending'e yazılır → kullanıcı başka komuta geçerse silinir."""
    markup = ForceReply(input_field_placeholder=placeholder) if placeholder else None
    try:
        m = await _app.bot.send_message(chat_id=chat_id, text=text,
                                        parse_mode="Markdown", reply_markup=markup)
        pending["prompt_msg_id"] = m.message_id
    except Exception as e:
        log.error(f"Soru gönderilemedi ({chat_id}): {e}")
    user["pending"] = pending
    users.save_async()


async def send_to(chat_id, text: str):
    """Düz metin bildirim (sinyal/alarm döngüsü)."""
    await _send(int(chat_id), text)


async def send_photo_to(chat_id, photo_url: str, caption: str):
    """Grafikli bildirim; grafik gönderilemezse düz metne düşer."""
    try:
        await _app.bot.send_photo(chat_id=int(chat_id), photo=photo_url,
                                  caption=caption, parse_mode="Markdown")
    except Exception as e:
        log.warning(f"Grafik gönderilemedi ({chat_id}): {e}")
        await _send(int(chat_id), caption)


# ============================================================
# ANALİZ (backtest)
# ============================================================
def analyze_period_buttons(sym, current_key) -> InlineKeyboardMarkup:
    opts = [("15dk", "15dk·60g"), ("1saat", "1saat·2y"),
            ("gunluk", "Günlük·2y"), ("haftalik", "Haftalık·5y")]
    row = [InlineKeyboardButton(("✅ " if k == current_key else "") + lbl,
                                callback_data=f"an2:{sym}:{k}")
           for k, lbl in opts]
    return InlineKeyboardMarkup([row])


async def _fetch_backtest_chart(sym, ikey):
    """Analiz için OHLCV çeker: önce TradingView (uzun geçmiş), olmazsa Yahoo.
    Döner (chart, kaynak_adı) — chart None ise veri yok."""
    if tv_client.is_enabled():
        chart = await asyncio.to_thread(tv_client.fetch_history, sym, ikey)
        if chart and len(chart["closes"]) >= 40:
            return chart, "TradingView"
    yh_iv, yh_rng, _ = yahoo_client.BACKTEST_RANGE.get(
        ikey, yahoo_client.BACKTEST_RANGE["gunluk"])
    chart = await asyncio.to_thread(yahoo_client.fetch_history, sym, yh_iv, yh_rng)
    if chart and len(chart["closes"]) >= 40:
        return chart, "Yahoo"
    return None, ""


async def analyze_watchlist(chat_id, user):
    """Listedeki tüm hisseleri tablo halinde analiz eder (hisse·karlı·zararlı·K/Z%)."""
    wl = user["watchlist"]
    if not wl:
        await _send(chat_id, "⭐ Listen boş. Önce hisse ekle.")
        return
    st = user["settings"]
    ikey = st.get("interval", "gunluk")
    is_cycle = st.get("analysis_mode", "lot") == "islem"

    try:
        msg = await _app.bot.send_message(
            chat_id=chat_id, text=f"📊 Liste analiz ediliyor (0/{len(wl)})...")
    except Exception:
        return

    rows = []
    for idx, sym in enumerate(wl, 1):
        chart, _src = await _fetch_backtest_chart(sym, ikey)
        if chart is None:
            rows.append((base_sym(sym), None))
        else:
            res = await asyncio.to_thread(strategy.backtest, chart, st)
            rows.append((base_sym(sym), res))
        try:
            await msg.edit_text(f"📊 Liste analiz ediliyor ({idx}/{len(wl)})...")
        except Exception:
            pass

    # Tablo (monospace)
    tbl = [f"{'Hisse':<7}{'Kâr':>4}{'Zar':>4}{'K/Z%':>9}"]
    for name, res in rows:
        if res is None:
            tbl.append(f"{name:<7}{'-':>4}{'-':>4}{'-':>9}")
            continue
        if is_cycle:
            w, l, p = res["cycle_wins"], res["cycle_losses"], res["cycle_total_pct"]
        else:
            w, l, p = res["wins"], res["losses"], res["total_pct"]
        val = fmt_num(p, 1)
        if p >= 0:
            val = "+" + val
        tbl.append(f"{name:<7}{w:>4}{l:>4}{val:>9}")

    mod_adi = "İşlem bazlı" if is_cycle else "Lot bazlı"
    text = (f"📊 *Liste Analizi*\n"
            f"_{mod_adi} · {interval_label(ikey)} · geçmiş veriyle backtest_\n"
            f"```\n" + "\n".join(tbl) + "\n```\n"
            "_Kâr/Zar = kârlı/zararlı işlem sayısı. Yatırım tavsiyesi değildir._")
    try:
        await msg.edit_text(text, parse_mode="Markdown")
    except Exception as e:
        log.error(f"Liste analizi mesajı düzenlenemedi: {e}")


async def analyze_symbol(chat_id, user, sym, interval_key=None, edit_message=None):
    """Backtest: lot biriktirmeli AL→SAT, seçilen zaman diliminde."""
    st = user["settings"]
    ikey = interval_key or st.get("interval", "gunluk")
    iv_label = interval_label(ikey)

    try:
        if edit_message is not None:
            msg = edit_message
            await msg.edit_text(f"📊 {iv_label} analiz ediliyor...")
        else:
            msg = await _app.bot.send_message(
                chat_id=chat_id, text=f"📊 {iv_label} analiz ediliyor, bekle...")
    except Exception:
        return

    # Önce TradingView (uzun geçmiş), olmazsa Yahoo'ya fallback
    chart, src = await _fetch_backtest_chart(sym, ikey)
    if chart is None:
        await msg.edit_text(f"❌ {base_sym(sym)} için yeterli geçmiş veri yok.")
        return

    res = await asyncio.to_thread(strategy.backtest, chart, st)

    # Dönem etiketi: kaç mum, kaç gün (verinin kendisinden)
    span_days = max(1, (chart["timestamps"][-1] - chart["timestamps"][0]) // 86400)
    period_label = f"{src} · {iv_label} · {res['bars']} mum (~{span_days} gün)"

    header = (f"📊 *{base_sym(sym)} — Geçmiş Analizi*\n"
              f"_Ayar: RSI({st['rsi_period']}) · {st.get('signal_mode', 'Crossover')} · "
              f"{period_label}_\n\n")

    is_cycle = st.get("analysis_mode", "lot") == "islem"
    # Moda göre metrik seç
    if is_cycle:
        n_trade = res["cycles"]
        n_win, n_loss = res["cycle_wins"], res["cycle_losses"]
        tot, avg = res["cycle_total_pct"], res["cycle_avg_pct"]
        best, worst = res["cycle_best"], res["cycle_worst"]
    else:
        n_trade = res["trades"]
        n_win, n_loss = res["wins"], res["losses"]
        tot, avg = res["total_pct"], res["avg_pct"]
        best, worst = res["best"], res["worst"]

    if n_trade == 0:
        body = ("Bu ayarlarla bu dönemde tamamlanmış (AL→SAT) işlem oluşmadı."
                "\n_Daha uzun bir zaman dilimi (👇) ya da farklı mod/eşik deneyebilirsin._")
        if res["open_lots"]:
            body += (f"\n_(Şu an {res['open_lots']} AL sinyali birikmiş ama "
                     "henüz SAT gelmemiş.)_")
    else:
        win_rate = n_win / n_trade * 100
        tsign = "+" if tot >= 0 else ""
        asign = "+" if avg >= 0 else ""
        emoji = "🟢" if tot >= 0 else "🔴"
        if is_cycle:
            baslik = ("🔄 *İŞLEM BAZLI SAYIM*\n"
                      "_Bir AL→SAT turu = 1 işlem; turdaki tüm lotların NET sonucu._\n\n"
                      f"🔄 Toplam işlem: *{n_trade}*\n"
                      f"🛒 Toplam alınan lot: *{res['total_lots']}*\n")
            son = (f"_Başarı %{fmt_num(win_rate, 0)} · işlem başına ort. "
                   f"{asign}{fmt_num(avg, 1)}%_\n"
                   f"_En iyi işlem: +{fmt_num(best, 1)}% · en kötü: {fmt_num(worst, 1)}%_")
        else:
            baslik = ("🛒 *LOT BAZLI SAYIM*\n"
                      "_Her AL'da +1 lot; her lot ayrı işlem sayılır._\n\n"
                      f"🛒 Toplam alınan lot: *{res['total_lots']}*\n"
                      f"🔄 Toplam Al-Sat (kapanan lot): *{n_trade}*\n")
            son = (f"_Döngü: {res['cycles']} · başarı %{fmt_num(win_rate, 0)} · "
                   f"lot başına ort. {asign}{fmt_num(avg, 1)}%_\n"
                   f"_En iyi lot: +{fmt_num(best, 1)}% · en kötü: {fmt_num(worst, 1)}%_")
        body = (
            f"{baslik}"
            f"🟢 Karlı işlem: *{n_win}*\n"
            f"🔴 Zararlı işlem: *{n_loss}*\n"
            f"{emoji} Kar/Zarar: *{tsign}{fmt_num(tot, 1)}%*\n\n"
            f"{son}"
        )
        if res["open_lots"]:
            body += (f"\n_(Şu an {res['open_lots']} lot açık — son AL'lar henüz "
                     "satılmadı, dahil değil.)_")

    note = ("\n\n_⚠️ Geçmiş performans geleceği garanti etmez. Komisyon/vergi hariç. "
            "Farklı zaman dilimi için aşağıdaki butonları kullan (15dk Yahoo'da en fazla "
            "60 gün; daha uzun geçmiş için 1 saat/günlük)._")
    try:
        await msg.edit_text(header + body + note, parse_mode="Markdown",
                            reply_markup=analyze_period_buttons(sym, ikey))
    except Exception as e:
        log.error(f"Analiz mesajı düzenlenemedi: {e}")


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
