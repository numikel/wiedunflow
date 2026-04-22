# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""SecretFilter — redact API-key-shaped substrings from log messages (US-069).

Pattern list is authoritative per ADR-0010. The filter replaces every
matched substring with the literal ``"[REDACTED]"``. Predictability over
recall: new provider key shapes are added by amending :data:`_PATTERNS`,
never by entropy-based heuristics that would surface false positives on
commit hashes, Pygments spans, or base64-encoded test fixtures.
"""

from __future__ import annotations

import re
from typing import Final

_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    # Anthropic session / admin / sk-ant keys — sk-ant-* cover all current variants.
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"),
    # OpenAI project-scoped keys (sk-proj-…).
    re.compile(r"sk-proj-[A-Za-z0-9_\-]{20,}"),
    # OpenAI classic secret keys and OpenAI-compatible deployments.
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    # OAuth / proxy bearer tokens.
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{16,}"),
    # Authorization HTTP header with any scheme.
    re.compile(r"(?i)authorization:\s*\S+"),
    # Generic long hex blobs (SHA/HMAC/session tokens).
    re.compile(r"\b[A-Fa-f0-9]{40,}\b"),
)

_REDACTED: Final[str] = "[REDACTED]"


def redact(msg: str) -> str:
    """Return ``msg`` with every known secret pattern replaced by ``[REDACTED]``."""
    out = msg
    for pattern in _PATTERNS:
        out = pattern.sub(_REDACTED, out)
    return out


__all__ = ["redact"]
