from PySide6.QtCore import QSize

from panolog.settings import Settings
from panolog.ui import themes
from panolog.ui.themes import THEMES, get_theme, note_angle, note_content_size


def test_known_themes_and_fallback():
    assert list(THEMES) == ["classic", "aurora", "paper", "brutal"]
    assert get_theme("paper").key == "paper"
    # Bilinmeyen ya da boş anahtar (ör. kaldırılmış bir tema) uygulamayı bozmaz.
    assert get_theme("yok").key == "classic"
    assert get_theme(None).key == "classic" and get_theme("").key == "classic"


def test_every_theme_is_complete():
    for theme in THEMES.values():
        assert theme.label and theme.qss.strip() and "#preview" in theme.preview_qss
        assert theme.rows in ("list", "cards", "notes")
        assert theme.backdrop in ("qss", "aurora", "cork", "brutal")
        assert len(theme.row_margins) == 4 and theme.text_lines >= 1
        # Liste öğesinin ve metinlerin rengi her temada tanımlı olmalı (okunmaz yazı olmasın).
        for selector in ("QLabel", "QLineEdit", "QTabBar::tab", "QListWidget", "#meta"):
            assert selector in theme.qss or selector in theme.row_qss, (theme.key, selector)
    assert THEMES["paper"].row_qss.strip()  # notlar kendi stil sayfasıyla çizilir
    assert [t.key for t in THEMES.values() if t.animated] == ["aurora"]
    assert [t.key for t in THEMES.values() if t.glass] == ["aurora"]


def test_only_classic_uses_stylesheet_background():
    assert "#popup" in THEMES["classic"].qss
    for key in ("aurora", "paper", "brutal"):
        assert THEMES[key].backdrop != "qss"


def test_note_angle_is_stable_small_and_never_flat():
    angles = [note_angle(seed) for seed in range(1, 200)]
    assert all(0.9 <= abs(a) <= 2.4 for a in angles)
    assert note_angle(42) == note_angle(42)
    assert any(a > 0 for a in angles) and any(a < 0 for a in angles)


def test_note_content_fits_inside_cell():
    cell = QSize(223, 142)
    size = note_content_size(cell)
    assert 0 < size.width() < cell.width() and 0 < size.height() < cell.height()


def test_aurora_blobs_move_but_stay_near_their_place():
    start, later = themes.aurora_blob_centers(0.0), themes.aurora_blob_centers(5.0)
    assert start != later
    for t in (0.0, 3.3, 60.0, 9999.0):
        for (_c, cx, cy, _r, _p), (x, y) in zip(themes.AURORA_BLOBS, themes.aurora_blob_centers(t)):
            assert abs(x - cx) <= 0.07 + 1e-9 and abs(y - cy) <= 0.06 + 1e-9


def test_settings_theme_defaults_and_roundtrip():
    s = Settings()
    assert (s.theme, s.animations) == ("classic", True)
    s.theme, s.animations = "brutal", False
    again = Settings.from_dict(s.to_dict())
    assert (again.theme, again.animations) == ("brutal", False)
    # Eski kayıtlarda bu alanlar yoktur; tür yanlışsa da varsayılan kalır.
    assert Settings.from_dict({}).theme == "classic"
    assert Settings.from_dict({"theme": 5, "animations": "evet"}).theme == "classic"
    assert Settings.from_dict({"theme": 5, "animations": "evet"}).animations is True
