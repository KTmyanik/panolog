"""Global kısayolla açılan, klavyeyle tam kontrol edilen geçmiş penceresi."""
from __future__ import annotations

import os
import time

from PySide6.QtCore import QEvent, QFileInfo, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QFontMetrics, QGuiApplication, QKeyEvent, QPixmap
from PySide6.QtWidgets import (
    QFileIconProvider,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QTabBar,
    QVBoxLayout,
    QWidget,
)

from .. import winapi
from ..classifier import Category
from ..snippets import Snippet, SnippetRepository
from ..storage.models import FileRef, Item
from ..storage.repository import Repository
from .formatting import app_label, files_detail, files_title, preview_lines, relative_time

TABS: list[tuple[Category, str]] = [
    (Category.IMAGE, "Görseller"),
    (Category.TEXT, "Metinler"),
    (Category.LINK, "Linkler"),
    (Category.FILE, "Dosyalar"),
]

_icon_provider: QFileIconProvider | None = None
_icon_cache: dict[tuple[str, bool], QPixmap] = {}


def _file_pixmap(ref: FileRef) -> QPixmap:
    """Dosyanın kabuk ikonu. Ağ yollarında diske dokunmadan genel ikon kullanılır;
    erişilemeyen bir paylaşım popup'ı dondurmasın."""
    global _icon_provider
    if _icon_provider is None:
        _icon_provider = QFileIconProvider()
    local = winapi.is_on_fixed_drive(ref.path)
    key = (ref.path if local else "", ref.is_dir)
    if key not in _icon_cache:
        if local:
            icon = _icon_provider.icon(QFileInfo(ref.path))
        else:
            kind = QFileIconProvider.IconType.Folder if ref.is_dir else QFileIconProvider.IconType.File
            icon = _icon_provider.icon(kind)
        _icon_cache[key] = icon.pixmap(32, 32)
    return _icon_cache[key]

_WIDTH, _HEIGHT = 480, 560
_THUMB_H = 64

_STYLE = """
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
"""


class _Row(QWidget):
    def __init__(self, item: Item, number: int | None, text_width: int) -> None:
        super().__init__()
        # Tıklamalar listeye ulaşsın.
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(10)

        badge = QLabel(str(number) if number else "")
        badge.setObjectName("badge" if number else "")
        badge.setFixedSize(20, 20)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)

        body = QVBoxLayout()
        body.setSpacing(2)
        meta_parts: list[str] = []
        if item.category is Category.FILE:
            if item.files:
                icon = QLabel()
                icon.setPixmap(_file_pixmap(item.files[0]))
                icon.setFixedSize(32, 32)
                lay.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
                text_width -= 42
            main = QLabel()
            main.setTextFormat(Qt.TextFormat.PlainText)
            fm = QFontMetrics(main.font())
            title = files_title([f.name for f in item.files])
            main.setText(fm.elidedText(title, Qt.TextElideMode.ElideMiddle, text_width))
            body.addWidget(main)
            if item.files:
                folder = QLabel(
                    fm.elidedText(
                        os.path.dirname(item.files[0].path),
                        Qt.TextElideMode.ElideMiddle,
                        text_width,
                    )
                )
                folder.setObjectName("meta")
                folder.setTextFormat(Qt.TextFormat.PlainText)
                body.addWidget(folder)
                meta_parts.append(files_detail(item.files))
        elif item.category is Category.IMAGE:
            thumb = QLabel()
            pix = QPixmap(item.thumb_path) if item.thumb_path else QPixmap()
            if not pix.isNull():
                thumb.setPixmap(
                    pix.scaled(
                        text_width,
                        _THUMB_H,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
            else:
                thumb.setText("(önizleme yok)")
            body.addWidget(thumb)
            if item.width and item.height:
                meta_parts.append(f"{item.width}×{item.height}")
            if item.ocr_text:
                # Okunan metnin ilk satırı: görselin neden arama sonucunda çıktığı görülsün.
                ocr = QLabel()
                ocr.setObjectName("meta")
                ocr.setTextFormat(Qt.TextFormat.PlainText)
                first = preview_lines(item.ocr_text, max_lines=1)[0]
                ocr.setText(
                    QFontMetrics(ocr.font()).elidedText(
                        f"“{first}”", Qt.TextElideMode.ElideRight, text_width
                    )
                )
                body.addWidget(ocr)
        else:
            main = QLabel()
            main.setTextFormat(Qt.TextFormat.PlainText)  # içerik asla HTML olarak yorumlanmaz
            if item.category is Category.LINK:
                main.setObjectName("link")
            fm = QFontMetrics(main.font())
            shown = item.masked_text if item.masked_text is not None else item.text
            lines = preview_lines(shown or "")
            main.setText(
                "\n".join(
                    fm.elidedText(ln, Qt.TextElideMode.ElideRight, text_width) for ln in lines
                )
            )
            body.addWidget(main)

        meta_parts.append(relative_time(item.copied_at))
        if app := app_label(item.source_app):
            meta_parts.append(app)
        if item.sensitive:
            if item.expires_at is not None:
                left = max(0, int(item.expires_at - time.time()))
                meta_parts.append(f"🔒 {left} sn sonra silinecek")
            else:
                meta_parts.append("🔒 hassas")
        meta = QLabel("  ·  ".join(meta_parts))
        meta.setObjectName("meta")
        meta.setTextFormat(Qt.TextFormat.PlainText)
        body.addWidget(meta)
        lay.addLayout(body, 1)

        if item.pinned:
            pin = QLabel("📌")
            lay.addWidget(pin, 0, Qt.AlignmentFlag.AlignTop)


class _SnippetRow(QWidget):
    def __init__(self, snippet: Snippet, number: int | None, text_width: int) -> None:
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(10)
        badge = QLabel(str(number) if number else "")
        badge.setObjectName("badge" if number else "")
        badge.setFixedSize(20, 20)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)

        body = QVBoxLayout()
        body.setSpacing(2)
        title = QLabel()
        title.setTextFormat(Qt.TextFormat.PlainText)
        fm = QFontMetrics(title.font())
        head = snippet.name + (f"   {snippet.shortcode}" if snippet.shortcode else "")
        title.setText(fm.elidedText(head, Qt.TextElideMode.ElideRight, text_width))
        body.addWidget(title)
        preview = QLabel(
            fm.elidedText(
                preview_lines(snippet.content, max_lines=1)[0],
                Qt.TextElideMode.ElideRight,
                text_width,
            )
        )
        preview.setObjectName("meta")
        preview.setTextFormat(Qt.TextFormat.PlainText)
        body.addWidget(preview)
        if snippet.tag:
            tag = QLabel(f"# {snippet.tag}")
            tag.setObjectName("link")
            tag.setTextFormat(Qt.TextFormat.PlainText)
            body.addWidget(tag)
        lay.addLayout(body, 1)


_HINT_HISTORY = (
    "Enter yapıştır · Shift+Enter düz metin · 1-9 hızlı seç · Ctrl+P sabitle · "
    "Ctrl+S şablon yap · Del sil"
)
_HINT_IMAGES = (
    "Enter yapıştır · 1-9 hızlı seç · Ctrl+O metne çevir (OCR) · Ctrl+P sabitle · Del sil"
)
_HINT_SNIPPETS = "Enter yapıştır · 1-9 hızlı seç · Ctrl+N yeni · Ctrl+E düzenle · Del sil"
_HINT_CONFIRM = "Şablonu silmek için Delete'e tekrar basın"


class Popup(QWidget):
    pasteRequested = Signal(int, bool)  # (öğe id, düz metin mi)
    snippetRequested = Signal(int)  # şablonu yapıştır
    saveAsSnippetRequested = Signal(int)  # geçmiş öğesinden şablon oluştur
    editSnippetRequested = Signal(int)  # şablon id; 0 = yeni şablon
    ocrRequested = Signal(int)  # görseldeki metni çıkar
    changed = Signal()

    def __init__(self, repo: Repository, snippets: SnippetRepository) -> None:
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self._repo = repo
        self._snippets = snippets
        self._items: list = []  # geçmiş sekmelerinde Item, Şablonlar sekmesinde Snippet
        self._confirm_delete: int | None = None
        self._status: str | None = None  # ipucu satırında geçici durum mesajı
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(_WIDTH, _HEIGHT)
        self.setStyleSheet(_STYLE)

        frame = QWidget(self)
        frame.setObjectName("popup")
        frame.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(frame)

        lay = QVBoxLayout(frame)
        lay.setContentsMargins(10, 10, 10, 8)
        lay.setSpacing(6)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Aramak için yazın…")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(lambda _t: self.refresh())
        self._search.installEventFilter(self)
        lay.addWidget(self._search)

        self._tabs = QTabBar()
        self._tabs.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._tabs.setDrawBase(False)
        self._tabs.setUsesScrollButtons(False)
        self._tabs.setExpanding(True)
        for _cat, title in TABS:
            self._tabs.addTab(title)
        self._tabs.addTab("Şablonlar")
        self._tabs.setCurrentIndex(1)
        self._tabs.currentChanged.connect(lambda _i: self.refresh())
        lay.addWidget(self._tabs)

        self._list = QListWidget()
        self._list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self._list.setSpacing(1)
        self._list.itemClicked.connect(lambda it: self._paste_row(self._list.row(it), False))
        lay.addWidget(self._list, 1)

        self._empty = QLabel()
        self._empty.setObjectName("empty")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._empty, 1)

        hint = self._hint = QLabel(_HINT_HISTORY)
        hint.setObjectName("hint")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        f = hint.font()
        f.setPointSizeF(max(7.0, f.pointSizeF() - 1.5))
        hint.setFont(f)
        lay.addWidget(hint)

        # Süreli (hassas) öğe görünürken geri sayımı ve silinmeyi canlı göster.
        self._tick = QTimer(self)
        self._tick.setInterval(1000)
        self._tick.timeout.connect(self._on_tick)

    def _on_tick(self) -> None:
        if any(getattr(i, "expires_at", None) is not None for i in self._items):
            self._repo.purge_expired()
            self.refresh()

    def showEvent(self, event) -> None:  # noqa: N802
        self._tick.start()
        super().showEvent(event)

    def hideEvent(self, event) -> None:  # noqa: N802
        self._tick.stop()
        super().hideEvent(event)

    # ---- açma / kapama ------------------------------------------------------
    def open_at_cursor(self) -> None:
        self._status = None
        self._search.blockSignals(True)
        self._search.clear()
        self._search.blockSignals(False)
        self.refresh()
        pos = QCursor.pos()
        screen = QGuiApplication.screenAt(pos) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        x = min(max(pos.x() - _WIDTH // 2, area.left() + 8), area.right() - _WIDTH - 8)
        y = min(max(pos.y() - 40, area.top() + 8), area.bottom() - _HEIGHT - 8)
        self.move(x, y)
        self.show()
        self.raise_()
        self.activateWindow()
        self._search.setFocus()

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802
        if event.type() == QEvent.Type.ActivationChange and not self.isActiveWindow():
            self.hide()
        super().changeEvent(event)

    # ---- liste --------------------------------------------------------------
    def on_snippets_tab(self) -> bool:
        return self._tabs.currentIndex() == len(TABS)

    def show_snippets_tab(self) -> None:
        self._tabs.setCurrentIndex(len(TABS))

    def show_category(self, category: Category) -> None:
        self._tabs.setCurrentIndex([c for c, _t in TABS].index(category))
        if self._items:
            self._list.setCurrentRow(0)

    def show_status(self, message: str) -> None:
        """İpucu satırında, bir sonraki tuşa kadar kalan durum mesajı gösterir."""
        self._status = message
        self._hint.setText(message)

    def _default_hint(self) -> str:
        if self.on_snippets_tab():
            return _HINT_SNIPPETS
        return _HINT_IMAGES if self.current_category() is Category.IMAGE else _HINT_HISTORY

    def current_category(self) -> Category:
        return TABS[self._tabs.currentIndex()][0]

    def refresh(self) -> None:
        keep = self._list.currentRow()
        query = self._search.text()
        snippets_tab = self.on_snippets_tab()
        self._confirm_delete = None
        self._hint.setText(self._status or self._default_hint())
        if snippets_tab:
            self._items = self._snippets.list(query)
        else:
            self._items = self._repo.list_items(self.current_category(), query)
        self._list.clear()
        text_width = _WIDTH - 110
        for i, item in enumerate(self._items):
            number = i + 1 if i < 9 else None
            row_cls = _SnippetRow if snippets_tab else _Row
            row = row_cls(item, number, text_width)
            lw = QListWidgetItem()
            lw.setSizeHint(QSize(0, row.sizeHint().height()))
            self._list.addItem(lw)
            self._list.setItemWidget(lw, row)
        has = bool(self._items)
        self._list.setVisible(has)
        self._empty.setVisible(not has)
        if not has:
            if query.strip():
                self._empty.setText("Sonuç yok")
            elif snippets_tab:
                self._empty.setText("Henüz şablon yok\nCtrl+N ile yeni şablon ekleyin")
            else:
                self._empty.setText("Bu kategoride henüz öğe yok")
        else:
            self._list.setCurrentRow(min(max(keep, 0), len(self._items) - 1))

    def _selected(self):
        row = self._list.currentRow()
        return self._items[row] if 0 <= row < len(self._items) else None

    def _move(self, step: int) -> None:
        n = len(self._items)
        if n:
            self._list.setCurrentRow((self._list.currentRow() + step) % n)

    def _switch_tab(self, step: int) -> None:
        self._list.setCurrentRow(-1)
        self._tabs.setCurrentIndex((self._tabs.currentIndex() + step) % self._tabs.count())
        if self._items:
            self._list.setCurrentRow(0)

    def _paste_row(self, row: int, plain: bool) -> None:
        if 0 <= row < len(self._items):
            if self.on_snippets_tab():
                self.snippetRequested.emit(self._items[row].id)
            else:
                self.pasteRequested.emit(self._items[row].id, plain)

    def _delete_selected(self) -> None:
        item = self._selected()
        if item is None:
            return
        if self.on_snippets_tab():
            # Şablonlar kalıcıdır; yanlışlıkla silinmesin diye ikinci basış istenir.
            if self._confirm_delete != item.id:
                self._confirm_delete = item.id
                self._hint.setText(_HINT_CONFIRM)
                return
            self._snippets.delete(item.id)
        else:
            self._repo.delete(item.id)
        self.refresh()
        self.changed.emit()

    def _toggle_pin(self) -> None:
        if self.on_snippets_tab():
            return
        if item := self._selected():
            self._repo.set_pinned(item.id, not item.pinned)
            self.refresh()
            # Öğe sıralamada yer değiştirir; seçim onu izlesin.
            for i, it in enumerate(self._items):
                if it.id == item.id:
                    self._list.setCurrentRow(i)
                    break

    # ---- klavye -------------------------------------------------------------
    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is self._search and event.type() == QEvent.Type.KeyPress:
            return self._handle_key(event)
        return super().eventFilter(obj, event)

    def _handle_key(self, e: QKeyEvent) -> bool:
        key, mods = e.key(), e.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
        no_mod = mods == Qt.KeyboardModifier.NoModifier
        shift = mods == Qt.KeyboardModifier.ShiftModifier
        ctrl = mods == Qt.KeyboardModifier.ControlModifier
        alt = mods == Qt.KeyboardModifier.AltModifier
        empty = not self._search.text()
        K = Qt.Key
        snippets_tab = self.on_snippets_tab()
        if key not in (K.Key_Control, K.Key_Shift, K.Key_Alt, K.Key_Meta) and self._status:
            self._status = None
            self._hint.setText(self._default_hint())
        if key != K.Key_Delete and self._confirm_delete is not None:
            self._confirm_delete = None  # başka tuş silme onayını iptal eder
            self._hint.setText(_HINT_SNIPPETS)

        if key == K.Key_Escape:
            self.hide()
        elif key == K.Key_Down and no_mod:
            self._move(1)
        elif key == K.Key_Up and no_mod:
            self._move(-1)
        elif key in (K.Key_Return, K.Key_Enter) and (no_mod or shift):
            self._paste_row(self._list.currentRow(), shift)
        elif key == K.Key_Tab and (no_mod or ctrl):
            self._switch_tab(1)
        elif key == K.Key_Backtab or (key == K.Key_Tab and shift):
            self._switch_tab(-1)
        elif key == K.Key_Right and no_mod and empty:
            self._switch_tab(1)
        elif key == K.Key_Left and no_mod and empty:
            self._switch_tab(-1)
        elif K.Key_1 <= key <= K.Key_9 and ((no_mod and empty) or alt):
            # Arama kutusu doluyken rakamlar aramaya yazılır; Alt+rakam her zaman seçer.
            self._paste_row(key - K.Key_1, False)
        elif (
            key == K.Key_Delete
            and no_mod
            and self._search.cursorPosition() == len(self._search.text())
        ):
            self._delete_selected()
        elif key == K.Key_P and ctrl:
            self._toggle_pin()
        elif key == K.Key_S and ctrl and not snippets_tab:
            if item := self._selected():
                self.saveAsSnippetRequested.emit(item.id)
        elif key == K.Key_O and ctrl and not snippets_tab:
            item = self._selected()
            if item is not None and item.category is Category.IMAGE:
                self.ocrRequested.emit(item.id)
            elif item is not None:
                self.show_status("Metne çevirme (OCR) yalnızca görsellerde çalışır")
        elif key == K.Key_N and ctrl and snippets_tab:
            self.editSnippetRequested.emit(0)
        elif key == K.Key_E and ctrl and snippets_tab:
            if item := self._selected():
                self.editSnippetRequested.emit(item.id)
        else:
            return False
        return True
