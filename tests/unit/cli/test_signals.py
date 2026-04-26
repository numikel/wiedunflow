# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Unit tests for the SIGINT handler (US-027, US-028)."""

from __future__ import annotations

import io
import signal
from types import FrameType

import pytest

from wiedunflow.cli.signals import SigintHandler, install_sigint_handler


class _AbortSpy:
    """Capture hard_abort calls without actually terminating the test process."""

    def __init__(self) -> None:
        self.calls: list[int] = []

    def __call__(self, code: int) -> None:
        self.calls.append(code)


def _fire_sigint(
    handler: SigintHandler, monotonic_value: float, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Invoke the private handler directly with a controlled monotonic clock."""
    monkeypatch.setattr("wiedunflow.cli.signals.time.monotonic", lambda: monotonic_value)
    handler._handle(signal.SIGINT, None)  # type: ignore[attr-defined]


def test_first_sigint_sets_should_finish_and_does_not_abort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spy = _AbortSpy()
    handler = SigintHandler(stderr=io.StringIO(), hard_abort=spy)
    _fire_sigint(handler, monotonic_value=100.0, monkeypatch=monkeypatch)
    assert handler.should_finish.is_set()
    assert spy.calls == []
    handler.restore()


def test_second_sigint_within_window_triggers_hard_abort(monkeypatch: pytest.MonkeyPatch) -> None:
    spy = _AbortSpy()
    handler = SigintHandler(stderr=io.StringIO(), hard_abort=spy)

    _fire_sigint(handler, monotonic_value=100.0, monkeypatch=monkeypatch)
    # Second SIGINT 1 second later — inside the 2s window.
    _fire_sigint(handler, monotonic_value=101.0, monkeypatch=monkeypatch)

    assert spy.calls == [130]
    handler.restore()


def test_second_sigint_outside_window_treated_as_new_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spy = _AbortSpy()
    handler = SigintHandler(stderr=io.StringIO(), hard_abort=spy)

    _fire_sigint(handler, monotonic_value=100.0, monkeypatch=monkeypatch)
    # 5 seconds later — outside the 2s hard-abort window.
    _fire_sigint(handler, monotonic_value=105.0, monkeypatch=monkeypatch)

    assert spy.calls == []  # No hard abort yet.
    assert handler.should_finish.is_set()
    handler.restore()


def test_handler_prints_banner_to_stderr(monkeypatch: pytest.MonkeyPatch) -> None:
    buf = io.StringIO()
    handler = SigintHandler(stderr=buf, hard_abort=_AbortSpy())
    _fire_sigint(handler, monotonic_value=0.0, monkeypatch=monkeypatch)
    handler.restore()
    assert "Finishing current lesson" in buf.getvalue()


def test_install_registers_signal_and_returns_handler() -> None:
    handler = install_sigint_handler(stderr=io.StringIO(), hard_abort=_AbortSpy())
    try:
        current = signal.getsignal(signal.SIGINT)
        assert callable(current)
    finally:
        handler.restore()


def test_restore_cancels_pending_timer(monkeypatch: pytest.MonkeyPatch) -> None:
    spy = _AbortSpy()
    handler = SigintHandler(stderr=io.StringIO(), hard_abort=spy)
    _fire_sigint(handler, monotonic_value=0.0, monkeypatch=monkeypatch)
    # Cancel before the safety timer fires.
    handler.restore()
    assert handler._timer is None  # type: ignore[attr-defined]


def test_double_restore_is_safe() -> None:
    handler = SigintHandler(stderr=io.StringIO(), hard_abort=_AbortSpy())
    handler.install()
    handler.restore()
    handler.restore()  # second call must not raise


# Ensure the signature check — handler callback accepts (int, frame|None).
def test_handler_accepts_frame_none(monkeypatch: pytest.MonkeyPatch) -> None:
    spy = _AbortSpy()
    handler = SigintHandler(stderr=io.StringIO(), hard_abort=spy)
    monkeypatch.setattr("wiedunflow.cli.signals.time.monotonic", lambda: 0.0)
    frame: FrameType | None = None
    handler._handle(signal.SIGINT, frame)  # type: ignore[attr-defined]
    handler.restore()
