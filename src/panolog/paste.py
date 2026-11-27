"""Seçilen öğeyi sistem clipboard'ına yazar ve önceki pencereye yapıştırır."""
from __future__ import annotations

import os

from PySide6.QtCore import QMimeData, QTimer, QUrl
from PySide6.QtGui import QGuiApplication, QImage

from . import winapi
from .classifier import Category
from .monitor.reader import INTERNAL_MIME
from .storage.models import Item

# Odak önceki pencereye geçtikten sonra Ctrl+V göndermeden önceki bekleme.
_PASTE_DELAY_MS = 120


def write_to_clipboard(item: Item, plain: bool = False) -> bool:
    """Öğeyi clipboard'a yazar. `plain` ise biçimlendirme (HTML) atılır."""
    mime = QMimeData()
    if item.category is Category.FILE:
        paths = [f.path for f in item.files]
        if plain:  # Shift+Enter: dosyaların kendisi yerine yolları metin olarak
            mime.setText("\n".join(paths))
        else:
            # Dosya referansı (CF_HDROP) olarak yazılır; Explorer'da yapıştırınca
            # orijinal dosya kopyalanır. Artık var olmayan yollar atlanır.
            existing = [p for p in paths if os.path.exists(p)]
            if not existing:
                return False
            mime.setUrls([QUrl.fromLocalFile(p) for p in existing])
    elif item.category is Category.IMAGE:
        image = QImage(item.image_path) if item.image_path else QImage()
        if image.isNull():
            return False
        mime.setImageData(image)
    else:
        if item.text is None:
            return False
        mime.setText(item.text)
        if item.html and not plain:
            mime.setHtml(item.html)
    mime.setData(INTERNAL_MIME, b"1")
    QGuiApplication.clipboard().setMimeData(mime)
    return True


def write_image_to_clipboard(image: QImage) -> None:
    """Görseli (ör. düzenlenmiş bir kopyayı) clipboard'a yazar; izleyici yeniden kaydetmez."""
    mime = QMimeData()
    mime.setImageData(image)
    mime.setData(INTERNAL_MIME, b"1")
    QGuiApplication.clipboard().setMimeData(mime)


def write_text_to_clipboard(text: str) -> None:
    """Düz metni (ör. açılmış bir şablonu) clipboard'a yazar; geçmişe kaydedilmez."""
    mime = QMimeData()
    mime.setText(text)
    mime.setData(INTERNAL_MIME, b"1")
    QGuiApplication.clipboard().setMimeData(mime)


def return_focus(hwnd: int | None, send_paste: bool) -> None:
    """Odağı verilen pencereye döndürür; istenirse ardından Ctrl+V gönderir."""
    if not hwnd or not winapi.IsWindow(hwnd):
        return
    winapi.SetForegroundWindow(hwnd)
    if not send_paste:
        return

    def _send() -> None:
        if winapi.GetForegroundWindow() == hwnd:  # yanlış pencereye yapıştırma
            winapi.send_ctrl_v()

    QTimer.singleShot(_PASTE_DELAY_MS, _send)
