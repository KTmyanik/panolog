"""OCR işlerini arayüzü bloklamadan, tek bir arka plan iş parçacığında sırayla çalıştırır."""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtGui import QImage

from .engine import OcrError, OcrResult, OcrUnavailable
from .pipeline import read_image


class _Signals(QObject):
    done = Signal(int, object, bool)  # (öğe id, OcrResult | Exception, etkileşimli mi)


class _Job(QRunnable):
    def __init__(self, item_id, source, interactive, signals, run) -> None:
        super().__init__()
        self._args = (item_id, source, interactive, signals, run)

    def run(self) -> None:
        item_id, source, interactive, signals, run = self._args
        try:
            image = source if isinstance(source, QImage) else QImage(source)
            outcome: object = run(image)
        except (OcrUnavailable, OcrError) as exc:
            outcome = exc
        except Exception as exc:  # noqa: BLE001 - iş parçacığı sessizce ölmesin
            outcome = OcrError(f"Metin okunamadı: {exc}")
        signals.done.emit(item_id, outcome, interactive)


class OcrService(QObject):
    """`interactive`: kullanıcı Ctrl+O ile istedi (sonuç ona gösterilir);
    değilse arka plan indekslemesidir."""

    finished = Signal(int, object, bool)  # (öğe id, OcrResult, etkileşimli mi)
    failed = Signal(int, object, bool)  # (öğe id, OcrUnavailable | OcrError, etkileşimli mi)

    def __init__(self, run: Callable[[QImage], OcrResult] = read_image) -> None:
        super().__init__()
        self._run = run
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._signals = _Signals(self)
        self._signals.done.connect(self._on_done)
        self._active: dict[int, bool] = {}  # öğe id -> etkileşimli mi

    def is_busy(self, item_id: int | None = None) -> bool:
        return bool(self._active) if item_id is None else item_id in self._active

    def request(self, item_id: int, source: QImage | str, interactive: bool) -> None:
        """`source`: QImage ya da PNG yolu. Aynı öğe zaten sıradaysa yeniden eklenmez;
        yalnızca etkileşimli isteğe yükseltilir."""
        if item_id in self._active:
            self._active[item_id] = self._active[item_id] or interactive
            return
        self._active[item_id] = interactive
        # Etkileşimli istek, bekleyen arka plan işlerinin önüne geçer.
        self._pool.start(
            _Job(item_id, source, interactive, self._signals, self._run), 1 if interactive else 0
        )

    def _on_done(self, item_id: int, outcome: object, _interactive: bool) -> None:
        interactive = self._active.pop(item_id, False)
        if isinstance(outcome, OcrResult):
            self.finished.emit(item_id, outcome, interactive)
        else:
            self.failed.emit(item_id, outcome, interactive)

    def wait(self) -> None:
        self._pool.waitForDone()
