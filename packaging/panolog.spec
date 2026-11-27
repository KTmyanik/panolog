# PyInstaller tarifi: tek dosyalık, konsolsuz Panolog.exe üretir.
# Kullanım (depo kökünden):  .\.venv\Scripts\pyinstaller.exe packaging\panolog.spec --noconfirm
# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH).parent
sys.path.insert(0, str(ROOT / "src"))

# Uygulama ikonu kodla çizilir; .exe için aynı çizimden .ico üretilir.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtGui import QGuiApplication  # noqa: E402

_qt = QGuiApplication.instance() or QGuiApplication([])
from panolog.ui.icons import app_icon  # noqa: E402

ICON = ROOT / "build" / "panolog.ico"
ICON.parent.mkdir(exist_ok=True)
if not app_icon().pixmap(256, 256).toImage().save(str(ICON), "ICO"):
    raise SystemExit("ikon üretilemedi")

# winrt (OCR) paketleri veri dosyası ve ikili içerir; hepsi açıkça toplanır.
datas, binaries, hiddenimports = collect_all("winrt")
# Yerel OCR modelleri (iki .onnx dosyası ve lisans notu).
MODELS = ROOT / "src" / "panolog" / "ocr" / "models"
datas += [(str(f), "panolog/ocr/models") for f in MODELS.iterdir() if f.is_file()]

a = Analysis(
    [str(ROOT / "packaging" / "entry.py")],
    pathex=[str(ROOT / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "unittest", "pydoc", "pytest"],
    noarchive=False,
)

# Kullanılmayan büyük Qt parçaları: yazılımsal OpenGL, çeviriler, ağ/QML/PDF modülleri.
_DROP = (
    "opengl32sw.dll",
    "qt6network",
    "qt6qml",
    "qt6quick",
    "qt6pdf",
    "qt6opengl",
    "qt6virtualkeyboard",
    "qt6svg",
)


def _keep(entry) -> bool:
    name = entry[0].replace("\\", "/").lower()
    if "/translations/" in name:
        return False
    return not any(os.path.basename(name).startswith(d) for d in _DROP)


a.binaries = [b for b in a.binaries if _keep(b)]
a.datas = [d for d in a.datas if _keep(d)]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Panolog",
    icon=str(ICON),
    console=False,
    upx=False,  # sıkıştırılmış .exe'ler güvenlik yazılımlarında daha sık yanlış alarm verir
    version=str(ROOT / "packaging" / "version_info.txt"),
)
