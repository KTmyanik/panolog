"""Şablonların JSON olarak içe/dışa aktarımı."""
from __future__ import annotations

import base64
import binascii
import json

from .repository import MAX_IMAGE_BYTES, PNG_MAGIC, Snippet, SnippetError

FORMAT_VERSION = 1


def dumps(snippets: list[Snippet]) -> str:
    data = {
        "version": FORMAT_VERSION,
        "snippets": [_entry(s) for s in snippets],
    }
    return json.dumps(data, ensure_ascii=False, indent=2)


def _entry(s: Snippet) -> dict:
    entry = {"name": s.name, "shortcode": s.shortcode, "content": s.content, "tag": s.tag}
    if s.image is not None:  # görsel şablon: PNG verisi base64 olarak
        entry["image"] = base64.b64encode(s.image).decode("ascii")
    return entry


def _decode_image(value, where: str) -> bytes:
    if not isinstance(value, str):
        raise SnippetError(f"{where} 'image' metin (base64) olmalı.")
    try:
        data = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise SnippetError(f"{where} 'image' geçerli base64 değil.") from exc
    if not data.startswith(PNG_MAGIC):
        raise SnippetError(f"{where} 'image' bir PNG görseli değil.")
    if len(data) > MAX_IMAGE_BYTES:
        raise SnippetError(f"{where} 'image' çok büyük (en çok 2 MB).")
    return data


def loads(raw: str) -> list[dict]:
    """JSON'u doğrular ve içe aktarılacak kayıtları döndürür. Hatalıysa SnippetError."""
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise SnippetError(f"Geçerli bir JSON dosyası değil: {exc}") from exc
    items = data.get("snippets") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise SnippetError("Dosyada 'snippets' listesi bulunamadı.")
    out: list[dict] = []
    for i, item in enumerate(items, 1):
        if not isinstance(item, dict):
            raise SnippetError(f"{i}. kayıt bir nesne değil.")
        name, content = item.get("name"), item.get("content")
        if not isinstance(name, str) or not name.strip():
            raise SnippetError(f"{i}. kayıtta 'name' eksik.")
        image = None
        if item.get("image") is not None:
            image = _decode_image(item["image"], f"{i}. kayıtta ('{name}')")
            content = ""
        elif not isinstance(content, str) or not content.strip():
            raise SnippetError(f"{i}. kayıtta ('{name}') 'content' eksik.")
        entry = {"name": name, "content": content}
        if image is not None:
            entry["image"] = image
        for key in ("shortcode", "tag"):
            value = item.get(key)
            if value is not None and not isinstance(value, str):
                raise SnippetError(f"{i}. kayıtta ('{name}') '{key}' metin olmalı.")
            entry[key] = value
        if entry["shortcode"] and any(ch.isspace() for ch in entry["shortcode"].strip()):
            raise SnippetError(f"{i}. kayıtta ('{name}') kısa kod boşluk içeremez.")
        out.append(entry)
    return out
