"""
İndikatör hesapları + sinyal motoru (saf Python — pandas/numpy gerekmez).
Eski OKX botunun strateji setinin BIST/ABD hisselerine uyarlanmış hali:
- Wilder RSI + RSI'ın EMA yumuşatması (rsi_ma)
- 3 sinyal modu: Crossover / RSI 50 Cross / RSI EMA Cross
- Hacim filtresi (MA × çarpan) + Volatilite (range) filtresi
- ATR bazlı önerilen Stop-Loss / Take-Profit
"""
import config


# ============================================================
# İNDİKATÖRLER
# ============================================================
def rsi(closes, period: int = 14):
    """Wilder RSI — son değeri döner (geriye uyumluluk için tutuldu)."""
    series = rsi_series(closes, period)
    return series[-1] if series and series[-1] is not None else None


def rsi_series(closes, period: int = 14):
    """Her bara hizalı Wilder RSI listesi (ilk `period` eleman None)."""
    n = len(closes)
    if n < period + 1:
        return []

    gains, losses = [], []
    for i in range(1, n):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))

    def _calc(ag, al):
        if al == 0:
            return 100.0
        return 100.0 - 100.0 / (1.0 + ag / al)

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    out = [None] * period           # closes[0..period-1] için RSI tanımsız
    out.append(_calc(avg_gain, avg_loss))   # closes[period]
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        out.append(_calc(avg_gain, avg_loss))
    return out                       # len == n


def ema_series(values, length: int):
    """values üzerinde EMA; None'ları atlar. length=1 → ham seri."""
    if length <= 1:
        return list(values)
    k = 2.0 / (length + 1)
    out, ema = [], None
    for v in values:
        if v is None:
            out.append(None)
            continue
        ema = v if ema is None else (v * k + ema * (1 - k))
        out.append(ema)
    return out


def atr(highs, lows, closes, length: int = 14):
    """Wilder ATR — son değer."""
    n = len(closes)
    if n < length + 1:
        return None
    trs = []
    for i in range(1, n):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)
    a = sum(trs[:length]) / length
    for i in range(length, len(trs)):
        a = (a * (length - 1) + trs[i]) / length
    return a


def _sma_last(values, window: int):
    vals = [v for v in values[-window:] if v is not None]
    return sum(vals) / len(vals) if vals else None


def _crossover(pa, ca, pb, cb):
    return pa <= pb and ca > cb


def _crossunder(pa, ca, pb, cb):
    return pa >= pb and ca < cb


# ============================================================
# SİNYAL MOTORU
# ============================================================
def check_signal(chart: dict, st: dict) -> dict:
    """
    Son bara göre AL/SAT sinyali üretir (eski botun check_signal mantığı).
    Sinyal yoksa None döner. Sinyal varsa bar timestamp + ATR SL/TP içerir.
    """
    closes = chart["closes"]
    highs  = chart["highs"]
    lows   = chart["lows"]
    vols   = chart["volumes"]

    period = int(st.get("rsi_period", 14))
    smooth = int(st.get("rsi_smooth", 1))
    low    = float(st.get("rsi_low", 30))
    high   = float(st.get("rsi_high", 70))
    mode   = st.get("signal_mode", "Crossover")

    need = max(period, config.VOLUME_MA_LEN, config.RANGE_FILTER_LEN) + 5
    if len(closes) < need:
        return None

    rsis = rsi_series(closes, period)
    if len(rsis) < 3 or rsis[-1] is None or rsis[-2] is None:
        return None
    rmas = ema_series(rsis, smooth)
    rsi_now, rsi_prev = rsis[-1], rsis[-2]
    ma_now, ma_prev   = rmas[-1], rmas[-2]
    if ma_now is None or ma_prev is None:
        return None

    long_sig = short_sig = False
    if mode == "RSI 50 Cross":
        long_sig  = _crossover(ma_prev, ma_now, 50, 50)
        short_sig = _crossunder(ma_prev, ma_now, 50, 50)
    elif mode == "RSI EMA Cross":
        long_sig  = _crossover(rsi_prev, rsi_now, ma_prev, ma_now)
        short_sig = _crossunder(rsi_prev, rsi_now, ma_prev, ma_now)
    else:  # Crossover (varsayılan)
        long_sig  = _crossover(ma_prev, ma_now, low, low)
        short_sig = _crossunder(ma_prev, ma_now, high, high)

    if not (long_sig or short_sig):
        return None

    # ---- Hacim filtresi ----
    volume_ok, vol_ratio = True, 0.0
    if st.get("vol_filter", True):
        vma = _sma_last(vols[:-1], config.VOLUME_MA_LEN)   # açık mum hariç
        if vma and vma > 0:
            vol_ratio = vols[-1] / vma
            volume_ok = vols[-1] > vma * config.VOLUME_MULTIPLIER

    # ---- Volatilite (range) filtresi ----
    range_ok, range_pct = True, 0.0
    if st.get("range_filter", True):
        n = config.RANGE_FILTER_LEN
        rh = highs[-(n + 1):-1]      # son N kapanmış mum
        rl = lows[-(n + 1):-1]
        rc = closes[-(n + 1):-1]
        rngs = [(h - l) / c * 100 for h, l, c in zip(rh, rl, rc) if c]
        if rngs:
            range_pct = sum(rngs) / len(rngs)
            range_ok = range_pct >= config.MIN_RANGE_PCT

    if not (volume_ok and range_ok):
        return None

    side = "long" if long_sig else "short"
    price = closes[-1]
    a = atr(highs, lows, closes, config.ATR_LENGTH)

    sl = tp = None
    if a:
        if side == "long":
            sl = price - a * config.SL_ATR_MULT
            tp = price + a * config.TP_ATR_MULT
        else:
            sl = price + a * config.SL_ATR_MULT
            tp = price - a * config.TP_ATR_MULT

    return {
        "side":      side,
        "rsi":       round(rsi_now, 1),
        "rsi_ma":    round(ma_now, 1) if ma_now is not None else None,
        "atr":       a,
        "price":     price,
        "sl":        sl,
        "tp":        tp,
        "vol_ratio": round(vol_ratio, 2),
        "range_pct": round(range_pct, 2),
        "mode":      mode,
        "bar_ts":    chart["timestamps"][-1],
    }
