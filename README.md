# 📈 Borsa Takip Bot

BIST ve ABD hisselerini Telegram'dan takip etmek için **çok kullanıcılı** bot.
Herkes kendi Telegram'ından `/start` diyerek **kendi** takip listesini, alarmlarını
ve portföyünü yönetir — paylaşıma uygundur.

> ⚠️ **Not:** Midas'ın halka açık bir API'si yoktur; bot Midas hesabına **bağlanmaz**.
> Midas'ta işlem gören hisseleri (BIST + ABD) Yahoo Finance verisiyle izler.
> BIST verisi ~15 dk gecikmelidir. **Yatırım tavsiyesi değildir.**

## Özellikler

- 📊 **Fiyatlar** — takip listesindeki hisselerin anlık fiyatı + günlük değişim
- 📈 **RSI Tarama** — listedeki hisselerin RSI'ı, aşırı alım/satım işaretli
- 🔔 **Alarmlar** — fiyat hedefi (1 kez çalışır) ve RSI aşırı alım/satım (4 saatte bir)
- 💼 **Portföy** — elindeki hisseleri gir (adet + maliyet), anlık kâr/zarar gör
- ⚙️ **Kişisel ayarlar** — RSI periyodu, eşikler, zaman dilimi (15dk/1saat/günlük/haftalık)
- 🔍 Sembol yazınca anında fiyat kartı + mini grafik (`THYAO`, `AAPL` ...)

## Mimari

```
Yahoo Finance (ücretsiz veri)
        ↓
Python Bot (Render Web Service, Flask + webhook)
        ↓ ↑
Telegram (her kullanıcı kendi sohbetinden)
        ↓
GitHub Gist (kullanıcı verileri — redeploy'a dayanıklı)
```

## Kurulum

1. **Telegram botu oluştur:** [@BotFather](https://t.me/BotFather) → `/newbot` → token'ı al.
2. **GitHub token:** GitHub → Settings → Developer settings → Personal access tokens →
   `gist` scope'lu token oluştur (kullanıcı verilerinin kalıcılığı için).
3. **Render'a deploy:** Bu repo'yu GitHub'a pushla → Render'da *New Web Service* →
   repo'yu seç (render.yaml otomatik algılanır) → env vars'ı gir:
   - `TELEGRAM_TOKEN` (zorunlu)
   - `GITHUB_TOKEN` (önerilir)
   - `ADMIN_CHAT_ID` (kendi chat ID'n — /admin için)
   - `ACCESS_CODE` (opsiyonel — doldurursan bot sadece kodu bilenlere açık olur)
4. **Free tier uyumasın:** [UptimeRobot](https://uptimerobot.com)'ta
   `https://SERVIS-ADI.onrender.com/health` adresine 5 dk'lık HTTP monitor ekle.

## Paylaşım

Botu kullanmak isteyen kişiye sadece botun Telegram kullanıcı adını ver.
`/start` diyen herkes kendi listesini kurar — senin verilerine erişemez.
Botu sınırlamak istersen `ACCESS_CODE` env var'ını doldur ve kodu sadece
istediğin kişilerle paylaş.

## Admin komutları

- `/admin` — kullanıcı sayısı, aktif alarm sayısı, son katılanlar
- `/duyuru mesaj` — tüm kullanıcılara duyuru gönder

## Lokal test

```bash
pip install -r requirements.txt
copy .env.example .env   # token'ları doldur
python main.py
```

Lokal modda webhook kurulamaz (public URL yok); Render'da otomatik kurulur.
