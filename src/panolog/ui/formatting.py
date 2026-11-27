"""Liste satırları için saf biçimlendirme yardımcıları."""
from __future__ import annotations

import time
from datetime import datetime


def relative_time(ts: float, now: float | None = None) -> str:
    now = time.time() if now is None else now
    delta = max(0, int(now - ts))
    if delta < 60:
        return "az önce"
    if delta < 3600:
        return f"{delta // 60} dk önce"
    if delta < 86400:
        return f"{delta // 3600} sa önce"
    then = datetime.fromtimestamp(ts)
    if delta < 7 * 86400:
        return f"{delta // 86400} gün önce {then:%H:%M}"
    return f"{then:%d.%m.%Y %H:%M}"


def preview_lines(text: str, max_lines: int = 2, max_chars: int = 160) -> list[str]:
    """Metnin boş olmayan ilk satırları; fazlası varsa son satıra '…' eklenir."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    out = [ln[:max_chars] + ("…" if len(ln) > max_chars else "") for ln in lines[:max_lines]]
    if len(lines) > max_lines and out and not out[-1].endswith("…"):
        out[-1] += " …"
    return out or [""]


def human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            break
        value /= 1024
    if unit == "B":
        return f"{int(value)} B"
    return f"{value:.1f}".replace(".", ",") + f" {unit}"


def files_title(names: list[str]) -> str:
    if not names:
        return "(dosya yok)"
    return names[0] if len(names) == 1 else f"{names[0]}  +{len(names) - 1} öğe daha"


def files_detail(files) -> str:
    """Boyut özeti: tek dosyada boyutu, klasörde 'Klasör', çokluda öğe sayısı ve toplam."""
    if len(files) == 1:
        f = files[0]
        if f.is_dir:
            return "Klasör"
        return human_size(f.size) if f.size is not None else "boyut bilinmiyor"
    total = sum(f.size for f in files if f.size is not None)
    dirs = sum(1 for f in files if f.is_dir)
    text = f"{len(files)} öğe"
    if dirs < len(files):
        text += f", {human_size(total)}"
    if dirs:
        text += f" + {dirs} klasör"
    return text


def app_label(source_app: str | None) -> str:
    if not source_app:
        return ""
    return source_app[:-4] if source_app.lower().endswith(".exe") else source_app
