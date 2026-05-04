# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

from datetime import UTC, datetime


class SystemClock:
    """Production Clock — wraps :func:`datetime.now(UTC)`.

    Implements the :class:`wiedunflow.interfaces.ports.Clock` Protocol via duck
    typing. Use :class:`tests.fakes.clock.FakeClock` in tests for determinism.
    """

    def now(self) -> datetime:
        """Return the current UTC datetime."""
        return datetime.now(UTC)
