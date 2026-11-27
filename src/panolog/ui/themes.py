"""Geçmiş penceresinin görünümleri (temalar): renkler, arka plan çizimi ve satır biçimi.

Tema yalnızca görünümü değiştirir; tuşlar ve davranış her temada aynıdır.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import (
    QBrush,
    QColor,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOption, QWidget

DEFAULT_THEME = "classic"

# Not (kâğıt) görünümünde her öğe için saklanan veriler.
ROLE_PIXMAP = Qt.ItemDataRole.UserRole + 1
ROLE_SEED = Qt.ItemDataRole.UserRole + 2


@dataclass(frozen=True)
class Theme:
    key: str
    label: str
    qss: str  # geçmiş penceresinin stil sayfası
    preview_qss: str  # büyük önizleme penceresi
    backdrop: str = "qss"  # arka planı kim çizer: "qss", "aurora", "cork", "brutal"
    rows: str = "list"  # "list" (düz satır), "cards" (çerçeveli kart), "notes" (iki sütun not)
    animated: bool = False  # arka plan hareketli mi
    glass: bool = False  # Windows izin verirse arkadaki masaüstü bulanık görünsün
    brand: bool = False  # üstte uygulama adı gösterilsin mi
    row_margins: tuple[int, int, int, int] = (8, 6, 8, 6)
    row_qss: str = ""  # "notes" görünümünde satırın kendi stil sayfası
    text_lines: int = 2  # satırda gösterilen metin satırı sayısı
    spacing: int = 6  # pencere içi dikey boşluk


_CLASSIC_QSS = """
#popup { background: #1f2127; border: 1px solid #3a3d46; border-radius: 10px; }
QLabel { color: #e6e8ec; }
QLineEdit { background: #2a2d35; color: #e6e8ec; border: 1px solid #3a3d46;
            border-radius: 6px; padding: 6px 8px; selection-background-color: #2f7de1; }
QLineEdit:focus { border-color: #2f7de1; }
QTabBar::tab { color: #a9aeb8; padding: 6px 10px; border: none;
               border-bottom: 2px solid transparent; }
QTabBar::tab:selected { color: #ffffff; border-bottom-color: #2f7de1; }
QListWidget { background: transparent; border: none; outline: none; }
QListWidget::item { border-radius: 6px; }
QListWidget::item:selected { background: #2d4a73; }
QListWidget::item:hover:!selected { background: #282b33; }
#meta, #hint, #empty { color: #8b909b; }
#badge { color: #8b909b; background: #2a2d35; border-radius: 4px; }
#link { color: #7fb4ff; }
QMenu { background: #2a2d35; color: #e6e8ec; border: 1px solid #3a3d46; }
QMenu::item:selected { background: #2d4a73; }
"""
_CLASSIC_PREVIEW = (
    "#preview { background: #1f2127; border: 1px solid #3a3d46; border-radius: 8px; }"
    "QLabel { color: #e6e8ec; }"
)

_AURORA_QSS = """
QLabel { color: #ffffff; }
QLineEdit { background: rgba(255,255,255,38); color: #ffffff;
            border: 1px solid rgba(255,255,255,70); border-radius: 12px; padding: 7px 11px;
            selection-background-color: #ff4fa3; }
QLineEdit:focus { border-color: rgba(255,255,255,170); }
QTabBar::tab { color: rgba(255,255,255,185); padding: 5px 9px; margin: 2px 2px;
               border-radius: 12px; }
QTabBar::tab:selected { background: #ffffff; color: #1a1640; }
QListWidget { background: transparent; border: none; outline: none; }
QListWidget::item { border-radius: 14px; }
QListWidget::item:selected {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                stop:0 rgba(255,79,163,170), stop:1 rgba(61,123,255,170)); }
QListWidget::item:hover:!selected { background: rgba(255,255,255,30); }
#meta, #hint, #empty { color: rgba(255,255,255,180); }
#badge { color: #ffffff; background: rgba(255,255,255,48); border-radius: 7px; }
#link { color: #cfe6ff; }
QMenu { background: #1b1f45; color: #ffffff; border: 1px solid rgba(255,255,255,70); }
QMenu::item:selected { background: #5a56d6; }
"""
_AURORA_PREVIEW = (
    "#preview { background: #171a3d; border: 1px solid rgba(255,255,255,90);"
    " border-radius: 14px; }"
    "QLabel { color: #ffffff; }"
)

_PAPER_QSS = """
QLabel { color: #2e2618; }
QLineEdit { background: #fffdf6; color: #2e2618; border: none;
            border-bottom: 2px solid #d9cfb8; border-radius: 3px; padding: 5px 10px;
            font-family: "Ink Free", "Segoe Print", "Segoe UI"; font-size: 14pt;
            selection-background-color: #e0b84a; selection-color: #2e2618; }
QTabBar::tab { font-family: "Ink Free", "Segoe Print", "Segoe UI"; font-size: 12pt;
               background: #e8dcc0; color: #6b5a3c; padding: 2px 8px; margin-right: 3px;
               border-top-left-radius: 6px; border-top-right-radius: 6px; }
QTabBar::tab:selected { background: #fffdf6; color: #2e2618; font-weight: bold; }
QListWidget { background: transparent; border: none; outline: none; }
QListWidget::item, QListWidget::item:selected, QListWidget::item:hover {
    background: transparent; border: none; }
#hint { color: #3d2f16; }
#empty { color: #3d2f16; font-family: "Ink Free", "Segoe Print", "Segoe UI"; font-size: 14pt; }
QMenu { background: #fffdf6; color: #2e2618; border: 1px solid #b89a66; }
QMenu::item:selected { background: #fff3a6; }
"""
_PAPER_ROW_QSS = """
QLabel { color: #2e2618; font-family: "Ink Free", "Segoe Print", "Segoe UI"; font-size: 11pt; }
#code { font-family: Consolas, "Courier New", monospace; font-size: 8pt; }
#meta { color: #a3392b; font-family: Consolas, "Courier New", monospace; font-size: 7pt; }
#badge { color: #7a6a4e; background: transparent; font-family: Consolas; font-size: 8pt; }
#link { color: #1d4f91; }
#thumb { border: 1px solid #b9ad92; }
"""
_PAPER_PREVIEW = (
    "#preview { background: #fffdf6; border: 1px solid #b89a66; border-radius: 3px; }"
    "QLabel { color: #2e2618; }"
)

_BRUTAL_QSS = """
QLabel { color: #111111; font-weight: 600; }
QLineEdit { background: #ffffff; color: #111111; border: 3px solid #111111; border-radius: 0;
            padding: 6px 10px; font-weight: 600; selection-background-color: #111111;
            selection-color: #ffd23f; }
QTabBar::tab { background: #ffffff; color: #111111; border: 3px solid #111111;
               padding: 2px 6px; margin-right: 5px; font-weight: 700; }
QTabBar::tab:selected { background: #111111; color: #ffffff; }
QListWidget { background: transparent; border: none; outline: none; }
QListWidget::item, QListWidget::item:selected, QListWidget::item:hover {
    background: transparent; border: none; }
#brand { font-family: "Arial Black", "Segoe UI Black", "Segoe UI"; font-size: 17pt;
         color: #111111; }
#count { font-family: Consolas, monospace; font-size: 8pt; color: #ffd23f;
         background: #111111; padding: 2px 7px; }
#meta, #hint, #empty { color: #111111; }
#badge { color: #ffffff; background: #111111; border-radius: 0; }
#link { color: #111111; text-decoration: underline; }
#thumb { border: 2px solid #111111; }
QMenu { background: #ffffff; color: #111111; border: 3px solid #111111; }
QMenu::item:selected { background: #ff5d8f; }
"""
_BRUTAL_PREVIEW = (
    "#preview { background: #ffffff; border: 3px solid #111111; border-radius: 0; }"
    "QLabel { color: #111111; }"
)

THEMES: dict[str, Theme] = {
    t.key: t
    for t in (
        Theme("classic", "Klasik (koyu)", _CLASSIC_QSS, _CLASSIC_PREVIEW),
        Theme(
            "aurora",
            "Aurora cam",
            _AURORA_QSS,
            _AURORA_PREVIEW,
            backdrop="aurora",
            animated=True,
            glass=True,
            row_margins=(10, 8, 10, 8),
        ),
        Theme(
            "paper",
            "Kâğıt masa",
            _PAPER_QSS,
            _PAPER_PREVIEW,
            backdrop="cork",
            rows="notes",
            row_margins=(4, 2, 4, 2),
            row_qss=_PAPER_ROW_QSS,
            text_lines=4,
        ),
        Theme(
            "brutal",
            "Sert çizgi",
            _BRUTAL_QSS,
            _BRUTAL_PREVIEW,
            backdrop="brutal",
            rows="cards",
            brand=True,
            row_margins=(14, 10, 20, 17),
            spacing=10,
        ),
    )
}


def get_theme(key: str | None) -> Theme:
    """Bilinmeyen (ör. eski bir sürümden kalan) anahtar için varsayılan tema döner."""
    return THEMES.get(key or "", THEMES[DEFAULT_THEME])


# ---- arka plan ---------------------------------------------------------------
AURORA_BASE = QColor(13, 16, 40)
# (renk, merkez x, merkez y, yarıçap, faz) — konum ve yarıçap pencere boyutuna oranlıdır.
AURORA_BLOBS: tuple[tuple[tuple[int, int, int], float, float, float, float], ...] = (
    ((255, 79, 163), 0.12, 0.10, 0.62, 0.0),
    ((61, 123, 255), 0.92, 0.38, 0.70, 2.1),
    ((47, 224, 181), 0.40, 1.02, 0.60, 4.2),
)


def aurora_blob_centers(t: float) -> list[tuple[float, float]]:
    """Renk lekelerinin t anındaki (oransal) merkezleri; yavaş ve döngüsel hareket."""
    return [
        (cx + 0.07 * math.sin(t * 0.45 + phase), cy + 0.06 * math.cos(t * 0.37 + phase))
        for _color, cx, cy, _r, phase in AURORA_BLOBS
    ]


GLASS_BASE_ALPHA = 165  # buzlu cam etkinken zeminin opaklığı (0-255)
GLASS_RADIUS = 8  # Windows 11'in pencere köşe yarıçapı


def paint_aurora(
    p: QPainter, rect: QRectF, t: float, base_alpha: int = 255, radius: float = 18
) -> None:
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setClipPath(path)
    base = QColor(AURORA_BASE)
    base.setAlpha(base_alpha)
    p.fillRect(rect, base)
    w, h = rect.width(), rect.height()
    for (color, _cx, _cy, radius, _phase), (cx, cy) in zip(AURORA_BLOBS, aurora_blob_centers(t)):
        center = QPointF(rect.left() + cx * w, rect.top() + cy * h)
        grad = QRadialGradient(center, radius * max(w, h))
        grad.setColorAt(0.0, QColor(*color, 205))
        grad.setColorAt(0.55, QColor(*color, 70))
        grad.setColorAt(1.0, QColor(*color, 0))
        p.fillRect(rect, QBrush(grad))
    p.fillRect(rect, QColor(255, 255, 255, 22))  # buzlu cam pusu
    p.setClipping(False)
    p.setPen(QPen(QColor(255, 255, 255, 90), 1))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)


_cork_tile: QPixmap | None = None


def _cork_brush() -> QBrush:
    global _cork_tile
    if _cork_tile is None:
        tile = QPixmap(9, 9)
        tile.fill(QColor("#c9a97a"))
        tp = QPainter(tile)
        tp.setRenderHint(QPainter.RenderHint.Antialiasing)
        tp.setPen(Qt.PenStyle.NoPen)
        tp.setBrush(QColor(90, 60, 20, 60))
        tp.drawEllipse(QPointF(2.5, 2.5), 0.9, 0.9)
        tp.setBrush(QColor(255, 235, 200, 45))
        tp.drawEllipse(QPointF(6.5, 6.0), 0.8, 0.8)
        tp.end()
        _cork_tile = tile
    return QBrush(_cork_tile)


def paint_cork(p: QPainter, rect: QRectF) -> None:
    path = QPainterPath()
    path.addRoundedRect(rect, 8, 8)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.fillPath(path, _cork_brush())
    p.setPen(QPen(QColor("#8a6a3c"), 2))
    p.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 8, 8)


BRUTAL_SHADOW = 5


def paint_brutal(p: QPainter, rect: QRectF, shadowed: list[QRect]) -> None:
    p.fillRect(rect, QColor("#ffd23f"))
    p.setPen(QPen(QColor("#111111"), 3))
    p.drawRect(rect.adjusted(1.5, 1.5, -1.5, -1.5))
    for r in shadowed:  # arama kutusu gibi öğelerin arkasına sert gölge
        p.fillRect(r.translated(BRUTAL_SHADOW, BRUTAL_SHADOW), QColor("#111111"))


class Backdrop(QWidget):
    """Pencerenin zemini. Klasik temada stil sayfası, diğerlerinde özel çizim kullanılır."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("popup")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self._theme = THEMES[DEFAULT_THEME]
        self._animate = True
        self._shadowed: list[QWidget] = []
        self.glass = False  # gerçek buzlu cam etkin: zemin yarı saydam ve köşeler Windows'un
        self._started = time.monotonic()
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self.update)

    def set_theme(self, theme: Theme, animate: bool) -> None:
        self._theme, self._animate = theme, animate
        self._sync_timer()
        self.update()

    def set_shadowed(self, widgets: list[QWidget]) -> None:
        self._shadowed = widgets

    def is_animating(self) -> bool:
        return self._timer.isActive()

    def _sync_timer(self) -> None:
        if self._theme.animated and self._animate and self.isVisible():
            self._timer.start()
        else:
            self._timer.stop()

    def showEvent(self, event) -> None:  # noqa: N802
        self._sync_timer()
        super().showEvent(event)

    def hideEvent(self, event) -> None:  # noqa: N802
        self._timer.stop()  # pencere kapalıyken hiç çizim yapılmaz
        super().hideEvent(event)

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        rect = QRectF(self.rect())
        kind = self._theme.backdrop
        if kind == "aurora":
            t = time.monotonic() - self._started if self._animate else 0.0
            if self.glass:
                paint_aurora(p, rect, t, GLASS_BASE_ALPHA, GLASS_RADIUS)
            else:
                paint_aurora(p, rect, t)
        elif kind == "cork":
            paint_cork(p, rect)
        elif kind == "brutal":
            visible = [w.geometry() for w in self._shadowed if w.isVisible()]
            paint_brutal(p, rect, visible)
        else:
            opt = QStyleOption()
            opt.initFrom(self)
            self.style().drawPrimitive(QStyle.PrimitiveElement.PE_Widget, opt, p, self)


# ---- satır çizimi --------------------------------------------------------------
class CardDelegate(QStyledItemDelegate):
    """"Sert çizgi": kalın çerçeveli, sert gölgeli kart. İçerik, üstündeki satır bileşenidir."""

    def paint(self, p: QPainter, option, index) -> None:
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        card = QRectF(option.rect).adjusted(3.5, 3.5, -9.5, -9.5)
        shadow = BRUTAL_SHADOW + (2 if hover and not selected else 0)
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        p.fillRect(card.translated(shadow, shadow), QColor("#111111"))
        p.fillRect(card, QColor("#ff5d8f" if selected else "#ffffff"))
        p.setPen(QPen(QColor("#111111"), 3))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(card)
        p.restore()


NOTE_COLORS = ("#fff3a6", "#fffdf6", "#bfe8d4", "#ffc9d6")
NOTE_MARGINS = (12, 16, 12, 10)  # ızgara hücresi içinde notun payı (sol, üst, sağ, alt)
NOTE_PADDING = (6, 10)  # not içinde içeriğin payı (yatay, üst)


def note_angle(seed: int) -> float:
    """Notun eğimi (derece): öğeye göre sabit, -2.4 ile +2.4 arasında, sıfıra yakın değil."""
    value = ((seed * 37) % 17 - 8) * 0.3
    return value if abs(value) >= 0.9 else (1.2 if seed % 2 else -1.2)


def note_content_size(cell: QSize) -> QSize:
    """Bir ızgara hücresindeki notun içine çizilecek satır görüntüsünün boyutu."""
    left, top, right, bottom = NOTE_MARGINS
    pad_x, pad_top = NOTE_PADDING
    return QSize(cell.width() - left - right - 2 * pad_x, cell.height() - top - bottom - pad_top - 4)


class NoteDelegate(QStyledItemDelegate):
    """"Kâğıt masa": bantla tutturulmuş, hafif eğik not. İçerik önceden çizilmiş bir görüntüdür."""

    def paint(self, p: QPainter, option, index) -> None:
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        seed = int(index.data(ROLE_SEED) or 0)
        left, top, right, bottom = NOTE_MARGINS
        note = QRectF(option.rect).adjusted(left, top, -right, -bottom)
        w, h = note.width(), note.height()
        local = QRectF(-w / 2, -h / 2, w, h)
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.translate(note.center())
        if selected:
            p.scale(1.04, 1.04)  # seçili not doğrulur ve öne çıkar
        elif not hover:
            p.rotate(note_angle(seed))
        p.setPen(Qt.PenStyle.NoPen)
        lift = (5.0, 11.0, 110) if selected else (2.0, 5.0, 85)
        p.setBrush(QColor(50, 30, 5, lift[2]))
        p.drawRect(local.translated(lift[0], lift[1]))
        p.setBrush(QColor(NOTE_COLORS[seed % len(NOTE_COLORS)]))
        p.drawRect(local)
        pixmap = index.data(ROLE_PIXMAP)
        if isinstance(pixmap, QPixmap) and not pixmap.isNull():
            pad_x, pad_top = NOTE_PADDING
            p.drawPixmap(QPointF(local.left() + pad_x, local.top() + pad_top), pixmap)
        if selected:
            p.setPen(QPen(QColor("#2e2618"), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(local.adjusted(1, 1, -1, -1))
            p.setPen(Qt.PenStyle.NoPen)
        p.rotate(-2.0 if seed % 2 else 2.0)
        p.setBrush(QColor(255, 255, 255, 165))
        p.drawRect(QRectF(-26, -h / 2 - 8, 52, 15))  # bant
        p.restore()
