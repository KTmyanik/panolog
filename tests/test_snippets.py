import json
from datetime import datetime

import pytest

from panolog.classifier import Category
from panolog.snippets import SnippetError, SnippetRepository, expand
from panolog.snippets import io_json
from panolog.snippets.variables import uses_clipboard
from panolog.storage import Repository, connect

NOW = datetime(2026, 11, 27, 9, 5)


@pytest.fixture
def conn():
    return connect(":memory:")


@pytest.fixture
def repo(conn):
    return SnippetRepository(conn)


# ---- değişkenler ------------------------------------------------------------
def test_expand_date_time_clipboard():
    out = expand("Tarih {tarih} saat {saat}: {pano}", now=NOW, clipboard_text="INC-42")
    assert out == "Tarih 27.11.2026 saat 09:05: INC-42"


def test_expand_repeats_and_unknown_placeholders():
    assert expand("{tarih} / {tarih}", now=NOW) == "27.11.2026 / 27.11.2026"
    assert expand("{isim} {TARIH} {} {{tarih}}", now=NOW) == "{isim} {TARIH} {} {27.11.2026}"
    assert expand("düz metin", now=NOW) == "düz metin"


def test_expand_does_not_reinterpret_clipboard_content():
    assert expand("> {pano}", now=NOW, clipboard_text="{tarih} {pano}") == "> {tarih} {pano}"


def test_expand_empty_clipboard_and_json_braces():
    assert expand('{"k": "{pano}"}', now=NOW) == '{"k": ""}'
    assert uses_clipboard("x {pano}") and not uses_clipboard("x {tarih}")


# ---- depo -------------------------------------------------------------------
def test_add_get_update_delete(repo):
    s = repo.add("  İmza ", "Saygılarımla,\nAd Soyad", " ;imza ", " e-posta ")
    assert (s.name, s.shortcode, s.tag) == ("İmza", ";imza", "e-posta")
    assert repo.get(s.id) == s and repo.by_shortcode(";imza") == s
    u = repo.update(s.id, "İmza (kısa)", "Sevgiler", "", "")
    assert (u.name, u.content, u.shortcode, u.tag) == ("İmza (kısa)", "Sevgiler", None, None)
    assert repo.delete(s.id) and not repo.delete(s.id)
    assert repo.count() == 0


@pytest.mark.parametrize(
    "name, content, shortcode",
    [("", "x", None), ("  ", "x", None), ("ad", "", None), ("ad", " \n", None), ("ad", "x", "; imza")],
)
def test_validation(repo, name, content, shortcode):
    with pytest.raises(SnippetError):
        repo.add(name, content, shortcode)
    assert repo.count() == 0


def test_shortcode_must_be_unique(repo):
    a = repo.add("A", "x", ";kod")
    with pytest.raises(SnippetError):
        repo.add("B", "y", ";kod")
    b = repo.add("B", "y", ";diger")
    with pytest.raises(SnippetError):
        repo.update(b.id, "B", "y", ";kod")
    repo.update(a.id, "A2", "x", ";kod")  # kendi kodunu koruyabilir
    repo.add("C", "z")
    repo.add("D", "z")  # kısa kodsuz birden çok şablon olabilir


def test_list_sorted_by_name_and_search(repo):
    repo.add("Şablon Z", "içerik", ";z")
    repo.add("adres", "İstiklal Cad. No:1", ";adr", "iletişim")
    repo.add("İmza", "Saygılarımla", ";imza", "e-posta")
    assert [s.name for s in repo.list()] == ["adres", "İmza", "Şablon Z"]
    assert [s.name for s in repo.list("IMZA")] == ["İmza"]
    assert [s.name for s in repo.list("istiklal")] == ["adres"]  # içerikte
    assert [s.name for s in repo.list("e-posta")] == ["İmza"]  # etikette
    assert [s.name for s in repo.list(";adr")] == ["adres"]  # kısa kodda
    assert repo.list("yok") == []


def test_exact_shortcode_match_comes_first(repo):
    repo.add("Aaa imza uzun", "x", ";imza2")
    repo.add("Zzz imza", "y", ";imza")
    assert [s.shortcode for s in repo.list(";imza")] == [";imza", ";imza2"]


def test_snippets_survive_history_clear_and_cleanup(conn, repo):
    history = Repository(conn)
    history.add_item(Category.TEXT, "h", text="geçmiş")
    repo.add("kalıcı", "x")
    history.clear(include_pinned=True)
    history.purge_older_than(0)
    history.enforce_limit(Category.TEXT, 0)
    assert history.count() == 0 and repo.count() == 1


# ---- JSON içe/dışa aktarma --------------------------------------------------
def test_export_import_roundtrip(repo):
    repo.add("İmza", "Saygılarımla,\n{tarih}", ";imza", "e-posta")
    repo.add("Kodsuz", "içerik")
    raw = io_json.dumps(repo.list())
    data = json.loads(raw)
    assert data["version"] == 1 and len(data["snippets"]) == 2
    assert "İmza" in raw  # ensure_ascii kapalı: Türkçe karakterler okunur kalır

    other = SnippetRepository(connect(":memory:"))
    assert other.import_many(io_json.loads(raw)) == (2, 0, 0)
    assert [(s.name, s.shortcode, s.content, s.tag) for s in other.list()] == [
        (s.name, s.shortcode, s.content, s.tag) for s in repo.list()
    ]
    assert other.import_many(io_json.loads(raw)) == (0, 0, 2)  # tekrar: hepsi zaten var


def test_import_updates_by_shortcode(repo):
    repo.add("İmza", "eski", ";imza")
    entries = [
        {"name": "İmza v2", "content": "yeni", "shortcode": ";imza", "tag": None},
        {"name": "Yeni", "content": "x", "shortcode": None, "tag": "t"},
    ]
    assert repo.import_many(entries) == (1, 1, 0)
    assert repo.by_shortcode(";imza").content == "yeni"
    assert repo.count() == 2


def test_import_accepts_bare_list():
    assert io_json.loads('[{"name": "a", "content": "b"}]') == [
        {"name": "a", "content": "b", "shortcode": None, "tag": None}
    ]


@pytest.mark.parametrize(
    "raw",
    [
        "bozuk json",
        '{"x": 1}',
        '{"snippets": "değil"}',
        '{"snippets": [1]}',
        '{"snippets": [{"content": "x"}]}',
        '{"snippets": [{"name": "a"}]}',
        '{"snippets": [{"name": "a", "content": "  "}]}',
        '{"snippets": [{"name": "a", "content": "b", "shortcode": 5}]}',
        '{"snippets": [{"name": "a", "content": "b", "shortcode": "; x"}]}',
    ],
)
def test_import_rejects_invalid(raw):
    with pytest.raises(SnippetError):
        io_json.loads(raw)
