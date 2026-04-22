# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Port for redacting secrets from log strings (US-069).

Implementations match API-key-shaped substrings, bearer tokens and
``Authorization:`` headers and replace them with ``[REDACTED]`` before the
message reaches any log sink. The filter is deliberately pattern-only
(pattern list hardcoded per ADR-0010) to keep the redaction surface
predictable across providers.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class SecretFilter(Protocol):
    """Redact secret-shaped substrings from arbitrary log messages."""

    def redact(self, msg: str) -> str:
        """Return ``msg`` with every known secret pattern replaced by ``[REDACTED]``."""
        ...
