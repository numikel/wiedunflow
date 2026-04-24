# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Port for per-provider consent persistence (US-007).

Consent is tracked per cloud LLM provider ("anthropic", "openai"), keyed
independently from preferences: the adapter writes to a dedicated
``consent.yaml`` file (not ``config.yaml``) so clearing zgods is a single
file deletion and state/config separation is clean (ADR-0010).
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable


@runtime_checkable
class ConsentStore(Protocol):
    """Persistent per-provider consent store backing the banner gate."""

    def is_granted(self, provider: str) -> bool:
        """Return True iff the user has previously granted consent for ``provider``."""
        ...

    def grant(self, provider: str, timestamp: datetime) -> None:
        """Persist consent for ``provider`` with the wall-clock ``timestamp``."""
        ...

    def revoke(self, provider: str) -> None:
        """Remove any previously granted consent for ``provider``."""
        ...
