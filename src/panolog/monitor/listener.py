"""Clipboard değişikliklerini Win32 AddClipboardFormatListener ile dinler."""
from __future__ import annotations

import ctypes
from ctypes import wintypes

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QWidget

from .. import winapi

# Kaynak uygulamanın tüm biçimleri yazmayı bitirmesi için kısa bekleme; art arda gelen
# bildirimleri de tek okumada birleştirir.
_SETTLE_MS = 60


class ClipboardListener(QWidget):
    """Gizli pencere. Clipboard değişince `changed(kaynak_uygulama)` yayar."""

    changed = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._hwnd = int(self.winId())
        self._source: str | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(_SETTLE_MS)
        self._timer.timeout.connect(lambda: self.changed.emit(self._source))
        winapi.AddClipboardFormatListener(self._hwnd)

    def stop(self) -> None:
        winapi.RemoveClipboardFormatListener(self._hwnd)
        self._timer.stop()

    def nativeEvent(self, event_type, message):  # noqa: N802 (Qt adı)
        if event_type == b"windows_generic_MSG":
            msg = ctypes.cast(int(message), ctypes.POINTER(wintypes.MSG)).contents
            if msg.message == winapi.WM_CLIPBOARDUPDATE:
                # Sahip pencere hemen şimdi okunmalı; sonra değişebilir.
                self._source = winapi.process_name_of_window(
                    winapi.GetClipboardOwner()
                ) or winapi.process_name_of_window(winapi.GetForegroundWindow())
                self._timer.start()
                return True, 0
        return False, 0
