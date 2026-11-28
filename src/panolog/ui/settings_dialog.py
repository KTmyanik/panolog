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
    QLineEdit,
    QListWidget,
    QListWidgetItem,
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
from ..settings.schema import RULE_ACTIONS, clean_rules
from .formatting import app_label
from .icons import app_icon
from .popup import TABS
from .themes import THEMES, get_theme


JOIN_SEPARATORS = [
    ("Yeni satır", "\n"),
    ("Boşluk", " "),
    ("Virgül", ", "),
    ("Noktalı virgül", "; "),
    ("Sekme", "\t"),
]


def rule_label(rule: dict) -> str:
    """Kuralın listede görünen metni: "excel.exe  →  Etiketle: rapor"."""
    name, needs_value = RULE_ACTIONS[rule["action"]]
    if rule["action"] == "expire":
        text = f"{rule['value']} dakika sonra sil"
    elif needs_value:
        text = f"{name}: {rule['value']}"
    else:
        text = name
    return f"{rule['app']}  →  {text}"


def ocr_status_text() -> str:
    """Ayarlar penceresinde gösterilen OCR durumu."""
    return pipeline.status()


class SettingsDialog(QDialog):
    def __init__(
        self,
        settings: Settings,
        on_delete_all: Callable[[], None],
        known_apps: list[str] | tuple[str, ...] = (),
        rule_app: str | None = None,
    ) -> None:
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
        rules_page = page("Kurallar")
        ocr_page, privacy_page = page("OCR"), page("Gizlilik")
        self._tabs = tabs

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
        self._seq_hotkey = QKeySequenceEdit(QKeySequence(settings.seq_hotkey))
        self._seq_hotkey.setMaximumSequenceLength(1)
        self._seq_hotkey.setToolTip(
            "Geçmiş penceresinde Ctrl+Enter ile sıraya alınan öğeleri birer birer yapıştırır."
        )
        form.addRow("Sıralı yapıştırma kısayolu:", self._seq_hotkey)
        self._separator = QComboBox()
        for label, value in JOIN_SEPARATORS:
            self._separator.addItem(label, value)
        self._separator.setCurrentIndex(max(0, self._separator.findData(settings.join_separator)))
        form.addRow("Çoklu seçimde ayraç:", self._separator)
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

        # Kurallar: varsayılan boş. Uygulama adı geçmişte görülenlerden seçilebilir.
        rules_box = QGroupBox("Uygulamaya göre kurallar")
        rules_lay = QVBoxLayout(rules_box)
        rules_note = QLabel(
            "Bir uygulamadan kopyalananlara ne yapılacağını belirler. Varsayılan olarak hiçbir "
            "kural yoktur. Her uygulama için tek kural tanımlanır."
        )
        rules_note.setWordWrap(True)
        rules_lay.addWidget(rules_note)
        self._rules: list[dict] = clean_rules(settings.rules)
        self._rule_list = QListWidget()
        self._rule_list.setFixedHeight(120)
        rules_lay.addWidget(self._rule_list)
        add_row = QHBoxLayout()
        self._rule_app = QComboBox()
        self._rule_app.setEditable(True)
        self._rule_app.setMinimumWidth(150)
        self._rule_app.lineEdit().setPlaceholderText("ör. excel.exe")
        for app in known_apps:
            self._rule_app.addItem(app)
        self._rule_app.setCurrentText(rule_app or "")
        self._rule_action = QComboBox()
        for key, (label, _needs) in RULE_ACTIONS.items():
            self._rule_action.addItem(label, key)
        self._rule_value = QLineEdit()
        self._rule_value.setFixedWidth(90)
        add_rule = QPushButton("Ekle")
        add_rule.setAutoDefault(False)
        remove_rule = QPushButton("Seçili kuralı sil")
        remove_rule.setAutoDefault(False)
        for widget in (self._rule_app, self._rule_action, self._rule_value, add_rule):
            add_row.addWidget(widget)
        rules_lay.addLayout(add_row)
        remove_row = QHBoxLayout()
        remove_row.addWidget(remove_rule)
        remove_row.addStretch(1)
        rules_lay.addLayout(remove_row)
        self._rule_action.currentIndexChanged.connect(self._sync_rule_value)
        add_rule.clicked.connect(self._add_rule)
        remove_rule.clicked.connect(self._remove_rule)
        self._rule_value.returnPressed.connect(self._add_rule)
        self._sync_rule_value()
        self._reload_rules()
        rules_page.addWidget(rules_box)
        rules_page.addStretch(1)
        if rule_app:  # geçmiş penceresinden "… için kural ekle" ile açıldı
            tabs.setCurrentIndex(tabs.indexOf(rules_page.parentWidget()))

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
        network = QGroupBox("İnternet")
        network_lay = QVBoxLayout(network)
        self._link_fetch = QCheckBox("Kopyalanan linklerin sayfa başlığını ve simgesini getir")
        self._link_fetch.setChecked(settings.link_fetch)
        network_lay.addWidget(self._link_fetch)
        network_note = QLabel(
            "Kapalıyken uygulama hiçbir ağ bağlantısı kurmaz. Açılırsa kopyaladığınız her genel "
            "internet adresine bir istek gönderilir; karşı sunucu bu isteği görür. Kurum içi "
            "(tek sözcüklü ya da yerel ağdaki) adreslere istek yapılmaz."
        )
        network_note.setWordWrap(True)
        network_note.setEnabled(False)
        network_lay.addWidget(network_note)
        privacy_page.addWidget(network)
        privacy_page.addStretch(1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Kaydet")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Vazgeç")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    # ---- kurallar -------------------------------------------------------------
    def _reload_rules(self) -> None:
        self._rule_list.clear()
        for rule in self._rules:
            self._rule_list.addItem(QListWidgetItem(rule_label(rule)))
        if not self._rules:
            empty = QListWidgetItem("Kural yok")
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self._rule_list.addItem(empty)

    def _sync_rule_value(self) -> None:
        action = self._rule_action.currentData()
        needs_value = RULE_ACTIONS[action][1]
        self._rule_value.setEnabled(needs_value)
        self._rule_value.setPlaceholderText(
            {"tag": "etiket", "expire": "dakika"}.get(action, "")
        )
        if not needs_value:
            self._rule_value.clear()

    def _add_rule(self) -> None:
        app = self._rule_app.currentText().strip().lower()
        if app and "." not in app:
            app += ".exe"  # "excel" yazan kullanıcı "excel.exe" demek istiyor
        candidate = {
            "app": app,
            "action": self._rule_action.currentData(),
            "value": self._rule_value.text(),
        }
        if not clean_rules([candidate]):
            QMessageBox.warning(
                self,
                APP_NAME,
                "Kural eklenemedi. Uygulama adını (ör. excel.exe) yazın; etiket için bir ad, "
                "süre için dakika olarak bir sayı girin.",
            )
            return
        # Aynı uygulama için eski kural varsa yenisiyle değişir.
        self._rules = clean_rules([candidate] + [r for r in self._rules if r["app"] != app])
        self._reload_rules()
        self._rule_app.setCurrentText("")
        self._rule_value.clear()

    def _remove_rule(self) -> None:
        row = self._rule_list.currentRow()
        if 0 <= row < len(self._rules):
            del self._rules[row]
            self._reload_rules()

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
        seq_hotkey = self._seq_hotkey.keySequence().toString(
            QKeySequence.SequenceFormat.PortableText
        )
        try:
            parse_hotkey(hotkey)
            parse_hotkey(seq_hotkey)
        except HotkeyError as exc:
            QMessageBox.warning(self, APP_NAME, str(exc))
            return
        if hotkey.lower() == seq_hotkey.lower():
            QMessageBox.warning(
                self, APP_NAME, "Pencere kısayolu ile sıralı yapıştırma kısayolu aynı olamaz."
            )
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
        s.seq_hotkey = seq_hotkey
        s.join_separator = self._separator.currentData()
        s.rules = list(self._rules)
        s.link_fetch = self._link_fetch.isChecked()
        s.animations = self._animations.isChecked()
        s.excluded_apps = [
            ln.strip().lower() for ln in self._excluded.toPlainText().splitlines() if ln.strip()
        ]
        self.result_settings = s
        self.accept()
