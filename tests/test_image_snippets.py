import base64
import json
import sqlite3

import pytest
from PySide6.QtCore import QRect, QSize
from PySide6.QtGui import QColor, QImage

from panolog.snippets import SnippetError, SnippetRepository, io_json
from panolog.snippets.repository import MAX_IMAGE_BYTES, PNG_MAGIC
from panolog.storage import connect
from panolog.storage.db import _MIGRATIONS
from panolog.ui import draw_canvas
from panolog.ui.draw_canvas import (
    CANVAS_SIZE,
    Stroke,
    base_rect,
    crop_to_ink,
    ink_bounds,
    render,
    to_png,
)

WHITE, BLACK = 0xFFFFFFFF, 0xFF111111


def png(color="#112233", size=(8, 6)) -> bytes:
    img = QImage(*size, QImage.Format.Format_ARGB32)
    img.fill(QColor(color))
    return to_png(img)


@pytest.fixture
def repo():
    return SnippetRepository(connect(":memory:"))


# ---- depo -------------------------------------------------------------------
def test_image_snippet_roundtrip(repo):
    data = png()
    s = repo.add("İmza", "yok sayılır", ";imza", "e-posta", image=data)
    assert s.is_image and s.image == data and s.content == ""
    assert repo.get(s.id) == s and repo.by_shortcode(";imza").image == data
    assert [x.name for x in repo.list("imza")] == ["İmza"]  # ad ve kısa kodla aranır
    text = repo.add("Metin", "merhaba")
    assert not text.is_image and text.image is None


def test_image_snippet_needs_no_text_but_text_snippet_does(repo):
    repo.add("Görsel", "", image=png())
    with pytest.raises(SnippetError):
        repo.add("Boş", "")


def test_image_must_be_png_and_small(repo):
    with pytest.raises(SnippetError):
        repo.add("Bozuk", "", image=b"GIF89a....")
    with pytest.raises(SnippetError):
        repo.add("Dev", "", image=PNG_MAGIC + b"0" * MAX_IMAGE_BYTES)
    assert repo.count() == 0


def test_update_switches_between_text_and_image(repo):
    s = repo.add("Şablon", "metin")
    as_image = repo.update(s.id, "Şablon", "", None, None, png())
    assert as_image.is_image and as_image.content == ""
    back = repo.update(s.id, "Şablon", "yine metin")
    assert not back.is_image and back.content == "yine metin"


def test_migration_adds_image_column_to_existing_database(tmp_path):
    path = tmp_path / "eski.db"
    conn = sqlite3.connect(path)
    for script in _MIGRATIONS[:7]:  # v7: görsel şablonlardan önceki şema
        conn.executescript(script)
    conn.execute("PRAGMA user_version = 7")
    conn.execute(
        "INSERT INTO snippets (name, content, created_at, updated_at) VALUES ('eski', 'x', 1, 1)"
    )
    conn.commit()
    conn.close()
    repo = SnippetRepository(connect(path))
    old = repo.list()[0]
    assert (old.name, old.content, old.image) == ("eski", "x", None)
    assert repo.add("yeni", "", image=png()).is_image


# ---- JSON -------------------------------------------------------------------
def test_export_import_keeps_images(repo):
    data = png("#abcdef")
    repo.add("İmza", "", ";imza", image=data)
    repo.add("Metin", "merhaba")
    raw = io_json.dumps(repo.list())
    exported = {e["name"]: e for e in json.loads(raw)["snippets"]}
    assert base64.b64decode(exported["İmza"]["image"]) == data
    assert "image" not in exported["Metin"]  # metin şablonlarının biçimi değişmedi

    other = SnippetRepository(connect(":memory:"))
    assert other.import_many(io_json.loads(raw)) == (2, 0, 0)
    assert other.by_shortcode(";imza").image == data
    assert other.import_many(io_json.loads(raw)) == (0, 0, 2)

    # aynı kısa kod, farklı görsel: güncellenir
    changed = json.loads(raw)
    changed["snippets"] = [e for e in changed["snippets"] if e["name"] == "İmza"]
    changed["snippets"][0]["image"] = base64.b64encode(png("#000000")).decode()
    assert other.import_many(io_json.loads(json.dumps(changed))) == (0, 1, 0)
    assert other.by_shortcode(";imza").image == png("#000000")


@pytest.mark.parametrize(
    "image",
    [5, "base64 değil!!", base64.b64encode(b"PNG degil").decode(), ""],
)
def test_import_rejects_bad_images(image):
    raw = json.dumps({"snippets": [{"name": "a", "image": image}]})
    with pytest.raises(SnippetError):
        io_json.loads(raw)


# ---- çizim ------------------------------------------------------------------
def test_render_draws_strokes_on_white():
    stroke = Stroke("#111111", 4.0, ((100.0, 100.0), (200.0, 100.0), (300.0, 100.0)))
    img = render(CANVAS_SIZE, None, (stroke,))
    assert img.size() == CANVAS_SIZE
    assert img.pixel(200, 100) == BLACK and img.pixel(10, 10) == WHITE
    dot = render(CANVAS_SIZE, None, (Stroke("#111111", 6.0, ((50.0, 50.0),)),))
    assert dot.pixel(50, 50) != WHITE


def test_ink_bounds_and_crop():
    blank = render(CANVAS_SIZE, None, ())
    assert ink_bounds(blank).isEmpty() and crop_to_ink(blank).isNull()
    stroke = Stroke("#111111", 2.0, ((100.0, 80.0), (220.0, 120.0)))
    img = render(CANVAS_SIZE, None, (stroke,))
    bounds = ink_bounds(img)
    assert QRect(96, 76, 130, 50).contains(bounds) and bounds.contains(QRect(102, 82, 116, 36))
    cropped = crop_to_ink(img, margin=10)
    assert cropped.width() == bounds.width() + 20 and cropped.height() == bounds.height() + 20
    assert cropped.pixel(0, 0) == WHITE
    edge = render(CANVAS_SIZE, None, (Stroke("#111111", 2.0, ((0.0, 0.0), (5.0, 5.0))),))
    assert crop_to_ink(edge, margin=10).width() <= 5 + 2 + 10 + 1  # kenarda taşmaz


def test_base_image_is_centered_and_never_enlarged():
    assert base_rect(QSize(560, 220), QSize(100, 50)).getRect() == (230.0, 85.0, 100.0, 50.0)
    big = base_rect(QSize(560, 220), QSize(1120, 880))
    assert (big.width(), big.height()) == (280.0, 220.0) and big.left() == 140.0


def test_canvas_state_undo_and_clear(qapp):
    canvas = draw_canvas.DrawCanvas()
    assert canvas.is_empty() and canvas.image().isNull() and not canvas.undo()
    canvas.add_stroke([(100.0, 100.0), (200.0, 120.0)])
    canvas.color, canvas.pen_width = "#1a3fa8", 5.5
    canvas.add_stroke([(120.0, 60.0), (180.0, 160.0)])
    two = canvas.image()
    assert not two.isNull() and two.width() < CANVAS_SIZE.width()
    assert canvas.undo()
    one = canvas.image()
    assert one.size() != two.size()
    canvas.clear()
    assert canvas.is_empty()
    assert canvas.undo() and canvas.image() == one  # temizleme de geri alınabilir
    base = QImage(40, 30, QImage.Format.Format_ARGB32)
    base.fill(QColor("#ff0000"))
    canvas = draw_canvas.DrawCanvas()  # yalnızca zemin görseli olan boş tuval
    canvas.set_base(base)
    with_base = canvas.image()
    assert with_base.pixel(with_base.width() // 2, with_base.height() // 2) == 0xFFFF0000
    assert to_png(canvas.image()).startswith(PNG_MAGIC)


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])
