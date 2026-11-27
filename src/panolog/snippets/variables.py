"""Şablon değişkenleri: {tarih}, {saat}, {pano}."""
from __future__ import annotations

import re
from datetime import datetime

VARIABLES = {
    "tarih": "bugünün tarihi (GG.AA.YYYY)",
    "saat": "şu anki saat (SS:DD)",
    "pano": "clipboard'daki mevcut metin",
}
_VAR = re.compile(r"\{(tarih|saat|pano)\}")


def expand(content: str, *, now: datetime | None = None, clipboard_text: str = "") -> str:
    """Değişkenleri tek geçişte açar; {pano} ile gelen metnin içindeki süslü parantezler
    yeniden yorumlanmaz. Bilinmeyen {…} ifadeleri olduğu gibi kalır."""
    now = now or datetime.now()
    values = {
        "tarih": now.strftime("%d.%m.%Y"),
        "saat": now.strftime("%H:%M"),
        "pano": clipboard_text,
    }
    return _VAR.sub(lambda m: values[m.group(1)], content)


def uses_clipboard(content: str) -> bool:
    return "{pano}" in content
