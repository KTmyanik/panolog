from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass

from ..classifier import Category


@dataclass(frozen=True)
class FileRef:
    """Kopyalanan bir dosya/klasörün yolu ve kopyalama anındaki bilgileri."""

    path: str
    size: int | None = None  # klasörlerde veya okunamadıysa None
    is_dir: bool = False

    @property
    def name(self) -> str:
        return os.path.basename(self.path.rstrip("\\/")) or self.path

    @classmethod
    def from_path(cls, path: str) -> "FileRef":
        path = os.path.normpath(path)
        try:
            st = os.stat(path)
        except OSError:
            return cls(path)
        is_dir = os.path.isdir(path)
        return cls(path, None if is_dir else st.st_size, is_dir)


def files_to_json(files: list[FileRef]) -> str:
    return json.dumps(
        [{"path": f.path, "size": f.size, "is_dir": f.is_dir} for f in files], ensure_ascii=False
    )


def files_from_json(raw: str | None) -> tuple[FileRef, ...]:
    if not raw:
        return ()
    try:
        return tuple(
            FileRef(str(d["path"]), d.get("size"), bool(d.get("is_dir"))) for d in json.loads(raw)
        )
    except (ValueError, KeyError, TypeError):
        return ()


@dataclass(frozen=True)
class Item:
    id: int
    category: Category
    content_hash: str
    text: str | None
    html: str | None
    image_path: str | None
    thumb_path: str | None
    width: int | None
    height: int | None
    source_app: str | None
    created_at: float
    copied_at: float
    pinned: bool
    expires_at: float | None
    files: tuple[FileRef, ...] = ()
    sensitive: bool = False
    masked_text: str | None = None  # doluysa listede asıl metin yerine bu gösterilir
    ocr_text: str | None = None  # görselden okunan metin
    ocr_done: bool = False  # OCR çalıştı (metin boş çıkmış olabilir)

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Item":
        return cls(
            id=row["id"],
            category=Category(row["category"]),
            content_hash=row["content_hash"],
            text=row["text"],
            html=row["html"],
            image_path=row["image_path"],
            thumb_path=row["thumb_path"],
            width=row["width"],
            height=row["height"],
            source_app=row["source_app"],
            created_at=row["created_at"],
            copied_at=row["copied_at"],
            pinned=bool(row["pinned"]),
            expires_at=row["expires_at"],
            files=files_from_json(row["files"]),
            sensitive=bool(row["sensitive"]),
            masked_text=row["masked_text"],
            ocr_text=row["ocr_text"],
            ocr_done=row["ocr_status"] == 1,
        )
