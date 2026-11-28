"""Clipboard geçmişi için veri erişim katmanı."""
from __future__ import annotations

import hashlib
import os
import sqlite3
import time
from typing import Callable, Iterable

from ..classifier import Category
from .models import FileRef, Item, files_to_json

_TR_FOLD = str.maketrans({"İ": "i", "I": "i", "ı": "i"})


def normalize_search(text: str) -> str:
    """Büyük/küçük harf ve Türkçe İ/I/ı/i farkını yok sayan arama biçimi."""
    return text.translate(_TR_FOLD).lower()


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()


def files_hash(paths: Iterable[str]) -> str:
    """Aynı dosya kümesi (sıra ve harf büyüklüğünden bağımsız) aynı hash'i verir."""
    return text_hash("\n".join(sorted(os.path.normcase(os.path.normpath(p)) for p in paths)))


def split_tag_query(query: str) -> tuple[str | None, str]:
    """Aramayı (etiket süzgeci, kalan metin) olarak ayırır.

    "#uat sorgu" -> ("uat", "sorgu"); "#" -> ("", ""); etiket yoksa (None, arama).
    """
    stripped = query.strip()
    if not stripped.startswith("#"):
        return None, query
    head, _, rest = stripped[1:].partition(" ")
    return head.lower(), rest


def clean_tag(tag: str | None) -> str | None:
    """Etiketi kaydetmeden önce sadeleştirir: baştaki '#', boşluklar atılır; boşsa None."""
    value = " ".join((tag or "").replace("#", " ").split())
    return value[:40] or None


def _like_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class Repository:
    def __init__(
        self,
        conn: sqlite3.Connection,
        clock: Callable[[], float] = time.time,
        on_delete: Callable[[Item], None] | None = None,
    ) -> None:
        self._conn = conn
        self._clock = clock
        self._on_delete = on_delete

    # ---- ekleme -------------------------------------------------------------
    def add_item(
        self,
        category: Category,
        content_hash: str,
        *,
        text: str | None = None,
        html: str | None = None,
        search_text: str | None = None,
        image_path: str | None = None,
        thumb_path: str | None = None,
        width: int | None = None,
        height: int | None = None,
        source_app: str | None = None,
        expires_at: float | None = None,
        files: list[FileRef] | None = None,
        sensitive: bool = False,
        masked_text: str | None = None,
        limit: int | None = None,
        kind: str | None = None,
    ) -> tuple[Item, bool]:
        """Öğeyi ekler; aynı içerik varsa yeni kayıt açmadan en üste taşır.

        (öğe, yeni_mi) döner.
        """
        now = self._clock()
        existing = self._conn.execute(
            "SELECT id FROM items WHERE category = ? AND content_hash = ?",
            (category.value, content_hash),
        ).fetchone()
        if existing:
            # Hassaslık durumu güncel ayarlara göre yenilenir. Yeni bir silinme süresi
            # geldiyse sayaç baştan başlar; sabitlenmiş öğeler ise hiç süreli olmaz.
            self._conn.execute(
                """UPDATE items SET copied_at = ?, source_app = COALESCE(?, source_app),
                          sensitive = ?, masked_text = ?,
                          expires_at = CASE WHEN pinned = 1 THEN NULL
                                            ELSE COALESCE(?, expires_at) END
                   WHERE id = ?""",
                (now, source_app, int(sensitive), masked_text, expires_at, existing["id"]),
            )
            self._conn.commit()
            return self.get(existing["id"]), False  # type: ignore[return-value]

        if search_text is None:
            # Dosyalarda yalnızca adlar aranır; klasör yolu eşleşme üretmesin.
            search_text = "\n".join(f.name for f in files) if files else (text or "")
        if masked_text is not None:
            search_text = masked_text  # maskelenen kısım aramayla da bulunamasın
        cur = self._conn.execute(
            """INSERT INTO items (category, content_hash, text, html, search_text, image_path,
                                  thumb_path, width, height, source_app, created_at, copied_at,
                                  expires_at, files, sensitive, masked_text, kind)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                category.value,
                content_hash,
                text,
                html,
                normalize_search(search_text),
                image_path,
                thumb_path,
                width,
                height,
                source_app,
                now,
                now,
                expires_at,
                files_to_json(files) if files else None,
                int(sensitive),
                masked_text,
                kind,
            ),
        )
        self._conn.commit()
        if limit is not None:
            self.enforce_limit(category, limit)
        return self.get(cur.lastrowid), True  # type: ignore[return-value, arg-type]

    # ---- okuma --------------------------------------------------------------
    def get(self, item_id: int) -> Item | None:
        row = self._conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        return Item.from_row(row) if row else None

    def list_items(self, category: Category, query: str = "") -> list[Item]:
        """Sabitlenenler üstte, sonra en yeni kopyalanan."""
        sql = "SELECT * FROM items WHERE category = ?"
        params: list[object] = [category.value]
        tag, query = split_tag_query(query)
        if tag is not None:
            # "#uat" yalnızca o etiketle başlayanları, tek başına "#" etiketli her şeyi getirir.
            sql += " AND tag IS NOT NULL AND lower(tag) LIKE ? ESCAPE '\\'"
            params.append(f"{_like_escape(tag)}%")
        q = normalize_search(query.strip())
        if q:
            sql += " AND search_text LIKE ? ESCAPE '\\'"
            params.append(f"%{_like_escape(q)}%")
        sql += " ORDER BY pinned DESC, copied_at DESC, id DESC"
        return [Item.from_row(r) for r in self._conn.execute(sql, params)]

    def count(self, category: Category | None = None) -> int:
        if category is None:
            return self._conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
        return self._conn.execute(
            "SELECT COUNT(*) FROM items WHERE category = ?", (category.value,)
        ).fetchone()[0]

    def image_files(self) -> set[str]:
        """DB'de referansı olan tüm görsel dosya yolları."""
        out: set[str] = set()
        for row in self._conn.execute("SELECT image_path, thumb_path FROM items"):
            out.update(p for p in row if p)
        return out

    # ---- güncelleme ---------------------------------------------------------
    def touch(self, item_id: int) -> None:
        self._conn.execute(
            "UPDATE items SET copied_at = ? WHERE id = ?", (self._clock(), item_id)
        )
        self._conn.commit()

    def set_pinned(self, item_id: int, pinned: bool) -> None:
        # Sabitlemek bilinçli bir "bunu sakla" kararıdır; otomatik silinme süresi kalkar.
        self._conn.execute(
            "UPDATE items SET pinned = ?, expires_at = CASE WHEN ? = 1 THEN NULL ELSE expires_at END"
            " WHERE id = ?",
            (1 if pinned else 0, 1 if pinned else 0, item_id),
        )
        self._conn.commit()

    # ---- etiketler ----------------------------------------------------------
    def set_tag(self, item_ids: Iterable[int], tag: str | None) -> int:
        """Öğeleri etiketler; etiketlenen öğe sabitlenir (otomatik temizlikte silinmesin).
        `tag` boşsa etiket kalkar, sabitleme olduğu gibi kalır. Etkilenen öğe sayısı döner."""
        tag = clean_tag(tag)
        changed = 0
        for item_id in item_ids:
            if tag is None:
                cur = self._conn.execute("UPDATE items SET tag = NULL WHERE id = ?", (item_id,))
            else:
                cur = self._conn.execute(
                    "UPDATE items SET tag = ?, pinned = 1, expires_at = NULL WHERE id = ?",
                    (tag, item_id),
                )
            changed += cur.rowcount
        self._conn.commit()
        return changed

    def set_expiry(self, item_id: int, expires_at: float) -> None:
        """Öğeye silinme zamanı verir; sabitlenmiş öğelere dokunmaz."""
        self._conn.execute(
            "UPDATE items SET expires_at = ? WHERE id = ? AND pinned = 0", (expires_at, item_id)
        )
        self._conn.commit()

    def restore_meta(
        self,
        item_id: int,
        *,
        created_at: float | None,
        copied_at: float | None,
        pinned: bool,
        tag: str | None,
    ) -> None:
        """Yedekten gelen öğenin tarihlerini, sabitlemesini ve etiketini geri yükler."""
        if isinstance(created_at, (int, float)) and isinstance(copied_at, (int, float)):
            self._conn.execute(
                "UPDATE items SET created_at = ?, copied_at = ? WHERE id = ?",
                (float(created_at), float(copied_at), item_id),
            )
        self._conn.execute(
            "UPDATE items SET pinned = ?, tag = ? WHERE id = ?",
            (1 if pinned else 0, clean_tag(tag if isinstance(tag, str) else None), item_id),
        )
        self._conn.commit()

    def tags(self, category: Category | None = None) -> list[tuple[str, int]]:
        """Kullanılan etiketler ve öğe sayıları, ada göre sıralı."""
        sql = "SELECT tag, COUNT(*) FROM items WHERE tag IS NOT NULL"
        params: list[object] = []
        if category is not None:
            sql += " AND category = ?"
            params.append(category.value)
        rows = self._conn.execute(sql + " GROUP BY tag", params).fetchall()
        return sorted(((r[0], r[1]) for r in rows), key=lambda r: normalize_search(r[0]))

    # ---- kod kategorisi ve linkler --------------------------------------------
    def reclassify(self, item_id: int, category: Category, kind: str | None) -> bool:
        """Öğenin kategorisini değiştirir. Hedefte aynı içerik varsa dokunmaz, False döner."""
        try:
            self._conn.execute(
                "UPDATE items SET category = ?, kind = ? WHERE id = ?",
                (category.value, kind, item_id),
            )
        except sqlite3.IntegrityError:
            return False
        self._conn.commit()
        return True

    def set_link_meta(self, item_id: int, title: str | None, icon: bytes | None) -> None:
        self._conn.execute(
            "UPDATE items SET link_title = ?, link_icon = ? WHERE id = ? AND category = ?",
            (title, icon, item_id, Category.LINK.value),
        )
        if title:  # başlıkla da aranabilsin
            row = self._conn.execute("SELECT text FROM items WHERE id = ?", (item_id,)).fetchone()
            if row is not None:
                self._conn.execute(
                    "UPDATE items SET search_text = ? WHERE id = ? AND category = ?",
                    (normalize_search(f"{row[0] or ''}\n{title}"), item_id, Category.LINK.value),
                )
        self._conn.commit()

    def all_items(self) -> list[Item]:
        """Tüm geçmiş: kategoriye, sonra kopyalanma zamanına göre (dışa aktarma için)."""
        rows = self._conn.execute("SELECT * FROM items ORDER BY category, copied_at DESC, id DESC")
        return [Item.from_row(r) for r in rows]

    # ---- kullanım sayaçları -----------------------------------------------------
    def bump_stat(self, category: Category, app: str | None, day: str | None = None) -> None:
        """Bugünün sayacını bir artırır. Yalnızca sayı tutulur; içerik kaydedilmez."""
        day = day or time.strftime("%Y-%m-%d", time.localtime(self._clock()))
        self._conn.execute(
            "INSERT INTO stats (day, category, app, count) VALUES (?, ?, ?, 1)"
            " ON CONFLICT (day, category, app) DO UPDATE SET count = count + 1",
            (day, category.value, (app or "").lower()),
        )
        self._conn.commit()

    def stats_by_day(self, since_day: str) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT day, SUM(count) FROM stats WHERE day >= ? GROUP BY day", (since_day,)
        )
        return {r[0]: r[1] for r in rows}

    def stats_by_app(self, since_day: str, limit: int = 8) -> list[tuple[str, int]]:
        rows = self._conn.execute(
            "SELECT app, SUM(count) AS n FROM stats WHERE day >= ? GROUP BY app"
            " ORDER BY n DESC, app LIMIT ?",
            (since_day, limit),
        )
        return [(r[0], r[1]) for r in rows]

    def stats_by_category(self, since_day: str) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT category, SUM(count) FROM stats WHERE day >= ? GROUP BY category", (since_day,)
        )
        return {r[0]: r[1] for r in rows}

    def clear_stats(self) -> None:
        self._conn.execute("DELETE FROM stats")
        self._conn.commit()

    def known_apps(self) -> list[str]:
        """Geçmişte ya da sayaçlarda görülen uygulama adları (kural eklerken önermek için)."""
        apps = {r[0].lower() for r in self._conn.execute(
            "SELECT DISTINCT source_app FROM items WHERE source_app IS NOT NULL AND source_app != ''"
        )}
        apps |= {r[0] for r in self._conn.execute("SELECT DISTINCT app FROM stats WHERE app != ''")}
        return sorted(apps)

    # ---- OCR ----------------------------------------------------------------
    def set_ocr(self, item_id: int, text: str | None) -> None:
        """Görselden okunan metni kaydeder ve aranabilir yapar. `text` None ise okuma
        başarısız sayılır ve bir daha denenmez."""
        if text is None:
            self._conn.execute("UPDATE items SET ocr_status = 2 WHERE id = ?", (item_id,))
        else:
            self._conn.execute(
                "UPDATE items SET ocr_text = ?, ocr_status = 1, search_text = ?"
                " WHERE id = ? AND category = ?",
                (text, normalize_search(text), item_id, Category.IMAGE.value),
            )
        self._conn.commit()

    def next_pending_ocr(self) -> Item | None:
        """OCR'ı henüz denenmemiş en yeni görsel."""
        row = self._conn.execute(
            "SELECT * FROM items WHERE category = ? AND ocr_status = 0"
            " ORDER BY copied_at DESC, id DESC LIMIT 1",
            (Category.IMAGE.value,),
        ).fetchone()
        return Item.from_row(row) if row else None

    def count_pending_ocr(self) -> int:
        return self._conn.execute(
            "SELECT COUNT(*) FROM items WHERE category = ? AND ocr_status = 0",
            (Category.IMAGE.value,),
        ).fetchone()[0]

    # ---- silme --------------------------------------------------------------
    def delete(self, item_id: int) -> bool:
        return bool(self._delete_where("id = ?", (item_id,)))

    def enforce_limit(self, category: Category, limit: int) -> int:
        """Limit sabitlenmemiş öğelere uygulanır; fazlası en eskiden başlanarak silinir."""
        limit = max(0, int(limit))
        return self._delete_where(
            """category = ? AND pinned = 0 AND id NOT IN (
                   SELECT id FROM items WHERE category = ? AND pinned = 0
                   ORDER BY copied_at DESC, id DESC LIMIT ?)""",
            (category.value, category.value, limit),
        )

    def purge_older_than(self, days: float) -> int:
        """N günden eski, sabitlenmemiş öğeleri siler."""
        cutoff = self._clock() - days * 86400
        return self._delete_where("pinned = 0 AND copied_at < ?", (cutoff,))

    def purge_expired(self) -> int:
        """Süresi dolan (ör. hassas veri) öğeleri siler; sabitlenmiş olsa bile."""
        return self._delete_where(
            "expires_at IS NOT NULL AND expires_at <= ?", (self._clock(),)
        )

    def clear(self, include_pinned: bool = False) -> int:
        return self._delete_where("1 = 1" if include_pinned else "pinned = 0", ())

    def _delete_where(self, where: str, params: Iterable[object]) -> int:
        params = tuple(params)
        rows = self._conn.execute(f"SELECT * FROM items WHERE {where}", params).fetchall()
        if not rows:
            return 0
        self._conn.executemany("DELETE FROM items WHERE id = ?", [(r["id"],) for r in rows])
        self._conn.commit()
        if self._on_delete:
            for r in rows:
                self._on_delete(Item.from_row(r))
        return len(rows)

    # ---- ayarlar (anahtar/değer) -------------------------------------------
    def get_setting(self, key: str) -> str | None:
        row = self._conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set_setting(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        self._conn.commit()
