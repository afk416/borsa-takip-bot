"""
GitHub Gist üzerinden kalıcı veri saklama.
- Bot başlangıçta kendi gist'ini bulur, yoksa oluşturur (private)
- Render redeploy'da bile kullanıcı verileri korunur
- Gerekli: GITHUB_TOKEN env var (gist scope'lu Personal Access Token)
"""
import os
import json
import requests
import logging

log = logging.getLogger(__name__)

GIST_FILENAME = "borsa_takip_bot_users.json"
GIST_DESCRIPTION = "Borsa Takip Bot — kullanıcı verileri (otomatik yönetilir)"

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
_gist_id_cache = None


def _headers():
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept":        "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def is_enabled() -> bool:
    return bool(GITHUB_TOKEN)


def find_or_create_gist() -> str:
    """Bot'un kullandığı gist ID'sini bulur (filename match) veya oluşturur."""
    global _gist_id_cache
    if _gist_id_cache:
        return _gist_id_cache
    if not GITHUB_TOKEN:
        return None

    listing_ok = False
    try:
        page = 1
        while True:
            r = requests.get(
                f"https://api.github.com/gists?per_page=100&page={page}",
                headers=_headers(), timeout=15,
            )
            r.raise_for_status()
            gists = r.json()
            listing_ok = True   # en az bir sayfa başarıyla okundu
            if not gists:
                break
            for g in gists:
                files = g.get("files") or {}
                if GIST_FILENAME in files:
                    _gist_id_cache = g["id"]
                    log.info(f"☁️ Bot gist'i bulundu: {_gist_id_cache}")
                    return _gist_id_cache
            if len(gists) < 100:
                break
            page += 1
    except Exception as e:
        log.error(f"Gist listeleme hatası: {e}")

    # KRİTİK: listeleme başarısız olduysa (network/DNS) YENİ gist OLUŞTURMA —
    # gist gerçekte var olabilir, yeni oluşturmak duplicate + veri kopması yaratır.
    if not listing_ok:
        log.warning("⚠️ Gist listelenemedi (geçici hata); yeni gist oluşturulmuyor.")
        return None

    # Liste başarılı ama filename bulunamadı → gist gerçekten yok, yenisini oluştur
    try:
        payload = {
            "description": GIST_DESCRIPTION,
            "public":      False,
            "files":       {GIST_FILENAME: {"content": "{}"}},
        }
        r = requests.post(
            "https://api.github.com/gists",
            json=payload, headers=_headers(), timeout=15,
        )
        r.raise_for_status()
        _gist_id_cache = r.json()["id"]
        log.info(f"☁️ Yeni private gist oluşturuldu: {_gist_id_cache}")
        return _gist_id_cache
    except Exception as e:
        log.error(f"Gist oluşturma hatası: {e}")
        return None


def load_from_gist() -> dict:
    """Gist'ten veri JSON'unu çeker."""
    gid = find_or_create_gist()
    if not gid:
        return {}
    try:
        r = requests.get(
            f"https://api.github.com/gists/{gid}",
            headers=_headers(), timeout=15,
        )
        r.raise_for_status()
        files = r.json().get("files", {})
        f = files.get(GIST_FILENAME, {})
        content = f.get("content", "{}")
        if not content.strip():
            return {}
        return json.loads(content)
    except Exception as e:
        log.error(f"Gist okuma hatası: {e}")
        return {}


def save_to_gist(data: dict) -> bool:
    """Veriyi gist'e yazar."""
    gid = find_or_create_gist()
    if not gid:
        return False
    try:
        payload = {
            "files": {
                GIST_FILENAME: {
                    "content": json.dumps(data, indent=2, ensure_ascii=False),
                }
            }
        }
        r = requests.patch(
            f"https://api.github.com/gists/{gid}",
            json=payload, headers=_headers(), timeout=15,
        )
        r.raise_for_status()
        log.info("☁️ Kullanıcı verileri gist'e yazıldı")
        return True
    except Exception as e:
        log.error(f"Gist yazma hatası: {e}")
        return False
