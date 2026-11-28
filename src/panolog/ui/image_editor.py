"""Görsel düzenleyici: fareyle seçilen alanı kapatma, bulanıklaştırma ya da kırpma."""
from __future__ import annotations

import math
from collections.abc import Callable

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QGuiApplication,
    QImage,
    QKeySequence,
    QMouseEvent,
    QPainter,
    QPen,
    QShortcut,
)
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import APP_NAME, imaging

_MAX_UNDO = 30
_MIN_DRAG = 3  # bundan küçük sürüklemeler (yanlışlıkla tıklama) yok sayılır
_MIN_CANVAS = QSize(420, 160)

Tool = Callable[[QImage, QRect], QImage]

# (ad, kısayol, açıklama, işlem)
TOOLS: list[tuple[str, str, str, Tool]] = [
    ("Kapat", "K", "Alanı düz siyahla örter. Gizli bilgi için bunu kullanın.", imaging.cover),
    (
        "Bulanıklaştır",
        "B",
        "Alanı bulanıklaştırır. Numara ve parola gibi yazıları gizlemek için güvenli değildir.",
        imaging.blur,
    ),
    ("Kırp", "C", "Yalnızca seçtiğiniz alan kalır.", imaging.crop),
    ("Kutu", "U", "Alanın çevresine kırmızı çerçeve çizer.", imaging.box),
    ("Ok", "O", "Sürüklediğiniz yönde kırmızı ok çizer; ok başı bıraktığınız uçtadır.", imaging.arrow),
]
LINE_TOOLS = {"Ok"}  # dikdörtgen yerine başlangıç ve bitiş noktasıyla çalışan araçlar


def fit_scale(image: QSize, available: QSize) -> float:
    """Görselin alana sığması için gereken ölçek; görsel büyütülmez (en çok 1.0)."""
    if image.isEmpty():
        return 1.0
    return min(1.0, available.width() / image.width(), available.height() / image.height())


class EditSession:
    """Düzenleme durumu: güncel görsel ve geri alma yığını (arayüzden bağımsız)."""

    def __init__(self, image: QImage) -> None:
        self.image = image
        self._undo: list[QImage] = []

    @property
    def modified(self) -> bool:
        return bool(self._undo)

    def apply(self, tool: Tool, rect: QRect) -> bool:
        """İşlemi uygular. Alan görselin dışındaysa hiçbir şey değişmez, False döner."""
        if imaging.clamp(self.image, rect).isEmpty():
            return False
        self._push(tool(self.image, rect))
        return True

    def apply_line(self, tool, start: QPoint, end: QPoint) -> bool:
        """İki noktayla çalışan aracı (ok) uygular; noktalar aynıysa False döner."""
        if (start - end).manhattanLength() < _MIN_DRAG:
            return False
        self._push(tool(self.image, start, end))
        return True

    def _push(self, image: QImage) -> None:
        self._undo.append(self.image)
        del self._undo[:-_MAX_UNDO]
        self.image = image

    def undo(self) -> bool:
        if not self._undo:
            return False
        self.image = self._undo.pop()
        return True


class _Canvas(QWidget):
    """Görseli (gerekirse küçülterek) gösterir; sürüklenen alanı görsel pikseline çevirir."""

    selected = Signal(QRect)  # görsel koordinatlarında
    lined = Signal(QPoint, QPoint)  # çizgi araçları için: başlangıç ve bitiş (görsel)

    def __init__(self, image: QImage, available: QSize) -> None:
        super().__init__()
        self._available = available
        self._image = image
        self._scale = 1.0
        self._origin: QPoint | None = None
        self._drag: QRect | None = None
        self._end: QPoint | None = None
        self.line_mode = False  # açıkken sürükleme dikdörtgen değil çizgi olarak gösterilir
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.set_image(image)

    def set_image(self, image: QImage) -> None:
        self._image = image
        self._scale = fit_scale(image.size(), self._available)
        self.setFixedSize(
            max(1, round(image.width() * self._scale)), max(1, round(image.height() * self._scale))
        )
        self._origin = self._drag = None
        self.update()

    def to_image(self, rect: QRect) -> QRect:
        """Tuval dikdörtgenini, dokunduğu bütün görsel piksellerini kapsayacak şekilde çevirir."""
        r = rect.normalized().intersected(self.rect())
        if r.isEmpty():
            return QRect()
        s = self._scale
        x0, y0 = math.floor(r.left() / s), math.floor(r.top() / s)
        x1 = min(self._image.width(), math.ceil((r.right() + 1) / s))
        y1 = min(self._image.height(), math.ceil((r.bottom() + 1) / s))
        return QRect(x0, y0, x1 - x0, y1 - y0)

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawImage(self.rect(), self._image)
        if self.line_mode and self._origin is not None and self._end is not None:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(QPen(imaging.MARK_COLOR, 2))
            painter.drawLine(self._origin, self._end)
        elif self._drag is not None:
            painter.fillRect(self._drag, QColor(47, 125, 225, 60))
            painter.setPen(QPen(QColor(255, 255, 255), 1, Qt.PenStyle.DashLine))
            painter.drawRect(self._drag.adjusted(0, 0, -1, -1))

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._origin = event.position().toPoint()
            self._drag = None

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._origin is not None:
            pos = event.position().toPoint()
            self._end = QPoint(
                min(max(pos.x(), 0), self.width() - 1), min(max(pos.y(), 0), self.height() - 1)
            )
            self._drag = QRect(self._origin, pos).normalized()
            self._drag = self._drag.intersected(self.rect())
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton or self._origin is None:
            return
        drag, origin, end = self._drag, self._origin, self._end
        self._origin = self._drag = self._end = None
        self.update()
        if self.line_mode:
            if end is not None:
                self.lined.emit(self.point_to_image(origin), self.point_to_image(end))
        elif drag is not None and drag.width() >= _MIN_DRAG and drag.height() >= _MIN_DRAG:
            self.selected.emit(self.to_image(drag))

    def point_to_image(self, point: QPoint) -> QPoint:
        s = self._scale
        return QPoint(
            min(self._image.width() - 1, int(point.x() / s)),
            min(self._image.height() - 1, int(point.y() / s)),
        )


class ImageEditorDialog(QDialog):
    """Kabul edilirse `result_image` düzenlenmiş görseli taşır."""

    def __init__(self, image: QImage, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} - Görseli düzenle")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        self._session = EditSession(image)
        self.result_image: QImage | None = None

        screen = self.screen() or QGuiApplication.primaryScreen()
        area = screen.availableGeometry().size()
        available = QSize(int(area.width() * 0.85), int(area.height() * 0.85) - 150)
        self._canvas = _Canvas(image, available)
        self._canvas.selected.connect(self._apply)
        self._canvas.lined.connect(self._apply_line)

        lay = QVBoxLayout(self)
        bar = QHBoxLayout()
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        for index, (name, key, tip, _tool) in enumerate(TOOLS):
            button = QPushButton(f"{name} ({key})")
            button.setCheckable(True)
            button.setToolTip(tip)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self._group.addButton(button, index)
            bar.addWidget(button)
            QShortcut(QKeySequence(key), self, activated=button.click)
        self._group.button(0).setChecked(True)
        self._group.idToggled.connect(lambda _id, _on: self._update_state())
        bar.addStretch(1)
        self._undo = QPushButton("Geri al (Ctrl+Z)")
        self._undo.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._undo.clicked.connect(self._undo_last)
        bar.addWidget(self._undo)
        QShortcut(QKeySequence.StandardKey.Undo, self, activated=self._undo_last)
        lay.addLayout(bar)

        self._tip = QLabel()
        self._tip.setWordWrap(True)
        lay.addWidget(self._tip)

        holder = QHBoxLayout()
        holder.addStretch(1)
        holder.addWidget(self._canvas)
        holder.addStretch(1)
        lay.addLayout(holder, 1)
        self.setMinimumWidth(_MIN_CANVAS.width())

        bottom = QHBoxLayout()
        self._info = QLabel()
        bottom.addWidget(self._info)
        bottom.addStretch(1)
        cancel = QPushButton("İptal (Esc)")
        cancel.setAutoDefault(False)
        cancel.clicked.connect(self.reject)
        bottom.addWidget(cancel)
        self._save = QPushButton("Kaydet ve kopyala (Enter)")
        self._save.setDefault(True)
        self._save.clicked.connect(self._accept)
        bottom.addWidget(self._save)
        lay.addLayout(bottom)
        self._update_state()

    @property
    def session(self) -> EditSession:
        return self._session

    def select_tool(self, index: int) -> None:
        self._group.button(index).setChecked(True)

    def _apply_line(self, start: QPoint, end: QPoint) -> None:
        tool = TOOLS[self._group.checkedId()][3]
        if self._session.apply_line(tool, start, end):
            self._canvas.set_image(self._session.image)
            self._update_state()

    def _apply(self, rect: QRect) -> None:
        tool = TOOLS[self._group.checkedId()][3]
        if self._session.apply(tool, rect):
            self._canvas.set_image(self._session.image)
            self.adjustSize()
            self._update_state()

    def _undo_last(self) -> None:
        if self._session.undo():
            self._canvas.set_image(self._session.image)
            self.adjustSize()
            self._update_state()

    def _update_state(self) -> None:
        image = self._session.image
        self._canvas.line_mode = TOOLS[self._group.checkedId()][0] in LINE_TOOLS
        self._tip.setText(
            f"Fareyle bir alan seçin. {TOOLS[self._group.checkedId()][2]}"
        )
        self._info.setText(f"{image.width()}×{image.height()}")
        self._undo.setEnabled(self._session.modified)
        self._save.setEnabled(self._session.modified)

    def _accept(self) -> None:
        if self._session.modified:
            self.result_image = self._session.image
            self.accept()
