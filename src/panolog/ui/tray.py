from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from .. import APP_NAME
from .icons import app_icon


class Tray(QSystemTrayIcon):
    openRequested = Signal()
    pauseToggled = Signal(bool)
    clearRequested = Signal()
    settingsRequested = Signal()
    snippetsRequested = Signal()
    quitRequested = Signal()

    def __init__(self) -> None:
        super().__init__(app_icon())
        self._paused = False
        menu = QMenu()
        menu.addAction("Geçmişi aç").triggered.connect(self.openRequested)
        self._pause_action = menu.addAction("Duraklat")
        self._pause_action.triggered.connect(self._toggle_pause)
        menu.addAction("Geçmişi temizle…").triggered.connect(self.clearRequested)
        menu.addSeparator()
        menu.addAction("Şablonlar…").triggered.connect(self.snippetsRequested)
        menu.addAction("Ayarlar…").triggered.connect(self.settingsRequested)
        menu.addSeparator()
        menu.addAction("Çıkış").triggered.connect(self.quitRequested)
        self._menu = menu  # referans kalsın
        self.setContextMenu(menu)
        self.activated.connect(self._on_activated)
        self._update()

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.openRequested.emit()

    def _toggle_pause(self) -> None:
        self._paused = not self._paused
        self._update()
        self.pauseToggled.emit(self._paused)

    def _update(self) -> None:
        self.setIcon(app_icon(self._paused))
        self._pause_action.setText("Devam et" if self._paused else "Duraklat")
        self.setToolTip(f"{APP_NAME} (duraklatıldı)" if self._paused else APP_NAME)
