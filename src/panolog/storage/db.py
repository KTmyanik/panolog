"""SQLite bağlantısı ve şema göçleri."""
from __future__ import annotations

import sqlite3
from pathlib import Path

_MIGRATIONS: list[str] = [
    # v1: çekirdek şema
    """
    CREATE TABLE items (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        category      TEXT NOT NULL,
        content_hash  TEXT NOT NULL,
        text          TEXT,
        html          TEXT,
        search_text   TEXT NOT NULL DEFAULT '',
        image_path    TEXT,
        thumb_path    TEXT,
        width         INTEGER,
        height        INTEGER,
        source_app    TEXT,
        created_at    REAL NOT NULL,
        copied_at     REAL NOT NULL,
        pinned        INTEGER NOT NULL DEFAULT 0,
        expires_at    REAL,
        UNIQUE (category, content_hash)
    );
    CREATE INDEX idx_items_list ON items (category, pinned DESC, copied_at DESC);
    CREATE TABLE settings (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    """,
    # v2: Dosyalar kategorisi. JSON listesi: [{"path", "size", "is_dir"}, ...]
    "ALTER TABLE items ADD COLUMN files TEXT;",
    # v3: hassas veri işareti ve listede gösterilecek maskeli metin
    """
    ALTER TABLE items ADD COLUMN sensitive INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE items ADD COLUMN masked_text TEXT;
    """,
    # v4: şablonlar (kalıcı; geçmiş limiti ve otomatik temizlikten bağımsız)
    """
    CREATE TABLE snippets (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        name        TEXT NOT NULL,
        shortcode   TEXT UNIQUE,
        content     TEXT NOT NULL,
        tag         TEXT,
        search_text TEXT NOT NULL DEFAULT '',
        created_at  REAL NOT NULL,
        updated_at  REAL NOT NULL
    );
    """,
    # v5: görsellerden OCR ile okunan metin. ocr_status: 0 = denenmedi, 1 = okundu
    # (metin boş olabilir), 2 = okunamadı (tekrar denenmez).
    """
    ALTER TABLE items ADD COLUMN ocr_text TEXT;
    ALTER TABLE items ADD COLUMN ocr_status INTEGER NOT NULL DEFAULT 0;
    """,
    # v6: OCR ön işlemesi iyileşti (görsel büyütülerek okunuyor). Daha önce okunan görseller
    # bir kez daha okunabilsin diye "denenmedi" durumuna alınır; eski metin, yenisi gelene
    # kadar aranabilir kalır.
    "UPDATE items SET ocr_status = 0 WHERE category = 'image';",
    # v7: yerel OCR modeli eklendi (kod ve numaralar çok daha doğru); aynı nedenle yeniden.
    "UPDATE items SET ocr_status = 0 WHERE category = 'image';",
    # v8: görsel şablonlar (ör. elle çizilmiş imza). PNG verisi doğrudan veritabanında durur:
    # küçüktür, kalıcıdır ve geçmişin görsel klasöründeki temizlikten etkilenmemelidir.
    "ALTER TABLE snippets ADD COLUMN image BLOB;",
]


def connect(path: Path | str) -> sqlite3.Connection:
    """Veritabanını açar, gerekiyorsa şemayı günceller. ':memory:' testlerde kullanılır."""
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    if str(path) != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
    # Silinen içerik dosyada kalmasın (hassas veri için önemli).
    conn.execute("PRAGMA secure_delete = ON")
    _migrate(conn)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    for i in range(version, len(_MIGRATIONS)):
        conn.executescript(_MIGRATIONS[i])
        conn.execute(f"PRAGMA user_version = {i + 1}")
        conn.commit()
