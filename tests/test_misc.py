import pytest

from panolog import winapi
from panolog.hotkey import HotkeyError, parse_hotkey
from panolog.ui.formatting import app_label, preview_lines, relative_time


def test_parse_hotkey():
    assert parse_hotkey("Ctrl+Shift+V") == (winapi.MOD_CONTROL | winapi.MOD_SHIFT, 0x56)
    assert parse_hotkey("ctrl + alt + f5") == (winapi.MOD_CONTROL | winapi.MOD_ALT, 0x74)
    assert parse_hotkey("Meta+1") == (winapi.MOD_WIN, 0x31)
    assert parse_hotkey("Alt+Space") == (winapi.MOD_ALT, 0x20)
    assert parse_hotkey("Ctrl++") == (winapi.MOD_CONTROL, 0xBB)


@pytest.mark.parametrize("bad", ["", "V", "Ctrl+", "Ctrl+Shift", "Ctrl+A+B", "Ctrl+Ğ", "Ctrl+F99"])
def test_parse_hotkey_rejects(bad):
    with pytest.raises(HotkeyError):
        parse_hotkey(bad)


def test_relative_time():
    now = 1_700_000_000.0
    assert relative_time(now - 5, now) == "az önce"
    assert relative_time(now - 125, now) == "2 dk önce"
    assert relative_time(now - 2 * 3600, now) == "2 sa önce"
    assert relative_time(now - 3 * 86400, now).startswith("3 gün önce")
    assert relative_time(now + 50, now) == "az önce"  # saat geri alınmışsa


def test_preview_lines():
    assert preview_lines("\n\n  ilk \n\nikinci\nüçüncü") == ["ilk", "ikinci …"]
    assert preview_lines("tek") == ["tek"]
    assert preview_lines("") == [""]
    assert preview_lines("x" * 500, max_chars=10) == ["x" * 10 + "…"]


def test_app_label():
    assert app_label("chrome.exe") == "chrome"
    assert app_label("EXCEL.EXE") == "EXCEL"
    assert app_label(None) == ""


def test_human_size():
    from panolog.ui.formatting import human_size

    assert human_size(0) == "0 B"
    assert human_size(1023) == "1023 B"
    assert human_size(1536) == "1,5 KB"
    assert human_size(5 * 1024**2) == "5,0 MB"
    assert human_size(3 * 1024**4) == "3072,0 GB"


def test_files_title_and_detail():
    from panolog.storage import FileRef
    from panolog.ui.formatting import files_detail, files_title

    assert files_title(["a.txt"]) == "a.txt"
    assert files_title(["a.txt", "b.txt", "c"]) == "a.txt  +2 öğe daha"
    assert files_detail([FileRef(r"C:\a.txt", 2048)]) == "2,0 KB"
    assert files_detail([FileRef(r"C:\d", None, True)]) == "Klasör"
    assert files_detail([FileRef(r"C:\yok.txt")]) == "boyut bilinmiyor"
    mixed = [FileRef(r"C:\a", 1024), FileRef(r"C:\b", 1024), FileRef(r"C:\d", None, True)]
    assert files_detail(mixed) == "3 öğe, 2,0 KB + 1 klasör"
    assert files_detail([FileRef(r"C:\d", None, True), FileRef(r"C:\e", None, True)]) == "2 öğe + 2 klasör"


# ---- eski addan (Clipboarder) veri taşıma ------------------------------------
def _legacy_home(base):
    import sqlite3

    from panolog.storage import db

    old = base / "Clipboarder"
    (old / "images").mkdir(parents=True)
    (old / "images" / "abc.png").write_bytes(b"png")
    (old / "images" / "abc_t.png").write_bytes(b"png")
    conn = sqlite3.connect(old / "clipboarder.db")
    conn.execute("PRAGMA journal_mode = WAL")
    for script in db._MIGRATIONS:
        conn.executescript(script)
    conn.execute(f"PRAGMA user_version = {len(db._MIGRATIONS)}")
    conn.execute(
        "INSERT INTO items (category, content_hash, image_path, thumb_path, created_at, copied_at)"
        " VALUES ('image', 'abc', ?, ?, 1, 1)",
        (str(old / "images" / "abc.png"), str(old / "images" / "abc_t.png")),
    )
    conn.execute(
        "INSERT INTO items (category, content_hash, text, search_text, created_at, copied_at)"
        " VALUES ('text', 't', 'merhaba', 'merhaba', 2, 2)"
    )
    conn.commit()
    conn.close()
    return old


def test_legacy_data_is_moved_and_image_paths_follow(tmp_path):
    from panolog import paths
    from panolog.classifier import Category
    from panolog.storage import Repository, connect

    old = _legacy_home(tmp_path)
    assert paths.migrate_legacy_data(tmp_path) is True
    new = tmp_path / "Panolog"
    assert not old.exists()
    assert (new / "panolog.db").is_file() and not (new / "clipboarder.db").exists()
    repo = Repository(connect(new / "panolog.db"))
    image = repo.list_items(Category.IMAGE)[0]
    assert image.image_path == str(new / "images" / "abc.png")
    assert image.thumb_path == str(new / "images" / "abc_t.png")
    import os

    assert os.path.isfile(image.image_path) and os.path.isfile(image.thumb_path)
    assert [i.text for i in repo.list_items(Category.TEXT)] == ["merhaba"]


def test_legacy_migration_runs_only_once_and_never_overwrites(tmp_path):
    from panolog import paths

    assert paths.migrate_legacy_data(tmp_path) is False  # eski veri yok
    _legacy_home(tmp_path)
    new = tmp_path / "Panolog"
    new.mkdir()
    (new / "panolog.db").write_bytes(b"mevcut")
    assert paths.migrate_legacy_data(tmp_path) is False  # yeni veri varsa dokunma
    assert (new / "panolog.db").read_bytes() == b"mevcut"
    assert (tmp_path / "Clipboarder" / "clipboarder.db").is_file()


def test_legacy_migration_into_empty_new_folder(tmp_path):
    from panolog import paths

    _legacy_home(tmp_path)
    (tmp_path / "Panolog").mkdir()  # uygulama klasörü boş oluşturmuş olabilir
    assert paths.migrate_legacy_data(tmp_path) is True
    assert (tmp_path / "Panolog" / "panolog.db").is_file()


def test_legacy_migration_refuses_non_empty_new_folder_without_db(tmp_path):
    import pytest

    from panolog import paths

    _legacy_home(tmp_path)
    (tmp_path / "Panolog").mkdir()
    (tmp_path / "Panolog" / "baska.txt").write_text("x")
    with pytest.raises(paths.LegacyMigrationError):
        paths.migrate_legacy_data(tmp_path)
    assert (tmp_path / "Clipboarder" / "clipboarder.db").is_file()  # eski veri yerinde
