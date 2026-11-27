"""Görsel düzenleme işlemleri: alan kapatma, bulanıklaştırma, kırpma.

İşlevler verilen görseli değiştirmez, yeni bir QImage döndürür.
"""
from __future__ import annotations

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter

COVER_COLOR = QColor(0, 0, 0)
_FORMAT = QImage.Format.Format_ARGB32


def clamp(image: QImage, rect: QRect) -> QRect:
    """Dikdörtgeni görselin sınırları içine alır; dışarıda kalıyorsa boş döner."""
    return rect.normalized().intersected(image.rect())


def _editable(image: QImage) -> QImage:
    return image.convertToFormat(_FORMAT) if image.format() != _FORMAT else image.copy()


def cover(image: QImage, rect: QRect, color: QColor = COVER_COLOR) -> QImage:
    """Alanı düz renkle örter. Altındaki pikseller tamamen yok olur; geri getirilemez."""
    out = _editable(image)
    area = clamp(out, rect)
    if not area.isEmpty():
        painter = QPainter(out)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.fillRect(area, color)
        painter.end()
    return out


def blur_block(width: int, height: int) -> int:
    """Bulanıklaştırmada tek renge indirilen karenin kenarı (piksel).

    Alanın kısa kenarına göre büyür: küçük bir metin satırı da, büyük bir yüz de
    tanınmayacak kadar az ayrıntıyla kalır.
    """
    return max(10, round(min(width, height) / 4))


def blur(image: QImage, rect: QRect) -> QImage:
    """Alanı güçlü biçimde bulanıklaştırır.

    Alan önce birkaç piksele küçültülür (ortalama alınır), sonra yumuşatılarak geri
    büyütülür. Metni gizlemek için güvenli sayılmaz; bunun için `cover` kullanılmalı.
    """
    out = _editable(image)
    area = clamp(out, rect)
    if area.isEmpty():
        return out
    block = blur_block(area.width(), area.height())
    small_w = max(1, round(area.width() / block))
    small_h = max(1, round(area.height() / block))
    smooth = Qt.TransformationMode.SmoothTransformation
    ignore = Qt.AspectRatioMode.IgnoreAspectRatio
    patch = out.copy(area).scaled(small_w, small_h, ignore, smooth)
    patch = patch.scaled(area.width(), area.height(), ignore, smooth)
    painter = QPainter(out)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
    painter.drawImage(area.topLeft(), patch)
    painter.end()
    return out


def crop(image: QImage, rect: QRect) -> QImage:
    """Yalnızca seçilen alanı döndürür; alan görselin dışındaysa görsel aynen kalır."""
    area = clamp(image, rect)
    return image.copy() if area.isEmpty() else image.copy(area)
