"""Metinde hassas veri kalıplarını bulan saf fonksiyonlar."""
from __future__ import annotations

import re
from dataclasses import dataclass

IBAN = "iban"
CARD = "card"
TCKN = "tckn"
EMAIL = "email"
PHONE = "phone"
SECRET = "secret"


@dataclass(frozen=True)
class Match:
    kind: str
    start: int
    end: int


# ---- IBAN -------------------------------------------------------------------
IBAN_LENGTHS = {
    "AD": 24, "AE": 23, "AL": 28, "AT": 20, "AZ": 28, "BA": 20, "BE": 16, "BG": 22,
    "BH": 22, "BR": 29, "CH": 21, "CY": 28, "CZ": 24, "DE": 22, "DK": 18, "EE": 20,
    "ES": 24, "FI": 18, "FR": 27, "GB": 22, "GE": 22, "GI": 23, "GR": 27, "HR": 21,
    "HU": 28, "IE": 22, "IL": 23, "IS": 26, "IT": 27, "JO": 30, "KW": 30, "KZ": 20,
    "LB": 28, "LI": 21, "LT": 20, "LU": 20, "LV": 21, "MC": 27, "MD": 24, "ME": 22,
    "MK": 19, "MT": 31, "NL": 18, "NO": 15, "PL": 28, "PT": 25, "QA": 29, "RO": 24,
    "RS": 22, "SA": 24, "SE": 24, "SI": 19, "SK": 24, "SM": 27, "TR": 26, "UA": 29,
    "VG": 24, "XK": 20,
}  # fmt: skip
_IBAN_START = re.compile(r"(?<![A-Za-z0-9])([A-Za-z]{2})\d{2}")
_SEPARATORS = "  -"


def _ascii_alnum(ch: str) -> bool:
    return ch.isascii() and ch.isalnum()


def is_valid_iban(value: str) -> bool:
    """Ülke uzunluğu ve mod-97 denetimi (ISO 13616). Boşluk ve tire yok sayılır."""
    s = "".join(ch for ch in value if ch not in _SEPARATORS).upper()
    if len(s) < 5 or IBAN_LENGTHS.get(s[:2]) != len(s) or not all(_ascii_alnum(c) for c in s):
        return False
    if not s[2:4].isdigit():
        return False
    rearranged = s[4:] + s[:4]
    return int("".join(str(int(ch, 36)) for ch in rearranged)) % 97 == 1


def _find_ibans(text: str) -> list[Match]:
    out = []
    for m in _IBAN_START.finditer(text):
        need = IBAN_LENGTHS.get(m.group(1).upper())
        if not need:
            continue
        i, count, last_sep = m.end(), 4, False
        while count < need and i < len(text):
            ch = text[i]
            if _ascii_alnum(ch):
                count, last_sep = count + 1, False
            elif ch in _SEPARATORS and not last_sep:
                last_sep = True
            else:
                break
            i += 1
        if count != need or (i < len(text) and _ascii_alnum(text[i])):
            continue
        if is_valid_iban(text[m.start() : i]):
            out.append(Match(IBAN, m.start(), i))
    return out


# ---- Kredi kartı ------------------------------------------------------------
_CARD_CANDIDATE = re.compile(r"(?<![0-9A-Za-z])\d(?:[ -]?\d){12,18}(?![0-9A-Za-z])")


def luhn_ok(digits: str) -> bool:
    if not digits.isascii() or not digits.isdigit():
        return False
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


def is_valid_card(value: str) -> bool:
    """13-19 hane + Luhn. Tümü aynı rakam olan diziler (0000...) reddedilir."""
    digits = "".join(ch for ch in value if ch not in " -")
    return 13 <= len(digits) <= 19 and len(set(digits)) > 1 and luhn_ok(digits)


# ---- TC kimlik numarası -----------------------------------------------------
_TCKN_CANDIDATE = re.compile(r"(?<![0-9A-Za-z])[1-9]\d{10}(?![0-9A-Za-z])")


def is_valid_tckn(value: str) -> bool:
    """11 hane, ilk hane 0 olamaz; 10. ve 11. haneler resmi algoritmayla doğrulanır."""
    if len(value) != 11 or not value.isascii() or not value.isdigit() or value[0] == "0":
        return False
    d = [int(c) for c in value]
    tenth = (sum(d[0:9:2]) * 7 - sum(d[1:8:2])) % 10
    return d[9] == tenth and d[10] == sum(d[:10]) % 10


# ---- E-posta ve telefon -----------------------------------------------------
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
_PHONE_TR = re.compile(
    r"(?<![0-9A-Za-z+])(?:(?:\+|00)90[ -]?|0)?\(?[2-5]\d{2}\)?[ -]?\d{3}[ -]?\d{2}[ -]?\d{2}"
    r"(?![0-9A-Za-z])"
)
_PHONE_INTL = re.compile(r"(?<![0-9A-Za-z+])\+\d(?:[ ()-]{0,2}\d){7,14}(?![0-9A-Za-z])")

def _plausible_tr_phone(value: str) -> bool:
    """Önek ve ayraç içermeyen çıplak 10 hane (ör. fatura no) yalnızca 5xx ise telefondur."""
    return not value.isdigit() or len(value) != 10 or value[0] == "5"


# ---- Parola / anahtar satırları ---------------------------------------------
_TR_FOLD = str.maketrans({"İ": "i", "I": "i", "ı": "i", "Ş": "ş"})
_SECRET = re.compile(
    r"(?:password|passwd|parola|şifre|sifre|token|api[_-]?key)\w*[ \t]*[:=]?[ \t]*"
)


def _fold(text: str) -> str:
    # Birebir (uzunluğu koruyan) dönüşüm: bulunan konumlar özgün metinde de geçerlidir.
    return "".join(c.lower() if len(c.lower()) == 1 else c for c in text.translate(_TR_FOLD))


def _find_secrets(text: str) -> list[Match]:
    """Anahtar kelime içeren satırlarda, kelimeden sonraki değer kısmını döndürür.

    Değer aynı satırda yoksa ("Şifre:" ve alt satırda değer) sonraki dolu satır alınır.
    """
    out: list[Match] = []
    folded = _fold(text)
    pos = 0
    lines = folded.split("\n")
    for idx, line in enumerate(lines):
        m = _SECRET.search(line)
        if m:
            start, end = pos + m.end(), pos + len(line.rstrip("\r"))
            if start >= end:  # değer bu satırda değil
                nxt = pos + len(line) + 1
                for later in lines[idx + 1 :]:
                    if later.strip():
                        lead = len(later) - len(later.lstrip())
                        start, end = nxt + lead, nxt + len(later.rstrip())
                        break
                    nxt += len(later) + 1
            out.append(Match(SECRET, start, max(start, end)))
        pos += len(line) + 1
    return out


def _overlaps(m: Match, others: list[Match]) -> bool:
    return any(m.start < o.end and o.start < m.end for o in others)


def find_sensitive(text: str, *, email: bool = False, phone: bool = False) -> list[Match]:
    """Çakışmayan eşleşmeleri konum sırasıyla döndürür.

    Öncelik: parola satırı > IBAN > kart > TCKN > telefon > e-posta.
    """
    found: list[Match] = []

    def add(candidates: list[Match]) -> None:
        for c in candidates:
            if not _overlaps(c, found):
                found.append(c)

    add(_find_secrets(text))
    add(_find_ibans(text))
    add(
        [
            Match(CARD, m.start(), m.end())
            for m in _CARD_CANDIDATE.finditer(text)
            if is_valid_card(m.group())
        ]
    )
    add(
        [
            Match(TCKN, m.start(), m.end())
            for m in _TCKN_CANDIDATE.finditer(text)
            if is_valid_tckn(m.group())
        ]
    )
    if phone:
        add(
            [
                Match(PHONE, m.start(), m.end())
                for m in _PHONE_TR.finditer(text)
                if _plausible_tr_phone(m.group())
            ]
        )
        add([Match(PHONE, m.start(), m.end()) for m in _PHONE_INTL.finditer(text)])
    if email:
        add([Match(EMAIL, m.start(), m.end()) for m in _EMAIL.finditer(text)])
    return sorted(found, key=lambda m: m.start)
