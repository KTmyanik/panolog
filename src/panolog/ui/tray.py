from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from .. import APP_NAME
from ..monitor.pause import PauseStatus, remaining_label
from .icons import app_icon

TIMED_PAUSE_SECONDS = 300


class Tray(QSystemTrayIcon):
    openRequested = Signal()
    pauseToggled = Signal(bool)
    pauseForRequested = Signal(int)  # saniye
    skipNextToggled = Signal(bool)
    menuOpening = Signal()  # kalan süre menü açılırken güncellensin
    clearRequested = Signal()
    settingsRequested = Signal()
    snippetsRequested = Signal()
    quitRequested = Signal()

    def __init__(self) -> None:
        super().__init__(app_icon())
        self._status = PauseStatus(False, None, False)
        menu = QMenu()
        menu.addAction("Geçmişi aç").triggered.connect(self.openRequested)
        self._pause_action = menu.addAction("Duraklat")
        self._pause_action.triggered.connect(
            lambda: self.pauseToggled.emit(not self._status.paused)
        )
        self._timed_action = menu.addAction(f"{TIMED_PAUSE_SECONDS // 60} dakika duraklat")
        self._timed_action.triggered.connect(
            lambda: self.pauseForRequested.emit(TIMED_PAUSE_SECONDS)
        )
        self._skip_action = menu.addAction("Sonraki kopyayı kaydetme")
        self._skip_action.setCheckable(True)
        self._skip_action.triggered.connect(self.skipNextToggled)
        menu.addAction("Geçmişi temizle…").triggered.connect(self.clearRequested)
        menu.addSeparator()
        menu.addAction("Şablonlar…").triggered.connect(self.snippetsRequested)
        menu.addAction("Ayarlar…").triggered.connect(self.settingsRequested)
        menu.addSeparator()
        menu.addAction("Çıkış").triggered.connect(self.quitRequested)
        menu.aboutToShow.connect(self.menuOpening)
        self._menu = menu  # referans kalsın
        self.setContextMenu(menu)
        self.activated.connect(self._on_activated)
        self.set_status(self._status)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.openRequested.emit()

    def set_status(self, status: PauseStatus) -> None:
        self._status = status
        # Gri ikon: şu an kopyalanan şey geçmişe girmeyecek.
        self.setIcon(app_icon(status.paused or status.skip_next))
        if status.paused and status.remaining is not None:
            left = remaining_label(status.remaining)
            self._pause_action.setText(f"Devam et ({left} kaldı)")
            tip = f"{APP_NAME} (duraklatıldı, {left} kaldı)"
        elif status.paused:
            self._pause_action.setText("Devam et")
            tip = f"{APP_NAME} (duraklatıldı)"
        else:
            self._pause_action.setText("Duraklat")
            tip = f"{APP_NAME} (sonraki kopya kaydedilmeyecek)" if status.skip_next else APP_NAME
        self._timed_action.setVisible(not status.paused)
        self._skip_action.setVisible(not status.paused)
        self._skip_action.setChecked(status.skip_next)
        self.setToolTip(tip)
