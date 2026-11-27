"""Uygulamanın yerel veri yolları. Her şey kullanıcının AppData klasöründe kalır."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from . import APP_NAME

# Uygulamanın eski adı. Veri klasörü ve dosya adları bir kereliğine yeni ada taşınır.
LEGACY_NAME = "Clipboarder"
DB_NAME = "panolog.db"
_LEGACY_DB_NAME = "clipboarder.db"


def _local_appdata() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local"))


def app_dir() -> Path:
    """Veri klasörü. PANOLOG_HOME ile (test/geliştirme için) değiştirilebilir."""
    override = os.environ.get("PANOLOG_HOME")
    base = Path(override) if override else _local_appdata() / APP_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base


def db_path() -> Path:
    return app_dir() / DB_NAME


def images_dir() -> Path:
    d = app_dir() / "images"
    d.mkdir(parents=True, exist_ok=True)
    return d


class LegacyMigrationError(Exception):
    """Eski veriler taşınamadı; kullanıcıya gösterilecek açıklamayı taşır."""


def migrate_legacy_data(base: Path | None = None) -> bool:
    """Eski addaki (Clipboarder) veri klasörünü yeni ada taşır. Taşıma yapıldıysa True.

    Yalnızca yeni klasörde henüz veritabanı yokken çalışır, yani bir kez. Veritabanında
    görsellerin tam yolu saklandığı için o yollar da yeni klasöre göre güncellenir.
    """
    if base is None:
        if os.environ.get("PANOLOG_HOME"):
            return False
        base = _local_appdata()
    old, new = base / LEGACY_NAME, base / APP_NAME
    if not (old / _LEGACY_DB_NAME).is_file() or (new / DB_NAME).exists():
        return False
    try:
        # Bekleyen yazmalar ana dosyaya alınır; -wal/-shm dosyaları geride kalmaz.
        conn = sqlite3.connect(str(old / _LEGACY_DB_NAME))
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.close()
        if new.exists():
            if any(new.iterdir()):
                raise LegacyMigrationError(
                    f"Yeni veri klasörü boş değil: {new}\nEski veriler şurada duruyor: {old}"
                )
            new.rmdir()
        os.rename(old, new)
        os.rename(new / _LEGACY_DB_NAME, new / DB_NAME)
        for suffix in ("-wal", "-shm"):
            leftover = new / (_LEGACY_DB_NAME + suffix)
            if leftover.exists():
                leftover.unlink()
        _rebase_image_paths(new / DB_NAME, old, new)
    except (OSError, sqlite3.Error) as exc:
        raise LegacyMigrationError(
            f"Eski veriler ({old}) yeni klasöre taşınamadı: {exc}\n"
            f"Eski sürüm ({LEGACY_NAME}) hâlâ çalışıyorsa kapatıp yeniden deneyin."
        ) from exc
    return True


def _rebase_image_paths(db: Path, old: Path, new: Path) -> None:
    prefix = os.path.normcase(str(old)) + os.sep
    conn = sqlite3.connect(str(db))
    try:
        rows = conn.execute("SELECT id, image_path, thumb_path FROM items").fetchall()
        for item_id, image_path, thumb_path in rows:
            moved = []
            for value in (image_path, thumb_path):
                if value and os.path.normcase(value).startswith(prefix):
                    value = str(new / value[len(prefix) :])
                moved.append(value)
            if moved != [image_path, thumb_path]:
                conn.execute(
                    "UPDATE items SET image_path = ?, thumb_path = ? WHERE id = ?", (*moved, item_id)
                )
        conn.commit()
    finally:
        conn.close()
