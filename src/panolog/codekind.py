"""Metnin kod olup olmadığını (SQL, JSON, XML, genel kod) saptar ve renklendirir.

Saf fonksiyonlardır (Qt bağımlılığı yok). Algılama bilerek temkinlidir: düz bir cümlenin
"Kod" sekmesine düşmesi, bir kod parçasının "Metinler"de kalmasından daha rahatsız edicidir.
"""
from __future__ import annotations

import html
import json
import re

KINDS = {"sql": "SQL", "json": "JSON", "xml": "XML", "code": "Kod"}

_SQL_START = re.compile(
    r"^\s*(?:--[^\n]*\n\s*|/\*.*?\*/\s*)*"
    r"(select|insert\s+into|update|delete\s+from|create|alter|drop|truncate|merge\s+into|with|"
    r"grant|revoke|declare|begin|exec|execute|call|commit|rollback|explain)\b",
    re.IGNORECASE | re.DOTALL,
)
# Başlangıç sözcüğünden sonra gelmesi beklenen ikinci işaret: "Select the best option" gibi
# cümleleri eler.
_SQL_FOLLOW = {
    "select": r"\bfrom\b|^\s*select\s+[\w*@'\"(]+\s*;?\s*$|\bselect\s+\S+\s*(,|\bas\b)",
    "update": r"\bset\b",
    "insert": r"\b(values|select)\b|\(",
    "delete": r"^\s*delete\s+from\s+[\w.\[\]\"`]+\s*(;|$|\bwhere\b)",
    "merge": r"\busing\b",
    "create": r"\b(table|view|index|procedure|function|trigger|sequence|schema|database|user|"
    r"or\s+replace|unique|temporary|temp|global)\b",
    "alter": r"\b(table|view|index|session|system|user|database|procedure|sequence)\b",
    "drop": r"\b(table|view|index|procedure|function|trigger|sequence|schema|database|user)\b",
    "truncate": r"\btable\b",
    "with": r"\bas\s*\(",
    "grant": r"\b(on|to)\b",
    "revoke": r"\b(on|from)\b",
    "declare": r"[@:;]|\b(cursor|varchar|number|int|date)\b",
    "begin": r";|\b(transaction|tran|end)\b",
    "exec": r"[\w.\[\]]+",
    "execute": r"\b(immediate|procedure)\b|[\w.\[\]]+\s*[(@]",
    "call": r"\(",
    "commit": r"^\s*commit\s*;?\s*$",
    "rollback": r"^\s*rollback\s*;?\s*$",
    "explain": r"\b(plan|select|analyze)\b",
}
_XML_START = re.compile(r"^\s*(<\?xml\b|<!DOCTYPE\b|<[A-Za-z_][\w:.-]*(\s[^<>]*)?/?>)")
_XML_END = re.compile(r"(</[A-Za-z_][\w:.-]*\s*>|/>)\s*$")
_CODE_LINE = re.compile(
    r"^\s*("
    r"(def|class|function|func|fn|import|from|package|using|namespace|public|private|protected|"
    r"static|const|let|var|val|return|if|elif|else|for|foreach|while|switch|case|try|catch|"
    r"finally|throw|raise|async|await|end|then|do|echo|export|set|#include|#define|#!/|@\w+)\b"
    r"|[{}\[\]()]+;?\s*$"
    r"|.*[;{}]\s*$"
    r"|.*(=>|->|::|:=|==|!=|&&|\|\||\+=|-=)\s*.*"
    r"|\s*[\w.\[\]\"']+\s*=\s*\S.*"
    r"|\s*[\w.]+\(.*\)\s*:?\s*$"
    r"|\s*(//|#|--|/\*|\*)\s?.*"
    r"|\$\s+\S+.*"
    r")",
)


def _first_word(match: re.Match) -> str:
    return match.group(1).split()[0].lower()


def is_sql(text: str) -> bool:
    m = _SQL_START.match(text)
    if not m:
        return False
    rest = text[m.start(1) :]
    return bool(re.search(_SQL_FOLLOW.get(_first_word(m), r"."), rest, re.IGNORECASE | re.DOTALL))


def is_json(text: str) -> bool:
    s = text.strip()
    if len(s) < 2 or s[0] not in "{[" or s[-1] not in "}]":
        return False
    try:
        value = json.loads(s)
    except ValueError:
        return False
    if isinstance(value, dict):
        return True
    # [1, 2] gibi kısa listeler düz metindir; nesne/dizi içeren ya da çok satırlı listeler JSON.
    return isinstance(value, list) and (
        any(isinstance(v, (dict, list)) for v in value) or (len(value) > 1 and "\n" in s)
    )


def is_xml(text: str) -> bool:
    s = text.strip()
    if not (_XML_START.match(s) and _XML_END.search(s)):
        return False
    return s.count("<") >= 2 or s.endswith("/>")


def is_code(text: str) -> bool:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) < 2:
        return False
    hits = sum(1 for ln in lines if _CODE_LINE.match(ln))
    structural = sum(1 for ln in lines if re.search(r"[;{}]\s*$|^\s*(def|class|function)\b", ln))
    return hits / len(lines) >= 0.6 and (structural >= 1 or hits >= 3)


def detect(text: str) -> str | None:
    """'sql', 'json', 'xml', 'code' ya da kod değilse None."""
    if not text or not text.strip() or len(text) > 2_000_000:
        return None
    if is_json(text):
        return "json"
    if is_xml(text):
        return "xml"
    if is_sql(text):
        return "sql"
    if is_code(text):
        return "code"
    return None


# ---- renklendirme -------------------------------------------------------------
_SQL_KEYWORDS = (
    "select from where and or not in is null like between exists join inner left right full "
    "outer cross on group by order having union all distinct as into values insert update set "
    "delete create alter drop table view index procedure function trigger sequence primary key "
    "foreign references constraint default unique check case when then else end with fetch "
    "first rows only limit offset top asc desc truncate merge using matched grant revoke begin "
    "commit rollback declare exec execute call if while return varchar varchar2 nvarchar char "
    "number numeric integer int bigint smallint decimal date timestamp datetime boolean clob "
    "blob count sum avg min max coalesce nvl cast convert over partition row_number"
).split()
_CODE_KEYWORDS = (
    "def class function func fn import from package using namespace public private protected "
    "static const let var val return if elif else for foreach while switch case break continue "
    "try catch except finally throw raise async await new delete this self super null None nil "
    "true false True False and or not in is lambda yield with as void int long double float "
    "string bool boolean char struct enum interface extends implements override final abstract "
    "then end do echo export typeof instanceof"
).split()
_STRING = r"'(?:[^'\\\n]|\\.|'')*'|\"(?:[^\"\\\n]|\\.)*\""
_NUMBER = r"\b\d+(?:\.\d+)?\b"


def _word_re(words) -> str:
    return r"\b(?:" + "|".join(sorted(map(re.escape, words), key=len, reverse=True)) + r")\b"


_TOKENIZERS: dict[str, re.Pattern] = {
    "sql": re.compile(
        rf"(?P<comment>--[^\n]*|/\*.*?\*/)|(?P<string>{_STRING})|(?P<number>{_NUMBER})"
        rf"|(?P<keyword>{_word_re(_SQL_KEYWORDS)})",
        re.IGNORECASE | re.DOTALL,
    ),
    "json": re.compile(
        r'(?P<key>"(?:[^"\\\n]|\\.)*"(?=\s*:))|(?P<string>"(?:[^"\\\n]|\\.)*")'
        r"|(?P<number>-?\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b)|(?P<keyword>\b(?:true|false|null)\b)"
    ),
    "xml": re.compile(
        r"(?P<comment><!--.*?-->)|(?P<keyword></?[A-Za-z_][\w:.-]*|/?>|<\?[\w-]+|\?>)"
        rf"|(?P<key>[A-Za-z_][\w:.-]*(?=\s*=))|(?P<string>{_STRING})",
        re.DOTALL,
    ),
    "code": re.compile(
        rf"(?P<comment>//[^\n]*|#[^\n]*|/\*.*?\*/)|(?P<string>{_STRING})|(?P<number>{_NUMBER})"
        rf"|(?P<keyword>{_word_re(_CODE_KEYWORDS)})",
        re.DOTALL,
    ),
}

PALETTE_DARK = {
    "keyword": "#7fb4ff", "string": "#a8d98a", "number": "#f0b171",
    "comment": "#7d8494", "key": "#e0a8ff",
}  # fmt: skip
PALETTE_LIGHT = {
    "keyword": "#0b4fb3", "string": "#1b7a2b", "number": "#a8480b",
    "comment": "#6b7280", "key": "#7a1fa2",
}  # fmt: skip


def tokens(text: str, kind: str) -> list[tuple[str, str | None]]:
    """Metni (parça, tür) çiftlerine böler; tür None ise düz metindir."""
    pattern = _TOKENIZERS.get(kind)
    if pattern is None:
        return [(text, None)]
    out: list[tuple[str, str | None]] = []
    pos = 0
    for m in pattern.finditer(text):
        if m.start() > pos:
            out.append((text[pos : m.start()], None))
        out.append((m.group(), m.lastgroup))
        pos = m.end()
    if pos < len(text):
        out.append((text[pos:], None))
    return out


def highlight_html(text: str, kind: str | None, palette: dict[str, str]) -> str:
    """Renklendirilmiş, güvenli HTML. İçerik her zaman kaçışlanır; etiket olarak yorumlanamaz."""
    parts: list[str] = []
    for piece, role in tokens(text, kind or ""):
        escaped = html.escape(piece, quote=False)
        color = palette.get(role or "")
        parts.append(f'<span style="color:{color}">{escaped}</span>' if color else escaped)
    return '<pre style="margin:0; white-space:pre-wrap">' + "".join(parts) + "</pre>"
