# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Tests for the FakeClock test double (F-006 — moved from src to tests/fakes)."""

from __future__ import annotations

from datetime import UTC, datetime

from tests.fakes.clock import FIXED_NOW, FakeClock
from wiedunflow.interfaces.ports import Clock


def test_fake_clock_returns_fixed_now() -> None:
    assert FakeClock().now() == FIXED_NOW
    assert FakeClock().now() == datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


def test_fake_clock_satisfies_clock_protocol() -> None:
    assert isinstance(FakeClock(), Clock)
