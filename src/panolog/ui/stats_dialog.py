"""Kullanım istatistikleri: günlük kopyalama sayısı, en çok kullanılan uygulamalar."""
from __future__ import annotations

import time
from collections.abc import Callable
from datetime import date, timedelta

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import APP_NAME
from ..backup import CATEGORY_TITLES
from ..classifier import Category
from ..storage.repository import Repository
from .formatting import app_label
from .icons import app_icon

DAYS = 14
_BAR = QColor("#2f7de1")
_BAR_TODAY = QColor("#f0883e")


def day_range(today: date, days: int = DAYS) -> list[date]:
    """Bugün dahil son `days` gün, eskiden yeniye."""
    return [today - timedelta(days=offset) for offset in range(days - 1, -1, -1)]


def nice_max(value: int) -> int:
    """Grafik ekseninin üst sınırı: değerden büyük ilk "yuvarlak" sayı (5, 10, 20, 50…)."""
    if value <= 5:
        return 5
    magnitude = 10 ** (len(str(value)) - 1)
    for factor in (1, 2, 5, 10):
        if value <= factor * magnitude:
            return factor * magnitude
    return 10 * magnitude


class _Bars(QWidget):
    """Dikey çubuk grafik: (etiket, değer, vurgulu mu) üçlüleri."""

    def __init__(self, data: list[tuple[str, int, bool]]) -> None:
        super().__init__()
        self._data = data
        self.setMinimumSize(520, 190)

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        text = self.palette().color(self.foregroundRole())
        muted = QColor(text)
        muted.setAlpha(120)
        left, top, bottom = 34.0, 16.0, 24.0
        width, height = self.width() - left - 6, self.height() - top - bottom
        top_value = nice_max(max((v for _l, v, _h in self._data), default=0))
        small = QFont(self.font())
        small.setPointSizeF(max(7.0, small.pointSizeF() - 1.5))
        p.setFont(small)
        for fraction in (0.0, 0.5, 1.0):
            y = top + height * (1 - fraction)
            p.setPen(muted)
            p.drawLine(int(left), int(y), int(left + width), int(y))
            p.drawText(
                QRectF(0, y - 8, left - 6, 16),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                str(round(top_value * fraction)),
            )
        slot = width / max(1, len(self._data))
        for i, (label, value, highlight) in enumerate(self._data):
            bar_h = height * value / top_value if top_value else 0
            x = left + i * slot + slot * 0.18
            rect = QRectF(x, top + height - bar_h, slot * 0.64, bar_h)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_BAR_TODAY if highlight else _BAR)
            p.drawRoundedRect(rect, 2, 2)
            p.setPen(text)
            if value:
                p.drawText(
                    QRectF(left + i * slot, rect.top() - 15, slot, 14),
                    Qt.AlignmentFlag.AlignCenter,
                    str(value),
                )
            p.setPen(muted)
            p.drawText(
                QRectF(left + i * slot, top + height + 4, slot, 16),
                Qt.AlignmentFlag.AlignCenter,
                label,
            )


class StatsDialog(QDialog):
    def __init__(self, repo: Repository, today: date | None = None) -> None:
        super().__init__()
        self._repo = repo
        self.setWindowTitle(f"{APP_NAME} – İstatistikler")
        self.setWindowIcon(app_icon())
        today = today or date.fromtimestamp(time.time())
        days = day_range(today)
        since = days[0].isoformat()
        by_day = repo.stats_by_day(since)
        self.day_counts = [(d, by_day.get(d.isoformat(), 0)) for d in days]
        self.total = sum(count for _d, count in self.day_counts)
        self.apps = repo.stats_by_app(since)
        self.categories = repo.stats_by_category(since)

        root = QVBoxLayout(self)
        today_count = self.day_counts[-1][1]
        average = self.total / len(days)
        summary = QLabel(
            f"<b>Son {DAYS} gün:</b> {self.total} kopya · günde ortalama {average:.1f} · "
            f"bugün {today_count}"
        )
        root.addWidget(summary)
        root.addWidget(
            _Bars([(f"{d.day}.{d.month}", count, d == today) for d, count in self.day_counts])
        )

        columns = QHBoxLayout()
        columns.addWidget(self._list("En çok kopyalanan uygulamalar", [
            (app_label(app) or "(bilinmiyor)", count) for app, count in self.apps
        ]))  # fmt: skip
        columns.addWidget(self._list("Türe göre", [
            (CATEGORY_TITLES[c], self.categories[c.value])
            for c in Category if self.categories.get(c.value)
        ]))  # fmt: skip
        root.addLayout(columns)

        note = QLabel(
            "Yalnızca sayılar tutulur (gün, tür, uygulama adı); kopyalanan içerik burada "
            "saklanmaz. Sayaçlar bu sürümden itibaren işler."
        )
        note.setWordWrap(True)
        note.setEnabled(False)
        root.addWidget(note)

        buttons = QHBoxLayout()
        reset = QPushButton("Sayaçları sıfırla")
        reset.setAutoDefault(False)
        reset.clicked.connect(self._reset)
        buttons.addWidget(reset)
        buttons.addStretch(1)
        close = QPushButton("Kapat")
        close.setDefault(True)
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        root.addLayout(buttons)

    def _list(self, title: str, rows: list[tuple[str, int]]) -> QWidget:
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 6, 0, 6)
        head = QLabel(f"<b>{title}</b>")
        lay.addWidget(head)
        if not rows:
            lay.addWidget(QLabel("Henüz veri yok"))
        total = sum(count for _n, count in rows) or 1
        for name, count in rows:
            row = QLabel(f"{name}  —  {count}  (%{round(100 * count / total)})")
            row.setTextFormat(Qt.TextFormat.PlainText)
            lay.addWidget(row)
        lay.addStretch(1)
        return box

    def _reset(self) -> None:
        answer = QMessageBox.question(
            self,
            APP_NAME,
            "Tüm kullanım sayaçları silinsin mi? Geçmişiniz etkilenmez.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._repo.clear_stats()
            self.accept()


def open_stats(repo: Repository, runner: Callable[[QDialog], None] | None = None) -> None:
    dialog = StatsDialog(repo)
    (runner or (lambda d: d.exec()))(dialog)
