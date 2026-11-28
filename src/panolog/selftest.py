"""Paketlenmiş .exe'nin sağlam olduğunu doğrulayan kendi kendine test.

`Panolog.exe --self-test rapor.txt` ile çalışır. Clipboard'a, global kısayola,
AppData'daki verilere ve çalışan başka bir kopyaya dokunmaz; yalnızca bileşenlerin
(Qt eklentileri, SQLite, OCR) pakette bulunup yüklendiğini sınar.
"""
from __future__ import annotations

import sys
import tempfile
import threading
import traceback
from pathlib import Path


def _check_storage() -> str:
    from .classifier import Category
    from .storage import Repository, connect
    from .storage.repository import text_hash

    repo = Repository(connect(":memory:"))
    repo.add_item(Category.TEXT, text_hash("IŞIK"), text="IŞIK")
    assert len(repo.list_items(Category.TEXT, "ışık")) == 1
    return "şema ve arama çalışıyor"


def _check_png() -> str:
    from PySide6.QtGui import QColor, QImage

    image = QImage(32, 16, QImage.Format.Format_ARGB32)
    image.fill(QColor("#2f7de1"))
    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "t.png")
        assert image.save(path, "PNG"), "PNG yazılamadı"
        back = QImage(path)
    assert back.width() == 32 and back.pixelColor(1, 1) == QColor("#2f7de1")
    return "PNG yazma/okuma çalışıyor"


def _check_ui() -> str:
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QColor, QImage

    from . import imaging
    from .classifier import Category
    from .settings import Settings
    from .snippets import SnippetRepository
    from .storage import Repository, connect
    from .storage.repository import text_hash
    from .ui.draw_canvas import to_png
    from .ui.image_editor import ImageEditorDialog
    from .ui.snippet_dialogs import SnippetEditDialog
    from .ui.popup import Popup
    from .ui.settings_dialog import SettingsDialog
    from .ui.themes import THEMES
    from .ui.tray import Tray

    conn = connect(":memory:")
    repo = Repository(conn)
    for text in ("SELECT 1 FROM dual;", "düz bir metin"):
        repo.add_item(Category.TEXT, text_hash(text), text=text)
    snippets = SnippetRepository(conn)
    # Görsel şablon: çiz, PNG olarak sakla, geri oku.
    drawing = SnippetEditDialog(snippets)
    drawing.canvas.add_stroke([(100.0, 100.0), (180.0, 60.0), (260.0, 110.0)])
    drawn = drawing.canvas.image()
    if drawn.isNull():
        raise RuntimeError("çizim alanı görsel üretmedi")
    saved = snippets.add("çizim", "", image=to_png(drawn))
    if QImage.fromData(saved.image).size() != drawn.size():
        raise RuntimeError("görsel şablon geri okunamadı")
    popup = Popup(repo, snippets)
    # Her tema uygulanıp çizilir: stil sayfası, arka plan ve satır çizimi paketten yükleniyor mu?
    for key in THEMES:
        popup.set_theme(key, animate=False)
        if popup.grab().isNull():
            raise RuntimeError(f"tema çizilemedi: {key}")
    popup.set_theme(None)
    SettingsDialog(Settings(), lambda: None)
    Tray()
    image = QImage(64, 48, QImage.Format.Format_ARGB32)
    image.fill(QColor("#ffffff"))
    editor = ImageEditorDialog(image)
    if not editor.session.apply(imaging.cover, QRect(4, 4, 20, 10)):
        raise RuntimeError("görsel düzenleyici işlem uygulamadı")
    if editor.session.image.pixel(10, 8) != 0xFF000000:
        raise RuntimeError("kapatılan alan siyah değil")
    return (
        f"pencereler oluşturuldu, {len(THEMES)} tema çizildi, düzenleyici ve çizim çalıştı"
    )


def _check_features() -> str:
    """Kod algılama, dönüştürme, yedek ve istatistik; ağ modülleri yüklenir ama istek atılmaz."""
    import ssl

    from . import backup, codekind, linkmeta, transforms
    from .classifier import Category, classify_text
    from .storage import Repository, connect
    from .storage.images import ImageStore
    from .storage.repository import text_hash
    from .ui.stats_dialog import StatsDialog

    if classify_text("SELECT a FROM t WHERE b = 1;") is not Category.CODE:
        raise RuntimeError("SQL kod olarak sınıflanmadı")
    if "<span" not in codekind.highlight_html('{"a": 1}', "json", codekind.PALETTE_DARK):
        raise RuntimeError("kod renklendirilmedi")
    if transforms.upper_tr("iğne") != "İĞNE":
        raise RuntimeError("Türkçe büyük harf dönüşümü yanlış")
    ssl.create_default_context()  # link başlığı için gereken TLS pakette mi?
    if linkmeta.parse_title("<html><title>Başlık</title></html>") != "Başlık":
        raise RuntimeError("sayfa başlığı ayrıştırılamadı")
    if linkmeta.is_fetchable("http://localhost/x"):
        raise RuntimeError("yerel adres istek atılabilir sayıldı")

    repo = Repository(connect(":memory:"))
    item, _new = repo.add_item(Category.TEXT, text_hash("yedek"), text="yedek")
    repo.set_tag([item.id], "uat")
    repo.bump_stat(Category.TEXT, "notepad.exe")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "yedek.json"
        backup.export_json(repo.all_items(), path)
        other = Repository(connect(":memory:"))
        added, _skipped = backup.import_json(path, other, ImageStore(Path(tmp) / "img"))
    if added != 1 or [t for t, _n in other.tags()] != ["uat"]:
        raise RuntimeError("yedek geri yüklenemedi")
    StatsDialog(repo)
    return "kod algılama, dönüştürme, yedek, istatistik ve TLS çalışıyor"


def _check_ocr() -> str:
    from PySide6.QtGui import QColor, QImage

    from .ocr import available_languages, model_engine, pick_language, recognize

    image = QImage(200, 60, QImage.Format.Format_ARGB32)
    image.fill(QColor("white"))
    if not model_engine.is_available():
        raise AssertionError("yerel OCR modeli pakette yok")
    model_engine.ModelOcr.instance().read(image)
    model_engine.ModelOcr.release()
    languages = available_languages()
    if pick_language(languages) is None:
        return "yerel model çalıştı; Windows'ta OCR dil paketi yok"
    outcome: list[object] = []

    def work() -> None:
        try:
            outcome.append(recognize(image))
        except Exception as exc:  # noqa: BLE001
            outcome.append(exc)

    thread = threading.Thread(target=work)
    thread.start()
    thread.join(30)
    assert outcome, "OCR zaman aşımına uğradı"
    if isinstance(outcome[0], Exception):
        raise outcome[0]
    return f"yerel model ve Windows motoru çalıştı; diller: {', '.join(languages)}"


def run(report_path: str | None) -> int:
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv[:1])  # noqa: F841
    lines: list[str] = []
    ok = True
    for name, check in (
        ("depolama", _check_storage),
        ("görsel", _check_png),
        ("arayüz", _check_ui),
        ("özellikler", _check_features),
        ("ocr", _check_ocr),
    ):
        try:
            lines.append(f"OK    {name}: {check()}")
        except Exception:  # noqa: BLE001
            ok = False
            lines.append(f"HATA  {name}:\n{traceback.format_exc()}")
    lines.append("SONUÇ: " + ("başarılı" if ok else "başarısız"))
    report = "\n".join(lines) + "\n"
    if report_path:
        Path(report_path).write_text(report, encoding="utf-8")
    elif sys.stdout is not None:  # pencereli .exe'de stdout yoktur
        sys.stdout.write(report)
    return 0 if ok else 1


def ocr_file(image_path: str, output_path: str) -> int:
    """`Panolog.exe --ocr görsel.png çıktı.txt`: görseli uygulamadaki OCR yoluyla okur ve
    metni dosyaya yazar. Geçmişe, clipboard'a ve çalışan kopyaya dokunmaz."""
    import time

    from PySide6.QtGui import QGuiApplication, QImage

    app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])  # noqa: F841
    outcome: list[object] = []

    def work() -> None:
        try:
            from .ocr import pipeline

            started = time.perf_counter()
            result = pipeline.read_image(QImage(image_path))
            outcome.append((result, time.perf_counter() - started))
        except Exception:  # noqa: BLE001
            outcome.append(traceback.format_exc())

    thread = threading.Thread(target=work)
    thread.start()
    thread.join(120)
    if not outcome or isinstance(outcome[0], str):
        Path(output_path).write_text(str(outcome[0]) if outcome else "zaman aşımı", encoding="utf-8")
        return 1
    result, seconds = outcome[0]
    Path(output_path).write_text(
        f"{result.text}\n\n[motor: {result.language}, süre: {seconds:.2f} sn]\n", encoding="utf-8"
    )
    return 0
