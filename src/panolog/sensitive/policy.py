"""Hassas veri algılandığında ne yapılacağına karar verir."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .detectors import find_sensitive
from .masking import mask_text

DEFAULT_TTL_SECONDS = 60


class SensitiveMode(str, Enum):
    OFF = "off"  # tarama yok; her şey normal öğe gibi kaydedilir (varsayılan)
    SKIP = "skip"  # hiç kaydetme
    MASK = "mask"  # kaydet, listede maskeli göster
    AUTO_DELETE = "auto_delete"  # kaydet, kısa süre sonra sil


@dataclass(frozen=True)
class Decision:
    sensitive: bool = False
    store: bool = True
    masked_text: str | None = None
    ttl_seconds: float | None = None
    kinds: frozenset[str] = frozenset()


def evaluate(
    text: str,
    mode: SensitiveMode | str = SensitiveMode.OFF,
    *,
    email: bool = False,
    phone: bool = False,
    ttl_seconds: float = DEFAULT_TTL_SECONDS,
) -> Decision:
    try:
        mode = SensitiveMode(mode)
    except ValueError:
        mode = SensitiveMode.OFF
    if mode is SensitiveMode.OFF:
        return Decision()
    matches = find_sensitive(text, email=email, phone=phone)
    if not matches:
        return Decision()
    kinds = frozenset(m.kind for m in matches)
    if mode is SensitiveMode.SKIP:
        return Decision(sensitive=True, store=False, kinds=kinds)
    if mode is SensitiveMode.MASK:
        return Decision(sensitive=True, masked_text=mask_text(text, matches), kinds=kinds)
    return Decision(sensitive=True, ttl_seconds=ttl_seconds, kinds=kinds)
