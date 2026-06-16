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
# HIZLI EKLEME / TARAMA LİSTELERİ (Yahoo'da doğrulanmış, ilk ~200 büyük hisse)
# BIST: BIST 30/100 + Yıldız Pazar | ABD: S&P 500 market cap ilk 200
# ============================================================
BIST_200 = [
    "THYAO", "GARAN", "AKBNK", "ISCTR", "YKBNK", "VAKBN", "HALKB", "KCHOL",
    "SAHOL", "ASELS", "BIMAS", "TUPRS", "EREGL", "SISE", "FROTO", "TOASO",
    "TCELL", "TTKOM", "SASA", "PETKM", "KRDMD", "ENKAI", "PGSUS", "TAVHL",
    "MGROS", "GUBRF", "ASTOR", "AEFES", "EKGYO", "TRALT", "ARCLK", "CCOLA",
    "TTRAK", "OYAKC", "OTKAR", "AKSA", "AKSEN", "ALARK", "DOAS", "HEKTS",
    "TKFEN", "ULKER", "VESTL", "VESBE", "SOKM", "ENJSA", "SKBNK", "TSKB",
    "ISMEN", "BRSAN", "BRYAT", "AGHOL", "MAVI", "MPARK", "SELEC", "ECILC",
    "TRMET", "TRENJ", "ZOREN", "ODAS", "KONTR", "SMRTG", "CIMSA", "AKCNS",
    "NUHCM", "BUCIM", "BSOKE", "BTCIM", "GESAN", "EUPWR", "CWENE", "ENERY",
    "AGROT", "QUAGR", "DOHOL", "GLYHO", "NTHOL", "PAHOL", "BERA", "ALBRK",
    "ANSGR", "AGESA", "ANHYT", "AKGRT", "TURSG", "RALYH", "EUREN", "KLRHO",
    "KUYAS", "MAGEN", "MIATK", "ARDYZ", "KAREL", "LOGO", "INDES", "PAPIL",
    "REEDR", "PATEK", "GRTHO", "GLRMK", "OBAMS", "TABGD", "BALSU", "GENIL",
    "EFOR", "TUKAS", "GOKNR", "TATEN", "KCAER", "KTLEV", "ALFAS", "AHGAZ",
    "BASGZ", "AYGAZ", "GWIND", "BIOEN", "AYDEM", "NATEN", "AKFYE", "IZENR",
    "ZRGYO", "TRGYO", "ALGYO", "AKFGY", "AKSGY", "ISGYO", "KLGYO", "PSGYO",
    "SNGYO", "SRVGY", "VKGYO", "HLGYO", "PAGYO", "RYGYO", "KZBGY", "DAPGM",
    "ADGYO", "AVPGY", "EGEEN", "KATMR", "PARSN", "BFREN", "KORDS", "BRISA",
    "GOLTS", "DEVA", "EGGUB", "SARKY", "TMSN", "ISDMR", "KRDMA", "KRDMB",
    "CLEBI", "CANTE", "POLHO", "POLTK", "KMPUR", "KLKIM", "BOBET", "YEOTK",
    "ESEN", "GENTS", "VAKKO", "KOTON", "SUWEN", "SUNTK", "YYLGD", "LILAK",
    "MOGAN", "ENTRA", "BIGEN", "MOPAS", "EBEBK", "GIPTA", "HRKET", "LYDHO",
    "LMKDC", "ARMGD", "BINHO", "BINBN", "KOPOL", "CVKMD", "PASEU", "A1CAP",
    "INVEO", "OYYAT", "GLCVY", "ESCAR", "ECZYT", "GEDIK", "RYSAS", "GMTAS",
    "MEGMT", "ATAKP", "ATATP", "USAK", "EGPRO", "KAYSE", "ALTNY", "FENER",
]

US_200 = [
    "NVDA", "GOOGL", "GOOG", "AAPL", "MSFT", "AMZN", "AVGO", "META", "TSLA",
    "MU", "LLY", "WMT", "JPM", "AMD", "V", "INTC", "XOM", "JNJ", "ORCL",
    "CSCO", "LRCX", "AMAT", "MA", "COST", "CAT", "BAC", "ABBV", "UNH", "GE",
    "CVX", "PG", "MS", "KO", "HD", "GS", "NFLX", "PLTR", "KLAC", "SNDK", "PM",
    "MRK", "TXN", "GEV", "DELL", "WFC", "IBM", "RTX", "C", "LIN", "WDC", "STX",
    "AXP", "PANW", "QCOM", "ANET", "MCD", "ADI", "PEP", "TMUS", "APH", "VZ",
    "AMGN", "TJX", "NEE", "BA", "DIS", "TMO", "APP", "CRWD", "BLK", "SCHW",
    "T", "UNP", "ETN", "DE", "GILD", "ABT", "BX", "GLW", "WELL", "UBER", "PFE",
    "ISRG", "HON", "PLD", "COP", "BKNG", "CRM", "CVS", "DHR", "SPGI", "CB",
    "LOW", "COF", "LMT", "PGR", "SYK", "PH", "MO", "SBUX", "NEM", "VRT",
    "VRTX", "BMY", "HWM", "EQIX", "PWR", "FTNT", "CDNS", "SO", "MAR", "TT",
    "NOW", "MDT", "ACN", "FCX", "BNY", "GD", "DUK", "CMI", "CEG", "CME", "PNC",
    "UPS", "MCK", "USB", "MNST", "KKR", "ADP", "JCI", "HCA", "WM", "WMB",
    "CSX", "HOOD", "ELV", "AMT", "SNPS", "CMCSA", "MMM", "RCL", "ABNB", "EMR",
    "ADBE", "DDOG", "SPG", "MCO", "MRSH", "FDX", "ICE", "APO", "MDLZ", "HLT",
    "SLB", "SHW", "NOC", "CVNA", "CI", "ECL", "INTU", "NXPI", "ITW", "CRH",
    "ROST", "ORLY", "COHR", "GM", "DASH", "MPWR", "MPC", "TDG", "CL", "VLO",
    "AON", "CTAS", "AEP", "EOG", "KMI", "NSC", "BSX", "PSX", "DLR", "LITE",
    "FIX", "MSI", "URI", "NKE", "WBD", "TRV", "RSG", "TER", "HPE", "PCAR",
    "TEL", "REGN", "APD", "GWW", "TFC", "BKR", "CIEN",
]

# Hisse Ekle menüsünde ilk 60 göster (grid makul kalsın); tarama tam listeyi kullanır
BIST_60 = BIST_200[:60]
US_60   = US_200[:60]
POPULAR_BIST = BIST_200[:18]
