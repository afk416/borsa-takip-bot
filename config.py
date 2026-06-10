"""
Borsa Takip Bot - Ayarlar
- Çok kullanıcılı: her kullanıcının kendi listesi/alarmı/portföyü var (users.py)
- Buradakiler bot geneli ayarlar + yeni kullanıcı defaultları
"""
import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ============================================================
# ENV VARS
# ============================================================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
GITHUB_TOKEN   = os.getenv("GITHUB_TOKEN", "")        # Gist persistence için
ADMIN_CHAT_ID  = os.getenv("ADMIN_CHAT_ID", "")       # /admin ve /duyuru için
ACCESS_CODE    = os.getenv("ACCESS_CODE", "")         # boşsa bot herkese açık

# ============================================================
# BOT GENELİ
# ============================================================
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "300"))   # alarm tarama (saniye)
RSI_ALERT_COOLDOWN_MIN = 240   # RSI alarmı aynı hisse için en erken 4 saatte bir
MAX_WATCHLIST = 30
MAX_ALERTS    = 20

# ============================================================
# YENİ KULLANICI DEFAULTLARI
# ============================================================
# Baz değerler eski OKX botundaki ayarlarla aynı (kullanıcının tercihi)
DEFAULT_SETTINGS = {
    "rsi_period":  21,
    "rsi_smooth":  1,         # RSI'a EMA yumuşatma (1 = ham RSI)
    "rsi_low":     25,        # Aşırı Satım (LOW)
    "rsi_high":    78,        # Aşırı Alım (HIGH)
    "interval":    "15dk",    # 15 dakikalık grafik (yahoo_client.INTERVALS anahtarı)
    "signal_mode": "Crossover",  # config.SIGNAL_MODES
    "vol_filter":   True,     # hacim filtresi aktif
    "vol_ma_len":   20,       # Hacim MA Pencere
    "vol_mult":     1.0,      # Çarpan (x MA)
    "range_filter": True,     # volatilite (range) filtresi aktif
    "range_len":    20,       # Pencere (mum)
    "min_range":    0.1,      # Min Ort. Range (%)
    "notif":       True,
    "signals":     False,     # otomatik AL/SAT sinyal modu (watchlist taraması)
    "analysis_mode": "lot",   # analiz sayımı: "lot" (her lot ayrı) | "islem" (döngü net)
}

# ============================================================
# SİNYAL STRATEJİSİ SABİTLERİ (yalnızca fallback / ATR — gerisi kişi başı ayar)
# ============================================================
SIGNAL_MODES      = ["Crossover", "RSI 50 Cross", "RSI EMA Cross"]
VOLUME_MA_LEN     = 20        # fallback (eski kayıtlar için)
VOLUME_MULTIPLIER = 1.0       # fallback
RANGE_FILTER_LEN  = 20        # fallback
MIN_RANGE_PCT     = 0.1       # fallback
ATR_LENGTH        = 14
SL_ATR_MULT       = 1.5       # önerilen Stop-Loss = fiyat ∓ ATR × bu
TP_ATR_MULT       = 3.0       # önerilen Take-Profit = fiyat ± ATR × bu

# ============================================================
# POPÜLER BIST HİSSELERİ (hızlı ekleme menüsü)
# ============================================================
POPULAR_BIST = [
    "THYAO", "ASELS", "GARAN", "AKBNK", "ISCTR", "YKBNK",
    "BIMAS", "EREGL", "SISE",  "KCHOL", "TUPRS", "SASA",
    "FROTO", "TCELL", "HEKTS", "PETKM", "ENKAI", "TOASO",
]
