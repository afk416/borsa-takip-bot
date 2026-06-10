"""
Çok kullanıcılı veri deposu.
- Her Telegram chat_id'si ayrı bir kullanıcı kaydı
- Tüm veri tek JSON olarak GitHub Gist'te saklanır (redeploy'a dayanıklı)
Yapı:
{
  "users": {
    "<chat_id>": {
      "name", "username", "created", "authorized",
      "watchlist": ["THYAO.IS", ...],
      "portfolio": {"THYAO.IS": {"qty": 10, "cost": 230.0}},
      "settings":  {"rsi_period", "rsi_low", "rsi_high", "interval", "notif", "signals"},
      "alerts":    [{"id", "symbol", "type", "value", "active", "last_fired"}],
      "signal_state": {"THYAO.IS": "low"},   # sinyal modu için son RSI bölgesi
      "next_alert_id": 1,
      "pending": None | {...}   # çok adımlı akışlar için bekleyen girdi
    }
  },
  "symbols": {"THYAO.IS": {"name": "...", "currency": "TRY"}}
}
"""
import copy
import logging
import threading
from datetime import datetime, timezone

import config
import github_persist

log = logging.getLogger(__name__)

DATA = {"users": {}, "symbols": {}}
_save_lock = threading.Lock()


def load():
    """Başlangıçta gist'ten yükle."""
    global DATA
    if not github_persist.is_enabled():
        log.warning("GITHUB_TOKEN yok — veriler sadece RAM'de tutulacak!")
        return
    stored = github_persist.load_from_gist()
    if stored.get("users") is not None:
        DATA = stored
        log.info(f"☁️ {len(DATA['users'])} kullanıcı yüklendi")
    DATA.setdefault("users", {})
    DATA.setdefault("symbols", {})


def save_async():
    """Gist'e arka plan thread'inde yaz (handler'ı bloklamasın)."""
    if not github_persist.is_enabled():
        return
    threading.Thread(target=_save_now, daemon=True).start()


def _save_now():
    with _save_lock:
        github_persist.save_to_gist(DATA)


def get_or_create(chat_id, name: str = "", username: str = "") -> dict:
    cid = str(chat_id)
    u = DATA["users"].get(cid)
    if u is None:
        u = {
            "name":       name or "",
            "username":   username or "",
            "created":    datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "authorized": not bool(config.ACCESS_CODE),
            "watchlist":  [],
            "portfolio":  {},
            "settings":   copy.deepcopy(config.DEFAULT_SETTINGS),
            "alerts":     [],
            "signal_state": {},
            "next_alert_id": 1,
            "pending":    None,
        }
        DATA["users"][cid] = u
        log.info(f"👤 Yeni kullanıcı: {cid} ({name})")
        save_async()
    else:
        # isim güncellenmiş olabilir
        if name and u.get("name") != name:
            u["name"] = name
        if username and u.get("username") != username:
            u["username"] = username
    # eski kayıtlara yeni alanları ekle
    u.setdefault("portfolio", {})
    u.setdefault("settings", copy.deepcopy(config.DEFAULT_SETTINGS))
    for k, v in config.DEFAULT_SETTINGS.items():
        u["settings"].setdefault(k, v)   # eski kayıtlara yeni ayar alanlarını ekle
    u.setdefault("alerts", [])
    u.setdefault("signal_state", {})
    u.setdefault("next_alert_id", 1)
    return u


def get(chat_id) -> dict:
    return DATA["users"].get(str(chat_id))


def remember_symbol(quote: dict):
    """Sembolün adını/para birimini global cache'e yaz (görüntüleme için)."""
    DATA["symbols"][quote["symbol"]] = {
        "name":     quote.get("name") or quote["symbol"],
        "currency": quote.get("currency") or "",
    }


def symbol_info(symbol: str) -> dict:
    return DATA["symbols"].get(symbol, {"name": symbol, "currency": ""})


def add_alert(user: dict, symbol: str, alert_type: str, value=None) -> dict:
    al = {
        "id":         user["next_alert_id"],
        "symbol":     symbol,
        "type":       alert_type,   # price_above | price_below | rsi_low | rsi_high
        "value":      value,
        "active":     True,
        "last_fired": None,
    }
    user["next_alert_id"] += 1
    user["alerts"].append(al)
    save_async()
    return al
