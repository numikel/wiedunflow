# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Unit tests for SystemClock — production Clock adapter (F-006)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from wiedunflow.adapters.system_clock import SystemClock
from wiedunflow.interfaces.ports import Clock


def test_system_clock_returns_utc_aware_datetime() -> None:
    """SystemClock.now() returns a UTC-aware datetime within tolerance of wall clock."""
    before = datetime.now(UTC)
    now = SystemClock().now()
    after = datetime.now(UTC)
    assert now.tzinfo is UTC
    assert before - timedelta(seconds=1) <= now <= after + timedelta(seconds=1)


def test_system_clock_satisfies_clock_protocol() -> None:
    """SystemClock structurally matches the Clock Protocol via runtime_checkable."""
    assert isinstance(SystemClock(), Clock)


def test_system_clock_now_is_not_constant() -> None:
    """Two consecutive now() calls should differ — SystemClock must not be a fake."""
    import time

    a = SystemClock().now()
    time.sleep(0.001)
    b = SystemClock().now()
    assert b > a, "SystemClock returned identical timestamps — looks like a fake"
