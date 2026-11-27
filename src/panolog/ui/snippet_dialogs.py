"""Şablon düzenleme ve yönetim pencereleri."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
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
    QVBoxLayout,
)

from .. import APP_NAME
from ..snippets import VARIABLES, Snippet, SnippetError, SnippetRepository
from ..snippets import io_json
from .icons import app_icon


class SnippetEditDialog(QDialog):
    """Yeni şablon oluşturur veya var olanı düzenler; Kaydet'te doğrudan depoya yazar."""

    def __init__(
        self,
        repo: SnippetRepository,
        snippet: Snippet | None = None,
        initial_content: str = "",
        parent=None,
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

        root.addWidget(QLabel("İçerik:"))
        self._content = QPlainTextEdit(snippet.content if snippet else initial_content)
        root.addWidget(self._content, 1)
        variables = QLabel(
            "Değişkenler: " + ",  ".join(f"{{{k}}} = {v}" for k, v in VARIABLES.items())
        )
        variables.setWordWrap(True)
        variables.setEnabled(False)
        root.addWidget(variables)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Kaydet")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Vazgeç")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self._name.setFocus()

    def _save(self) -> None:
        args = (
            self._name.text(),
            self._content.toPlainText(),
            self._shortcode.text(),
            self._tag.text(),
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
