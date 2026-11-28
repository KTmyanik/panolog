import pytest

from panolog import codekind, transforms
from panolog.classifier import Category, classify_text
from panolog.transforms import TransformError

SQL = [
    "SELECT * FROM musteri",
    "select m.ad, h.bakiye\nfrom musteri m\njoin hesap h on h.mno = m.mno\nwhere m.sube = 34;",
    "-- müşteri listesi\nSELECT id FROM t;",
    "INSERT INTO log (id, mesaj) VALUES (1, 'x')",
    "UPDATE hesap SET durum = 'K' WHERE id = 5",
    "delete from gecici where tarih < sysdate - 7",
    "CREATE TABLE Persons (\n  PersonID int,\n  LastName varchar(255)\n);",
    "ALTER TABLE musteri ADD COLUMN eposta VARCHAR(100)",
    "WITH son AS (SELECT 1 FROM dual) SELECT * FROM son",
    "COMMIT;",
    "select 1",
    "SELECT sysdate, user",
    "TRUNCATE TABLE gecici",
]
NOT_SQL = [
    "Select the best option for your team",
    "Update: toplantı 15:00'e alındı",
    "Create a new account to continue",
    "With best regards,\nMesut",
    "Delete from the list anything you do not need.",
    "Drop me a line when you arrive",
    "Begin with the first chapter",
    "Call me maybe",
    "Commit to the plan and follow through",
    "Grant Hill was a great player",
]
JSON = ['{"a": 1}', '{\n  "ad": "Ayşe",\n  "liste": [1, 2]\n}', '[{"id": 1}, {"id": 2}]', "[\n  1,\n  2\n]"]
NOT_JSON = ["[1, 2]", "{not json}", "[x]", "{}x", "42", '"metin"', "[]"]
XML = [
    '<?xml version="1.0"?>\n<kok><a>1</a></kok>',
    "<musteri id=\"5\"><ad>Ayşe</ad></musteri>",
    "<br/>",
    "<div class=\"x\">\n  <span>metin</span>\n</div>",
]
NOT_XML = ["<3 seni seviyorum", "a < b and c > d", "<bitmemiş", "x <y> z", "<yalnız>"]
CODE = [
    "def topla(a, b):\n    return a + b",
    "function f(x) {\n  return x * 2;\n}",
    "for (int i = 0; i < n; i++) {\n    toplam += i;\n}",
    "import os\nimport sys\nprint(os.getcwd())",
    "const x = 5;\nlet y = x + 1;\nconsole.log(y);",
    "public class A {\n    private int x;\n}",
    "$ git status\n$ git add -A\n$ git commit -m 'x'",
]
NOT_CODE = [
    "Merhaba,\nYarın toplantı var.\nSaygılar",
    "tek satır",
    "Alışveriş listesi:\n- süt\n- ekmek\n- yumurta",
    "TR12 0006 2000 1234 0006 2998 76",
    "Ad: Ayşe\nSoyad: Yılmaz\nTelefon: 0555 111 22 33",
    "Müşteri no: 10045532\nTutar: 1.250,00 TL",
    "1. adım\n2. adım\n3. adım",
    "Toplantı notları\nKatılanlar: Ali, Veli\nKarar: ertelendi",
]


@pytest.mark.parametrize("text", SQL)
def test_sql_detected(text):
    assert codekind.detect(text) == "sql", text


@pytest.mark.parametrize("text", NOT_SQL + NOT_CODE)
def test_plain_text_is_not_code(text):
    assert codekind.detect(text) is None, text
    assert classify_text(text) is Category.TEXT


@pytest.mark.parametrize("text", JSON)
def test_json_detected(text):
    assert codekind.detect(text) == "json"


@pytest.mark.parametrize("text", NOT_JSON)
def test_not_json(text):
    assert codekind.detect(text) != "json"


@pytest.mark.parametrize("text", XML)
def test_xml_detected(text):
    assert codekind.detect(text) == "xml"


@pytest.mark.parametrize("text", NOT_XML)
def test_not_xml(text):
    assert codekind.detect(text) != "xml"


@pytest.mark.parametrize("text", CODE)
def test_code_detected(text):
    assert codekind.detect(text) == "code", text
    assert classify_text(text) is Category.CODE


def test_links_stay_links_and_empty_is_none():
    assert classify_text("https://example.com/a?b=1") is Category.LINK
    assert codekind.detect("") is None and codekind.detect("   \n") is None


def test_tokens_cover_the_whole_text():
    for kind, text in (("sql", SQL[1]), ("json", JSON[1]), ("xml", XML[0]), ("code", CODE[1])):
        assert "".join(piece for piece, _role in codekind.tokens(text, kind)) == text
    roles = dict((p.lower(), r) for p, r in codekind.tokens("SELECT 'a' FROM t -- not", "sql"))
    assert roles["select"] == "keyword" and roles["'a'"] == "string" and roles["-- not"] == "comment"
    keys = [p for p, r in codekind.tokens('{"ad": "x", "n": 5, "ok": true}', "json") if r == "key"]
    assert keys == ['"ad"', '"n"', '"ok"']


def test_highlight_escapes_content():
    out = codekind.highlight_html("SELECT '<b>x</b>' FROM t WHERE a < 5 & b > 2", "sql", codekind.PALETTE_DARK)
    assert "<b>" not in out and "&lt;b&gt;" in out and "&amp;" in out
    assert out.count("<span") >= 3
    plain = codekind.highlight_html("<script>alert(1)</script>", None, codekind.PALETTE_DARK)
    assert "<script>" not in plain and "&lt;script&gt;" in plain


# ---- dönüşümler ---------------------------------------------------------------
def test_turkish_case():
    assert transforms.upper_tr("ışık iğne çay") == "IŞIK İĞNE ÇAY"
    assert transforms.lower_tr("IŞIK İĞNE ÇAY") == "ışık iğne çay"
    assert transforms.title_tr("istanbul ISPARTA ığdır 3.kat") == "İstanbul Isparta Iğdır 3.Kat"


def test_spaces_and_lines():
    assert transforms.clean_spaces("  a   b \t c \n\n\n  d e  ") == "a b c\nd e"
    assert transforms.join_lines(" a \n\n b\nc ") == "a b c"
    assert transforms.join_lines("a\nb", ", ") == "a, b"
    assert transforms.lines_to_csv("123\n O'Brien \n\n456") == "'123', 'O''Brien', '456'"


def test_json_transforms():
    assert transforms.json_pretty('{"ad":"Ayşe","n":[1,2]}') == '{\n  "ad": "Ayşe",\n  "n": [\n    1,\n    2\n  ]\n}'
    assert transforms.json_minify('{\n  "ad": "Ayşe",\n  "n": [1, 2]\n}') == '{"ad":"Ayşe","n":[1,2]}'
    with pytest.raises(TransformError):
        transforms.json_pretty("json değil")


def test_turkish_character_fixes():
    assert transforms.ascii_fold("Çağrı İŞLEMİ ığdır öğüt") == "Cagri ISLEMI igdir ogut"
    broken = "Müşteri çağrısı İşlem".encode("utf-8").decode("cp1254")
    assert broken != "Müşteri çağrısı İşlem"
    assert transforms.fix_mojibake(broken) == "Müşteri çağrısı İşlem"
    assert transforms.fix_mojibake("Zaten düzgün çalışıyor") == "Zaten düzgün çalışıyor"


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://a.com/x?utm_source=n&id=5&utm_medium=e", "https://a.com/x?id=5"),
        ("https://a.com/x?fbclid=abc", "https://a.com/x"),
        ("https://a.com/x?id=5&q=a+b#bolum", "https://a.com/x?id=5&q=a+b#bolum"),
        ("https://a.com/x?gclid=1&q=%C3%A7ay#b", "https://a.com/x?q=%C3%A7ay#b"),
        ("https://a.com/x", "https://a.com/x"),
        ("  https://a.com/?UTM_Campaign=x&a=  ", "https://a.com/?a="),
        ("metin", "metin"),
    ],
)
def test_clean_url(url, expected):
    assert transforms.clean_url(url) == expected


def test_transform_menus_are_callable():
    for entry in transforms.TEXT_TRANSFORMS + transforms.LINK_TRANSFORMS:
        if entry is None:
            continue
        label, fn = entry
        assert label and isinstance(fn('{"a": 1}'), str)
