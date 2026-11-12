"""Ayarları config.yaml'dan, gizli anahtarları .env'den okur."""
import os
from pathlib import Path

import truststore
import yaml
from dotenv import load_dotenv

# HTTPS bağlantılarında işletim sisteminin sertifika deposunu kullan
# (antivirüs/kurumsal ağ sertifikalarında SSL hatasını önler, doğrulama kapanmaz)
truststore.inject_into_ssl()

# Proje kök klasörü (src/ klasörünün bir üstü)
ROOT = Path(__file__).resolve().parent.parent

# .env varsa ortam değişkenlerine yükle (anahtarlar asla yazdırılmaz)
load_dotenv(ROOT / ".env")


def load_config(path: Path | None = None) -> dict:
    """config.yaml dosyasını sözlük olarak döndürür."""
    path = path or ROOT / "config.yaml"
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_secret(name: str) -> str | None:
    """Bir API anahtarını ortamdan okur. Değeri loglamayın/yazdırmayın."""
    value = os.getenv(name)
    return value or None


def resolve_path(cfg: dict, key: str) -> Path:
    """config'deki göreli yolu proje köküne göre mutlak yola çevirir."""
    return ROOT / cfg["paths"][key]
