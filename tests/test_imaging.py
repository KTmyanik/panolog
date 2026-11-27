from PySide6.QtCore import QRect, QSize
from PySide6.QtGui import QColor, QImage

from panolog import imaging
from panolog.ui.image_editor import EditSession, fit_scale
from panolog.ui.preview import preview_geometry

WHITE, BLACK, RED = 0xFFFFFFFF, 0xFF000000, 0xFFFF0000


def checker(width=120, height=80, cell=2) -> QImage:
    """İnce siyah-beyaz dama: bulanıklaşınca griye döner, ayrıntı kaybı ölçülebilir."""
    img = QImage(width, height, QImage.Format.Format_ARGB32)
    for y in range(height):
        for x in range(width):
            img.setPixel(x, y, BLACK if (x // cell + y // cell) % 2 else WHITE)
    return img


def distinct(image: QImage, rect: QRect) -> set[int]:
    return {
        image.pixel(x, y)
        for y in range(rect.top(), rect.bottom() + 1)
        for x in range(rect.left(), rect.right() + 1)
    }


def same_outside(a: QImage, b: QImage, rect: QRect) -> bool:
    return all(
        a.pixel(x, y) == b.pixel(x, y)
        for y in range(a.height())
        for x in range(a.width())
        if not rect.contains(x, y)
    )


# ---- kapatma ----------------------------------------------------------------
def test_cover_fills_only_the_area_and_keeps_original():
    src = checker()
    rect = QRect(10, 20, 30, 15)
    out = imaging.cover(src, rect)
    assert distinct(out, rect) == {BLACK}
    assert same_outside(src, out, rect)
    assert distinct(src, rect) == {BLACK, WHITE}  # asıl görsel değişmedi
    assert out.size() == src.size()


def test_cover_replaces_transparent_pixels_and_accepts_colour():
    src = QImage(20, 20, QImage.Format.Format_ARGB32)
    src.fill(QColor(0, 0, 0, 0))
    out = imaging.cover(src, QRect(0, 0, 10, 10), QColor(255, 0, 0))
    assert out.pixel(5, 5) == RED and out.pixel(15, 15) == 0


def test_cover_clamps_and_ignores_outside_rects():
    src = checker()
    out = imaging.cover(src, QRect(100, 60, 500, 500))
    assert distinct(out, QRect(100, 60, 20, 20)) == {BLACK}
    assert same_outside(src, out, QRect(100, 60, 20, 20))
    assert imaging.cover(src, QRect(500, 500, 10, 10)) == src
    # ters yönde sürüklenmiş dikdörtgen de çalışır
    backwards = imaging.cover(src, QRect(40, 35, -30, -15))
    assert backwards.pixel(20, 25) == BLACK and backwards.pixel(15, 28) == BLACK


def test_cover_works_on_other_formats():
    src = checker().convertToFormat(QImage.Format.Format_RGB888)
    out = imaging.cover(src, QRect(0, 0, 4, 4))
    assert distinct(out, QRect(0, 0, 4, 4)) == {BLACK}
    assert out.pixel(100, 40) == src.pixel(100, 40)


# ---- bulanıklaştırma --------------------------------------------------------
def test_blur_removes_detail_inside_only():
    src = checker()
    rect = QRect(20, 10, 60, 40)
    out = imaging.blur(src, rect)
    assert same_outside(src, out, rect)
    inner = rect.adjusted(4, 4, -4, -4)
    for y in range(inner.top(), inner.bottom() + 1):
        for x in range(inner.left(), inner.right() + 1):
            grey = QColor(out.pixel(x, y)).red()
            assert 96 <= grey <= 160, (x, y, grey)  # dama deseni kalmadı, hepsi griye yakın
    assert distinct(src, rect) == {BLACK, WHITE}


def test_blur_hides_a_text_sized_line():
    # 14 piksellik "yazı" satırı: bulanıklaştırınca komşu pikseller ayırt edilemez olmalı.
    src = QImage(200, 14, QImage.Format.Format_ARGB32)
    src.fill(QColor(255, 255, 255))
    for x in range(0, 200, 6):
        for y in range(2, 12):
            src.setPixel(x, y, BLACK)
            src.setPixel(x + 1, y, BLACK)
    out = imaging.blur(src, src.rect())
    row = [QColor(out.pixel(x, 7)).red() for x in range(10, 190)]
    assert max(abs(a - b) for a, b in zip(row, row[1:])) <= 8


def test_blur_block_grows_with_area():
    assert imaging.blur_block(200, 14) == 10
    assert imaging.blur_block(400, 400) == 100
    assert imaging.blur(checker(), QRect(300, 300, 5, 5)) == checker()
    tiny = imaging.blur(checker(), QRect(0, 0, 1, 1))  # tek piksel de hata vermez
    assert tiny.size() == QSize(120, 80)


# ---- kırpma -----------------------------------------------------------------
def test_crop():
    src = checker()
    out = imaging.crop(src, QRect(10, 20, 30, 15))
    assert out.size() == QSize(30, 15)
    assert out.pixel(0, 0) == src.pixel(10, 20) and out.pixel(29, 14) == src.pixel(39, 34)
    assert imaging.crop(src, QRect(100, 70, 999, 999)).size() == QSize(20, 10)
    assert imaging.crop(src, QRect(999, 999, 5, 5)).size() == src.size()


# ---- düzenleme oturumu ------------------------------------------------------
def test_session_apply_and_undo():
    src = checker()
    s = EditSession(src)
    assert not s.modified and not s.undo()
    assert s.apply(imaging.cover, QRect(0, 0, 10, 10))
    assert s.apply(imaging.crop, QRect(0, 0, 50, 40))
    assert s.modified and s.image.size() == QSize(50, 40) and s.image.pixel(5, 5) == BLACK
    assert s.undo() and s.image.size() == src.size() and s.image.pixel(5, 5) == BLACK
    assert s.undo() and s.image == src and not s.modified
    assert not s.undo()


def test_session_ignores_rect_outside_image():
    s = EditSession(checker())
    assert not s.apply(imaging.cover, QRect(500, 500, 10, 10))
    assert not s.modified


def test_session_undo_is_bounded():
    s = EditSession(checker(20, 20))
    for i in range(40):
        s.apply(imaging.cover, QRect(i % 10, 0, 2, 2))
    undone = 0
    while s.undo():
        undone += 1
    assert undone == 30


# ---- yerleşim ---------------------------------------------------------------
def test_fit_scale_never_enlarges():
    assert fit_scale(QSize(100, 50), QSize(1000, 1000)) == 1.0
    assert fit_scale(QSize(2000, 500), QSize(1000, 1000)) == 0.5
    assert fit_scale(QSize(500, 4000), QSize(1000, 1000)) == 0.25
    assert fit_scale(QSize(0, 0), QSize(10, 10)) == 1.0


SCREEN = QRect(0, 0, 1920, 1040)


def test_preview_goes_to_the_roomier_side_and_stays_on_screen():
    popup = QRect(200, 300, 480, 560)
    geo = preview_geometry(popup, SCREEN, QSize(3840, 2160))
    assert geo.left() > popup.right() and SCREEN.contains(geo)
    assert not geo.intersects(popup)
    inner_w, inner_h = geo.width() - 12, geo.height() - 12
    assert abs(inner_w / inner_h - 16 / 9) < 0.01  # oran korunur

    popup = QRect(1400, 300, 480, 560)
    geo = preview_geometry(popup, SCREEN, QSize(3840, 2160))
    assert geo.right() < popup.left() and SCREEN.contains(geo) and not geo.intersects(popup)


def test_preview_does_not_enlarge_small_images():
    popup = QRect(200, 300, 480, 560)
    geo = preview_geometry(popup, SCREEN, QSize(300, 100))
    assert geo.size() == QSize(312, 112)
    assert geo.center().y() == popup.center().y() or abs(geo.center().y() - popup.center().y()) <= 1


def test_preview_tall_image_is_clamped_vertically():
    popup = QRect(200, 400, 480, 560)
    geo = preview_geometry(popup, SCREEN, QSize(600, 5000))
    assert SCREEN.contains(geo) and geo.height() <= SCREEN.height() - 16


def test_preview_on_screen_too_narrow_for_a_side_panel():
    screen = QRect(0, 0, 640, 700)
    popup = QRect(80, 70, 480, 560)
    geo = preview_geometry(popup, screen, QSize(1920, 1080))
    assert screen.contains(geo) and geo.width() > 400
