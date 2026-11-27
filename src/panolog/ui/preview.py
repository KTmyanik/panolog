"""Büyük önizleme (görsel ya da metin): geçmiş penceresinin yanında açılan, odak almayan pencere."""
from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QFont, QFontMetrics, QPixmap
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from .themes import DEFAULT_THEME, get_theme

_GAP = 8  # popup ile önizleme ve ekran kenarı arasındaki boşluk
_BORDER = 6  # görselin çevresindeki çerçeve
_MIN_SIDE = 160  # yanda bundan dar yer kalıyorsa önizleme popup'ın üstüne biner

_TEXT_MAX_WIDTH = 760  # metin önizlemesinin en büyük genişliği (piksel)
_TEXT_PAD = 10
TEXT_MAX_LINES = 200
TEXT_MAX_CHARS = 20_000


def clip_text(text: str, max_lines: int = TEXT_MAX_LINES, max_chars: int = TEXT_MAX_CHARS):
    """Önizlemede gösterilecek kısım ve dışarıda kalan satır sayısı.

    Çok büyük bir metin (ör. bütün bir log dosyası) pencereyi kilitlemesin diye kısaltılır.
    """
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    shown: list[str] = []
    used = 0
    for line in lines[:max_lines]:
        room = max_chars - used
        if room <= 0:
            break
        if len(line) > room:
            shown.append(line[:room] + "…")
            used = max_chars
            break
        shown.append(line)
        used += len(line) + 1
    return "\n".join(shown), len(lines) - len(shown)


def preview_geometry(popup: QRect, screen: QRect, image: QSize) -> QRect:
    """Önizleme penceresinin yeri ve boyutu.

    Popup'ın daha geniş yer kalan yanına, ekrana sığacak şekilde yerleşir. Görsel
    asla büyütülmez; yalnızca sığmıyorsa küçültülür.
    """
    room_right = screen.right() - popup.right() - 2 * _GAP
    room_left = popup.left() - screen.left() - 2 * _GAP
    on_right = room_right >= room_left
    room = max(room_right, room_left)
    if room < _MIN_SIDE:  # yanlarda yer yok (çok dar ekran): ekranın tamamını kullan
        room = screen.width() - 2 * _GAP
    max_w = room - 2 * _BORDER
    max_h = screen.height() - 2 * _GAP - 2 * _BORDER
    size = QSize(image)
    if size.width() > max_w or size.height() > max_h:
        size.scale(max_w, max_h, Qt.AspectRatioMode.KeepAspectRatio)
    w = max(1, size.width()) + 2 * _BORDER
    h = max(1, size.height()) + 2 * _BORDER
    if max(room_right, room_left) < _MIN_SIDE:
        x = screen.left() + (screen.width() - w) // 2
    elif on_right:
        x = popup.right() + 1 + _GAP
    else:
        x = popup.left() - _GAP - w
    y = popup.top() + (popup.height() - h) // 2
    y = min(max(y, screen.top() + _GAP), screen.bottom() + 1 - _GAP - h)
    return QRect(x, y, w, h)


class ImagePreview(QWidget):
    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.WindowTransparentForInput,
        )
        # Önizleme açılınca popup etkin pencere olmayı sürdürmeli; yoksa kendini kapatır.
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(get_theme(DEFAULT_THEME).preview_qss)
        frame = QWidget(self)
        frame.setObjectName("preview")
        frame.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(frame)
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(_BORDER, _BORDER, _BORDER, _BORDER)
        self._label = QLabel()
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setTextFormat(Qt.TextFormat.PlainText)  # içerik asla HTML olarak yorumlanmaz
        self._mono = QFont("Consolas")
        self._mono.setStyleHint(QFont.StyleHint.Monospace)
        self._mono.setPointSizeF(10.0)
        self._label.setFont(self._mono)
        lay.addWidget(self._label)
        self._path: str | None = None
        self._pixmap = QPixmap()

    def show_image(self, path: str, popup: QRect, screen: QRect) -> bool:
        """Görseli gösterir; dosya okunamazsa False döner ve pencere kapanır."""
        if path != self._path:
            self._path, self._pixmap = path, QPixmap(path)
        return self._show_pixmap(popup, screen)

    def show_data(self, data: bytes, key: str, popup: QRect, screen: QRect) -> bool:
        """Bellekteki bir görseli (ör. görsel şablon) gösterir. `key` önbellek anahtarıdır."""
        if key != self._path:
            pixmap = QPixmap()
            pixmap.loadFromData(data)
            self._path, self._pixmap = key, pixmap
        return self._show_pixmap(popup, screen)

    def _show_pixmap(self, popup: QRect, screen: QRect) -> bool:
        if self._pixmap.isNull():
            self._path = None  # dosya henüz yazılıyor olabilir; sonraki denemede yeniden oku
            self.hide()
            return False
        # Ekran ölçeklemesinde (ör. %150) görsel kendi pikselleriyle gösterilir, büyütülmez.
        ratio = self.devicePixelRatioF()
        logical = QSize(
            max(1, round(self._pixmap.width() / ratio)), max(1, round(self._pixmap.height() / ratio))
        )
        geo = preview_geometry(popup, screen, logical)
        inner = geo.size() - QSize(2 * _BORDER, 2 * _BORDER)
        shown = self._pixmap
        if inner * ratio != shown.size():
            shown = shown.scaled(
                inner * ratio,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        else:
            shown = QPixmap(shown)
        shown.setDevicePixelRatio(ratio)
        self._label.setWordWrap(False)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setContentsMargins(0, 0, 0, 0)
        self._label.setPixmap(shown)
        self.setGeometry(geo)
        self.show()
        return True

    def show_text(self, text: str, popup: QRect, screen: QRect) -> bool:
        """Metni eş aralıklı yazıyla, satırları kaydırarak gösterir. Boş metinde False döner.

        Ekrana sığmayan metin alttan kısaltılır ve kaç satırın gösterilmediği yazılır.
        """
        shown, hidden = clip_text(text)
        if not shown.strip():
            self.hide()
            return False
        self._path, self._pixmap = None, QPixmap()
        fm = QFontMetrics(self._mono)
        pad = 2 * _TEXT_PAD
        # Önce yanda ne kadar yer olduğunu öğren, sonra metni o genişliğe göre kaydır.
        room = preview_geometry(popup, screen, QSize(100_000, 1)).width() - 2 * _BORDER
        max_h = screen.height() - 2 * _GAP - 2 * _BORDER
        lines = shown.split("\n")
        total = len(lines) + hidden
        widest = max(fm.horizontalAdvance(line) for line in lines) + 2
        width = max(120, min(widest, _TEXT_MAX_WIDTH, room - pad))
        self._label.setWordWrap(True)
        self._label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self._label.setContentsMargins(_TEXT_PAD, _TEXT_PAD, _TEXT_PAD, _TEXT_PAD)
        height = 0
        for _attempt in range(8):
            body = "\n".join(lines)
            if len(lines) < total:
                body += f"\n\n… {total - len(lines)} satır daha"
            self._label.setText(body)
            height = self._label.heightForWidth(width + pad)
            if height <= max_h:
                break
            if len(lines) > 1:  # sığacak kadar satır bırak
                lines = lines[: max(1, int(len(lines) * max_h / height) - 1)]
            else:  # tek ve çok uzun bir satır (ör. sıkıştırılmış JSON)
                keep = max(40, int(len(lines[0]) * max_h / height) - 40)
                lines = [lines[0][:keep] + "…"]
        self.setGeometry(preview_geometry(popup, screen, QSize(width + pad, min(height, max_h))))
        self.show()
        return True

    def forget(self) -> None:
        """Kapatır ve bellekteki görseli bırakır."""
        self.hide()
        self._path, self._pixmap = None, QPixmap()
        self._label.clear()
