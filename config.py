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
DEFAULT_SETTINGS = {
    "rsi_period": 14,
    "rsi_low":    30,
    "rsi_high":   70,
    "interval":   "gunluk",   # yahoo_client.INTERVALS anahtarı
    "notif":      True,
    "signals":    False,      # otomatik AL/SAT sinyal modu (watchlist taraması)
}

# ============================================================
# POPÜLER BIST HİSSELERİ (hızlı ekleme menüsü)
# ============================================================
POPULAR_BIST = [
    "THYAO", "ASELS", "GARAN", "AKBNK", "ISCTR", "YKBNK",
    "BIMAS", "EREGL", "SISE",  "KCHOL", "TUPRS", "SASA",
    "FROTO", "TCELL", "HEKTS", "PETKM", "ENKAI", "TOASO",
]
