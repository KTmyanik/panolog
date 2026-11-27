"""Global kısayolla açılan, klavyeyle tam kontrol edilen geçmiş penceresi."""
from __future__ import annotations

import os
import time

from PySide6.QtCore import QEvent, QFileInfo, QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QFontMetrics, QGuiApplication, QKeyEvent, QPixmap, QRegion
from PySide6.QtWidgets import (
    QFileIconProvider,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QTabBar,
    QVBoxLayout,
    QWidget,
)

from .. import APP_NAME, winapi
from ..classifier import Category
from ..snippets import Snippet, SnippetRepository
from ..storage.models import FileRef, Item
from ..storage.repository import Repository
from .formatting import app_label, files_detail, files_title, preview_lines, relative_time
from ..ocr.merge import looks_like_code
from .preview import ImagePreview
from .themes import (
    DEFAULT_THEME,
    ROLE_PIXMAP,
    ROLE_SEED,
    Backdrop,
    CardDelegate,
    NoteDelegate,
    Theme,
    get_theme,
    note_content_size,
)

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
_SNIPPET_THUMB_H = 44
_HOVER_PREVIEW_MS = 450  # imleç bir görselin üzerinde bu kadar durunca önizleme açılır

# "notes" görünümünde ızgara hücresi. İki hücre liste genişliğinden (pencere - 20) biraz dar
# olmalı; tam sığınca Qt ikinci notu alt satıra atıyor.
_NOTE_CELL = QSize((_WIDTH - 20 - 4) // 2, 142)


class _Row(QWidget):
    def __init__(self, item: Item, number: int | None, text_width: int, theme: Theme) -> None:
        super().__init__()
        # Tıklamalar listeye ulaşsın.
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(*theme.row_margins)
        lay.setSpacing(10)
        wrap = theme.rows == "notes"
        if wrap and item.pinned:
            text_width -= 24  # raptiye işaretine yer kalsın

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
            thumb.setObjectName("thumb")
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
            body.addWidget(thumb, 0, Qt.AlignmentFlag.AlignLeft)
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
            lines = preview_lines(shown or "", max_lines=theme.text_lines)
            if item.category is Category.TEXT and any(looks_like_code(ln) for ln in lines):
                main.setObjectName("code")  # bazı temalar kodu eş aralıklı yazıyla gösterir
                main.ensurePolished()
            if wrap:
                main.setWordWrap(True)
                main.setFixedWidth(text_width)
                # Uzun metin notun altındaki damganın üstüne taşmasın; fazlası kesilir.
                main.setFixedHeight(note_content_size(_NOTE_CELL).height() - 26)
                main.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
                main.setText("\n".join(lines))
                body.addWidget(main, 1)
            else:
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
        meta = QLabel()
        meta.setObjectName("meta")
        meta.setTextFormat(Qt.TextFormat.PlainText)
        if wrap:
            meta.setFixedWidth(text_width)
            meta.setText(" · ".join(reversed(meta_parts)).upper())  # damga: önce uygulama ve zaman
        else:
            meta.setText(
                QFontMetrics(meta.font()).elidedText(
                    "  ·  ".join(meta_parts), Qt.TextElideMode.ElideRight, text_width
                )
            )
        body.addWidget(meta)
        lay.addLayout(body, 1)

        if item.pinned:
            pin = QLabel("📌")
            lay.addWidget(pin, 0, Qt.AlignmentFlag.AlignTop)


class _SnippetRow(QWidget):
    def __init__(self, snippet: Snippet, number: int | None, text_width: int, theme: Theme) -> None:
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(*theme.row_margins)
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
        if snippet.is_image:
            # Görsel şablon: koyu temalarda da görünsün diye küçük resim beyaz zeminde durur.
            thumb = QLabel()
            thumb.setObjectName("thumb")
            pix = QPixmap()
            pix.loadFromData(snippet.image)
            if not pix.isNull():
                thumb.setPixmap(
                    pix.scaled(
                        min(text_width, pix.width()),
                        min(_SNIPPET_THUMB_H, pix.height()),
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
            else:
                thumb.setText("(görsel okunamadı)")
            body.addWidget(thumb, 0, Qt.AlignmentFlag.AlignLeft)
        else:
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
    "Enter yapıştır · Shift+Enter düz metin · Boşluk önizle · Ctrl+P sabitle · "
    "Ctrl+S şablon yap · Del sil"
)
_HINT_IMAGES = (
    "Enter yapıştır · Boşluk büyüt · Ctrl+E düzenle · Ctrl+O metne çevir · "
    "Ctrl+P sabitle · Del sil"
)
_HINT_SNIPPETS = "Enter yapıştır · Boşluk önizle · Ctrl+N yeni · Ctrl+E düzenle · Del sil"
_HINT_CONFIRM = "Şablonu silmek için Delete'e tekrar basın"


class Popup(QWidget):
    pasteRequested = Signal(int, bool)  # (öğe id, düz metin mi)
    snippetRequested = Signal(int)  # şablonu yapıştır
    saveAsSnippetRequested = Signal(int)  # geçmiş öğesinden şablon oluştur
    editSnippetRequested = Signal(int)  # şablon id; 0 = yeni şablon
    ocrRequested = Signal(int)  # görseldeki metni çıkar
    editImageRequested = Signal(int)  # görseli düzenleyicide aç
    saveImageRequested = Signal(int)  # görseli PNG dosyası olarak kaydet
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
        self._theme = get_theme(DEFAULT_THEME)

        frame = self._frame = Backdrop(self)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(frame)

        lay = self._layout = QVBoxLayout(frame)
        lay.setContentsMargins(10, 10, 10, 8)
        lay.setSpacing(6)

        # Uygulama adı ve kayıt sayısı; yalnızca bunu isteyen temalarda görünür.
        self._brand = QWidget()
        brand_lay = QHBoxLayout(self._brand)
        brand_lay.setContentsMargins(2, 0, 2, 0)
        brand_name = QLabel(APP_NAME.upper())
        brand_name.setObjectName("brand")
        brand_lay.addWidget(brand_name)
        brand_lay.addStretch(1)
        self._count = QLabel()
        self._count.setObjectName("count")
        brand_lay.addWidget(self._count)
        self._brand.hide()
        lay.addWidget(self._brand)

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
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._show_menu)
        self._list.currentRowChanged.connect(self._on_row_changed)
        self._list.verticalScrollBar().valueChanged.connect(lambda _v: self._hide_preview())
        self._viewport = self._list.viewport()
        self._viewport.setMouseTracking(True)
        self._viewport.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self._plain_delegate = self._list.itemDelegate()
        self._card_delegate = CardDelegate(self._list)
        self._note_delegate = NoteDelegate(self._list)
        frame.set_shadowed([self._search])
        self._viewport.installEventFilter(self)
        lay.addWidget(self._list, 1)

        # Büyük önizleme: imleç görselin üzerinde durunca ya da Boşluk ile açılır.
        self._preview = ImagePreview()
        self._preview_pinned = False  # Boşluk ile açıldı: seçimi izler, imleçle kapanmaz
        self._hover_row = -1
        self._hover_timer = QTimer(self)
        self._hover_timer.setSingleShot(True)
        self._hover_timer.setInterval(_HOVER_PREVIEW_MS)
        self._hover_timer.timeout.connect(self._show_hover_preview)
        self._menu_open = False
        self._refreshing = False

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
        self.set_theme(DEFAULT_THEME)

    def _on_tick(self) -> None:
        if any(getattr(i, "expires_at", None) is not None for i in self._items):
            self._repo.purge_expired()
            self.refresh()

    # ---- tema ---------------------------------------------------------------
    @property
    def theme(self) -> Theme:
        return self._theme

    def set_theme(self, key: str | None, animate: bool = True) -> None:
        """Görünümü değiştirir. Davranış ve tuşlar her temada aynıdır."""
        theme = self._theme = get_theme(key)
        self.setStyleSheet(theme.qss)
        self._preview.setStyleSheet(theme.preview_qss)
        self._frame.set_theme(theme, animate)
        self._apply_window_effects()
        self._layout.setSpacing(theme.spacing)
        self._brand.setVisible(theme.brand)
        notes = theme.rows == "notes"
        self._list.setFlow(QListView.Flow.LeftToRight if notes else QListView.Flow.TopToBottom)
        self._list.setWrapping(notes)
        self._list.setResizeMode(QListView.ResizeMode.Adjust)
        self._list.setGridSize(_NOTE_CELL if notes else QSize())
        # Notlarda kaydırma çubuğu gizlenir (tekerlek ve ok tuşları yine kaydırır); çubuk
        # genişliği yiyip ikinci sütunu düşürmesin.
        self._list.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff if notes else Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._list.setSpacing(0 if theme.rows != "list" else 1)
        self._list.setItemDelegate(
            {"cards": self._card_delegate, "notes": self._note_delegate}.get(
                theme.rows, self._plain_delegate
            )
        )
        self.refresh()

    def _apply_window_effects(self) -> None:
        """Temanın istediği Windows pencere efektlerini (buzlu cam, köşeler) uygular."""
        theme = self._theme
        glass = False
        if QGuiApplication.platformName() == "windows":
            hwnd = int(self.winId())
            glass = winapi.set_backdrop_blur(hwnd, theme.glass) and theme.glass
            winapi.set_window_corners(
                hwnd, winapi.CORNER_ROUND if glass else winapi.CORNER_DEFAULT
            )
        self._frame.glass = glass
        self._frame.update()

    def showEvent(self, event) -> None:  # noqa: N802
        self._tick.start()
        super().showEvent(event)

    def hideEvent(self, event) -> None:  # noqa: N802
        self._tick.stop()
        self._hover_row = -1
        self._hover_timer.stop()
        self._preview_pinned = False
        self._preview.forget()
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
        if (
            event.type() == QEvent.Type.ActivationChange
            and not self.isActiveWindow()
            and not self._menu_open
        ):
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
        self._refreshing = True  # liste yeniden kurulurken seçim değişimleri önizlemeyi kapatmasın
        self._hint.setText(self._status or self._default_hint())
        if snippets_tab:
            self._items = self._snippets.list(query)
        else:
            self._items = self._repo.list_items(self.current_category(), query)
        self._list.clear()
        theme = self._theme
        self._count.setText(f"{len(self._items)} KAYIT")
        row_cls = _SnippetRow if snippets_tab else _Row
        if theme.rows == "notes":
            self._fill_notes(row_cls)
        else:
            extra = theme.row_margins[0] + theme.row_margins[2] - 16
            text_width = _WIDTH - 110 - extra
            for i, item in enumerate(self._items):
                number = i + 1 if i < 9 else None
                row = row_cls(item, number, text_width, theme)
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
        self._refreshing = False
        self._hover_row = -1
        self._sync_preview()

    def _fill_notes(self, row_cls) -> None:
        """Not görünümü: her satır bir görüntüye çizilir; eğik notu NoteDelegate boyar."""
        theme = self._theme
        size = note_content_size(_NOTE_CELL)
        margins = theme.row_margins
        text_width = size.width() - margins[0] - margins[2] - 30  # numara rozeti + boşluk
        ratio = self.devicePixelRatioF()
        for i, item in enumerate(self._items):
            row = row_cls(item, i + 1 if i < 9 else None, text_width, theme)
            row.setStyleSheet(theme.row_qss)
            row.setFixedSize(size)
            row.ensurePolished()
            row.layout().activate()
            pixmap = QPixmap(size * ratio)
            pixmap.setDevicePixelRatio(ratio)
            pixmap.fill(Qt.GlobalColor.transparent)
            row.render(pixmap, QPoint(), QRegion(), QWidget.RenderFlag.DrawChildren)
            row.deleteLater()
            lw = QListWidgetItem()
            lw.setSizeHint(_NOTE_CELL)
            lw.setData(ROLE_PIXMAP, pixmap)
            lw.setData(ROLE_SEED, int(item.id))
            self._list.addItem(lw)

    def _selected(self):
        row = self._list.currentRow()
        return self._items[row] if 0 <= row < len(self._items) else None

    # ---- büyük önizleme -----------------------------------------------------
    def _image_at(self, row: int) -> Item | None:
        if self.on_snippets_tab() or not 0 <= row < len(self._items):
            return None
        item = self._items[row]
        return item if item.category is Category.IMAGE and item.image_path else None

    def _text_at(self, row: int) -> str | None:
        """Satırın önizlenecek metni: metin/link öğesi ya da şablon içeriği."""
        if not 0 <= row < len(self._items):
            return None
        item = self._items[row]
        if self.on_snippets_tab():
            return None if item.is_image else item.content
        if item.category in (Category.TEXT, Category.LINK):
            # Maskelenmiş (hassas) öğenin asıl metni önizlemede de gösterilmez.
            return item.masked_text if item.masked_text is not None else item.text
        return None

    def _snippet_image_at(self, row: int) -> Snippet | None:
        if not self.on_snippets_tab() or not 0 <= row < len(self._items):
            return None
        return self._items[row] if self._items[row].is_image else None

    def _can_preview(self, row: int) -> bool:
        return (
            self._image_at(row) is not None
            or self._snippet_image_at(row) is not None
            or bool(self._text_at(row))
        )

    def _show_preview(self, row: int) -> bool:
        screen = self.screen() or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        item = self._image_at(row)
        if item is not None:
            return self._preview.show_image(item.image_path, self.frameGeometry(), area)
        snippet = self._snippet_image_at(row)
        if snippet is not None:
            return self._preview.show_data(
                snippet.image, f"snippet:{snippet.id}:{snippet.updated_at}", self.frameGeometry(), area
            )
        text = self._text_at(row)
        if text:
            return self._preview.show_text(text, self.frameGeometry(), area)
        self._preview.hide()
        return False

    def _hide_preview(self) -> None:
        self._hover_row = -1
        self._hover_timer.stop()
        self._preview_pinned = False
        self._preview.hide()

    def _toggle_preview(self) -> None:
        if self._preview_pinned and self._preview.isVisible():
            self._hide_preview()
            return
        self._hover_timer.stop()
        self._preview_pinned = self._show_preview(self._list.currentRow())
        if not self._preview_pinned and self._image_at(self._list.currentRow()) is not None:
            self.show_status("Görsel dosyası okunamadı")

    def _on_row_changed(self, _row: int) -> None:
        if not self._refreshing:
            self._sync_preview()

    def _sync_preview(self) -> None:
        """Liste ya da seçim değişti: sabit önizleme seçimi izler, imleçle açılan kapanır."""
        if self._preview_pinned:
            self._preview_pinned = self._show_preview(self._list.currentRow())
        elif self._preview.isVisible():
            self._hide_preview()

    def _hover(self, pos: QPoint | None) -> None:
        row = self._list.row(self._list.itemAt(pos)) if pos is not None else -1
        if self._image_at(row) is None:
            row = -1
        if row == self._hover_row:
            return
        self._hover_row = row
        self._hover_timer.stop()
        if self._preview_pinned:
            return
        if row < 0:
            self._preview.hide()
        elif self._preview.isVisible():
            self._show_preview(row)  # zaten açık: komşu görsele beklemeden geç
        else:
            self._hover_timer.start()

    def _show_hover_preview(self) -> None:
        if self.isVisible() and not self._preview_pinned:
            self._show_preview(self._hover_row)

    # ---- sağ tık menüsü -----------------------------------------------------
    def _show_menu(self, pos: QPoint) -> None:
        row = self._list.row(self._list.itemAt(pos))
        if not 0 <= row < len(self._items):
            return
        self._list.setCurrentRow(row)
        item = self._items[row]
        self._hover_timer.stop()
        menu = QMenu(self)
        menu.addAction("Yapıştır", lambda: self._paste_row(row, False))
        if not self.on_snippets_tab() and item.category is Category.IMAGE:
            menu.addAction("Büyüt\tBoşluk", self._toggle_preview)
            menu.addAction("Düzenle…\tCtrl+E", lambda: self.editImageRequested.emit(item.id))
            menu.addAction(
                "PNG olarak kaydet…\tCtrl+Shift+S", lambda: self.saveImageRequested.emit(item.id)
            )
            menu.addAction("Metne çevir (OCR)\tCtrl+O", lambda: self.ocrRequested.emit(item.id))
        elif self._can_preview(row):
            menu.addAction("Önizle\tBoşluk", self._toggle_preview)
        if self.on_snippets_tab():
            menu.addAction("Düzenle…\tCtrl+E", lambda: self.editSnippetRequested.emit(item.id))
        else:
            menu.addAction(
                "Sabitlemeyi kaldır\tCtrl+P" if item.pinned else "Sabitle\tCtrl+P", self._toggle_pin
            )
        menu.addSeparator()
        menu.addAction("Sil\tDel", self._delete_selected)
        # Menü açıkken popup etkinliğini yitirebilir; bu yüzden kendini kapatmamalı.
        self._menu_open = True
        try:
            menu.exec(self._list.viewport().mapToGlobal(pos))
        finally:
            self._menu_open = False
        if self.isVisible():
            self.activateWindow()
            self._search.setFocus()

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
        # Arama kutusunun filtresi liste oluşmadan kurulur; o ana kadar _list yoktur.
        if obj is getattr(self, "_viewport", None):
            # Yalnızca gerçek fare hareketi sayılır: pencere imlecin altında açıldığında
            # kullanıcı istemeden önizleme çıkmasın.
            if event.type() == QEvent.Type.MouseMove:
                self._hover(event.position().toPoint())
            elif event.type() == QEvent.Type.Leave:
                self._hover(None)
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
        elif key == K.Key_E and ctrl:
            item = self._selected()
            if item is not None and item.category is Category.IMAGE:
                self.editImageRequested.emit(item.id)
            elif item is not None:
                self.show_status("Düzenleme yalnızca görsellerde çalışır")
        elif key == K.Key_Space and (ctrl or (no_mod and empty)):
            # Arama kutusu doluyken Boşluk aramaya yazılır; Ctrl+Boşluk her zaman önizler.
            if not self._can_preview(self._list.currentRow()):
                return False
            self._toggle_preview()
        elif key == K.Key_S and mods == (
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
        ):
            item = None if snippets_tab else self._selected()
            if item is not None and item.category is Category.IMAGE:
                self.saveImageRequested.emit(item.id)
            elif item is not None:
                self.show_status("Dosyaya kaydetme yalnızca görsellerde çalışır")
        else:
            return False
        return True
