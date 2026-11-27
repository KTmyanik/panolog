import pytest

from panolog.classifier import Category
from panolog.settings import Settings, SettingsStore
from panolog.storage import Repository, connect, normalize_search
from panolog.storage.repository import text_hash


class Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        self.t += 1
        return self.t


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def deleted():
    return []


@pytest.fixture
def repo(clock, deleted):
    return Repository(connect(":memory:"), clock=clock, on_delete=deleted.append)


def add(repo, text, category=Category.TEXT, **kw):
    return repo.add_item(category, text_hash(text), text=text, **kw)


def texts(repo, category=Category.TEXT, query=""):
    return [i.text for i in repo.list_items(category, query)]


def test_newest_first(repo):
    for t in ("a", "b", "c"):
        add(repo, t)
    assert texts(repo) == ["c", "b", "a"]


def test_duplicate_moves_to_top_without_new_row(repo):
    first, created1 = add(repo, "a")
    add(repo, "b")
    again, created2 = add(repo, "a", source_app="excel.exe")
    assert created1 and not created2
    assert again.id == first.id
    assert again.created_at == first.created_at and again.copied_at > first.copied_at
    assert again.source_app == "excel.exe"
    assert texts(repo) == ["a", "b"]
    assert repo.count() == 2


def test_same_content_in_different_categories_is_separate(repo):
    add(repo, "x", Category.TEXT)
    add(repo, "x", Category.LINK)
    assert repo.count(Category.TEXT) == 1 and repo.count(Category.LINK) == 1


def test_categories_are_isolated(repo):
    add(repo, "metin")
    add(repo, "https://a.com", Category.LINK)
    assert texts(repo) == ["metin"]
    assert texts(repo, Category.LINK) == ["https://a.com"]


def test_limit_removes_oldest_unpinned(repo, deleted):
    for t in ("a", "b", "c"):
        add(repo, t, limit=3)
    add(repo, "d", limit=3)
    assert texts(repo) == ["d", "c", "b"]
    assert [i.text for i in deleted] == ["a"]


def test_pinned_survive_limit_and_sort_first(repo):
    a, _ = add(repo, "a", limit=2)
    repo.set_pinned(a.id, True)
    for t in ("b", "c", "d"):
        add(repo, t, limit=2)
    assert texts(repo) == ["a", "d", "c"]
    assert repo.get(a.id).pinned


def test_limit_only_affects_own_category(repo):
    add(repo, "https://a.com", Category.LINK, limit=1)
    add(repo, "a", limit=1)
    add(repo, "b", limit=1)
    assert texts(repo, Category.LINK) == ["https://a.com"]
    assert texts(repo) == ["b"]


def test_search_is_case_and_turkish_insensitive(repo):
    add(repo, "İSTANBUL Şubesi")
    add(repo, "Ankara")
    add(repo, "ISPARTA ılık")
    assert texts(repo, query="istanbul") == ["İSTANBUL Şubesi"]
    assert texts(repo, query="ISTANBUL") == ["İSTANBUL Şubesi"]
    assert texts(repo, query="ılık") == ["ISPARTA ılık"]
    assert texts(repo, query="ısparta") == ["ISPARTA ılık"]
    assert texts(repo, query="yok") == []
    assert normalize_search("Iİıi") == "iiii"


def test_search_treats_wildcards_literally(repo):
    add(repo, "%100 başarı")
    add(repo, "a_b")
    add(repo, "axb")
    assert texts(repo, query="%") == ["%100 başarı"]
    assert texts(repo, query="a_b") == ["a_b"]


def test_delete(repo, deleted):
    a, _ = add(repo, "a")
    assert repo.delete(a.id) is True
    assert repo.delete(a.id) is False
    assert repo.get(a.id) is None
    assert len(deleted) == 1


def test_touch_moves_to_top(repo):
    a, _ = add(repo, "a")
    add(repo, "b")
    repo.touch(a.id)
    assert texts(repo) == ["a", "b"]


def test_purge_older_than_skips_pinned(repo, clock):
    old, _ = add(repo, "eski")
    pinned, _ = add(repo, "sabit")
    repo.set_pinned(pinned.id, True)
    clock.t += 8 * 86400
    add(repo, "yeni")
    assert repo.purge_older_than(7) == 1
    assert texts(repo) == ["sabit", "yeni"]


def test_purge_expired(repo, clock):
    add(repo, "gizli", expires_at=clock.t + 60)
    add(repo, "normal")
    assert repo.purge_expired() == 0
    clock.t += 61
    assert repo.purge_expired() == 1
    assert texts(repo) == ["normal"]


def test_clear_keeps_pinned_unless_asked(repo):
    a, _ = add(repo, "a")
    repo.set_pinned(a.id, True)
    add(repo, "b")
    assert repo.clear() == 1
    assert texts(repo) == ["a"]
    assert repo.clear(include_pinned=True) == 1
    assert repo.count() == 0


def test_image_item_roundtrip(repo):
    item, _ = repo.add_item(
        Category.IMAGE, "h1", image_path="C:/x/h1.png", thumb_path="C:/x/h1_t.png",
        width=10, height=20,
    )
    assert (item.width, item.height) == (10, 20)
    assert repo.image_files() == {"C:/x/h1.png", "C:/x/h1_t.png"}


def test_schema_persists_on_disk(tmp_path):
    path = tmp_path / "t.db"
    conn = connect(path)
    Repository(conn).add_item(Category.TEXT, "h", text="kalıcı")
    conn.close()
    conn = connect(path)  # ikinci açılışta göç tekrar çalışmamalı
    assert [i.text for i in Repository(conn).list_items(Category.TEXT)] == ["kalıcı"]
    conn.close()


def test_settings_roundtrip_and_tolerance(repo):
    store = SettingsStore(repo)
    assert store.load() == Settings()
    s = Settings(retention_days=3, hotkey="Ctrl+Alt+C", auto_paste=False)
    s.limits["text"] = 10
    store.save(s)
    assert store.load() == s
    loaded = Settings.from_dict({"limits": {"text": 5, "bogus": 1}, "unknown": 1, "hotkey": 42})
    assert loaded.limit_for(Category.TEXT) == 5
    assert loaded.limit_for(Category.IMAGE) == 50
    assert loaded.hotkey == "Ctrl+Shift+V"
    repo.set_setting("app", "{bozuk")
    assert store.load() == Settings()


def test_excluded_apps_case_insensitive():
    s = Settings()
    assert s.is_excluded("KeePass.exe")
    assert not s.is_excluded("chrome.exe")
    assert not s.is_excluded(None)


# ---- Dosyalar kategorisi ----------------------------------------------------
from panolog.storage import FileRef  # noqa: E402
from panolog.storage.repository import files_hash  # noqa: E402


def test_file_item_roundtrip_and_search_by_name(repo):
    files = [FileRef(r"C:\Raporlar\Bütçe 2026.xlsx", 2048), FileRef(r"C:\Raporlar\Arşiv", None, True)]
    item, created = repo.add_item(Category.FILE, files_hash(f.path for f in files), files=files)
    assert created and item.files == tuple(files)
    assert item.files[0].name == "Bütçe 2026.xlsx" and item.files[1].is_dir
    found = lambda q: len(repo.list_items(Category.FILE, q))  # noqa: E731
    assert found("bütçe") == 1 and found("ARŞİV") == 1
    assert found("raporlar") == 0  # klasör yolu değil, yalnızca adlar aranır
    assert repo.list_items(Category.TEXT) == []


def test_files_hash_ignores_order_and_case():
    a = files_hash([r"C:\x\A.txt", r"C:\x\b.txt"])
    assert a == files_hash([r"c:\X\b.TXT", r"C:\x\a.txt"])
    assert a == files_hash([r"C:\x\.\A.txt", r"C:/x/b.txt"])
    assert a != files_hash([r"C:\x\A.txt"])


def test_same_files_copied_again_move_to_top(repo):
    one = [FileRef(r"C:\a.txt", 1)]
    two = [FileRef(r"C:\b.txt", 1)]
    first, _ = repo.add_item(Category.FILE, files_hash([r"C:\a.txt"]), files=one)
    repo.add_item(Category.FILE, files_hash([r"C:\b.txt"]), files=two)
    again, created = repo.add_item(Category.FILE, files_hash([r"c:\A.TXT"]), files=one)
    assert not created and again.id == first.id
    assert [i.files[0].name for i in repo.list_items(Category.FILE)] == ["a.txt", "b.txt"]


def test_fileref_from_path(tmp_path):
    f = tmp_path / "veri.csv"
    f.write_bytes(b"12345")
    ref = FileRef.from_path(str(f))
    assert (ref.name, ref.size, ref.is_dir) == ("veri.csv", 5, False)
    d = FileRef.from_path(str(tmp_path))
    assert d.is_dir and d.size is None
    missing = FileRef.from_path(str(tmp_path / "yok.txt"))
    assert missing.size is None and not missing.is_dir


def test_migration_from_v1_database(tmp_path):
    import sqlite3

    from panolog.storage.db import _MIGRATIONS

    path = tmp_path / "v1.db"
    old = sqlite3.connect(path)
    old.executescript(_MIGRATIONS[0])
    old.execute("PRAGMA user_version = 1")
    old.execute(
        "INSERT INTO items (category, content_hash, text, search_text, created_at, copied_at)"
        " VALUES ('text', 'h', 'eski kayıt', 'eski kayit', 1, 1)"
    )
    old.commit()
    old.close()
    conn = connect(path)
    r = Repository(conn)
    assert [i.text for i in r.list_items(Category.TEXT)] == ["eski kayıt"]
    assert r.list_items(Category.TEXT)[0].files == ()
    r.add_item(Category.FILE, "fh", files=[FileRef(r"C:\a.txt", 1)])
    assert r.count(Category.FILE) == 1
    conn.close()
