"""Yapıştırmadan önce uygulanan metin dönüşümleri (saf fonksiyonlar)."""
from __future__ import annotations

import json
import re
from collections.abc import Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


class TransformError(ValueError):
    """Dönüşüm bu metne uygulanamadı (ör. geçerli JSON değil)."""


# ---- büyük/küçük harf (Türkçe kurallarıyla) -------------------------------------
def upper_tr(text: str) -> str:
    return text.replace("i", "İ").replace("ı", "I").upper()


def lower_tr(text: str) -> str:
    return text.replace("I", "ı").replace("İ", "i").lower()


def title_tr(text: str) -> str:
    """Her sözcüğün ilk harfi büyük, kalanı küçük."""
    return re.sub(r"[^\W\d_]+", lambda m: upper_tr(m.group()[0]) + lower_tr(m.group()[1:]), text)


# ---- boşluk ve satırlar ---------------------------------------------------------
def clean_spaces(text: str) -> str:
    """Satır başı/sonu boşlukları atar, art arda boşlukları teke indirir, boş satırları siler."""
    lines = (re.sub(r"[ \t ]+", " ", ln).strip() for ln in text.splitlines())
    return "\n".join(ln for ln in lines if ln)


def join_lines(text: str, separator: str = " ") -> str:
    return separator.join(ln.strip() for ln in text.splitlines() if ln.strip())


def lines_to_csv(text: str) -> str:
    """Her satırı tek tırnak içine alıp virgülle birleştirir: SQL IN (...) listeleri için."""
    values = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return ", ".join("'" + v.replace("'", "''") + "'" for v in values)


# ---- JSON -----------------------------------------------------------------------
def _load_json(text: str):
    try:
        return json.loads(text)
    except ValueError as exc:
        raise TransformError(f"Geçerli JSON değil: {exc}") from exc


def json_pretty(text: str) -> str:
    return json.dumps(_load_json(text), ensure_ascii=False, indent=2)


def json_minify(text: str) -> str:
    return json.dumps(_load_json(text), ensure_ascii=False, separators=(",", ":"))


# ---- Türkçe karakterler -----------------------------------------------------------
_ASCII_FOLD = str.maketrans("çğıöşüÇĞİÖŞÜâîûÂÎÛ", "cgiosuCGIOSUaiuAIU")
# UTF-8 metnin yanlışlıkla Windows-1254/1252 olarak okunmasıyla oluşan bozuk diziler.
_MOJIBAKE_MARKS = ("Ã", "Ä", "Å", "â€")


def ascii_fold(text: str) -> str:
    """Türkçe harfleri ASCII karşılıklarına çevirir (ç→c, ş→s, İ→I…)."""
    return text.translate(_ASCII_FOLD)


def fix_mojibake(text: str) -> str:
    """"Ã§", "ÅŸ", "Ä±" gibi bozuk görünen Türkçe karakterleri onarır.

    Metin bozuk değilse aynen döner; onarılamayan metin TransformError verir.
    """
    if not any(mark in text for mark in _MOJIBAKE_MARKS):
        return text
    for encoding in ("cp1254", "cp1252", "latin-1"):
        try:
            fixed = text.encode(encoding).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
        if fixed != text:
            return fixed
    raise TransformError("Bozuk karakterler onarılamadı.")


# ---- linkler -----------------------------------------------------------------------
_TRACKING_EXACT = frozenset(
    "fbclid gclid gclsrc dclid gbraid wbraid msclkid yclid twclid ttclid igshid igsh mc_cid "
    "mc_eid mkt_tok _hsenc _hsmi hsctatracking oly_anon_id oly_enc_id vero_id vero_conv "
    "ref_src ref_url s_cid cmpid si spm scm trk trkcampaign srsltid".split()
)
_TRACKING_PREFIXES = ("utm_", "pk_", "mtm_", "hsa_", "stm_")


def is_tracking_param(name: str) -> bool:
    low = name.lower()
    return low in _TRACKING_EXACT or low.startswith(_TRACKING_PREFIXES)


def clean_url(url: str) -> str:
    """Bağlantıdan takip parametrelerini (utm_*, fbclid, gclid…) atar; gerisine dokunmaz."""
    stripped = url.strip()
    try:
        parts = urlsplit(stripped)
    except ValueError:
        return url
    if not parts.query:
        return stripped
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    kept = [(k, v) for k, v in pairs if not is_tracking_param(k)]
    if len(kept) == len(pairs):
        return stripped
    return urlunsplit(parts._replace(query=urlencode(kept, doseq=True)))


# ---- menü -----------------------------------------------------------------------------
# (ad, işlev). Ayraç için None kullanılır.
TEXT_TRANSFORMS: list[tuple[str, Callable[[str], str]] | None] = [
    ("BÜYÜK HARF", upper_tr),
    ("küçük harf", lower_tr),
    ("Baş Harfler Büyük", title_tr),
    None,
    ("Boşlukları temizle", clean_spaces),
    ("Satırları birleştir (boşlukla)", join_lines),
    ("Satırları birleştir (virgülle)", lambda t: join_lines(t, ", ")),
    ("Satırları SQL listesine çevir ('a', 'b')", lines_to_csv),
    None,
    ("JSON'u güzelleştir", json_pretty),
    ("JSON'u sıkıştır", json_minify),
    None,
    ("Bozuk Türkçe karakterleri onar (Ã§ → ç)", fix_mojibake),
    ("Türkçe karakterleri sadeleştir (ç → c)", ascii_fold),
]
LINK_TRANSFORMS: list[tuple[str, Callable[[str], str]] | None] = [
    ("Takip parametrelerini temizle", clean_url),
]
