"""Görsellerin diskte PNG olarak saklanması. DB'de yalnızca yol ve hash tutulur."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

from PySide6.QtCore import QRunnable, Qt, QThreadPool
from PySide6.QtGui import QImage

from .models import Item

THUMB_SIZE = 256


def hash_image(image: QImage) -> str:
    """Piksel verisinin hash'i; aynı görsel farklı biçimde gelse de aynı sonucu verir."""
    img = image.convertToFormat(QImage.Format.Format_RGBA8888)
    h = hashlib.sha256()
    h.update(f"{img.width()}x{img.height()}:".encode())
    stride, row_bytes = img.bytesPerLine(), img.width() * 4
    bits = img.constBits()
    if stride == row_bytes:
        h.update(bits)
    else:  # satır sonu dolgusunu hash'e katma
        view = memoryview(bits)
        for y in range(img.height()):
            h.update(view[y * stride : y * stride + row_bytes])
    return h.hexdigest()


class _SaveTask(QRunnable):
    def __init__(self, image: QImage, path: Path) -> None:
        super().__init__()
        self._image, self._path = image, path

    def run(self) -> None:
        tmp = self._path.with_suffix(".tmp")
        # Kalite 60: PNG kayıpsızdır, bu değer yalnızca sıkıştırma hızını ayarlar.
        if self._image.save(str(tmp), "PNG", 60):
            os.replace(tmp, self._path)


class ImageStore:
    def __init__(self, directory: Path) -> None:
        self._dir = directory
        self._pool = QThreadPool.globalInstance()

    def full_path(self, content_hash: str) -> Path:
        return self._dir / f"{content_hash}.png"

    def thumb_path(self, content_hash: str) -> Path:
        return self._dir / f"{content_hash}_t.png"

    def save(self, image: QImage, content_hash: str) -> tuple[Path, Path]:
        """Küçük önizlemeyi hemen, tam boy PNG'yi arka planda yazar."""
        full, thumb = self.full_path(content_hash), self.thumb_path(content_hash)
        if not thumb.exists():
            image.scaled(
                THUMB_SIZE,
                THUMB_SIZE,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ).save(str(thumb), "PNG")
        if not full.exists():
            self._pool.start(_SaveTask(image.copy(), full))
        return full, thumb

    def wait(self) -> None:
        self._pool.waitForDone()

    def remove_for(self, item: Item) -> None:
        for p in (item.image_path, item.thumb_path):
            if p:
                try:
                    os.remove(p)
                except OSError:
                    pass

    def sweep_orphans(self, referenced: set[str]) -> int:
        """DB'de karşılığı kalmamış görsel dosyalarını siler."""
        known = {os.path.normcase(p) for p in referenced}
        removed = 0
        for f in self._dir.iterdir():
            if f.is_file() and os.path.normcase(str(f)) not in known:
                try:
                    f.unlink()
                    removed += 1
                except OSError:
                    pass
        return removed
