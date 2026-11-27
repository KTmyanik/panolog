"""İki OCR motorunun sonucunu birleştirir.

Model motoru kod, numara ve noktalamada güçlüdür ama Türkçe ı/i ve İ/I ayrımında zayıftır
("çikiş yapin"). Windows'un Türkçe motoru Türkçe düz metinde güçlüdür ama kodu bozar
("PRİMARY", "c01umn"). Bu yüzden temel alınan her zaman model motorunun okumasıdır;
Windows'tan yalnızca Türkçe harf düzeltmeleri, yalnızca Türkçe olduğu anlaşılan
satırlarda ve yalnızca iki motorun aynı sözcüğü okuduğu yerlerde alınır.
"""
from __future__ import annotations

import difflib
import re

from .lines import Line, merge_rows

# Model, Türkçe ş yerine bazen Romence ș (virgüllü) üretir.
# Ayrıca tam genişlikli (Doğu Asya) noktalama üretebilir: "（" -> "(", "：" -> ":".
_MODEL_FIX = str.maketrans(
    {"ș": "ş", "Ș": "Ş", "ț": "t", "Ț": "T", **{chr(c): chr(c - 0xFEE0) for c in range(0xFF01, 0xFF5F)}}
)
# İki okumayı karşılaştırmak için: Türkçe harfler ASCII karşılıklarına indirgenir.
_FOLD = str.maketrans(
    {"ı": "i", "İ": "I", "ş": "s", "Ş": "S", "ğ": "g", "Ğ": "G", "ç": "c", "Ç": "C",
     "ö": "o", "Ö": "O", "ü": "u", "Ü": "U", "ș": "s", "Ș": "S"}
)
# Yalnızca Türkçede bulunan, modelin de güvenilir okuduğu harfler: satırın Türkçe olduğunun kanıtı.
_STRONG = set("çğöşüÇĞÖŞÜ")
# Kod satırı işaretleri: bu karakterleri içeren satırlar düz metin sayılmaz.
_CODE = re.compile(r"[_=;(){}\[\]<>|\\@#$%^&*`~]")
_WORD = re.compile(r"^[^\W\d_]+$")  # yalnızca harflerden oluşan sözcük
_EDGE = ".,:;!?\"'()…"


def fix_model_text(text: str) -> str:
    return text.translate(_MODEL_FIX)


def fold(text: str) -> str:
    """Karşılaştırma anahtarı: Türkçe harf ve büyük/küçük harf farkı yok sayılır
    (model "ilk", Windows "İlk" okuduysa aynı sözcüktür)."""
    return text.translate(_FOLD).lower()


_TURKISH = set("çğıöşüÇĞİÖŞÜ")
_I_FAMILY = set("iıIİ")


def _upper(c: str) -> str:
    return {"i": "İ", "ı": "I"}.get(c, c.upper())


def _lower(c: str) -> str:
    return {"İ": "i", "I": "ı"}.get(c, c.lower())


def merge_word(model: str, windows: str) -> str:
    """İki motorun aynı sözcük için okumasını harf harf birleştirir.

    Temel modelin okumasıdır. Windows'un harfi yalnızca şu durumlarda alınır:
    - i/ı/I/İ ayrımı (modelin en zayıf olduğu yer; Windows'un Türkçe motoru burada güvenilir),
    - aynı harfin Türkçe biçimi (s -> ş, g -> ğ ...); büyük/küçüklük modelden gelir,
    - uzun sözcükte tek bir harfin yerine Türkçe bir harf (model "gubesi", Windows "şubesi").
    Windows'un Türkçe olmayan farkları (ör. ı yerine l: "kartl") alınmaz.
    """
    if len(model) != len(windows):
        return model
    unrelated = [i for i, (m, w) in enumerate(zip(model, windows)) if fold(m) != fold(w)]
    if len(unrelated) > 1 or (unrelated and len(model) < 5):
        return model
    # Sözcüğün geri kalanı büyük harfse düzeltilen harf de büyük olmalı ("IşIK" -> "IŞIK").
    out = []
    for i, (m, w) in enumerate(zip(model, windows)):
        if m == w:
            out.append(m)
        elif m in _I_FAMILY and w in _I_FAMILY:
            out.append(w)
        elif w in _TURKISH and w not in _I_FAMILY:
            rest = model[:i] + model[i + 1 :]
            upper = rest.isupper() or m.isupper()  # aksi halde modelin büyük/küçüklüğü
            out.append(_upper(w) if upper else _lower(w))
        else:
            out.append(m)
    return "".join(out)


def has_strong_turkish(text: str) -> bool:
    return any(c in _STRONG for c in text)


def looks_like_code(text: str) -> bool:
    return bool(_CODE.search(text))


def _core(token: str) -> tuple[str, str, str]:
    """Sözcüğü (baştaki noktalama, çekirdek, sondaki noktalama) olarak ayırır."""
    start = 0
    while start < len(token) and token[start] in _EDGE:
        start += 1
    end = len(token)
    while end > start and token[end - 1] in _EDGE:
        end -= 1
    return token[:start], token[start:end], token[end:]


def merge_line(model_text: str, windows_text: str) -> str:
    """Model satırındaki sözcüklerde, Windows aynı sözcüğü yalnızca Türkçe harf farkıyla
    okuduysa Windows'un yazımını alır. Başka hiçbir şey değişmez."""
    m_tokens, w_tokens = model_text.split(" "), windows_text.split()
    m_keys = [fold(_core(t)[1]) for t in m_tokens]
    w_keys = [fold(_core(t)[1]) for t in w_tokens]
    out = list(m_tokens)
    matcher = difflib.SequenceMatcher(None, m_keys, w_keys, autojunk=False)
    for tag, a0, a1, b0, b1 in matcher.get_opcodes():
        if tag == "equal" or (tag == "replace" and a1 - a0 == b1 - b0):
            for k in range(a1 - a0):
                lead, m_core, tail = _core(m_tokens[a0 + k])
                w_core = _core(w_tokens[b0 + k])[1]
                if m_core != w_core and _WORD.match(m_core) and _WORD.match(w_core):
                    out[a0 + k] = lead + merge_word(m_core, w_core) + tail
    return " ".join(out)


def _match(row: Line, candidates: list[Line]) -> Line | None:
    """Dikeyde en çok örtüşen Windows satırı (en az yarı yarıya örtüşmeli)."""
    best, best_overlap = None, 0.0
    for c in candidates:
        overlap = min(row.y1, c.y1) - max(row.y0, c.y0)
        if overlap > best_overlap:
            best, best_overlap = c, overlap
    if best is None or best_overlap < 0.5 * min(row.height, best.height):
        return None
    return best


def merge(model_lines: list[Line], windows_lines: list[Line]) -> str:
    """Birleştirilmiş metin. `windows_lines` boşsa yalnızca model okuması döner."""
    rows = [
        Line(fix_model_text(r.text), r.x0, r.y0, r.x1, r.y1, r.score) for r in merge_rows(model_lines)
    ]
    if not rows:  # model hiçbir şey bulamadıysa Windows'un okuması hiç yoktan iyidir
        return "\n".join(r.text for r in merge_rows(windows_lines))
    w_rows = merge_rows(windows_lines)
    if not w_rows:
        return "\n".join(r.text for r in rows)

    # Belge genelinde Türkçe mi? Düz metin satırlarının çoğunda Türkçeye özgü harf varsa,
    # o harfleri içermeyen düz metin satırları da (ör. "Hesap kapalı") Türkçe sayılır.
    prose = [r for r in rows if not looks_like_code(r.text) and len(r.text.split()) >= 2]
    strong = sum(1 for r in prose if has_strong_turkish(r.text))
    turkish_document = bool(prose) and strong * 2 >= len(prose)

    out = []
    for row in rows:
        text = row.text
        turkish = has_strong_turkish(text) or (turkish_document and not looks_like_code(text))
        if turkish:
            partner = _match(row, w_rows)
            if partner is not None:
                text = merge_line(text, partner.text)
        out.append(text)
    return "\n".join(out)
