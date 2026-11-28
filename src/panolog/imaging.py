"""Görsel düzenleme işlemleri: alan kapatma, bulanıklaştırma, kırpma, kutu ve ok çizme.

İşlevler verilen görseli değiştirmez, yeni bir QImage döndürür.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPolygonF

COVER_COLOR = QColor(0, 0, 0)
MARK_COLOR = QColor(229, 38, 43)  # kutu ve ok: kırmızı
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


def mark_width(image: QImage) -> int:
    """Kutu ve ok çizgisinin kalınlığı: görsel büyüdükçe kalınlaşır, küçük görselde 3 piksel."""
    return max(3, round(min(image.width(), image.height()) / 160))


def box(image: QImage, rect: QRect, color: QColor = MARK_COLOR, width: int | None = None) -> QImage:
    """Alanın çevresine çerçeve çizer; içi olduğu gibi kalır."""
    out = _editable(image)
    area = clamp(out, rect)
    if area.isEmpty():
        return out
    width = width or mark_width(out)
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(color, width)
    pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
    painter.setPen(pen)
    half = width / 2
    painter.drawRect(QRectF(area).adjusted(half, half, -half, -half))
    painter.end()
    return out


def arrow(
    image: QImage, start: QPoint, end: QPoint, color: QColor = MARK_COLOR, width: int | None = None
) -> QImage:
    """`start` noktasından `end` noktasına ok çizer; ok başı `end` ucundadır."""
    out = _editable(image)
    dx, dy = end.x() - start.x(), end.y() - start.y()
    length = math.hypot(dx, dy)
    if length < 1:
        return out
    width = width or mark_width(out)
    head = min(max(width * 4.5, 12.0), length * 0.6)
    ux, uy = dx / length, dy / length
    tip = QPointF(end)
    base = QPointF(end.x() - ux * head, end.y() - uy * head)
    half = head * 0.45
    left = QPointF(base.x() - uy * half, base.y() + ux * half)
    right = QPointF(base.x() + uy * half, base.y() - ux * half)
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(color, width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.drawLine(QPointF(start), base)  # gövde ok başının dibinde biter; uç sivri kalır
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    painter.drawPolygon(QPolygonF([tip, left, right]))
    painter.end()
    return out
