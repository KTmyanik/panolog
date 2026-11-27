"""Yerel OCR modeli, satır dizimi ve iki motorun birleştirilmesi."""
from pathlib import Path

import pytest
from PySide6.QtGui import QImage

from panolog.ocr import merge, model_engine, pipeline
from panolog.ocr.engine import OcrError, OcrResult, OcrUnavailable
from panolog.ocr.lines import Line, group_lines, lines_to_text, merge_rows

np = pytest.importorskip("numpy")
FIXTURE = Path(__file__).parent / "data" / "ocr_sql.png"
FIXTURE_TEXT = (
    "CREATE TABLE Persons (\n"
    "PersonID INT PRIMARY KEY,\n"
    "column1 VARCHAR(255) NOT NULL,\n"
    ");"
)


# ---- bağlı bileşenler ---------------------------------------------------------
def _mask(rows):
    return np.array([[c == "#" for c in row] for row in rows])


def test_components_finds_separate_blobs_with_boxes_and_areas():
    found = model_engine.components(_mask([
        "##....#",
        "##....#",
        ".......",
        "...#...",
    ]))
    assert sorted(found) == [(0, 0, 2, 2, 4), (3, 3, 4, 4, 1), (6, 0, 7, 2, 2)]


def test_components_joins_diagonal_neighbours():
    assert model_engine.components(_mask(["#..", ".#.", "..#"])) == [(0, 0, 3, 3, 3)]


def test_components_merges_branches_that_meet_later():
    # U biçimi: iki kol alt satırda birleşir, tek bileşen olmalı.
    found = model_engine.components(_mask(["#.#", "#.#", "###"]))
    assert found == [(0, 0, 3, 3, 7)]


def test_components_empty_mask():
    assert model_engine.components(np.zeros((4, 5), dtype=bool)) == []


def test_unclip_expands_by_area_over_perimeter():
    x0, y0, x1, y1 = model_engine.unclip(10, 10, 110, 30, ratio=1.6)
    d = 100 * 20 * 1.6 / (2 * 120)
    assert (x0, y0, x1, y1) == pytest.approx((10 - d, 10 - d, 110 + d, 30 + d))
    assert model_engine.unclip(5, 5, 5, 9) == (5, 5, 5, 9)  # alansız kutu değişmez


def test_ctc_decode_drops_blanks_and_repeats():
    chars = ["", "a", "b", " "]
    text, score = model_engine.ctc_decode([1, 1, 0, 1, 2, 2, 3, 0], [0.9, 0.8, 1, 0.7, 0.5, 0.4, 1.0, 1], chars)
    assert text == "aab "
    assert score == pytest.approx((0.9 + 0.7 + 0.5 + 1.0) / 4)
    assert model_engine.ctc_decode([0, 0], [1, 1], chars) == ("", 0.0)


def test_to_array_is_bgr_and_ignores_row_padding():
    image = QImage(3, 2, QImage.Format.Format_RGB888)  # 3 px * 3 bayt = 9; satır 12'ye dolar
    image.fill(0xFF102030)  # R=0x10 G=0x20 B=0x30
    array = model_engine.to_array(image)
    assert array.shape == (2, 3, 3)
    assert array[1, 2].tolist() == [0x30, 0x20, 0x10]


# ---- satır dizimi -------------------------------------------------------------
def test_lines_are_ordered_top_to_bottom_then_left_to_right():
    parts = [
        Line("dünya", 60, 11, 100, 29),
        Line("ikinci", 0, 40, 50, 60),
        Line("merhaba", 0, 10, 50, 30),
    ]
    assert [[p.text for p in row] for row in group_lines(parts)] == [["merhaba", "dünya"], ["ikinci"]]
    assert lines_to_text(parts) == "merhaba dünya\nikinci"
    row = merge_rows(parts)[0]
    assert (row.x0, row.y0, row.x1, row.y1) == (0, 10, 100, 30)


# ---- birleştirme --------------------------------------------------------------
def _line(text, y):
    return Line(text, 0, y, 500, y + 20)


def test_model_quirks_are_fixed():
    assert merge.fix_model_text("güneșli （a）：") == "güneşli (a):"


def test_turkish_letters_come_from_windows_on_turkish_lines():
    model = [_line("Lütfen değişiklikleri kaydedip çikiş yapin", 0)]
    windows = [_line("Lütfen değişiklikleri kaydedip çıkış yapın", 1)]
    assert merge.merge(model, windows) == "Lütfen değişiklikleri kaydedip çıkış yapın"


def test_code_lines_ignore_windows_even_if_it_adds_turkish_letters():
    model = [_line("PersonID INT PRIMARY KEY,", 0), _line("SELECT user_id FROM app_users WHERE id = 1;", 30)]
    windows = [_line("Person1D INT PRİMARY KEY,", 0), _line("SELECT user_İd FROM app üşers WHERE İd = 1;", 30)]
    assert merge.merge(model, windows) == (
        "PersonID INT PRIMARY KEY,\nSELECT user_id FROM app_users WHERE id = 1;"
    )


def test_english_prose_is_not_turkified():
    model = [_line("Invoice billing limit", 0), _line("GitHub Issues: fix timing", 30)]
    windows = [_line("ınvoice billing limit", 0), _line("GitHub Issues: fıx timing", 30)]
    assert merge.merge(model, windows) == "Invoice billing limit\nGitHub Issues: fix timing"


def test_weak_turkish_line_is_fixed_when_the_document_is_turkish():
    model = [
        _line("Sayın müşterimiz, hoş geldiniz", 0),
        _line("Hesap kapali", 30),  # Türkçeye özgü harf yok; belge geneline bakılır
        _line("Ödeme alındı, teşekkürler", 60),
    ]
    windows = [
        _line("Sayın müşterimiz, hoş geldiniz", 0),
        _line("Hesap kapalı", 30),
        _line("Ödeme alındı, teşekkürler", 60),
    ]
    assert merge.merge(model, windows).splitlines()[1] == "Hesap kapalı"


def test_windows_non_turkish_differences_are_not_taken():
    # Windows ı yerine l okumuş ("kartl"); modelin doğru okuması korunur.
    assert merge.merge_word("kartı", "kartl") == "kartı"
    assert merge.merge_word("limitiniz", "limitinlz") == "limitiniz"


def test_single_misread_letter_is_fixed_in_long_words_only():
    assert merge.merge_word("gubesi", "şubesi") == "şubesi"
    assert merge.merge_word("gul", "şul") == "gul"  # kısa sözcükte riskli
    assert merge.merge_word("abcdef", "şbcdeğ") == "abcdef"  # iki harf farkı: aynı sözcük değil


def test_case_follows_the_rest_of_the_word():
    assert merge.merge_word("IsIK", "IŞIK") == "IŞIK"
    assert merge.merge_word("IşIK", "IŞIK") == "IŞIK"
    assert merge.merge_word("Odeme", "ödeme") == "Ödeme"  # Windows'un küçük harfi alınmaz
    assert merge.merge_word("istanbul", "İstanbul") == "İstanbul"  # i ailesinde Windows'a güvenilir


def test_words_with_digits_or_different_length_are_left_alone():
    assert merge.merge_line("şube column1 çıkış", "şube columnı çıkış") == "şube column1 çıkış"
    assert merge.merge_word("abc", "abcd") == "abc"


def test_punctuation_around_words_is_kept_from_the_model():
    assert merge.merge_line("Açiklama: (kayit) yok.", "Açıklama; (kayıt) yok") == "Açıklama: (kayıt) yok."


def test_lines_are_paired_by_position_not_order():
    model = [_line("çikiş yapin lütfen", 100), _line("güneşli bir gün", 0)]
    windows = [_line("çıkış yapın lütfen", 101), _line("başka bir satır", 300)]
    assert merge.merge(model, windows) == "güneşli bir gün\nçıkış yapın lütfen"


def test_without_windows_lines_model_text_is_returned():
    assert merge.merge([_line("güneșli", 0)], []) == "güneşli"


def test_windows_text_is_used_when_model_found_nothing():
    assert merge.merge([], [_line("yalnızca windows", 0)]) == "yalnızca windows"


# ---- boru hattı ---------------------------------------------------------------
@pytest.fixture
def image():
    img = QImage(40, 20, QImage.Format.Format_ARGB32)
    img.fill(0xFFFFFFFF)
    return img


class _FakeModel:
    def __init__(self, lines):
        self._lines = lines

    def read(self, _image):
        if isinstance(self._lines, Exception):
            raise self._lines
        return self._lines


def _use(monkeypatch, *, model, windows_languages, windows=None):
    monkeypatch.setattr(model_engine, "is_available", lambda: model is not None)
    monkeypatch.setattr(model_engine.ModelOcr, "instance", classmethod(lambda cls: _FakeModel(model)))
    monkeypatch.setattr(pipeline.engine, "available_languages", lambda: list(windows_languages))
    calls = []

    def recognize(_image, language=None):
        calls.append(language)
        if windows is None:
            raise OcrUnavailable("yok")
        return windows

    monkeypatch.setattr(pipeline.engine, "recognize", recognize)
    return calls


def test_pipeline_merges_model_with_turkish_windows(monkeypatch, image):
    win = OcrResult("çıkış yapın lütfen", "tr", (_line("çıkış yapın lütfen", 0),))
    calls = _use(monkeypatch, model=[_line("çikiş yapin lütfen", 0)], windows_languages=["en-US", "tr"], windows=win)
    result = pipeline.read_image(image)
    assert result.text == "çıkış yapın lütfen" and result.language == "model+tr"
    assert calls == ["tr"]


def test_pipeline_uses_model_alone_without_turkish_pack(monkeypatch, image):
    calls = _use(monkeypatch, model=[_line("column1 datatype,", 0)], windows_languages=["en-US"])
    result = pipeline.read_image(image)
    assert result.text == "column1 datatype," and result.language == "model"
    assert calls == []  # İngilizce Windows motoru hiç çağrılmaz
    assert "Türkçe OCR dil paketi yüklü değil" in pipeline.warning()
    assert "Language.OCR" not in pipeline.warning(short=True)


def test_pipeline_falls_back_to_windows_when_model_is_missing(monkeypatch, image):
    win = OcrResult("windows metni", "tr", ())
    calls = _use(monkeypatch, model=None, windows_languages=["tr"], windows=win)
    assert pipeline.read_image(image) is win
    assert calls == [None]


def test_pipeline_falls_back_to_windows_when_model_crashes(monkeypatch, image):
    win = OcrResult("windows metni", "tr", ())
    _use(monkeypatch, model=RuntimeError("bozuk model"), windows_languages=["tr"], windows=win)
    assert pipeline.read_image(image) is win


def test_pipeline_reports_error_when_nothing_works(monkeypatch, image):
    _use(monkeypatch, model=RuntimeError("bozuk model"), windows_languages=[])
    with pytest.raises(OcrError):
        pipeline.read_image(image)


def test_no_warning_when_model_and_turkish_are_present(monkeypatch):
    _use(monkeypatch, model=[], windows_languages=["en-US", "tr"])
    assert pipeline.warning() is None
    assert "otomatik birleştirilir" in pipeline.status()


def test_null_image_is_rejected():
    with pytest.raises(OcrError):
        pipeline.read_image(QImage())


# ---- gerçek model (kuruluysa) -------------------------------------------------
@pytest.mark.skipif(not model_engine.is_available(), reason="yerel OCR modeli kurulu değil")
def test_model_reads_sql_screenshot_exactly():
    # column1'deki 1, satır sonundaki "(" ve "," ile yalnızca noktalama içeren ");" satırı:
    # Windows OCR'ın okuyamadığı, modelin eklenme nedeni olan durumlar.
    ocr = model_engine.ModelOcr.instance()
    try:
        assert merge.merge(ocr.read(QImage(str(FIXTURE))), []) == FIXTURE_TEXT
    finally:
        model_engine.ModelOcr.release()


@pytest.mark.skipif(not model_engine.is_available(), reason="yerel OCR modeli kurulu değil")
def test_model_returns_nothing_for_blank_image():
    img = QImage(300, 120, QImage.Format.Format_ARGB32)
    img.fill(0xFF3478C6)
    try:
        assert model_engine.ModelOcr.instance().read(img) == []
    finally:
        model_engine.ModelOcr.release()


# ---- kutu birleştirme ---------------------------------------------------------
def test_trailing_punctuation_box_joins_its_line():
    # Bulucu satır sonundaki virgülü ayrı kutu vermiş; satırla birleşmeli.
    boxes = [(21, 53, 225, 72), (222, 65, 228, 72), (22, 82, 264, 100)]
    assert model_engine.join_neighbours(boxes, 18) == [(21, 53, 228, 72), (22, 82, 264, 100)]


def test_distant_boxes_on_the_same_row_stay_separate():
    boxes = [(0, 0, 100, 20), (160, 0, 260, 20)]  # sütunlar: aradaki boşluk büyük
    assert model_engine.join_neighbours(boxes, 20) == boxes


def test_missed_part_next_to_a_line_extends_that_line():
    boxes = [(22, 27, 191, 43)]
    assert model_engine.attach_part(boxes, (197, 28, 203, 46, 30), 16) is True
    assert boxes == [(22, 27, 203, 46)]


def test_missed_part_on_another_row_is_not_attached():
    boxes = [(22, 27, 191, 43)]
    assert model_engine.attach_part(boxes, (30, 120, 50, 124, 12), 16) is False
    assert model_engine.attach_part(boxes, (400, 30, 410, 40, 12), 16) is False  # aynı satır, uzak
    assert boxes == [(22, 27, 191, 43)]
