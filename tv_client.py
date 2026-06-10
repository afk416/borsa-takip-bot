"""
TradingView (tvdatafeed) veri istemcisi — SADECE analiz/backtest için.
- Yahoo'nun 60 günlük 15dk limitini aşar (login'siz ~5000 bar ≈ 15dk'da ~7 ay)
- BIST (exchange=BIST) ve ABD (NASDAQ/NYSE/AMEX) destekler
- Çıktı yahoo_client.fetch_history ile AYNI şema → strategy.backtest doğrudan kullanır
- ~15 dk gecikmeli (backtest için önemsiz). Canlı sinyaller yine Yahoo'dan gelir.
- Başarısız olursa None döner; çağıran taraf Yahoo'ya fallback yapar.
"""
import time
import logging
import threading

log = logging.getLogger(__name__)
# tvdatafeed çok log basar — sustur
logging.getLogger("tvDatafeed").setLevel(logging.CRITICAL)

HISTORY_BARS = 5000   # login'siz üst sınır
CACHE_TTL = 3600      # çekilen veri 1 saat cache'lenir (tek+liste analizi tutarlı)

_tv = None
_lock = threading.Lock()
_cache = {}           # (symbol, interval_key) -> (zaman, data)


def is_enabled() -> bool:
    try:
        import tvDatafeed  # noqa: F401
        return True
    except Exception:
        return False


def _get_tv():
    global _tv
    if _tv is None:
        with _lock:
            if _tv is None:
                from tvDatafeed import TvDatafeed
                _tv = TvDatafeed()   # login'siz
    return _tv


def _interval(interval_key):
    from tvDatafeed import Interval
    return {
        "15dk":     Interval.in_15_minute,
        "1saat":    Interval.in_1_hour,
        "gunluk":   Interval.in_daily,
        "haftalik": Interval.in_weekly,
    }.get(interval_key, Interval.in_daily)


def _resolve(symbol: str):
    """yahoo sembolü → (tv_symbol, denenecek borsalar)."""
    s = symbol.strip().upper()
    if s.endswith(".IS"):
        return s[:-3], ["BIST"]
    return s, ["NASDAQ", "NYSE", "AMEX"]


def _fetch_once(symbol: str, interval_key: str):
    try:
        tv = _get_tv()
        iv = _interval(interval_key)
        tvsym, exchanges = _resolve(symbol)
        df = None
        for exch in exchanges:
            # ABD: extended hours (pre/post market) — TradingView ile aynı veri.
            # BIST: tek seans, extended yok.
            ext = (exch != "BIST")
            try:
                df = tv.get_hist(symbol=tvsym, exchange=exch, interval=iv,
                                 n_bars=HISTORY_BARS, extended_session=ext)
            except Exception:
                df = None
            if df is not None and len(df) > 0:
                break
        if df is None or len(df) == 0:
            return None

        closes = [float(x) for x in df["close"]]
        highs  = [float(x) for x in df["high"]]
        lows   = [float(x) for x in df["low"]]
        vols   = ([float(x) for x in df["volume"]]
                  if "volume" in df.columns else [0.0] * len(closes))
        ts     = [int(t.timestamp()) for t in df.index]
        return {"closes": closes, "highs": highs, "lows": lows,
                "volumes": vols, "timestamps": ts, "meta": {}}
    except Exception as e:
        log.warning(f"tvdatafeed hatası ({symbol}/{interval_key}): {e}")
        return None


def fetch_history(symbol: str, interval_key: str = "gunluk", retries: int = 3):
    """OHLCV dict döner. 1 saat cache + retry (tvdatafeed ara sıra boş döner).
    Hepsi boşsa None. Cache sayesinde liste analizi/açık lot tekrar tekrar çekmez."""
    key = (symbol, interval_key)
    cached = _cache.get(key)
    if cached and (time.time() - cached[0]) < CACHE_TTL:
        return cached[1]
    global _tv
    for attempt in range(retries + 1):
        out = _fetch_once(symbol, interval_key)
        if out:
            _cache[key] = (time.time(), out)
            return out
        if attempt == 1:        # 2. denemede de boşsa bağlantıyı tazele
            with _lock:
                _tv = None
    return None
