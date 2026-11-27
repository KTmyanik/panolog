"""Windows ile başlangıçta çalışma: HKCU\\...\\Run anahtarı (yönetici yetkisi gerekmez)."""
from __future__ import annotations

import sys
import winreg
from pathlib import Path

from .. import APP_NAME

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def launch_command() -> str:
    if getattr(sys, "frozen", False):  # PyInstaller .exe
        return f'"{sys.executable}"'
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    exe = pythonw if pythonw.exists() else Path(sys.executable)
    return f'"{exe}" -m panolog'


def is_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            winreg.QueryValueEx(key, APP_NAME)
            return True
    except OSError:
        return False


def set_enabled(enabled: bool) -> None:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, launch_command())
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass


def migrate_legacy(legacy_name: str = "Clipboarder") -> bool:
    """Eski addaki başlangıç kaydını siler; kayıt varsa yenisini bu sürüm için yazar."""
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE
        ) as key:
            try:
                winreg.QueryValueEx(key, legacy_name)
            except FileNotFoundError:
                return False
            winreg.DeleteValue(key, legacy_name)
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, launch_command())
            return True
    except OSError:
        return False
