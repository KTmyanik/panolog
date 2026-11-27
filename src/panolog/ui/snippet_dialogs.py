"""Şablon düzenleme ve yönetim pencereleri."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .. import APP_NAME
from ..snippets import VARIABLES, Snippet, SnippetError, SnippetRepository
from ..snippets import io_json
from .draw_canvas import INK_COLORS, PEN_WIDTHS, DrawCanvas, to_png
from .icons import app_icon


class SnippetEditDialog(QDialog):
    """Yeni şablon oluşturur veya var olanı düzenler; Kaydet'te doğrudan depoya yazar.

    Şablon ya metindir ya da görsel (ör. elle çizilmiş imza); hangi sekme açıksa o kaydedilir.
    """

    def __init__(
        self,
        repo: SnippetRepository,
        snippet: Snippet | None = None,
        initial_content: str = "",
        parent=None,
        initial_image: QImage | None = None,
    ) -> None:
        super().__init__(parent)
        self._repo = repo
        self._snippet = snippet
        self.saved: Snippet | None = None
        self.setWindowTitle(f"{APP_NAME} – " + ("Şablonu düzenle" if snippet else "Yeni şablon"))
        self.setWindowIcon(app_icon())
        self.setMinimumSize(460, 380)

        root = QVBoxLayout(self)
        form = QFormLayout()
        self._name = QLineEdit(snippet.name if snippet else "")
        self._name.setPlaceholderText("ör. E-posta imzası")
        form.addRow("Ad:", self._name)
        self._shortcode = QLineEdit((snippet.shortcode or "") if snippet else "")
        self._shortcode.setPlaceholderText("isteğe bağlı, ör. ;imza")
        form.addRow("Kısa kod:", self._shortcode)
        self._tag = QLineEdit((snippet.tag or "") if snippet else "")
        self._tag.setPlaceholderText("isteğe bağlı, ör. e-posta")
        form.addRow("Etiket:", self._tag)
        root.addLayout(form)

        self._tabs = QTabWidget()
        root.addWidget(self._tabs, 1)

        # Metin
        text_page = QWidget()
        text_lay = QVBoxLayout(text_page)
        self._content = QPlainTextEdit(snippet.content if snippet else initial_content)
        text_lay.addWidget(self._content, 1)
        variables = QLabel(
            "Değişkenler: " + ",  ".join(f"{{{k}}} = {v}" for k, v in VARIABLES.items())
        )
        variables.setWordWrap(True)
        variables.setEnabled(False)
        text_lay.addWidget(variables)
        self._tabs.addTab(text_page, "Metin")

        # Çizim
        draw_page = QWidget()
        draw_lay = QVBoxLayout(draw_page)
        bar = QHBoxLayout()
        self._ink = QComboBox()
        for label, color in INK_COLORS.items():
            self._ink.addItem(label, color)
        self._pen = QComboBox()
        for label, width in PEN_WIDTHS.items():
            self._pen.addItem(label, width)
        self._pen.setCurrentIndex(1)
        bar.addWidget(QLabel("Kalem:"))
        bar.addWidget(self._ink)
        bar.addWidget(self._pen)
        bar.addStretch(1)
        self._undo = QPushButton("Geri al")
        self._clear = QPushButton("Temizle")
        load = QPushButton("Dosyadan…")
        load.setToolTip("Taranmış bir imzayı ya da başka bir görseli çizim alanına getirir.")
        for button in (self._undo, self._clear, load):
            button.setAutoDefault(False)
            bar.addWidget(button)
        draw_lay.addLayout(bar)
        self._canvas = DrawCanvas()
        holder = QHBoxLayout()
        holder.addStretch(1)
        holder.addWidget(self._canvas)
        holder.addStretch(1)
        draw_lay.addLayout(holder)
        note = QLabel(
            "Fareyle (ya da dokunmatik ekranda kalemle) çizin. Kaydedilen görsel, çizimin "
            "çevresine kırpılır ve beyaz zeminlidir; yapıştırınca görsel olarak eklenir."
        )
        note.setWordWrap(True)
        note.setEnabled(False)
        draw_lay.addWidget(note)
        draw_lay.addStretch(1)
        self._tabs.addTab(draw_page, "Çizim")

        self._ink.currentIndexChanged.connect(self._sync_pen)
        self._pen.currentIndexChanged.connect(self._sync_pen)
        self._undo.clicked.connect(self._canvas.undo)
        self._clear.clicked.connect(self._canvas.clear)
        load.clicked.connect(self._load_file)
        self._canvas.changed.connect(self._sync_buttons)
        undo_key = QShortcut(QKeySequence.StandardKey.Undo, self._canvas)
        undo_key.setContext(Qt.ShortcutContext.WindowShortcut)
        undo_key.activated.connect(self._undo_if_drawing)

        existing = QImage.fromData(snippet.image) if snippet and snippet.image else initial_image
        if existing is not None and not existing.isNull():
            self._canvas.set_base(existing, undoable=False)
            self._tabs.setCurrentIndex(1)
        self._sync_pen()
        self._sync_buttons()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Kaydet")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Vazgeç")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self._name.setFocus()

    @property
    def canvas(self) -> DrawCanvas:
        return self._canvas

    def show_drawing(self) -> None:
        self._tabs.setCurrentIndex(1)

    def is_drawing(self) -> bool:
        return self._tabs.currentIndex() == 1

    def _sync_pen(self) -> None:
        self._canvas.color = self._ink.currentData()
        self._canvas.pen_width = float(self._pen.currentData())

    def _sync_buttons(self) -> None:
        self._undo.setEnabled(self._canvas.can_undo())
        self._clear.setEnabled(not self._canvas.is_empty())

    def _undo_if_drawing(self) -> None:
        # Metin sekmesinde Ctrl+Z metin kutusunun kendi geri almasıdır.
        if self.is_drawing() and not self._content.hasFocus():
            self._canvas.undo()

    def _load_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Görsel seç", "", "Görseller (*.png *.jpg *.jpeg *.bmp)"
        )
        if not path:
            return
        image = QImage(path)
        if image.isNull():
            QMessageBox.warning(self, APP_NAME, "Bu dosya görsel olarak açılamadı.")
            return
        self._canvas.set_base(image)

    def _save(self) -> None:
        image = None
        if self.is_drawing():
            drawn = self._canvas.image()
            if drawn.isNull():
                QMessageBox.warning(self, APP_NAME, "Çizim alanı boş. Önce bir şey çizin.")
                return
            image = to_png(drawn)
        args = (
            self._name.text(),
            "" if image is not None else self._content.toPlainText(),
            self._shortcode.text(),
            self._tag.text(),
            image,
        )
        try:
            if self._snippet:
                self.saved = self._repo.update(self._snippet.id, *args)
            else:
                self.saved = self._repo.add(*args)
        except SnippetError as exc:
            QMessageBox.warning(self, APP_NAME, str(exc))
            return
        self.accept()


class SnippetManagerDialog(QDialog):
    def __init__(self, repo: SnippetRepository) -> None:
        super().__init__()
        self._repo = repo
        self.setWindowTitle(f"{APP_NAME} – Şablonlar")
        self.setWindowIcon(app_icon())
        self.setMinimumSize(520, 420)

        root = QHBoxLayout(self)
        self._list = QListWidget()
        self._list.itemDoubleClicked.connect(lambda _i: self._edit())
        root.addWidget(self._list, 1)

        side = QVBoxLayout()
        for label, slot in (
            ("Yeni…", self._new),
            ("Düzenle…", self._edit),
            ("Sil", self._delete),
            (None, None),
            ("İçe aktar…", self._import),
            ("Dışa aktar…", self._export),
        ):
            if label is None:
                side.addSpacing(16)
                continue
            button = QPushButton(label)
            button.clicked.connect(slot)
            side.addWidget(button)
        side.addStretch(1)
        close = QPushButton("Kapat")
        close.clicked.connect(self.accept)
        side.addWidget(close)
        root.addLayout(side)
        self._reload()

    def _reload(self, select_id: int | None = None) -> None:
        self._list.clear()
        for s in self._repo.list():
            parts = [s.name]
            if s.shortcode:
                parts.append(s.shortcode)
            if s.tag:
                parts.append(f"# {s.tag}")
            item = QListWidgetItem("    ".join(parts))
            item.setData(Qt.ItemDataRole.UserRole, s.id)
            if s.is_image:
                item.setText(item.text() + "    [görsel]")
            else:
                item.setToolTip(s.content[:500])
            self._list.addItem(item)
            if s.id == select_id:
                self._list.setCurrentItem(item)
        if self._list.currentRow() < 0 and self._list.count():
            self._list.setCurrentRow(0)

    def _current(self) -> Snippet | None:
        item = self._list.currentItem()
        return self._repo.get(item.data(Qt.ItemDataRole.UserRole)) if item else None

    def _new(self) -> None:
        dialog = SnippetEditDialog(self._repo, parent=self)
        if dialog.exec() and dialog.saved:
            self._reload(dialog.saved.id)

    def _edit(self) -> None:
        if snippet := self._current():
            dialog = SnippetEditDialog(self._repo, snippet, parent=self)
            if dialog.exec():
                self._reload(snippet.id)

    def _delete(self) -> None:
        snippet = self._current()
        if not snippet:
            return
        answer = QMessageBox.question(
            self,
            APP_NAME,
            f"'{snippet.name}' şablonu silinsin mi?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._repo.delete(snippet.id)
            self._reload()

    def _import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Şablonları içe aktar", "", "JSON (*.json)")
        if not path:
            return
        try:
            entries = io_json.loads(Path(path).read_text(encoding="utf-8-sig"))
            added, updated, skipped = self._repo.import_many(entries)
        except (OSError, UnicodeDecodeError, SnippetError) as exc:
            QMessageBox.warning(self, APP_NAME, f"İçe aktarılamadı:\n{exc}")
            return
        self._reload()
        QMessageBox.information(
            self,
            APP_NAME,
            f"{added} şablon eklendi, {updated} güncellendi, {skipped} zaten vardı.",
        )

    def _export(self) -> None:
        snippets = self._repo.list()
        if not snippets:
            QMessageBox.information(self, APP_NAME, "Dışa aktarılacak şablon yok.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Şablonları dışa aktar", "panolog-sablonlar.json", "JSON (*.json)"
        )
        if not path:
            return
        try:
            Path(path).write_text(io_json.dumps(snippets), encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, APP_NAME, f"Dışa aktarılamadı:\n{exc}")
            return
        QMessageBox.information(self, APP_NAME, f"{len(snippets)} şablon dışa aktarıldı.")
