import pytest

from panolog.sensitive import (
    SensitiveMode,
    evaluate,
    find_sensitive,
    is_valid_card,
    is_valid_iban,
    is_valid_tckn,
    mask_text,
)
from panolog.sensitive.detectors import CARD, EMAIL, IBAN, PHONE, SECRET, TCKN, luhn_ok


def kinds(text, **kw):
    return [m.kind for m in find_sensitive(text, **kw)]


def masked(text, **kw):
    return mask_text(text, find_sensitive(text, **kw))


def make_tckn(first9: str) -> str:
    d = [int(c) for c in first9]
    tenth = (sum(d[0::2]) * 7 - sum(d[1::2])) % 10
    return first9 + str(tenth) + str((sum(d) + tenth) % 10)


# ---- IBAN -------------------------------------------------------------------
@pytest.mark.parametrize(
    "iban",
    [
        "TR330006100519786457841326",
        "TR33 0006 1005 1978 6457 8413 26",
        "tr33 0006 1005 1978 6457 8413 26",
        "DE89370400440532013000",
        "GB82 WEST 1234 5698 7654 32",
        "NL91ABNA0417164300",
        "FR1420041010050500013M02606",
    ],
)
def test_valid_iban(iban):
    assert is_valid_iban(iban)
    assert kinds(f"Hesap: {iban} olarak kayıtlı.") == [IBAN]


@pytest.mark.parametrize(
    "iban",
    [
        "TR330006100519786457841327",  # denetim hanesi tutmuyor
        "TR340006100519786457841326",  # mod-97 tutmuyor
        "TR3300061005197864578413",  # kısa
        "TR33000610051978645784132600",  # uzun
        "DE89370400440532013001",
        "ZZ330006100519786457841326",  # bilinmeyen ülke
        "TR33000610051978645784132Ö",
        "",
    ],
)
def test_invalid_iban(iban):
    assert not is_valid_iban(iban)
    assert IBAN not in kinds(f"Hesap: {iban}")


def test_iban_not_matched_inside_longer_token():
    assert kinds("XTR330006100519786457841326") == []
    assert IBAN not in kinds("TR330006100519786457841326A")


def test_iban_followed_by_word_is_still_found():
    text = "TR33 0006 1005 1978 6457 8413 26 numaralı hesaba"
    assert kinds(text) == [IBAN]
    assert masked(text) == "TR33 **** 1326 numaralı hesaba"


# ---- Kredi kartı (Luhn) -----------------------------------------------------
@pytest.mark.parametrize(
    "card",
    [
        "4111111111111111",
        "4111 1111 1111 1111",
        "4111-1111-1111-1111",
        "5555555555554444",
        "378282246310005",  # 15 hane (Amex)
        "6011111111111117",
        "4012888888881881",
    ],
)
def test_valid_card(card):
    assert is_valid_card(card)
    assert kinds(f"Kart {card} ile ödendi") == [CARD]


@pytest.mark.parametrize(
    "card",
    [
        "4111111111111112",  # Luhn tutmuyor
        "1234567890123456",
        "0000000000000000",  # Luhn tutar ama kart değil
        "411111111111",  # 12 hane: kısa
        "41111111111111111111",  # 20 hane: uzun
    ],
)
def test_invalid_card(card):
    assert not is_valid_card(card)
    assert CARD not in kinds(f"No: {card}")


def test_luhn():
    assert luhn_ok("79927398713")
    assert not luhn_ok("79927398710")
    assert not luhn_ok("7992739871a")


# ---- TCKN -------------------------------------------------------------------
@pytest.mark.parametrize(
    "tckn", ["10000000146", make_tckn("123456789"), make_tckn("987654321"), make_tckn("555555555")]
)
def test_valid_tckn(tckn):
    assert is_valid_tckn(tckn)
    assert kinds(f"TC: {tckn}.") == [TCKN]


@pytest.mark.parametrize(
    "tckn",
    [
        "10000000147",  # 11. hane yanlış
        "10000000156",  # 10. hane yanlış
        "12345678901",
        "00000000000",
        "01234567890",  # 0 ile başlayamaz
        "1000000014",  # 10 hane
        "100000001460",  # 12 hane
        "1000000014a",
    ],
)
def test_invalid_tckn(tckn):
    assert not is_valid_tckn(tckn)
    assert TCKN not in kinds(f"TC: {tckn}")


def test_tckn_not_matched_inside_longer_number():
    assert kinds("Sipariş 910000000146") == []
    assert kinds("ref-A10000000146") == []


# ---- E-posta ve telefon (ayarla açılır) -------------------------------------
def test_email_and_phone_are_off_by_default():
    text = "ali.veli@banka.com.tr / 0532 123 45 67"
    assert kinds(text) == []
    assert kinds(text, email=True) == [EMAIL]
    assert kinds(text, phone=True) == [PHONE]
    assert kinds(text, email=True, phone=True) == [EMAIL, PHONE]


@pytest.mark.parametrize(
    "phone",
    ["0532 123 45 67", "05321234567", "+90 532 123 45 67", "+905321234567", "(212) 555 12 34",
     "0090 532 123 45 67", "+44 20 7946 0958"],
)
def test_phone_formats(phone):
    assert kinds(f"Tel: {phone}", phone=True) == [PHONE]


@pytest.mark.parametrize("text", ["Tutar 1234567", "2026-11-27", "Sürüm 10.0.26200", "14:30"])
def test_not_phone(text):
    assert kinds(text, phone=True) == []


def test_tckn_wins_over_phone():
    assert kinds("10000000146", phone=True) == [TCKN]


# ---- Parola / token satırları -----------------------------------------------
@pytest.mark.parametrize(
    "line",
    [
        "password: hunter2",
        "Password=hunter2",
        "PAROLA: gizli",
        "Şifre: gizli",
        "ŞİFRE = gizli",
        "sifre gizli",
        "kullanıcı parolası: gizli",
        "access_token: eyJhbGciOi",
        "TOKEN=abc",
        "api_key=sk-123",
        "API-KEY: sk-123",
        "apikey sk-123",
        'export DB_PASSWORD="x"',
    ],
)
def test_secret_lines(line):
    assert kinds(line) == [SECRET]
    assert "gizli" not in masked(line) and "hunter2" not in masked(line)
    assert "sk-123" not in masked(line) and "eyJ" not in masked(line)


def test_secret_masks_only_that_line():
    text = "kullanıcı: deneme\npassword: hunter2\nsunucu: db01"
    assert masked(text) == "kullanıcı: deneme\npassword: ********\nsunucu: db01"


def test_secret_value_on_next_line():
    assert masked("Şifre:\n\n  abc123\nson") == "Şifre:\n\n  ********\nson"
    assert kinds("Şifre") == [SECRET]  # değer yok ama yine de hassas sayılır


def test_secret_takes_priority_over_other_matches_on_its_value():
    assert kinds("token: TR330006100519786457841326") == [SECRET]
    assert kinds("TC 10000000146 şifre: x") == [TCKN, SECRET]


# ---- Maskeleme --------------------------------------------------------------
def test_mask_formats():
    assert masked("TR33 0006 1005 1978 6457 8413 26") == "TR33 **** 1326"
    assert masked("DE89370400440532013000") == "DE89 **** 3000"
    assert masked("4111 1111 1111 1111") == "**** **** **** 1111"
    assert masked("378282246310005") == "***********0005"
    assert masked("10000000146") == "*********46"
    assert masked("ali.veli@banka.com.tr", email=True) == "a***@banka.com.tr"
    assert masked("0532 123 45 67", phone=True) == "**** *** ** 67"
    assert masked("API_KEY=sk-123") == "API_KEY=********"


def test_mask_multiple_in_one_text():
    text = "IBAN TR330006100519786457841326, kart 4111111111111111, TC 10000000146"
    assert masked(text) == "IBAN TR33 **** 1326, kart ************1111, TC *********46"


@pytest.mark.parametrize(
    "text",
    [
        "Toplantı yarın 14:00'te, 3. katta.",
        "SELECT * FROM musteri WHERE id = 42",
        "Fatura no 2026000123, tutar 1.250,00 TL",
        "https://example.com/rapor?id=12345",
        "",
    ],
)
def test_ordinary_text_is_not_sensitive(text):
    assert kinds(text, email=True, phone=True) == []
    assert masked(text) == text


# ---- Politika ---------------------------------------------------------------
def test_policy_non_sensitive():
    d = evaluate("merhaba", "auto_delete")
    assert d.store and not d.sensitive and d.masked_text is None and d.ttl_seconds is None


def test_policy_default_is_off():
    for text in ("TC 10000000146", "4111 1111 1111 1111", "password: hunter2"):
        d = evaluate(text)
        assert d.store and not d.sensitive and d.masked_text is None and d.ttl_seconds is None
    assert evaluate("TC 10000000146", SensitiveMode.OFF, email=True, phone=True) == evaluate("x")


def test_policy_auto_delete_60s():
    d = evaluate("TC 10000000146", "auto_delete")
    assert d.sensitive and d.store and d.ttl_seconds == 60 and d.masked_text is None
    assert d.kinds == {TCKN}


def test_policy_skip():
    d = evaluate("TC 10000000146", SensitiveMode.SKIP)
    assert d.sensitive and not d.store


def test_policy_mask():
    d = evaluate("TC 10000000146", "mask")
    assert d.store and d.masked_text == "TC *********46" and d.ttl_seconds is None


def test_policy_unknown_mode_falls_back_to_off():
    assert not evaluate("TC 10000000146", "bozuk").sensitive


def test_policy_respects_email_phone_toggles():
    assert not evaluate("a@b.com", "mask").sensitive
    assert evaluate("a@b.com", "mask", email=True).sensitive
    assert not evaluate("0532 123 45 67", "mask").sensitive
    assert evaluate("0532 123 45 67", "mask", phone=True).sensitive
