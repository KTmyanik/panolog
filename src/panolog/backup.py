"""Geçmişin dışa aktarılması (JSON yedek, Markdown) ve JSON yedekten geri yüklenmesi."""
from __future__ import annotations

import json
import os
import re
import shutil
import time
from pathlib import Path

from PySide6.QtGui import QImage

from . import APP_NAME
from .classifier import Category
from .storage.images import ImageStore, hash_image
from .storage.models import FileRef, Item
from .storage.repository import Repository, files_hash, text_hash

FORMAT_VERSION = 1
_TEXT_CATEGORIES = (Category.TEXT, Category.CODE, Category.LINK)
CATEGORY_TITLES = {
    Category.TEXT: "Metinler",
    Category.CODE: "Kod",
    Category.LINK: "Linkler",
    Category.FILE: "Dosyalar",
    Category.IMAGE: "Görseller",
}


class BackupError(ValueError):
    pass


def exportable(items: list[Item]) -> list[Item]:
    """Süreli (kendiliğinden silinecek) öğeler yedeğe girmez: silinmek üzere işaretlidirler."""
    return [i for i in items if i.expires_at is None]


def images_dir_for(path: Path) -> Path:
    """Dışa aktarılan dosyanın yanındaki görsel klasörü: 'yedek.json' -> 'yedek_gorseller'."""
    return path.with_name(path.stem + "_gorseller")


def _copy_image(item: Item, folder: Path) -> str | None:
    """Görseli klasöre kopyalar; dışa aktarılan dosyaya göre göreli yolunu döndürür."""
    if not item.image_path or not os.path.isfile(item.image_path):
        return None
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{item.content_hash[:16]}.png"
    if not target.exists():
        shutil.copyfile(item.image_path, target)
    return f"{folder.name}/{target.name}"


def _stamp(ts: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))


# ---- JSON -------------------------------------------------------------------
def export_json(items: list[Item], path: Path) -> int:
    """Öğeleri JSON yedeğe yazar; görseller yandaki klasöre kopyalanır. Yazılan öğe sayısı."""
    path = Path(path)
    folder = images_dir_for(path)
    records = []
    for item in exportable(items):
        record: dict = {
            "category": item.category.value,
            "source_app": item.source_app,
            "created_at": item.created_at,
            "copied_at": item.copied_at,
            "pinned": item.pinned,
            "tag": item.tag,
        }
        if item.category in _TEXT_CATEGORIES:
            record["text"] = item.text or ""
            if item.html:
                record["html"] = item.html
            if item.kind:
                record["kind"] = item.kind
            if item.link_title:
                record["link_title"] = item.link_title
        elif item.category is Category.FILE:
            record["files"] = [
                {"path": f.path, "size": f.size, "is_dir": f.is_dir} for f in item.files
            ]
        else:
            relative = _copy_image(item, folder)
            if relative is None:
                continue  # görsel dosyası kaybolmuş; yedeğe boş kayıt yazma
            record.update(image=relative, width=item.width, height=item.height)
            if item.ocr_text:
                record["ocr_text"] = item.ocr_text
        records.append(record)
    data = {
        "app": APP_NAME,
        "version": FORMAT_VERSION,
        "exported_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "items": records,
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(records)


def import_json(path: Path, repo: Repository, images: ImageStore) -> tuple[int, int]:
    """JSON yedeği geçmişe ekler. (eklenen, zaten var olduğu için atlanan) döner.

    Var olan öğeler değiştirilmez; yedekteki sabitleme, etiket ve tarih yalnızca yeni
    eklenenlere uygulanır.
    """
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise BackupError(f"Yedek dosyası okunamadı: {exc}") from exc
    records = data.get("items") if isinstance(data, dict) else None
    if not isinstance(records, list):
        raise BackupError("Bu dosya bir Panolog yedeği değil ('items' listesi yok).")
    added = skipped = 0
    for record in records:
        if not isinstance(record, dict):
            continue
        try:
            category = Category(record.get("category"))
        except ValueError:
            continue
        common = {"source_app": record.get("source_app") or None}
        item = created = None
        if category in _TEXT_CATEGORIES:
            text = record.get("text")
            if not isinstance(text, str) or not text.strip():
                continue
            item, created = repo.add_item(
                category, text_hash(text), text=text, html=record.get("html") or None,
                kind=record.get("kind") or None, **common,
            )  # fmt: skip
            if created and record.get("link_title"):
                repo.set_link_meta(item.id, str(record["link_title"]), None)
        elif category is Category.FILE:
            files = [
                FileRef(str(f["path"]), f.get("size"), bool(f.get("is_dir")))
                for f in record.get("files") or []
                if isinstance(f, dict) and f.get("path")
            ]
            if not files:
                continue
            item, created = repo.add_item(
                category, files_hash(f.path for f in files), files=files, **common
            )
        else:
            relative = record.get("image")
            image = QImage(str(path.parent / relative)) if isinstance(relative, str) else QImage()
            if image.isNull():
                continue
            digest = hash_image(image)
            full, thumb = images.save(image, digest)
            item, created = repo.add_item(
                category, digest, image_path=str(full), thumb_path=str(thumb),
                width=image.width(), height=image.height(), **common,
            )  # fmt: skip
            if created and record.get("ocr_text"):
                repo.set_ocr(item.id, str(record["ocr_text"]))
        if not created:
            skipped += 1
            continue
        added += 1
        repo.restore_meta(
            item.id,
            created_at=record.get("created_at"),
            copied_at=record.get("copied_at"),
            pinned=bool(record.get("pinned")),
            tag=record.get("tag"),
        )
    images.wait()
    return added, skipped


# ---- Markdown -----------------------------------------------------------------
def _fence(text: str) -> str:
    """Metindeki en uzun ``` dizisinden bir fazla uzunlukta çit: içerik çiti kıramaz."""
    longest = max((len(m.group()) for m in re.finditer(r"`+", text)), default=0)
    return "`" * max(3, longest + 1)


def export_markdown(items: list[Item], path: Path) -> int:
    """Öğeleri okunabilir bir Markdown belgesine yazar; görseller yandaki klasöre kopyalanır."""
    path = Path(path)
    folder = images_dir_for(path)
    items = exportable(items)
    lines = [f"# {APP_NAME} geçmişi", "", f"Dışa aktarılma: {_stamp(time.time())} · {len(items)} öğe", ""]
    written = 0
    for category in (Category.TEXT, Category.CODE, Category.LINK, Category.FILE, Category.IMAGE):
        group = [i for i in items if i.category is category]
        if not group:
            continue
        lines += [f"## {CATEGORY_TITLES[category]}", ""]
        for item in group:
            meta = [_stamp(item.copied_at)]
            if item.source_app:
                meta.append(item.source_app)
            if item.tag:
                meta.append(f"#{item.tag}")
            if item.pinned:
                meta.append("sabit")
            head = " · ".join(meta)
            if category is Category.LINK:
                url = (item.text or "").strip()
                label = item.link_title or url
                lines += [f"- [{label.replace('[', '(').replace(']', ')')}](<{url}>) ({head})"]
            elif category is Category.FILE:
                lines += [f"- {head}"] + [f"  - `{f.path}`" for f in item.files]
            elif category is Category.IMAGE:
                relative = _copy_image(item, folder)
                if relative is None:
                    continue
                lines += [f"**{head}**", "", f"![{item.width}×{item.height}](<{relative}>)", ""]
            else:
                text = item.text or ""
                fence = _fence(text)
                lang = item.kind if item.kind in ("sql", "json", "xml") else ""
                lines += [f"**{head}**", "", f"{fence}{lang}", text, fence, ""]
            written += 1
        lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return written
