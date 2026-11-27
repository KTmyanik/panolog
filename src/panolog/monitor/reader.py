"""Clipboard'ın o anki içeriğini okur ve kaydedilip kaydedilmeyeceğine karar verir."""
from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtGui import QGuiApplication, QImage

from .. import winapi

# Popup'tan yapıştırırken clipboard'a kendi yazdığımız içeriği tanımak için işaret.
INTERNAL_MIME = "application/x-panolog-internal"

# Parola yöneticilerinin "bunu geçmişe alma" demek için kullandığı Windows biçimleri.
_FMT_EXCLUDE = "ExcludeClipboardContentFromMonitorProcessing"
_FMT_CAN_INCLUDE = "CanIncludeInClipboardHistory"

MAX_TEXT_CHARS = 1_000_000


@dataclass
class ClipPayload:
    text: str | None = None
    html: str | None = None
    image: QImage | None = None
    files: list[str] = field(default_factory=list)
    internal: bool = False  # içeriği biz yazdık
    private: bool = False  # kaynak uygulama geçmişe alınmasını istemiyor


def _win_mime(name: str) -> str:
    return f'application/x-qt-windows-mime;value="{name}"'


def _is_private(mime) -> bool:
    if winapi.clipboard_format_present(_FMT_EXCLUDE):
        return True
    if winapi.clipboard_format_present(_FMT_CAN_INCLUDE):
        data = bytes(mime.data(_win_mime(_FMT_CAN_INCLUDE)))
        # Değer DWORD 0 ise "alma" demektir; okunamazsa güvenli tarafta kal.
        return len(data) < 4 or int.from_bytes(data[:4], "little") == 0
    return False


def read_clipboard() -> ClipPayload:
    mime = QGuiApplication.clipboard().mimeData()
    payload = ClipPayload()
    if mime is None:
        return payload
    if mime.hasFormat(INTERNAL_MIME):
        payload.internal = True
        return payload
    if _is_private(mime):
        payload.private = True
        return payload

    if mime.hasUrls():
        payload.files = [u.toLocalFile() for u in mime.urls() if u.isLocalFile()]
    if mime.hasText():
        text = mime.text()
        if text and len(text) <= MAX_TEXT_CHARS:
            payload.text = text
            if mime.hasHtml():
                payload.html = mime.html()
    if payload.text is None and not payload.files and mime.hasImage():
        image = mime.imageData()
        if isinstance(image, QImage) and not image.isNull():
            payload.image = image
    return payload
