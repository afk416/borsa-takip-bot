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

    period = int(st.get("rsi_period", 21))
    smooth = int(st.get("rsi_smooth", 1))
    low    = float(st.get("rsi_low", 25))
    high   = float(st.get("rsi_high", 78))
    mode   = st.get("signal_mode", "Crossover")

    vol_ma_len = int(st.get("vol_ma_len", config.VOLUME_MA_LEN))
    vol_mult   = float(st.get("vol_mult", config.VOLUME_MULTIPLIER))
    range_len  = int(st.get("range_len", config.RANGE_FILTER_LEN))
    min_range  = float(st.get("min_range", config.MIN_RANGE_PCT))

    need = max(period, vol_ma_len, range_len) + 5
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
        vma = _sma_last(vols[:-1], vol_ma_len)   # açık mum hariç
        if vma and vma > 0:
            vol_ratio = vols[-1] / vma
            volume_ok = vols[-1] > vma * vol_mult

    # ---- Volatilite (range) filtresi ----
    range_ok, range_pct = True, 0.0
    if st.get("range_filter", True):
        n = range_len
        rh = highs[-(n + 1):-1]      # son N kapanmış mum
        rl = lows[-(n + 1):-1]
        rc = closes[-(n + 1):-1]
        rngs = [(h - l) / c * 100 for h, l, c in zip(rh, rl, rc) if c]
        if rngs:
            range_pct = sum(rngs) / len(rngs)
            range_ok = range_pct >= min_range

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


# ============================================================
# BACKTEST (geçmiş analiz — long-only)
# ============================================================
def backtest(chart: dict, st: dict) -> dict:
    """
    Geçmiş veride lot-biriktirme mantığıyla simüle eder (canlı motorla birebir):
    HER AL sinyalinde +1 lot toplanır (o barın fiyatından), İLK SAT sinyalinde
    biriken TÜM lotlar o barın fiyatından satılır. Pozisyon yokken SAT'a tepkisiz.
    Her kapanan lot ayrı bir "işlem" sayılır (kendi alış fiyatına göre K/Z).
    Açık kalan (SAT görmemiş) lotlar işlem sayılmaz.
    Döner: {trades, wins, losses, total_pct, avg_pct, best, worst,
            cycles, total_lots, open_lots, bars}
    """
    closes = chart["closes"]
    highs  = chart["highs"]
    lows   = chart["lows"]
    vols   = chart["volumes"]
    n = len(closes)

    period = int(st.get("rsi_period", 21))
    smooth = int(st.get("rsi_smooth", 1))
    low    = float(st.get("rsi_low", 25))
    high   = float(st.get("rsi_high", 78))
    mode   = st.get("signal_mode", "Crossover")
    vf  = st.get("vol_filter", True)
    vml = int(st.get("vol_ma_len", config.VOLUME_MA_LEN))
    vmu = float(st.get("vol_mult", config.VOLUME_MULTIPLIER))
    rf  = st.get("range_filter", True)
    rl  = int(st.get("range_len", config.RANGE_FILTER_LEN))
    mr  = float(st.get("min_range", config.MIN_RANGE_PCT))

    need = max(period, vml, rl) + 5

    # İndikatörleri TEK kez hesapla (O(n)) — canlı check_signal ile aynı mantık
    rsis = rsi_series(closes, period)
    rmas = ema_series(rsis, smooth)

    open_lots = []     # açık lotların alış fiyatları
    trades = []        # LOT bazlı: kapanan her lotun kar/zarar yüzdesi
    cycle_trades = []  # İŞLEM bazlı: her AL→SAT döngüsünün NET kar/zarar yüzdesi
    total_lots = 0     # toplam alınan lot (AL sinyali) sayısı
    total_spent = 0.0  # harcanan = SADECE KAPATILAN lotların alış fiyatları toplamı

    for i in range(need, n):
        rn, rp = rsis[i], rsis[i - 1]
        mn, mp = rmas[i], rmas[i - 1]
        if rn is None or rp is None or mn is None or mp is None:
            continue

        if mode == "RSI 50 Cross":
            long_sig  = _crossover(mp, mn, 50, 50)
            short_sig = _crossunder(mp, mn, 50, 50)
        elif mode == "RSI EMA Cross":
            long_sig  = _crossover(rp, rn, mp, mn)
            short_sig = _crossunder(rp, rn, mp, mn)
        else:
            long_sig  = _crossover(mp, mn, low, low)
            short_sig = _crossunder(mp, mn, high, high)
        if not (long_sig or short_sig):
            continue

        # Hacim filtresi (açık mum hariç: i-vml .. i-1) — canlı ile aynı
        if vf:
            win = [v for v in vols[i - vml:i] if v is not None]
            if win:
                vma = sum(win) / len(win)
                if vma > 0 and not (vols[i] > vma * vmu):
                    continue

        # Volatilite filtresi (son rl kapanmış mum) — canlı ile aynı
        if rf:
            rngs = [(highs[j] - lows[j]) / closes[j] * 100
                    for j in range(i - rl, i) if closes[j]]
            if rngs and (sum(rngs) / len(rngs)) < mr:
                continue

        if long_sig:
            open_lots.append(closes[i])    # her AL'da +1 lot biriktir
            total_lots += 1
        elif short_sig and open_lots:
            sat = closes[i]
            valid = [al for al in open_lots if al > 0]
            # LOT bazlı: her lot ayrı işlem; harcanan = kapatılan lotun alışı
            for al in valid:
                trades.append((sat - al) / al * 100.0)
                total_spent += al          # SADECE kapatılan lot sayılır
            # İŞLEM bazlı: bu döngünün net sonucu (sermaye ağırlıklı)
            if valid:
                cost = sum(valid)
                proceeds = sat * len(valid)
                cycle_trades.append((proceeds - cost) / cost * 100.0)
            open_lots = []
        # short + açık lot yok → tepkisiz (asla short açmaz)

    wins = sum(1 for t in trades if t > 0)
    losses = len(trades) - wins
    total = sum(trades)
    c_wins = sum(1 for c in cycle_trades if c > 0)
    c_losses = len(cycle_trades) - c_wins
    c_total = sum(cycle_trades)
    return {
        # LOT bazlı (her lot ayrı işlem)
        "trades":     len(trades),     # kapanan lot (= al-sat) sayısı
        "wins":       wins,
        "losses":     losses,
        "total_pct":  total,
        "avg_pct":    (total / len(trades)) if trades else 0.0,
        "best":       max(trades) if trades else 0.0,
        "worst":      min(trades) if trades else 0.0,
        # İŞLEM bazlı (her AL→SAT döngüsü = 1 işlem, net sonuç)
        "cycles":       len(cycle_trades),   # tamamlanan döngü/işlem sayısı
        "cycle_wins":   c_wins,
        "cycle_losses": c_losses,
        "cycle_total_pct": c_total,
        "cycle_avg_pct": (c_total / len(cycle_trades)) if cycle_trades else 0.0,
        "cycle_best":   max(cycle_trades) if cycle_trades else 0.0,
        "cycle_worst":  min(cycle_trades) if cycle_trades else 0.0,
        # ortak
        "total_lots":  total_lots,      # toplam alınan lot
        "total_spent": total_spent,     # harcanan = lot alış fiyatları toplamı
        "open_lots":   len(open_lots),  # hâlâ açık (satılmamış) lot
        "bars":        n,
    }


def open_lot_timeline(chart: dict, st: dict):
    """Her bar için o an AÇIK (alınmış ama satılmamış) lot sayısı.
    Döner: [(timestamp, open_count), ...]. backtest ile aynı sinyal mantığı."""
    closes = chart["closes"]
    highs  = chart["highs"]
    lows   = chart["lows"]
    vols   = chart["volumes"]
    ts     = chart["timestamps"]
    n = len(closes)

    period = int(st.get("rsi_period", 21))
    smooth = int(st.get("rsi_smooth", 1))
    low    = float(st.get("rsi_low", 25))
    high   = float(st.get("rsi_high", 78))
    mode   = st.get("signal_mode", "Crossover")
    vf  = st.get("vol_filter", True)
    vml = int(st.get("vol_ma_len", config.VOLUME_MA_LEN))
    vmu = float(st.get("vol_mult", config.VOLUME_MULTIPLIER))
    rf  = st.get("range_filter", True)
    rl  = int(st.get("range_len", config.RANGE_FILTER_LEN))
    mr  = float(st.get("min_range", config.MIN_RANGE_PCT))
    need = max(period, vml, rl) + 5

    rsis = rsi_series(closes, period)
    rmas = ema_series(rsis, smooth)

    open_count = 0
    out = []
    for i in range(n):
        if i >= need:
            rn, rp = rsis[i], rsis[i - 1]
            mn, mp = rmas[i], rmas[i - 1]
            if not (rn is None or rp is None or mn is None or mp is None):
                if mode == "RSI 50 Cross":
                    ls, ss = _crossover(mp, mn, 50, 50), _crossunder(mp, mn, 50, 50)
                elif mode == "RSI EMA Cross":
                    ls, ss = _crossover(rp, rn, mp, mn), _crossunder(rp, rn, mp, mn)
                else:
                    ls, ss = _crossover(mp, mn, low, low), _crossunder(mp, mn, high, high)
                if ls or ss:
                    ok = True
                    if vf:
                        win = [v for v in vols[i - vml:i] if v is not None]
                        if win:
                            vma = sum(win) / len(win)
                            if vma > 0 and not (vols[i] > vma * vmu):
                                ok = False
                    if ok and rf:
                        rngs = [(highs[j] - lows[j]) / closes[j] * 100
                                for j in range(i - rl, i) if closes[j]]
                        if rngs and (sum(rngs) / len(rngs)) < mr:
                            ok = False
                    if ok:
                        if ls:
                            open_count += 1
                        elif ss and open_count > 0:
                            open_count = 0   # ilk SAT'ta tüm lotlar kapanır
        out.append((ts[i], open_count))
    return out
