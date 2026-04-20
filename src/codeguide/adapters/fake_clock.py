# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

from datetime import UTC, datetime

FIXED_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
"""Fixed timestamp returned by FakeClock — 2026-01-01T12:00:00+00:00."""


class FakeClock:
    """Deterministic Clock for testing — always returns FIXED_NOW.

    Implements the Clock Protocol via duck typing.  Injecting FakeClock
    makes any timestamp-dependent logic fully deterministic in tests.
    """

    def now(self) -> datetime:
        """Return the fixed UTC datetime 2026-01-01T12:00:00+00:00.

        Returns:
            A timezone-aware datetime fixed at FIXED_NOW.
        """
        return FIXED_NOW
