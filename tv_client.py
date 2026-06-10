"""
TradingView (tvdatafeed) veri istemcisi — SADECE analiz/backtest için.
- Yahoo'nun 60 günlük 15dk limitini aşar (login'siz ~5000 bar ≈ 15dk'da ~7 ay)
- BIST (exchange=BIST) ve ABD (NASDAQ/NYSE/AMEX) destekler
- Çıktı yahoo_client.fetch_history ile AYNI şema → strategy.backtest doğrudan kullanır
- ~15 dk gecikmeli (backtest için önemsiz). Canlı sinyaller yine Yahoo'dan gelir.
- Başarısız olursa None döner; çağıran taraf Yahoo'ya fallback yapar.
"""
import logging
import threading

log = logging.getLogger(__name__)
# tvdatafeed çok log basar — sustur
logging.getLogger("tvDatafeed").setLevel(logging.CRITICAL)

HISTORY_BARS = 5000   # login'siz üst sınır

_tv = None
_lock = threading.Lock()


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


def fetch_history(symbol: str, interval_key: str = "gunluk"):
    """OHLCV dict döner (yahoo_client.fetch_history şeması). Hata/boşsa None."""
    try:
        tv = _get_tv()
        iv = _interval(interval_key)
        tvsym, exchanges = _resolve(symbol)
        df = None
        for exch in exchanges:
            try:
                df = tv.get_hist(symbol=tvsym, exchange=exch,
                                 interval=iv, n_bars=HISTORY_BARS)
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
