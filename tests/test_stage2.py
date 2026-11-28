"""Etiketler, sayaçlar, kurallar, yedekleme, link başlığı ayrıştırma ve çizim araçları."""
import json
from datetime import date

import pytest
from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QColor, QImage

from panolog import backup, imaging, linkmeta
from panolog.classifier import Category
from panolog.settings import Settings
from panolog.settings.schema import clean_rules
from panolog.storage import Repository, connect
from panolog.storage.images import ImageStore, hash_image
from panolog.storage.models import FileRef
from panolog.storage.repository import clean_tag, split_tag_query, text_hash
from panolog.ui.image_editor import EditSession
from panolog.ui.stats_dialog import day_range, nice_max

RED = imaging.MARK_COLOR.rgb()


@pytest.fixture
def repo():
    return Repository(connect(":memory:"))


def add_text(repo, text, category=Category.TEXT, **kw):
    return repo.add_item(category, text_hash(text), text=text, **kw)[0]


# ---- etiketler ----------------------------------------------------------------
def test_tag_helpers():
    assert split_tag_query("#uat sorgu") == ("uat", "sorgu")
    assert split_tag_query("  #UAT") == ("uat", "")
    assert split_tag_query("#") == ("", "")
    assert split_tag_query("düz arama") == (None, "düz arama")
    assert clean_tag("  #UAT   testleri ") == "UAT testleri"
    assert clean_tag("") is None and clean_tag("##") is None and clean_tag(None) is None
    assert len(clean_tag("x" * 100)) == 40


def test_tagging_pins_and_filters(repo):
    a, b, c = (add_text(repo, t) for t in ("müşteri sorgusu", "hesap sorgusu", "not"))
    repo.set_expiry(a.id, 9e12)
    assert repo.set_tag([a.id, b.id], "#uat") == 2
    tagged = repo.get(a.id)
    assert (tagged.tag, tagged.pinned, tagged.expires_at) == ("uat", True, None)
    assert {i.id for i in repo.list_items(Category.TEXT, "#uat")} == {a.id, b.id}
    assert {i.id for i in repo.list_items(Category.TEXT, "#UA")} == {a.id, b.id}  # önek, harf duyarsız
    assert [i.id for i in repo.list_items(Category.TEXT, "#uat müşteri")] == [a.id]
    assert {i.id for i in repo.list_items(Category.TEXT, "#")} == {a.id, b.id}
    assert repo.list_items(Category.TEXT, "#yok") == []
    assert len(repo.list_items(Category.TEXT)) == 3
    assert c.id in {i.id for i in repo.list_items(Category.TEXT, "not")}


def test_tags_listing_and_removal(repo):
    a, b = add_text(repo, "a"), add_text(repo, "b")
    link = add_text(repo, "https://x.com", Category.LINK)
    repo.set_tag([a.id], "zeta")
    repo.set_tag([b.id, link.id], "Alfa")
    assert repo.tags() == [("Alfa", 2), ("zeta", 1)]
    assert repo.tags(Category.LINK) == [("Alfa", 1)]
    repo.set_tag([a.id], "")
    cleared = repo.get(a.id)
    assert cleared.tag is None and cleared.pinned  # etiket kalkar, sabitleme kalır
    assert repo.tags() == [("Alfa", 2)]


def test_set_expiry_skips_pinned(repo):
    a, b = add_text(repo, "a"), add_text(repo, "b")
    repo.set_pinned(a.id, True)
    repo.set_expiry(a.id, 5.0)
    repo.set_expiry(b.id, 5.0)
    assert repo.get(a.id).expires_at is None and repo.get(b.id).expires_at == 5.0


# ---- kod kategorisi --------------------------------------------------------------
def test_kind_is_stored_and_reclassify(repo):
    code = repo.add_item(Category.CODE, text_hash("SELECT 1"), text="SELECT 1", kind="sql")[0]
    assert code.kind == "sql" and repo.list_items(Category.CODE)[0].id == code.id
    plain = add_text(repo, "SELECT * FROM t")
    assert repo.reclassify(plain.id, Category.CODE, "sql")
    moved = repo.get(plain.id)
    assert (moved.category, moved.kind) == (Category.CODE, "sql")
    # hedef kategoride aynı içerik varsa taşınmaz, hata da vermez
    dup = add_text(repo, "SELECT 1")
    assert not repo.reclassify(dup.id, Category.CODE, "sql")
    assert repo.get(dup.id).category is Category.TEXT


# ---- sayaçlar -----------------------------------------------------------------------
def test_stats_count_without_content(repo):
    for _ in range(3):
        repo.bump_stat(Category.TEXT, "EXCEL.EXE", "2026-11-27")
    repo.bump_stat(Category.IMAGE, "snippingtool.exe", "2026-11-27")
    repo.bump_stat(Category.TEXT, None, "2026-11-26")
    repo.bump_stat(Category.TEXT, "excel.exe", "2026-11-01")
    assert repo.stats_by_day("2026-11-20") == {"2026-11-27": 4, "2026-11-26": 1}
    assert repo.stats_by_app("2026-11-20") == [("excel.exe", 3), ("", 1), ("snippingtool.exe", 1)]
    assert repo.stats_by_category("2026-11-20") == {"text": 4, "image": 1}
    assert repo.stats_by_app("2026-11-01", limit=1) == [("excel.exe", 4)]
    columns = [r[1] for r in repo._conn.execute("PRAGMA table_info(stats)")]
    assert columns == ["day", "category", "app", "count"]  # içerik sütunu yok
    repo.clear_stats()
    assert repo.stats_by_day("2000-01-01") == {}


def test_known_apps_merges_history_and_stats(repo):
    add_text(repo, "a", source_app="Chrome.exe")
    repo.bump_stat(Category.TEXT, "excel.exe", "2026-11-27")
    assert repo.known_apps() == ["chrome.exe", "excel.exe"]


def test_stats_helpers():
    days = day_range(date(2026, 11, 27), 14)
    assert len(days) == 14 and days[0] == date(2026, 11, 14) and days[-1] == date(2026, 11, 27)
    assert [nice_max(v) for v in (0, 3, 5, 6, 10, 11, 37, 50, 51, 180, 999)] == [
        5, 5, 5, 10, 10, 20, 50, 50, 100, 200, 1000,
    ]  # fmt: skip


# ---- kurallar -----------------------------------------------------------------------
def test_no_rules_by_default():
    s = Settings()
    assert s.rules == [] and s.rule_for("excel.exe") is None and s.rule_for(None) is None
    assert s.link_fetch is False  # ağ özelliği varsayılan kapalı


def test_clean_rules_validates():
    rules = clean_rules(
        [
            {"app": " Excel.EXE ", "action": "skip", "value": "yok sayılır"},
            {"app": "teams.exe", "action": "tag", "value": " toplantı "},
            {"app": "notepad.exe", "action": "expire", "value": "30"},
            {"app": "excel.exe", "action": "tag", "value": "ikinci kural"},  # aynı uygulama
            {"app": "", "action": "skip"},
            {"app": "a.exe", "action": "bilinmeyen"},
            {"app": "b.exe", "action": "tag", "value": ""},
            {"app": "c.exe", "action": "expire", "value": "sıfır"},
            {"app": "d.exe", "action": "expire", "value": "0"},
            "bozuk",
        ]
    )
    assert rules == [
        {"app": "excel.exe", "action": "skip", "value": ""},
        {"app": "teams.exe", "action": "tag", "value": "toplantı"},
        {"app": "notepad.exe", "action": "expire", "value": "30"},
    ]
    assert clean_rules("liste değil") == []


def test_rules_roundtrip_and_lookup():
    s = Settings()
    s.rules = [{"app": "excel.exe", "action": "tag", "value": "rapor"}]
    s.seq_hotkey, s.join_separator = "Ctrl+Alt+B", ", "
    again = Settings.from_dict(json.loads(json.dumps(s.to_dict())))
    assert again.rule_for("EXCEL.EXE") == {"app": "excel.exe", "action": "tag", "value": "rapor"}
    assert again.rule_for("word.exe") is None
    assert (again.seq_hotkey, again.join_separator) == ("Ctrl+Alt+B", ", ")
    assert Settings.from_dict({"rules": [{"app": "x.exe", "action": "sil"}]}).rules == []


# ---- yedekleme ------------------------------------------------------------------------
def test_export_import_roundtrip(tmp_path, repo):
    images = ImageStore(tmp_path / "img")
    (tmp_path / "img").mkdir()
    sql = repo.add_item(Category.CODE, text_hash("SELECT 1"), text="SELECT 1", kind="sql",
                        source_app="dbeaver.exe")[0]
    repo.set_tag([sql.id], "uat")
    add_text(repo, "düz ```çitli``` metin")
    link = add_text(repo, "https://example.com/a", Category.LINK)
    repo.set_link_meta(link.id, "Örnek [sayfa]", None)
    repo.add_item(Category.FILE, "h", files=[FileRef(r"C:\tmp\a.txt", 5, False)])
    picture = QImage(30, 20, QImage.Format.Format_ARGB32)
    picture.fill(QColor("#336699"))
    digest = hash_image(picture)
    full, thumb = images.save(picture, digest)
    images.wait()
    repo.add_item(Category.IMAGE, digest, image_path=str(full), thumb_path=str(thumb),
                  width=30, height=20)
    temp = add_text(repo, "süreli")
    repo.set_expiry(temp.id, 9e12)

    target = tmp_path / "yedek.json"
    assert backup.export_json(repo.all_items(), target) == 5  # süreli öğe yedeğe girmez
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["app"] == "Panolog" and "süreli" not in target.read_text(encoding="utf-8")
    assert (tmp_path / "yedek_gorseller").is_dir()

    other = Repository(connect(":memory:"))
    other_images = ImageStore(tmp_path / "img2")
    (tmp_path / "img2").mkdir()
    assert backup.import_json(target, other, other_images) == (5, 0)
    restored = other.list_items(Category.CODE)[0]
    assert (restored.text, restored.kind, restored.tag, restored.pinned, restored.source_app) == (
        "SELECT 1", "sql", "uat", True, "dbeaver.exe",
    )  # fmt: skip
    assert restored.copied_at == repo.get(sql.id).copied_at
    assert other.list_items(Category.LINK)[0].link_title == "Örnek [sayfa]"
    assert other.list_items(Category.FILE)[0].files[0].path == r"C:\tmp\a.txt"
    img = other.list_items(Category.IMAGE)[0]
    assert QImage(img.image_path).pixel(5, 5) == picture.pixel(5, 5)
    assert backup.import_json(target, other, other_images) == (0, 5)  # ikinci kez: hepsi var


def test_import_rejects_non_backups(tmp_path, repo):
    images = ImageStore(tmp_path)
    for name, content in (("a.json", "bozuk"), ("b.json", '{"snippets": []}'), ("c.json", "[1]")):
        (tmp_path / name).write_text(content, encoding="utf-8")
        with pytest.raises(backup.BackupError):
            backup.import_json(tmp_path / name, repo, images)
    with pytest.raises(backup.BackupError):
        backup.import_json(tmp_path / "yok.json", repo, images)
    (tmp_path / "d.json").write_text(
        json.dumps({"items": [{"category": "uzay"}, {"category": "text", "text": " "}, 5,
                              {"category": "image", "image": "yok.png"}]}), encoding="utf-8")
    assert backup.import_json(tmp_path / "d.json", repo, images) == (0, 0)


def test_markdown_export(tmp_path, repo):
    repo.add_item(Category.CODE, text_hash("SELECT 1"), text="SELECT 1", kind="sql")
    add_text(repo, "içinde ``` üç ters tırnak var")
    link = add_text(repo, "https://example.com/a?b=1", Category.LINK)
    repo.set_link_meta(link.id, "Örnek [sayfa]", None)
    target = tmp_path / "gecmis.md"
    assert backup.export_markdown(repo.all_items(), target) == 3
    text = target.read_text(encoding="utf-8")
    assert text.startswith("# Panolog geçmişi") and "## Kod" in text and "```sql\nSELECT 1\n```" in text
    assert "````\niçinde ``` üç ters tırnak var\n````" in text  # çit içerikten uzun
    assert "[Örnek (sayfa)](<https://example.com/a?b=1>)" in text


# ---- link başlığı ----------------------------------------------------------------------
@pytest.mark.parametrize(
    "url, ok",
    [
        ("https://example.com/a", True),
        ("http://sub.example.co.uk", True),
        ("https://93.184.216.34/", True),
        ("ftp://example.com", False),
        ("https://intranet/portal", False),
        ("https://localhost:8080", False),
        ("https://127.0.0.1/x", False),
        ("https://10.1.2.3/x", False),
        ("https://192.168.1.5", False),
        ("https://sunucu.local/x", False),
        ("https://portal.banka.corp/x", False),
        ("https://kullanici:parola@example.com", False),
        ("metin", False),
        ("", False),
    ],
)
def test_is_fetchable_only_public_web(url, ok):
    assert linkmeta.is_fetchable(url) is ok


def test_parse_title_and_icon():
    page = (
        '<html><head><TITLE>\n  Çay &amp; <b>Kahve</b>  \n</TITLE>'
        '<link rel="stylesheet" href="a.css"><link rel="shortcut icon" href="/img/fav.png">'
        "</head></html>"
    )
    assert linkmeta.parse_title(page) == "Çay & Kahve"
    assert linkmeta.parse_title("<html></html>") is None
    assert linkmeta.parse_title("<title>" + "x" * 500 + "</title>") == "x" * 200
    assert linkmeta.parse_icon_url(page, "https://a.com/b/c") == "https://a.com/img/fav.png"
    assert linkmeta.parse_icon_url("<html></html>", "https://a.com/b/c") == "https://a.com/favicon.ico"
    assert linkmeta.decode_page("çay".encode("cp1254"), "windows-1254") == "çay"
    assert linkmeta.decode_page(b'<meta charset="utf-8">\xc3\xa7', None).endswith("ç")
    assert linkmeta.decode_page(b"abc", "uydurma-kodlama") == "abc"


def test_fetch_refuses_private_addresses_without_network(monkeypatch):
    called = []
    monkeypatch.setattr(linkmeta, "_get", lambda *a: called.append(a))
    monkeypatch.setattr(linkmeta, "_resolves_to_public", lambda host: called.append(host) or False)
    assert linkmeta.fetch("https://intranet/portal") == (None, None)
    assert called == []  # yerel adres için DNS sorgusu bile yapılmaz
    assert linkmeta.fetch("https://example.com") == (None, None)  # özel adrese çözülüyor
    assert called == ["example.com"]


def test_fetch_parses_page_with_fake_network(monkeypatch):
    pages = {
        "https://example.com/a": (b"<title>Merhaba</title><link rel='icon' href='i.png'>", "utf-8"),
        "https://example.com/i.png": (b"\x89PNG....", None),
    }
    monkeypatch.setattr(linkmeta, "_resolves_to_public", lambda host: True)
    monkeypatch.setattr(linkmeta, "_get", lambda url, limit: (*pages[url], url))
    assert linkmeta.fetch("https://example.com/a") == ("Merhaba", b"\x89PNG....")


# ---- kutu ve ok ------------------------------------------------------------------------
def white(w=200, h=120):
    img = QImage(w, h, QImage.Format.Format_ARGB32)
    img.fill(QColor("#ffffff"))
    return img


def test_box_draws_frame_and_keeps_inside():
    src = white()
    out = imaging.box(src, QRect(40, 30, 100, 60), width=4)
    assert out.pixel(41, 60) == RED and out.pixel(138, 60) == RED and out.pixel(90, 31) == RED
    assert out.pixel(90, 60) == 0xFFFFFFFF  # içi dokunulmadı
    assert out.pixel(10, 10) == 0xFFFFFFFF and src.pixel(41, 60) == 0xFFFFFFFF
    assert imaging.box(src, QRect(500, 500, 10, 10)) == src


def test_arrow_points_to_the_end():
    out = imaging.arrow(white(), QPoint(20, 60), QPoint(180, 60), width=4)
    assert out.pixel(100, 60) == RED  # gövde
    assert out.pixel(170, 60) == RED and out.pixel(164, 64) == RED  # ok başı gövdeden geniş
    assert out.pixel(140, 64) == 0xFFFFFFFF  # gövde o kadar geniş değil
    assert out.pixel(30, 68) == 0xFFFFFFFF  # başlangıç ucunda ok başı yok
    assert out.pixel(100, 20) == 0xFFFFFFFF
    assert imaging.arrow(white(), QPoint(5, 5), QPoint(5, 5)) == white()
    assert imaging.mark_width(white(1600, 900)) > imaging.mark_width(white()) == 3


def test_session_line_tool_and_undo():
    s = EditSession(white())
    assert not s.apply_line(imaging.arrow, QPoint(5, 5), QPoint(6, 5))  # yanlışlıkla tıklama
    assert s.apply_line(imaging.arrow, QPoint(20, 60), QPoint(180, 60))
    assert s.modified and s.image.pixel(100, 60) == RED
    assert s.undo() and s.image == white()
