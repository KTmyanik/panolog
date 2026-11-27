"""Şablonların JSON olarak içe/dışa aktarımı."""
from __future__ import annotations

import json

from .repository import Snippet, SnippetError

FORMAT_VERSION = 1


def dumps(snippets: list[Snippet]) -> str:
    data = {
        "version": FORMAT_VERSION,
        "snippets": [
            {"name": s.name, "shortcode": s.shortcode, "content": s.content, "tag": s.tag}
            for s in snippets
        ],
    }
    return json.dumps(data, ensure_ascii=False, indent=2)


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
        if not isinstance(content, str) or not content.strip():
            raise SnippetError(f"{i}. kayıtta ('{name}') 'content' eksik.")
        entry = {"name": name, "content": content}
        for key in ("shortcode", "tag"):
            value = item.get(key)
            if value is not None and not isinstance(value, str):
                raise SnippetError(f"{i}. kayıtta ('{name}') '{key}' metin olmalı.")
            entry[key] = value
        if entry["shortcode"] and any(ch.isspace() for ch in entry["shortcode"].strip()):
            raise SnippetError(f"{i}. kayıtta ('{name}') kısa kod boşluk içeremez.")
        out.append(entry)
    return out
