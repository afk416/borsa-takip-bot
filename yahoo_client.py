"""
Yahoo Finance veri istemcisi (ücretsiz, API key gerektirmez).
- BIST hisseleri: SEMBOL.IS (örn THYAO.IS) — veri ~15 dk gecikmeli
- ABD hisseleri: düz sembol (örn AAPL)
- v8 chart endpoint'i kullanılır (crumb/cookie gerektirmez)
"""
import json
import time
import logging
import requests

log = logging.getLogger(__name__)

HOSTS = [
    "https://query1.finance.yahoo.com",
    "https://query2.finance.yahoo.com",
]
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

# interval_key -> (yahoo interval, yahoo range, görünen ad)
INTERVALS = {
    "15dk":     ("15m", "5d",  "15 Dakika"),
    "1saat":    ("60m", "1mo", "1 Saat"),
    "gunluk":   ("1d",  "6mo", "Günlük"),
    "haftalik": ("1wk", "2y",  "Haftalık"),
}

# Backtest için: aynı zaman diliminde Yahoo'nun verdiği EN UZUN geçmiş
# interval_key -> (yahoo interval, yahoo range, görünen dönem etiketi)
BACKTEST_RANGE = {
    "15dk":     ("15m", "60d",  "son ~60 gün · 15dk"),
    "1saat":    ("60m", "730d", "son ~2 yıl · 1 saat"),
    "gunluk":   ("1d",  "2y",   "son 2 yıl · günlük"),
    "haftalik": ("1wk", "5y",   "son 5 yıl · haftalık"),
}

CHART_CACHE_TTL = 120   # saniye
QUOTE_CACHE_TTL = 60

_chart_cache = {}   # (symbol, interval_key) -> (ts, data)
_quote_cache = {}   # symbol -> (ts, data)


def _get(url: str, params: dict):
    """İki Yahoo host'unu sırayla dener."""
    last_err = None
    for host in HOSTS:
        try:
            r = requests.get(host + url, params=params, headers=HEADERS, timeout=15)
            if r.status_code == 404:
                return None   # sembol yok — diğer host'u denemeye gerek yok
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_err = e
    log.warning(f"Yahoo isteği başarısız ({url}): {last_err}")
    return None


def _chart_raw(symbol: str, yh_interval: str, yh_range: str):
    data = _get(f"/v8/finance/chart/{symbol}",
                {"interval": yh_interval, "range": yh_range})
    if not data:
        return None
    result = (data.get("chart") or {}).get("result") or []
    if not result:
        return None
    return result[0]


def _extract(res):
    """Yahoo chart sonucundan hizalı OHLCV serisi çıkarır."""
    if not res:
        return None
    quote = ((res.get("indicators") or {}).get("quote") or [{}])[0]
    closes_raw = quote.get("close") or []
    highs_raw  = quote.get("high") or []
    lows_raw   = quote.get("low") or []
    vols_raw   = quote.get("volume") or []
    timestamps_raw = res.get("timestamp") or []

    closes, highs, lows, volumes, timestamps = [], [], [], [], []
    for i, ts in enumerate(timestamps_raw):
        c = closes_raw[i] if i < len(closes_raw) else None
        if c is None:
            continue   # boş mumu atla (hizayı korur)
        closes.append(float(c))
        timestamps.append(ts)
        h = highs_raw[i] if i < len(highs_raw) else None
        l = lows_raw[i] if i < len(lows_raw) else None
        v = vols_raw[i] if i < len(vols_raw) else None
        highs.append(float(h) if h is not None else float(c))
        lows.append(float(l) if l is not None else float(c))
        volumes.append(float(v) if v is not None else 0.0)

    if not closes:
        return None
    return {"closes": closes, "highs": highs, "lows": lows,
            "volumes": volumes, "timestamps": timestamps,
            "meta": res.get("meta") or {}}


def fetch_chart(symbol: str, interval_key: str = "gunluk"):
    """
    OHLCV serisi + meta döner (hepsi aynı uzunlukta, hizalı):
    {"closes", "highs", "lows", "volumes", "timestamps", "meta"}
    """
    key = (symbol, interval_key)
    cached = _chart_cache.get(key)
    if cached and time.time() - cached[0] < CHART_CACHE_TTL:
        return cached[1]

    yh_interval, yh_range, _ = INTERVALS.get(interval_key, INTERVALS["gunluk"])
    out = _extract(_chart_raw(symbol, yh_interval, yh_range))
    if out:
        _chart_cache[key] = (time.time(), out)
    return out


def fetch_history(symbol: str, yh_interval: str = "1d", yh_range: str = "1y"):
    """Backtest için uzun geçmiş (varsayılan 1 yıl günlük). Cache'siz."""
    return _extract(_chart_raw(symbol, yh_interval, yh_range))


def get_quote(symbol: str):
    """
    Anlık fiyat bilgisi:
    {"symbol", "price", "prev", "chg_pct", "currency", "name"}
    """
    cached = _quote_cache.get(symbol)
    if cached and time.time() - cached[0] < QUOTE_CACHE_TTL:
        return cached[1]

    res = _chart_raw(symbol, "1d", "1d")
    if not res:
        return None
    meta = res.get("meta") or {}
    price = meta.get("regularMarketPrice")
    if price is None:
        return None
    prev = meta.get("previousClose") or meta.get("chartPreviousClose")
    chg_pct = None
    if prev:
        chg_pct = (float(price) - float(prev)) / float(prev) * 100.0

    out = {
        "symbol":   symbol,
        "price":    float(price),
        "prev":     float(prev) if prev else None,
        "chg_pct":  chg_pct,
        "currency": meta.get("currency") or "",
        "name":     meta.get("shortName") or meta.get("longName") or symbol,
    }
    _quote_cache[symbol] = (time.time(), out)
    return out


def resolve_symbol(query: str):
    """
    Kullanıcının yazdığı sembolü Yahoo sembolüne çevirir.
    "THYAO" -> THYAO.IS (önce BIST denenir), "AAPL" -> AAPL
    Döner: quote dict veya None
    """
    q = query.strip().upper().replace("İ", "I")
    if not q or len(q) > 12 or not q.replace(".", "").replace("-", "").isalnum():
        return None

    candidates = [q] if "." in q else [f"{q}.IS", q]
    for cand in candidates:
        quote = get_quote(cand)
        if quote:
            return quote
    return None
