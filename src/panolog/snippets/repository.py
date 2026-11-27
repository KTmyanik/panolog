"""Şablonların (kalıcı metin parçaları) veri erişim katmanı."""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from typing import Callable

from ..storage.repository import _like_escape, normalize_search


class SnippetError(ValueError):
    pass


@dataclass(frozen=True)
class Snippet:
    id: int
    name: str
    shortcode: str | None
    content: str
    tag: str | None
    created_at: float
    updated_at: float

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Snippet":
        return cls(
            row["id"], row["name"], row["shortcode"], row["content"], row["tag"],
            row["created_at"], row["updated_at"],
        )  # fmt: skip


def _clean(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


class SnippetRepository:
    def __init__(self, conn: sqlite3.Connection, clock: Callable[[], float] = time.time) -> None:
        self._conn = conn
        self._clock = clock

    def _validate(self, name: str, content: str, shortcode: str | None, own_id: int | None):
        name = name.strip()
        if not name:
            raise SnippetError("Şablon adı boş olamaz.")
        if not content.strip():
            raise SnippetError("Şablon içeriği boş olamaz.")
        shortcode = _clean(shortcode)
        if shortcode:
            if any(ch.isspace() for ch in shortcode):
                raise SnippetError("Kısa kod boşluk içeremez.")
            other = self.by_shortcode(shortcode)
            if other and other.id != own_id:
                raise SnippetError(f"'{shortcode}' kısa kodu '{other.name}' şablonunda kullanılıyor.")
        return name, shortcode

    @staticmethod
    def _search_text(name: str, shortcode: str | None, content: str, tag: str | None) -> str:
        return normalize_search("\n".join(p for p in (name, shortcode, tag, content) if p))

    def add(
        self, name: str, content: str, shortcode: str | None = None, tag: str | None = None
    ) -> Snippet:
        name, shortcode = self._validate(name, content, shortcode, None)
        tag, now = _clean(tag), self._clock()
        cur = self._conn.execute(
            "INSERT INTO snippets (name, shortcode, content, tag, search_text, created_at,"
            " updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (name, shortcode, content, tag, self._search_text(name, shortcode, content, tag),
             now, now),
        )  # fmt: skip
        self._conn.commit()
        return self.get(cur.lastrowid)  # type: ignore[return-value, arg-type]

    def update(
        self,
        snippet_id: int,
        name: str,
        content: str,
        shortcode: str | None = None,
        tag: str | None = None,
    ) -> Snippet:
        name, shortcode = self._validate(name, content, shortcode, snippet_id)
        tag = _clean(tag)
        self._conn.execute(
            "UPDATE snippets SET name = ?, shortcode = ?, content = ?, tag = ?, search_text = ?,"
            " updated_at = ? WHERE id = ?",
            (name, shortcode, content, tag, self._search_text(name, shortcode, content, tag),
             self._clock(), snippet_id),
        )  # fmt: skip
        self._conn.commit()
        return self.get(snippet_id)  # type: ignore[return-value]

    def delete(self, snippet_id: int) -> bool:
        cur = self._conn.execute("DELETE FROM snippets WHERE id = ?", (snippet_id,))
        self._conn.commit()
        return cur.rowcount > 0

    def get(self, snippet_id: int) -> Snippet | None:
        row = self._conn.execute("SELECT * FROM snippets WHERE id = ?", (snippet_id,)).fetchone()
        return Snippet.from_row(row) if row else None

    def by_shortcode(self, shortcode: str) -> Snippet | None:
        row = self._conn.execute(
            "SELECT * FROM snippets WHERE shortcode = ?", (shortcode.strip(),)
        ).fetchone()
        return Snippet.from_row(row) if row else None

    def list(self, query: str = "") -> list[Snippet]:
        """Ada göre sıralı. Arama ad, kısa kod, etiket ve içerikte yapılır; kısa kodu
        aramayla birebir eşleşen şablon en üste gelir."""
        raw = query.strip()
        sql, params = "SELECT * FROM snippets", []
        if raw:
            sql += " WHERE search_text LIKE ? ESCAPE '\\'"
            params.append(f"%{_like_escape(normalize_search(raw))}%")
        rows = [Snippet.from_row(r) for r in self._conn.execute(sql, params)]
        rows.sort(key=lambda s: (s.shortcode != raw if raw else False, normalize_search(s.name), s.id))
        return rows

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM snippets").fetchone()[0]

    def import_many(self, entries: list[dict]) -> tuple[int, int, int]:
        """(eklenen, güncellenen, atlanan) döner.

        Kısa kodu zaten kayıtlı olan şablon güncellenir; adı ve içeriği birebir aynı olan
        atlanır; diğerleri eklenir.
        """
        added = updated = skipped = 0
        for e in entries:
            name, content = e["name"], e["content"]
            shortcode, tag = _clean(e.get("shortcode")), _clean(e.get("tag"))
            existing = self.by_shortcode(shortcode) if shortcode else None
            if existing:
                if (existing.name, existing.content, existing.tag) == (name.strip(), content, tag):
                    skipped += 1
                else:
                    self.update(existing.id, name, content, shortcode, tag)
                    updated += 1
                continue
            same = self._conn.execute(
                "SELECT 1 FROM snippets WHERE name = ? AND content = ?", (name.strip(), content)
            ).fetchone()
            if same:
                skipped += 1
            else:
                self.add(name, content, shortcode, tag)
                added += 1
        return added, updated, skipped
