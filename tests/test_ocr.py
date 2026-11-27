import time

import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QImage

from panolog.classifier import Category
from panolog.ocr import (
    OcrError,
    OcrResult,
    OcrService,
    OcrUnavailable,
    language_warning,
    missing_languages,
    pick_language,
)
from panolog.ocr.engine import prepare_image, upscale_factor
from panolog.settings import Settings
from panolog.storage import Repository, connect
from panolog.storage.repository import text_hash


# ---- dil seçimi -------------------------------------------------------------
def test_turkish_preferred_over_english():
    assert pick_language(["en-US", "tr"]) == "tr"
    assert pick_language(["en-US", "tr-TR", "de-DE"]) == "tr-TR"


def test_english_used_when_turkish_missing():
    assert pick_language(["de-DE", "en-GB"]) == "en-GB"


def test_falls_back_to_any_installed_language():
    assert pick_language(["de-DE"]) == "de-DE"
    assert pick_language([]) is None


def test_missing_languages():
    assert missing_languages(["en-US"]) == ["tr"]
    assert missing_languages(["tr", "en-US"]) == []
    assert missing_languages([]) == ["tr", "en"]


def test_no_warning_when_turkish_installed():
    assert language_warning(["tr", "en-US"]) is None
    assert language_warning(["tr-TR"]) is None  # Türkçe motoru İngilizce metni de okur


def test_warning_when_turkish_missing_names_engine_and_fix():
    w = language_warning(["en-US"])
    assert "Türkçe OCR dil paketi yüklü değil" in w
    assert "en-US" in w
    assert "Language.OCR~~~tr-TR" in w


def test_warning_when_no_language_at_all():
    w = language_warning([])
    assert "yüklü bir OCR dil paketi yok" in w
    assert "Dil ekle" in w


# ---- görsel hazırlığı -------------------------------------------------------
def test_prepare_image_converts_to_bgra():
    img = QImage(10, 6, QImage.Format.Format_RGB888)
    out = prepare_image(img, 10000)
    assert out.format() == QImage.Format.Format_ARGB32
    assert out.sizeInBytes() == out.width() * out.height() * 4


def test_small_images_are_upscaled_for_accuracy():
    # Ekran görüntüsü boyutundaki görseller 2 kat büyütülür (alt çizgi vb. kaybolmasın).
    out = prepare_image(QImage(785, 211, QImage.Format.Format_ARGB32), 10000)
    assert (out.width(), out.height()) == (1570, 422)


def test_upscale_factor_limits():
    assert upscale_factor(785, 211, 10000) == 2.0
    assert upscale_factor(1920, 1080, 10000) == 2.0
    assert upscale_factor(3000, 1000, 10000) == pytest.approx(4000 / 3000)
    assert upscale_factor(3840, 2160, 10000) == 1.0  # kazanç küçük, büyütme
    assert upscale_factor(8000, 100, 10000) == 1.0
    assert upscale_factor(500, 500, 600) == 1.2  # motorun sınırı aşılmaz
    assert upscale_factor(0, 0, 10000) == 2.0


def test_prepare_image_shrinks_oversized_keeping_aspect():
    img = QImage(400, 100, QImage.Format.Format_ARGB32)
    out = prepare_image(img, 200)
    assert (out.width(), out.height()) == (200, 50)


# ---- depolama ---------------------------------------------------------------
@pytest.fixture
def repo():
    return Repository(connect(":memory:"))


def _image(repo, digest="img1"):
    item, _ = repo.add_item(Category.IMAGE, digest, image_path=f"{digest}.png", thumb_path="t.png")
    return item


def test_new_image_has_no_ocr(repo):
    item = _image(repo)
    assert item.ocr_text is None and item.ocr_done is False
    assert repo.list_items(Category.IMAGE, "fatura") == []


def test_set_ocr_makes_image_searchable(repo):
    item = _image(repo)
    repo.set_ocr(item.id, "Fatura No: 2026-0042\nIŞIK Ticaret")
    got = repo.get(item.id)
    assert got.ocr_done and got.ocr_text.startswith("Fatura No")
    assert [i.id for i in repo.list_items(Category.IMAGE, "fatura")] == [item.id]
    # Türkçe büyük/küçük harf duyarsız
    assert [i.id for i in repo.list_items(Category.IMAGE, "ışık")] == [item.id]
    assert [i.id for i in repo.list_items(Category.IMAGE, "TİCARET")] == [item.id]
    assert repo.list_items(Category.IMAGE, "yok böyle bir şey") == []


def test_empty_ocr_result_counts_as_done(repo):
    item = _image(repo)
    repo.set_ocr(item.id, "")
    assert repo.get(item.id).ocr_done is True
    assert repo.next_pending_ocr() is None


def test_failed_ocr_is_not_retried(repo):
    item = _image(repo)
    repo.set_ocr(item.id, None)
    got = repo.get(item.id)
    assert got.ocr_done is False and got.ocr_text is None
    assert repo.next_pending_ocr() is None


def test_pending_queue_newest_first_and_images_only(repo):
    repo.add_item(Category.TEXT, text_hash("a"), text="a")
    first = _image(repo, "img1")
    second = _image(repo, "img2")
    assert repo.count_pending_ocr() == 2
    assert repo.next_pending_ocr().id == second.id
    repo.set_ocr(second.id, "x")
    assert repo.next_pending_ocr().id == first.id
    repo.set_ocr(first.id, "y")
    assert repo.next_pending_ocr() is None and repo.count_pending_ocr() == 0


def test_set_ocr_ignores_non_images(repo):
    item, _ = repo.add_item(Category.TEXT, text_hash("merhaba"), text="merhaba")
    repo.set_ocr(item.id, "başka metin")
    assert repo.get(item.id).ocr_text is None
    assert [i.id for i in repo.list_items(Category.TEXT, "merhaba")] == [item.id]


def test_recopying_image_keeps_ocr_text(repo):
    item = _image(repo)
    repo.set_ocr(item.id, "sözleşme")
    again, created = repo.add_item(Category.IMAGE, "img1", image_path="img1.png")
    assert not created and again.ocr_text == "sözleşme"
    assert repo.list_items(Category.IMAGE, "sözleşme")


def test_old_database_is_migrated(tmp_path):
    import sqlite3

    from panolog.storage import db

    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    for script in db._MIGRATIONS[:4]:
        conn.executescript(script)
    conn.execute("PRAGMA user_version = 4")
    conn.execute(
        "INSERT INTO items (category, content_hash, image_path, created_at, copied_at)"
        " VALUES ('image', 'h', 'h.png', 1, 1)"
    )
    conn.commit()
    conn.close()
    repo = Repository(connect(path))
    item = repo.next_pending_ocr()
    assert item is not None and item.ocr_done is False


# ---- ayar -------------------------------------------------------------------
def test_auto_ocr_is_off_by_default_and_round_trips():
    assert Settings().ocr_auto is False
    s = Settings()
    s.ocr_auto = True
    assert Settings.from_dict(s.to_dict()).ocr_auto is True
    assert Settings.from_dict({}).ocr_auto is False


# ---- servis -----------------------------------------------------------------
@pytest.fixture(scope="module")
def qapp():
    return QCoreApplication.instance() or QCoreApplication([])


def _drain(qapp, service, timeout=5.0):
    end = time.time() + timeout
    while service.is_busy() and time.time() < end:
        qapp.processEvents()
        time.sleep(0.005)
    assert not service.is_busy()


def test_service_delivers_result_on_main_thread(qapp):
    service = OcrService(run=lambda image: OcrResult(f"{image.width()}x{image.height()}", "tr"))
    got = []
    service.finished.connect(lambda *a: got.append(a))
    service.request(7, QImage(3, 2, QImage.Format.Format_ARGB32), interactive=True)
    assert service.is_busy(7)
    _drain(qapp, service)
    assert got == [(7, OcrResult("3x2", "tr"), True)]


def test_service_reports_failures(qapp):
    def boom(_image):
        raise OcrUnavailable("dil paketi yok")

    def crash(_image):
        raise ValueError("beklenmeyen")

    failures = []
    for run in (boom, crash):
        service = OcrService(run=run)
        service.failed.connect(lambda *a: failures.append(a))
        service.request(1, QImage(1, 1, QImage.Format.Format_ARGB32), interactive=False)
        _drain(qapp, service)
    assert isinstance(failures[0][1], OcrUnavailable) and failures[0][2] is False
    assert isinstance(failures[1][1], OcrError) and "beklenmeyen" in str(failures[1][1])


def test_duplicate_request_runs_once_and_is_upgraded_to_interactive(qapp):
    calls = []

    def slow(_image):
        calls.append(1)
        time.sleep(0.05)
        return OcrResult("ok", "tr")

    service = OcrService(run=slow)
    got = []
    service.finished.connect(lambda *a: got.append(a))
    image = QImage(1, 1, QImage.Format.Format_ARGB32)
    service.request(5, image, interactive=False)
    service.request(5, image, interactive=True)
    _drain(qapp, service)
    assert len(calls) == 1
    assert got == [(5, OcrResult("ok", "tr"), True)]


def test_images_read_by_the_old_ocr_are_queued_again(tmp_path):
    import sqlite3

    from panolog.storage import db

    path = tmp_path / "v5.db"
    conn = sqlite3.connect(path)
    for script in db._MIGRATIONS[:5]:
        conn.executescript(script)
    conn.execute("PRAGMA user_version = 5")
    conn.execute(
        "INSERT INTO items (category, content_hash, image_path, created_at, copied_at,"
        " ocr_text, ocr_status, search_text) VALUES ('image', 'h', 'h.png', 1, 1,"
        " 'table name', 1, 'table name')"
    )
    conn.commit()
    conn.close()
    repo = Repository(connect(path))
    item = repo.next_pending_ocr()
    assert item is not None and item.ocr_done is False
    assert item.ocr_text == "table name"  # yenisi gelene kadar eski metin durur
    assert repo.list_items(Category.IMAGE, "table name")
    repo.set_ocr(item.id, "table_name")
    assert repo.get(item.id).ocr_text == "table_name"
