from datetime import datetime

from panolog.app import default_image_name
from panolog.monitor.pause import (
    SKIP_ARMED_SECONDS,
    SKIP_ECHO_SECONDS,
    PauseState,
    remaining_label,
)
from panolog.ui.preview import clip_text


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def make():
    clock = Clock()
    return PauseState(clock), clock


# ---- duraklatma -------------------------------------------------------------
def test_starts_active():
    state, _ = make()
    assert state.allow() and not state.is_paused()
    status = state.status()
    assert (status.paused, status.until, status.skip_next) == (False, None, False)
    assert state.next_change() is None


def test_pause_and_resume():
    state, clock = make()
    state.pause()
    clock.now += 10_000  # süresiz duraklatma kendiliğinden bitmez
    assert state.is_paused() and not state.allow() and state.next_change() is None
    state.resume()
    assert state.allow()


def test_timed_pause_ends_by_itself():
    state, clock = make()
    state.pause_for(300)
    assert state.status().until == 1300.0 and state.next_change() == 1300.0
    clock.now += 299
    assert state.is_paused() and not state.allow()
    clock.now += 1
    assert not state.is_paused() and state.allow()
    assert state.status().until is None and state.next_change() is None


def test_resume_cancels_timed_pause():
    state, clock = make()
    state.pause_for(300)
    state.resume()
    assert state.allow() and state.status().until is None


# ---- sonraki kopyayı kaydetme -----------------------------------------------
def test_skip_next_swallows_exactly_one_copy():
    state, clock = make()
    state.skip_next()
    assert state.status().skip_next
    assert not state.allow()  # atlanan kopya
    assert not state.status().skip_next
    clock.now += SKIP_ECHO_SECONDS + 0.1
    assert state.allow() and state.allow()


def test_skip_next_also_swallows_immediate_repeats_of_the_same_copy():
    state, clock = make()
    state.skip_next()
    assert not state.allow()
    clock.now += 0.3  # aynı Ctrl+C'nin ikinci clipboard bildirimi
    assert not state.allow()
    clock.now += SKIP_ECHO_SECONDS
    assert state.allow()


def test_skip_next_expires_when_unused():
    state, clock = make()
    state.skip_next()
    assert state.next_change() == 1000.0 + SKIP_ARMED_SECONDS
    clock.now += SKIP_ARMED_SECONDS
    assert not state.status().skip_next
    assert state.allow()


def test_skip_next_can_be_cancelled_and_is_cleared_by_pause():
    state, _ = make()
    state.skip_next()
    state.skip_next(False)
    assert state.allow()
    state.skip_next()
    state.pause()
    state.resume()
    assert not state.status().skip_next and state.allow()


def test_remaining_label():
    assert remaining_label(300) == "5 dk"
    assert remaining_label(241) == "5 dk"
    assert remaining_label(60) == "1 dk"
    assert remaining_label(59.4) == "59 sn"
    assert remaining_label(-3) == "0 sn"


# ---- metin önizlemesi -------------------------------------------------------
def test_clip_text_short_text_is_untouched():
    assert clip_text("a\nb\r\nc") == ("a\nb\nc", 0)
    assert clip_text("") == ("", 0)


def test_clip_text_limits_lines_and_chars():
    text = "\n".join(f"satır {i}" for i in range(500))
    shown, hidden = clip_text(text, max_lines=200)
    assert shown.count("\n") == 199 and hidden == 300
    shown, hidden = clip_text("x" * 50_000, max_chars=1000)
    assert shown == "x" * 1000 + "…" and hidden == 0
    shown, hidden = clip_text("aaaa\nbbbb\ncccc", max_chars=7)
    assert shown == "aaaa\nbb…" and hidden == 1


# ---- dosya adı --------------------------------------------------------------
def test_default_image_name_is_a_valid_windows_file_name():
    name = default_image_name(datetime(2026, 11, 27, 9, 5, 7))
    assert name == "Panolog 2026-11-27 090507.png"
    assert not set(name) & set('\\/:*?"<>|')
