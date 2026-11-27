from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields

from ..classifier import Category

DEFAULT_LIMIT = 50
DEFAULT_HOTKEY = "Ctrl+Shift+V"
DEFAULT_EXCLUDED_APPS = [
    "keepass.exe",
    "keepassxc.exe",
    "bitwarden.exe",
    "1password.exe",
]


def _default_limits() -> dict[str, int]:
    return {c.value: DEFAULT_LIMIT for c in Category}


@dataclass
class Settings:
    limits: dict[str, int] = field(default_factory=_default_limits)
    retention_enabled: bool = True
    retention_days: int = 7
    hotkey: str = DEFAULT_HOTKEY
    auto_paste: bool = True
    excluded_apps: list[str] = field(default_factory=lambda: list(DEFAULT_EXCLUDED_APPS))
    autostart: bool = False
    # Hassas veri: "off" (normal kaydet), "mask" (maskeli göster), "auto_delete" (süre sonra
    # sil), "skip" (kaydetme). Varsayılan "off": test/UAT'de TCKN ve kart numaraları sık
    # kopyalanıp tekrar kullanılıyor; koruma isteyen ayarlardan açar.
    sensitive_mode: str = "off"
    sensitive_ttl_seconds: int = 60
    detect_email: bool = False
    detect_phone: bool = False
    # Açıksa her yeni görsel (ve geçmişteki okunmamışlar) arka planda OCR'lanır; görseller
    # içlerindeki metinle aranabilir olur. Kapalıyken OCR yalnızca Ctrl+O ile çalışır.
    ocr_auto: bool = False
    # Geçmiş penceresinin görünümü (ui/themes.py) ve hareketli arka planların açık olması.
    theme: str = "classic"
    animations: bool = True

    def limit_for(self, category: Category) -> int:
        return int(self.limits.get(category.value, DEFAULT_LIMIT))

    def is_excluded(self, app: str | None) -> bool:
        return bool(app) and app.lower() in {a.strip().lower() for a in self.excluded_apps}

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Settings":
        """Bilinmeyen anahtarları yok sayar, eksikleri varsayılanla doldurur."""
        s = cls()
        for f in fields(cls):
            if f.name not in data:
                continue
            value = data[f.name]
            if f.name == "limits":
                merged = _default_limits()
                if isinstance(value, dict):
                    merged.update({k: int(v) for k, v in value.items() if k in merged})
                value = merged
            elif not isinstance(value, type(getattr(s, f.name))):
                continue
            setattr(s, f.name, value)
        return s
