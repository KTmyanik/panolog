"""Clipboard içeriğini kategoriye ayıran saf fonksiyonlar (Qt/Win32 bağımlılığı yok)."""
from __future__ import annotations

import re
from enum import Enum

from . import codekind


class Category(str, Enum):
    IMAGE = "image"
    TEXT = "text"
    CODE = "code"  # SQL, JSON, XML ve diğer kod parçaları
    LINK = "link"
    FILE = "file"


_SCHEME_RE = re.compile(r"^(https?|ftp)://[^\s/?#]+\.?[^\s]*$", re.IGNORECASE)
_HOST_RE = re.compile(
    r"^(?:www\.)?(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+(?P<tld>[a-z]{2,24})"
    r"(?::\d{1,5})?(?:[/?#]\S*)?$",
    re.IGNORECASE,
)
# Şemasız yazılan adresleri ("example.com/yol") link saymak için bilinen uzantılar.
# Liste bilinçli olarak dar: "rapor.txt" veya "main.py" gibi dosya adları link sayılmamalı.
_KNOWN_TLDS = frozenset(
    "com net org edu gov mil int io dev app ai co me info biz tv cloud online site "
    "tr de uk fr nl es it eu us ca au jp cn ru in br ch se no pl az".split()
)


def is_url(text: str) -> bool:
    """Metnin tamamı tek bir URL ise True döner."""
    s = text.strip()
    if not s or len(s) > 2048 or any(ch.isspace() for ch in s):
        return False
    if _SCHEME_RE.match(s):
        return True
    if "@" in s:  # e-posta adresleri link değildir
        return False
    m = _HOST_RE.match(s)
    if not m:
        return False
    return s.lower().startswith("www.") or m.group("tld").lower() in _KNOWN_TLDS


def classify_text(text: str) -> Category:
    if is_url(text):
        return Category.LINK
    return Category.CODE if codekind.detect(text) else Category.TEXT


def classify(*, has_files: bool, has_image: bool, text: str | None) -> Category | None:
    """Öncelik: dosya > metin/link > görsel.

    Metin görselden önce gelir, çünkü Excel/Word gibi uygulamalar hücre veya paragraf
    kopyalarken metnin yanında bir de görsel sunar; kullanıcı asıl metni kopyalamıştır.
    """
    if has_files:
        return Category.FILE
    if text is not None and text.strip():
        return classify_text(text)
    if has_image:
        return Category.IMAGE
    return None
