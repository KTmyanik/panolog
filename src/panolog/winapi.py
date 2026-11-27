"""Kullanılan Win32 çağrılarının ctypes tanımları (ek bağımlılık gerektirmez)."""
from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

WM_HOTKEY = 0x0312
WM_CLIPBOARDUPDATE = 0x031D

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000

VK_SHIFT, VK_CONTROL, VK_MENU, VK_LWIN, VK_RWIN = 0x10, 0x11, 0x12, 0x5B, 0x5C
VK_V = 0x56

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
ERROR_ALREADY_EXISTS = 183

ULONG_PTR = ctypes.c_size_t


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUT_UNION)]


def _sig(func, restype, *argtypes):
    func.restype = restype
    func.argtypes = argtypes
    return func


AddClipboardFormatListener = _sig(user32.AddClipboardFormatListener, wintypes.BOOL, wintypes.HWND)
RemoveClipboardFormatListener = _sig(
    user32.RemoveClipboardFormatListener, wintypes.BOOL, wintypes.HWND
)
GetClipboardOwner = _sig(user32.GetClipboardOwner, wintypes.HWND)
GetForegroundWindow = _sig(user32.GetForegroundWindow, wintypes.HWND)
SetForegroundWindow = _sig(user32.SetForegroundWindow, wintypes.BOOL, wintypes.HWND)
IsWindow = _sig(user32.IsWindow, wintypes.BOOL, wintypes.HWND)
GetWindowThreadProcessId = _sig(
    user32.GetWindowThreadProcessId, wintypes.DWORD, wintypes.HWND, wintypes.LPDWORD
)
RegisterHotKey = _sig(
    user32.RegisterHotKey, wintypes.BOOL, wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT
)
UnregisterHotKey = _sig(user32.UnregisterHotKey, wintypes.BOOL, wintypes.HWND, ctypes.c_int)
RegisterClipboardFormatW = _sig(user32.RegisterClipboardFormatW, wintypes.UINT, wintypes.LPCWSTR)
IsClipboardFormatAvailable = _sig(user32.IsClipboardFormatAvailable, wintypes.BOOL, wintypes.UINT)
GetAsyncKeyState = _sig(user32.GetAsyncKeyState, ctypes.c_short, ctypes.c_int)
SendInput = _sig(
    user32.SendInput, wintypes.UINT, wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int
)
OpenProcess = _sig(
    kernel32.OpenProcess, wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD
)
CloseHandle = _sig(kernel32.CloseHandle, wintypes.BOOL, wintypes.HANDLE)
QueryFullProcessImageNameW = _sig(
    kernel32.QueryFullProcessImageNameW,
    wintypes.BOOL,
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.LPWSTR,
    wintypes.PDWORD,
)
CreateMutexW = _sig(
    kernel32.CreateMutexW, wintypes.HANDLE, wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR
)


GetDriveTypeW = _sig(kernel32.GetDriveTypeW, wintypes.UINT, wintypes.LPCWSTR)
DRIVE_FIXED = 3


def is_on_fixed_drive(path: str) -> bool:
    """Yol yerel sabit diskteyse True. Ağ G/Ç'si yapmaz; UNC ve ağ sürücüleri False döner."""
    drive = os.path.splitdrive(path)[0]
    if len(drive) != 2 or drive[1] != ":":
        return False
    return GetDriveTypeW(drive + "\\") == DRIVE_FIXED


def process_name_of_window(hwnd: int | None) -> str | None:
    """Pencerenin sahibi sürecin exe adı (küçük harf, ör. 'chrome.exe')."""
    if not hwnd:
        return None
    pid = wintypes.DWORD(0)
    GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value:
        return None
    handle = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not handle:
        return None
    try:
        size = wintypes.DWORD(1024)
        buf = ctypes.create_unicode_buffer(size.value)
        if not QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return None
        return os.path.basename(buf.value).lower() or None
    finally:
        CloseHandle(handle)


def clipboard_format_present(name: str) -> bool:
    fmt = RegisterClipboardFormatW(name)
    return bool(fmt and IsClipboardFormatAvailable(fmt))


def _key(vk: int, up: bool = False) -> INPUT:
    inp = INPUT(type=INPUT_KEYBOARD)
    inp.ki = KEYBDINPUT(wVk=vk, dwFlags=KEYEVENTF_KEYUP if up else 0)
    return inp


def send_ctrl_v() -> None:
    """Aktif pencereye Ctrl+V gönderir.

    Kullanıcı o an Shift/Alt/Win tuşunu basılı tutuyorsa (ör. Shift+Enter ile seçim)
    hedef uygulama bunu Ctrl+Shift+V olarak görmesin diye önce o tuşlar bırakılır.
    """
    seq: list[INPUT] = []
    for vk in (VK_SHIFT, VK_MENU, VK_LWIN, VK_RWIN):
        if GetAsyncKeyState(vk) & 0x8000:
            seq.append(_key(vk, up=True))
    seq += [_key(VK_CONTROL), _key(VK_V), _key(VK_V, up=True), _key(VK_CONTROL, up=True)]
    arr = (INPUT * len(seq))(*seq)
    SendInput(len(seq), arr, ctypes.sizeof(INPUT))


def acquire_single_instance(name: str) -> bool:
    """Adlandırılmış mutex ile tek kopya çalışmayı sağlar. Zaten çalışıyorsa False."""
    handle = CreateMutexW(None, False, name)
    acquire_single_instance._handle = handle  # süreç boyunca açık kalsın
    return ctypes.get_last_error() != ERROR_ALREADY_EXISTS
