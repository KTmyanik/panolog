from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QKeySequenceEdit,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .. import APP_NAME
from ..hotkey import HotkeyError, parse_hotkey
from ..ocr import pipeline
from ..settings import Settings
from .icons import app_icon
from .popup import TABS
from .themes import THEMES, get_theme


def ocr_status_text() -> str:
    """Ayarlar penceresinde gösterilen OCR durumu."""
    return pipeline.status()


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, on_delete_all: Callable[[], None]) -> None:
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} – Ayarlar")
        self.setWindowIcon(app_icon())
        self.setMinimumWidth(470)
        self._settings = settings
        self._on_delete_all = on_delete_all
        root = QVBoxLayout(self)
        # Tek sayfada küçük ekranlara sığmıyordu; bölümler sekmelere ayrıldı.
        tabs = QTabWidget()
        root.addWidget(tabs)

        def page(title: str) -> QVBoxLayout:
            widget = QWidget()
            tabs.addTab(widget, title)
            return QVBoxLayout(widget)

        general, look_page = page("Genel"), page("Görünüm")
        ocr_page, privacy_page = page("OCR"), page("Gizlilik")

        # Geçmiş
        history = QGroupBox("Geçmiş")
        form = QFormLayout(history)
        self._limits: dict[str, QSpinBox] = {}
        for category, title in TABS:
            spin = QSpinBox()
            spin.setRange(1, 1000)
            spin.setValue(settings.limit_for(category))
            spin.setSuffix(" öğe")
            self._limits[category.value] = spin
            form.addRow(f"{title} limiti:", spin)
        self._retention = QCheckBox("Eski öğeleri otomatik sil (sabitlenenler hariç)")
        self._retention.setChecked(settings.retention_enabled)
        self._days = QSpinBox()
        self._days.setRange(1, 365)
        self._days.setValue(settings.retention_days)
        self._days.setSuffix(" gün sonra")
        self._days.setEnabled(settings.retention_enabled)
        self._retention.toggled.connect(self._days.setEnabled)
        form.addRow(self._retention)
        form.addRow("Silme süresi:", self._days)
        general.addWidget(history)

        # Davranış
        behavior = QGroupBox("Davranış")
        form = QFormLayout(behavior)
        self._hotkey = QKeySequenceEdit(QKeySequence(settings.hotkey))
        self._hotkey.setMaximumSequenceLength(1)
        form.addRow("Kısayol tuşu:", self._hotkey)
        self._auto_paste = QCheckBox("Seçilen öğeyi otomatik yapıştır (Ctrl+V gönder)")
        self._auto_paste.setChecked(settings.auto_paste)
        form.addRow(self._auto_paste)
        self._autostart = QCheckBox("Windows ile başlangıçta çalıştır")
        self._autostart.setChecked(settings.autostart)
        form.addRow(self._autostart)
        general.addWidget(behavior)
        general.addStretch(1)

        # Görünüm
        look_box = QGroupBox("Geçmiş penceresinin görünümü")
        look_form = QFormLayout(look_box)
        self._theme = QComboBox()
        for theme in THEMES.values():
            self._theme.addItem(theme.label, theme.key)
        self._theme.setCurrentIndex(max(0, self._theme.findData(get_theme(settings.theme).key)))
        look_form.addRow("Tema:", self._theme)
        self._animations = QCheckBox("Hareketli arka plan (Aurora cam)")
        self._animations.setChecked(settings.animations)
        look_form.addRow(self._animations)
        look_note = QLabel(
            "Tema yalnızca görünümü değiştirir; tuşlar ve davranış aynı kalır. Hareketli arka "
            "plan yalnızca pencere açıkken çizilir; bilgisayarı yoruyorsa kapatabilirsiniz."
        )
        look_note.setWordWrap(True)
        look_form.addRow(look_note)
        look_page.addWidget(look_box)
        look_page.addStretch(1)

        # OCR
        ocr_box = QGroupBox("Görsellerden metin okuma (OCR)")
        ocr_lay = QVBoxLayout(ocr_box)
        self._ocr_auto = QCheckBox(
            "Yeni görselleri otomatik OCR'la (içlerindeki metinle aranabilir olur)"
        )
        self._ocr_auto.setChecked(settings.ocr_auto)
        ocr_lay.addWidget(self._ocr_auto)
        ocr_status = QLabel(ocr_status_text())
        ocr_status.setWordWrap(True)
        ocr_status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        ocr_lay.addWidget(ocr_status)
        ocr_page.addWidget(ocr_box)
        ocr_page.addStretch(1)

        # Gizlilik
        privacy = QGroupBox("Gizlilik")
        box = QVBoxLayout(privacy)
        box.addWidget(
            QLabel("Hassas veri (IBAN, kart no, TCKN, parola/token satırı) algılanınca:")
        )
        self._mode = QComboBox()
        ttl = settings.sensitive_ttl_seconds
        for value, label in (
            ("off", "Normal kaydet (özel işlem yapma)"),
            ("mask", "Kaydet, listede maskeli göster (süresiz)"),
            ("auto_delete", f"Kaydet, {ttl} saniye sonra otomatik sil"),
            ("skip", "Hiç kaydetme"),
        ):
            self._mode.addItem(label, value)
        self._mode.setCurrentIndex(max(0, self._mode.findData(settings.sensitive_mode)))
        box.addWidget(self._mode)

        def _sync_toggles() -> None:
            on = self._mode.currentData() != "off"
            self._email.setEnabled(on)
            self._phone.setEnabled(on)

        self._mode.currentIndexChanged.connect(lambda _i: _sync_toggles())
        self._email = QCheckBox("E-posta adreslerini de hassas say")
        self._email.setChecked(settings.detect_email)
        box.addWidget(self._email)
        self._phone = QCheckBox("Telefon numaralarını da hassas say")
        self._phone.setChecked(settings.detect_phone)
        box.addWidget(self._phone)
        _sync_toggles()
        box.addWidget(QLabel("Kopyalamaları kaydedilmeyecek uygulamalar (satır başına bir .exe adı):"))
        self._excluded = QPlainTextEdit("\n".join(settings.excluded_apps))
        self._excluded.setFixedHeight(90)
        box.addWidget(self._excluded)
        row = QHBoxLayout()
        delete_all = QPushButton("Tüm geçmişi sil…")
        delete_all.clicked.connect(self._confirm_delete_all)
        row.addWidget(delete_all)
        row.addStretch(1)
        box.addLayout(row)
        privacy_page.addWidget(privacy)
        privacy_page.addStretch(1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Kaydet")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Vazgeç")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _confirm_delete_all(self) -> None:
        answer = QMessageBox.warning(
            self,
            APP_NAME,
            "Sabitlenenler dahil tüm clipboard geçmişi kalıcı olarak silinecek.\n"
            "Bu işlem geri alınamaz. Devam edilsin mi?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._on_delete_all()

    def _accept(self) -> None:
        hotkey = self._hotkey.keySequence().toString(QKeySequence.SequenceFormat.PortableText)
        try:
            parse_hotkey(hotkey)
        except HotkeyError as exc:
            QMessageBox.warning(self, APP_NAME, str(exc))
            return
        s = Settings.from_dict(self._settings.to_dict())
        s.limits.update({k: spin.value() for k, spin in self._limits.items()})
        s.retention_enabled = self._retention.isChecked()
        s.retention_days = self._days.value()
        s.hotkey = hotkey
        s.auto_paste = self._auto_paste.isChecked()
        s.autostart = self._autostart.isChecked()
        s.sensitive_mode = self._mode.currentData()
        s.detect_email = self._email.isChecked()
        s.detect_phone = self._phone.isChecked()
        s.ocr_auto = self._ocr_auto.isChecked()
        s.theme = self._theme.currentData()
        s.animations = self._animations.isChecked()
        s.excluded_apps = [
            ln.strip().lower() for ln in self._excluded.toPlainText().splitlines() if ln.strip()
        ]
        self.result_settings = s
        self.accept()
