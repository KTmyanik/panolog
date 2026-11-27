"""Serbest çizim alanı: imza gibi elle çizilen görsel şablonlar için."""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

CANVAS_SIZE = QSize(560, 220)
PAPER = QColor("#ffffff")
INK_COLORS = {"Siyah": "#111111", "Mavi": "#1a3fa8"}
PEN_WIDTHS = {"İnce": 2.0, "Orta": 3.5, "Kalın": 5.5}
CROP_MARGIN = 12  # kaydedilen görselde mürekkebin çevresinde bırakılan boşluk (piksel)
_MAX_UNDO = 60


@dataclass(frozen=True)
class Stroke:
    color: str
    width: float
    points: tuple[tuple[float, float], ...]


def stroke_path(points: tuple[tuple[float, float], ...]) -> QPainterPath:
    """Noktalardan yumuşak bir eğri: ara noktalar köşe değil, eğrinin denetim noktası olur."""
    path = QPainterPath(QPointF(*points[0]))
    if len(points) == 1:
        return path
    if len(points) == 2:
        path.lineTo(QPointF(*points[1]))
        return path
    for (x0, y0), (x1, y1) in zip(points[1:-1], points[2:]):
        path.quadTo(QPointF(x0, y0), QPointF((x0 + x1) / 2, (y0 + y1) / 2))
    path.lineTo(QPointF(*points[-1]))
    return path


def render(size: QSize, base: QImage | None, strokes: tuple[Stroke, ...]) -> QImage:
    """Beyaz zemin üzerine (varsa) temel görseli ve çizgileri çizer."""
    image = QImage(size, QImage.Format.Format_ARGB32)
    image.fill(PAPER)
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    if base is not None and not base.isNull():
        p.drawImage(base_rect(size, base.size()), base)
    for stroke in strokes:
        pen = QPen(QColor(stroke.color), stroke.width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        if len(stroke.points) == 1:  # tek tıklama: nokta
            p.drawPoint(QPointF(*stroke.points[0]))
        else:
            p.drawPath(stroke_path(stroke.points))
    p.end()
    return image


def base_rect(canvas: QSize, image: QSize) -> QRectF:
    """Temel görselin tuvaldeki yeri: ortalanır, sığmıyorsa küçültülür, büyütülmez."""
    size = QSize(image)
    if size.width() > canvas.width() or size.height() > canvas.height():
        size.scale(canvas, Qt.AspectRatioMode.KeepAspectRatio)
    return QRectF(
        (canvas.width() - size.width()) / 2, (canvas.height() - size.height()) / 2,
        size.width(), size.height(),
    )  # fmt: skip


def ink_bounds(image: QImage) -> QRect:
    """Beyaz olmayan piksellerin sınır kutusu; görsel tamamen beyazsa boş dikdörtgen."""
    img = image.convertToFormat(QImage.Format.Format_RGB32)
    width, height = img.width(), img.height()
    white = 0xFFFFFFFF
    left, top, right, bottom = width, height, -1, -1
    view = memoryview(img.constBits()).cast("I")
    stride = img.bytesPerLine() // 4
    for y in range(height):
        row = view[y * stride : y * stride + width]
        if all(px == white for px in row):
            continue
        first = next(x for x, px in enumerate(row) if px != white)
        last = next(x for x in range(width - 1, -1, -1) if row[x] != white)
        left, right = min(left, first), max(right, last)
        top = y if top == height else top
        bottom = y
    if right < 0:
        return QRect()
    return QRect(left, top, right - left + 1, bottom - top + 1)


def crop_to_ink(image: QImage, margin: int = CROP_MARGIN) -> QImage:
    """Görseli mürekkebin çevresine kırpar; boşsa boş (null) görsel döner."""
    bounds = ink_bounds(image)
    if bounds.isEmpty():
        return QImage()
    return image.copy(bounds.adjusted(-margin, -margin, margin, margin).intersected(image.rect()))


def to_png(image: QImage) -> bytes:
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    buffer.close()
    return bytes(data)


class DrawCanvas(QWidget):
    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(CANVAS_SIZE)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._base: QImage | None = None
        self._strokes: tuple[Stroke, ...] = ()
        self._undo: list[tuple[QImage | None, tuple[Stroke, ...]]] = []
        self._current: list[tuple[float, float]] | None = None
        self.color = INK_COLORS["Siyah"]
        self.pen_width = PEN_WIDTHS["Orta"]

    # ---- durum --------------------------------------------------------------
    def is_empty(self) -> bool:
        return self._base is None and not self._strokes

    def can_undo(self) -> bool:
        return bool(self._undo)

    def _push(self) -> None:
        self._undo.append((self._base, self._strokes))
        del self._undo[:-_MAX_UNDO]

    def set_base(self, image: QImage | None, *, undoable: bool = True) -> None:
        """Var olan bir görseli (düzenlenen şablon, taranmış imza) zemine yerleştirir."""
        if undoable:
            self._push()
        self._base = image if image is not None and not image.isNull() else None
        self._changed()

    def add_stroke(self, points: list[tuple[float, float]]) -> None:
        if not points:
            return
        self._push()
        self._strokes += (Stroke(self.color, self.pen_width, tuple(points)),)
        self._changed()

    def clear(self) -> None:
        if self.is_empty():
            return
        self._push()
        self._base, self._strokes = None, ()
        self._changed()

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._base, self._strokes = self._undo.pop()
        self._changed()
        return True

    def _changed(self) -> None:
        self.update()
        self.changed.emit()

    def image(self) -> QImage:
        """Çizimin, mürekkebin çevresine kırpılmış hâli; boşsa null görsel."""
        return crop_to_ink(render(CANVAS_SIZE, self._base, self._strokes))

    # ---- çizim --------------------------------------------------------------
    def paintEvent(self, _event) -> None:  # noqa: N802
        strokes = self._strokes
        if self._current:
            strokes += (Stroke(self.color, self.pen_width, tuple(self._current)),)
        p = QPainter(self)
        p.drawImage(0, 0, render(CANVAS_SIZE, self._base, strokes))
        p.setPen(QPen(QColor("#c8ccd4"), 1))
        p.drawRect(self.rect().adjusted(0, 0, -1, -1))

    def _point(self, event: QMouseEvent) -> tuple[float, float]:
        pos = event.position()
        x = min(max(pos.x(), 0.0), self.width() - 1.0)
        y = min(max(pos.y(), 0.0), self.height() - 1.0)
        return (x, y)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._current = [self._point(event)]
            self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._current is not None:
            point = self._point(event)
            last = self._current[-1]
            if abs(point[0] - last[0]) + abs(point[1] - last[1]) >= 1.5:  # titremeyi ele
                self._current.append(point)
                self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._current is not None:
            points, self._current = self._current, None
            self.add_stroke(points)
