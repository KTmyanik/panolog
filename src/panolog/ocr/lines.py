"""OCR motorlarının ortak çıktısı: metin parçaları ve bunların satırlara dizilmesi."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Line:
    """Okunan bir metin parçası ve görseldeki yeri (piksel)."""

    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    score: float = 1.0

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2

    @property
    def height(self) -> float:
        return self.y1 - self.y0


def group_lines(parts: list[Line]) -> list[list[Line]]:
    """Parçaları okuma sırasına dizer: üstten alta satırlar, satır içinde soldan sağa."""
    rows: list[list[Line]] = []
    for part in sorted(parts, key=lambda p: p.cy):
        if rows:
            last = rows[-1][-1]
            if abs(last.cy - part.cy) < max(part.height, last.height) * 0.5:
                rows[-1].append(part)
                continue
        rows.append([part])
    return [sorted(row, key=lambda p: p.x0) for row in rows]


def merge_rows(parts: list[Line]) -> list[Line]:
    """Aynı satırdaki parçaları tek bir Line'da birleştirir (okuma sırasıyla)."""
    return [
        Line(
            " ".join(p.text for p in row),
            min(p.x0 for p in row),
            min(p.y0 for p in row),
            max(p.x1 for p in row),
            max(p.y1 for p in row),
            min(p.score for p in row),
        )
        for row in group_lines(parts)
    ]


def lines_to_text(parts: list[Line]) -> str:
    return "\n".join(row.text for row in merge_rows(parts))
