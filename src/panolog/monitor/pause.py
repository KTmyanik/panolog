"""Kaydetmeyi duraklatma durumu: süresiz, süreli ve "yalnızca sonraki kopya"."""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

# "Sonraki kopyayı kaydetme" kullanılmazsa bu kadar sonra kendiliğinden iptal olur;
# unutulup saatler sonraki ilgisiz bir kopyayı yutmasın.
SKIP_ARMED_SECONDS = 120.0
# Bazı uygulamalar tek bir Ctrl+C için clipboard'ı art arda birkaç kez yazar; atlanan
# kopyanın hemen ardından gelen bu yinelemeler de atlanır.
SKIP_ECHO_SECONDS = 1.0


@dataclass(frozen=True)
class PauseStatus:
    paused: bool
    until: float | None  # süreli duraklatmanın biteceği an; süresizse None
    skip_next: bool

    @property
    def remaining(self) -> float | None:
        return None if self.until is None else max(0.0, self.until - time.time())


class PauseState:
    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._paused = False
        self._until: float | None = None
        self._skip_deadline: float | None = None
        self._echo_until = 0.0

    # ---- komutlar -----------------------------------------------------------
    def pause(self) -> None:
        self._paused, self._until = True, None
        self._skip_deadline = None

    def pause_for(self, seconds: float) -> None:
        self._paused, self._until = True, self._clock() + seconds
        self._skip_deadline = None

    def resume(self) -> None:
        self._paused, self._until = False, None

    def skip_next(self, armed: bool = True) -> None:
        self._skip_deadline = self._clock() + SKIP_ARMED_SECONDS if armed else None

    # ---- sorgular -----------------------------------------------------------
    def _expire(self) -> None:
        now = self._clock()
        if self._paused and self._until is not None and now >= self._until:
            self._paused, self._until = False, None
        if self._skip_deadline is not None and now >= self._skip_deadline:
            self._skip_deadline = None

    def status(self) -> PauseStatus:
        self._expire()
        return PauseStatus(self._paused, self._until, self._skip_deadline is not None)

    def is_paused(self) -> bool:
        self._expire()
        return self._paused

    def next_change(self) -> float | None:
        """Durumun kendiliğinden değişeceği an (arayüzü o zaman yenilemek için)."""
        self._expire()
        times = [t for t in (self._until, self._skip_deadline) if t is not None]
        return min(times) if times else None

    def allow(self) -> bool:
        """Kaydedilebilir bir kopya geldi: geçmişe eklensin mi?

        "Sonraki kopyayı kaydetme" kuruluysa bu çağrı onu tüketir.
        """
        self._expire()
        now = self._clock()
        if self._paused or now < self._echo_until:
            return False
        if self._skip_deadline is not None:
            self._skip_deadline = None
            self._echo_until = now + SKIP_ECHO_SECONDS
            return False
        return True


def remaining_label(seconds: float) -> str:
    """Kalan süre, menüde gösterilecek biçimde ("4 dk", "45 sn")."""
    seconds = max(0, int(round(seconds)))
    if seconds >= 60:
        return f"{(seconds + 59) // 60} dk"
    return f"{seconds} sn"
