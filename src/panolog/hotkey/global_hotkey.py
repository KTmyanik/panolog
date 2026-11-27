"""Win32 RegisterHotKey ile global kısayol.

Klavye kancası (hook) kurulmaz: uygulama yalnızca kayıtlı kombinasyon basıldığında
haberdar olur, diğer tuş vuruşlarını hiç görmez.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget

from .. import winapi

_MODIFIERS = {
    "ctrl": winapi.MOD_CONTROL,
    "control": winapi.MOD_CONTROL,
    "shift": winapi.MOD_SHIFT,
    "alt": winapi.MOD_ALT,
    "win": winapi.MOD_WIN,
    "meta": winapi.MOD_WIN,
}
_NAMED_KEYS = {
    "space": 0x20,
    "tab": 0x09,
    "enter": 0x0D,
    "return": 0x0D,
    "esc": 0x1B,
    "escape": 0x1B,
    "ins": 0x2D,
    "insert": 0x2D,
    "del": 0x2E,
    "delete": 0x2E,
    "home": 0x24,
    "end": 0x23,
    "pgup": 0x21,
    "pgdown": 0x22,
    "left": 0x25,
    "up": 0x26,
    "right": 0x27,
    "down": 0x28,
    "`": 0xC0,
    "-": 0xBD,
    "=": 0xBB,
    "[": 0xDB,
    "]": 0xDD,
    "\\": 0xDC,
    ";": 0xBA,
    "'": 0xDE,
    ",": 0xBC,
    ".": 0xBE,
    "/": 0xBF,
}


class HotkeyError(ValueError):
    pass


def parse_hotkey(text: str) -> tuple[int, int]:
    """'Ctrl+Shift+V' -> (modifier bayrakları, sanal tuş kodu)."""
    parts = [p.strip() for p in text.split("+")]
    if text.rstrip().endswith("++"):  # 'Ctrl++' gibi: tuşun kendisi '+'
        parts = [p for p in parts if p] + ["+"]
    if not parts or any(not p for p in parts):
        raise HotkeyError(f"Geçersiz kısayol: {text!r}")
    mods, vk = 0, None
    for part in parts:
        low = part.lower()
        if low in _MODIFIERS:
            mods |= _MODIFIERS[low]
            continue
        if vk is not None:
            raise HotkeyError(f"Birden fazla tuş: {text!r}")
        if len(part) == 1 and part.isascii() and part.isalnum():
            vk = ord(part.upper())
        elif low in _NAMED_KEYS:
            vk = _NAMED_KEYS[low]
        elif low == "+":
            vk = 0xBB
        elif low[0] == "f" and low[1:].isdigit() and 1 <= int(low[1:]) <= 24:
            vk = 0x70 + int(low[1:]) - 1
        else:
            raise HotkeyError(f"Bilinmeyen tuş: {part!r}")
    if vk is None:
        raise HotkeyError(f"Kısayolda tuş yok: {text!r}")
    if not mods:
        raise HotkeyError("Kısayol en az bir Ctrl/Alt/Shift/Win içermeli")
    return mods, vk


class GlobalHotkey(QWidget):
    """Gizli bir pencere üzerinden WM_HOTKEY dinler ve `activated` yayar."""

    activated = Signal()
    _ID = 1

    def __init__(self) -> None:
        super().__init__()
        self._hwnd = int(self.winId())
        self._registered = False

    def register(self, text: str) -> None:
        """Kısayolu kaydeder. Geçersizse veya başka uygulamadaysa HotkeyError fırlatır."""
        mods, vk = parse_hotkey(text)
        self.unregister()
        if not winapi.RegisterHotKey(self._hwnd, self._ID, mods | winapi.MOD_NOREPEAT, vk):
            raise HotkeyError(
                f"'{text}' kısayolu kaydedilemedi; başka bir uygulama kullanıyor olabilir."
            )
        self._registered = True

    def unregister(self) -> None:
        if self._registered:
            winapi.UnregisterHotKey(self._hwnd, self._ID)
            self._registered = False

    def nativeEvent(self, event_type, message):  # noqa: N802 (Qt adı)
        if event_type == b"windows_generic_MSG":
            msg = ctypes.cast(int(message), ctypes.POINTER(wintypes.MSG)).contents
            if msg.message == winapi.WM_HOTKEY and msg.wParam == self._ID:
                self.activated.emit()
                return True, 0
        return False, 0
