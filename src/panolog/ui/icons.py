"""Tray ikonu kod ile çizilir; ayrı bir görsel dosyası gerekmez."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap


def app_icon(paused: bool = False) -> QIcon:
    pix = QPixmap(64, 64)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    board = QColor("#8a8f98") if paused else QColor("#2f7de1")
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(board)
    p.drawRoundedRect(QRectF(10, 8, 44, 52), 8, 8)
    p.setBrush(QColor("#ffffff"))
    p.drawRoundedRect(QRectF(16, 18, 32, 36), 3, 3)
    p.setBrush(QColor("#1d4f91") if not paused else QColor("#5c6068"))
    p.drawRoundedRect(QRectF(22, 4, 20, 12), 4, 4)
    p.setBrush(board)
    for y in (25, 33, 41):
        p.drawRoundedRect(QRectF(21, y, 22 if y != 41 else 14, 4), 2, 2)
    p.end()
    return QIcon(pix)
