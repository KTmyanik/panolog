"""Hassas eşleşmelerin listede gösterilecek maskeli biçimi."""
from __future__ import annotations

from .detectors import CARD, EMAIL, IBAN, PHONE, SECRET, TCKN, Match

_SECRET_MASK = "********"  # sabit uzunluk: parolanın uzunluğu da sızmasın


def _keep_last_digits(value: str, keep: int) -> str:
    """Son `keep` rakam dışındaki rakamları yıldızlar; ayraçları korur."""
    total = sum(ch.isdigit() for ch in value)
    out, seen = [], 0
    for ch in value:
        if ch.isdigit():
            seen += 1
            out.append(ch if seen > total - keep else "*")
        else:
            out.append(ch)
    return "".join(out)


def mask_value(kind: str, value: str) -> str:
    if kind == IBAN:
        compact = "".join(ch for ch in value if ch.isalnum()).upper()
        return f"{compact[:4]} **** {compact[-4:]}"
    if kind == CARD:
        return _keep_last_digits(value, 4)
    if kind in (TCKN, PHONE):
        return _keep_last_digits(value, 2)
    if kind == EMAIL:
        local, _, domain = value.partition("@")
        return f"{local[:1]}***@{domain}"
    if kind == SECRET:
        return _SECRET_MASK if value else ""
    return "*" * len(value)


def mask_text(text: str, matches: list[Match]) -> str:
    out, pos = [], 0
    for m in sorted(matches, key=lambda m: m.start):
        out.append(text[pos : m.start])
        out.append(mask_value(m.kind, text[m.start : m.end]))
        pos = m.end
    out.append(text[pos:])
    return "".join(out)
