from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields

from ..classifier import Category

DEFAULT_LIMIT = 50
DEFAULT_HOTKEY = "Ctrl+Shift+V"
DEFAULT_SEQ_HOTKEY = "Ctrl+Alt+N"
# Uygulama kuralı eylemleri: (anahtar, ad, değer gerekiyor mu)
RULE_ACTIONS = {
    "skip": ("Kaydetme", False),
    "tag": ("Etiketle", True),
    "expire": ("Süre sonunda sil (dakika)", True),
}
DEFAULT_EXCLUDED_APPS = [
    "keepass.exe",
    "keepassxc.exe",
    "bitwarden.exe",
    "1password.exe",
]


def _default_limits() -> dict[str, int]:
    return {c.value: DEFAULT_LIMIT for c in Category}


def clean_rules(value) -> list[dict]:
    """Kural listesini doğrular; bozuk kayıtlar sessizce atılır, uygulama adı küçültülür."""
    out: list[dict] = []
    if not isinstance(value, list):
        return out
    seen: set[str] = set()
    for rule in value:
        if not isinstance(rule, dict):
            continue
        app = str(rule.get("app", "")).strip().lower()
        action = rule.get("action")
        if not app or action not in RULE_ACTIONS or app in seen:
            continue
        text = str(rule.get("value", "") or "").strip()
        if action == "tag" and not text:
            continue
        if action == "expire":
            try:
                minutes = int(text)
            except ValueError:
                continue
            if not 1 <= minutes <= 100_000:
                continue
            text = str(minutes)
        seen.add(app)
        out.append({"app": app, "action": action, "value": text if RULE_ACTIONS[action][1] else ""})
    return out


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
    # Uygulamaya göre kurallar: [{"app": "excel.exe", "action": "skip|tag|expire",
    # "value": "..."}]. Varsayılan boş: hiçbir uygulama için kural yoktur.
    rules: list[dict] = field(default_factory=list)
    # Sıralı yapıştırma: kuyruğa alınan öğeleri bu kısayol birer birer yapıştırır.
    seq_hotkey: str = DEFAULT_SEQ_HOTKEY
    # Çoklu seçimde öğeler bu ayraçla birleştirilir (\n = yeni satır).
    join_separator: str = "\n"
    # Açıksa kopyalanan linklerin sayfa başlığı ve simgesi internetten alınır. Varsayılan
    # kapalı: açılmadıkça uygulama hiçbir ağ bağlantısı kurmaz.
    link_fetch: bool = False

    def limit_for(self, category: Category) -> int:
        return int(self.limits.get(category.value, DEFAULT_LIMIT))

    def rule_for(self, app: str | None) -> dict | None:
        """Uygulama için tanımlı ilk geçerli kural; yoksa None."""
        name = (app or "").strip().lower()
        if not name:
            return None
        for rule in self.rules:
            if str(rule.get("app", "")).strip().lower() == name and rule.get("action") in RULE_ACTIONS:
                return rule
        return None

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
            elif f.name == "rules":
                value = clean_rules(value)
            elif not isinstance(value, type(getattr(s, f.name))):
                continue
            setattr(s, f.name, value)
        return s
