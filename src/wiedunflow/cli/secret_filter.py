# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""SecretFilter — redact API-key-shaped substrings from log messages (US-069).

Pattern list is authoritative per ADR-0010. The filter replaces every
matched substring with the literal ``"[REDACTED]"``. Predictability over
recall: new provider key shapes are added by amending :data:`_PATTERNS`,
never by entropy-based heuristics that would surface false positives on
commit hashes, Pygments spans, or base64-encoded test fixtures.

Additional helpers:

- :func:`redact_path` — replace absolute paths outside the repo root with
  the placeholder ``"<external>"``. Called explicitly by callers that have
  access to ``repo_root``; **not** invoked automatically by :func:`redact`.
- :func:`truncate_source` — produce a ``"<hash>:<symbol>"`` reference
  instead of embedding full source bodies in log output.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    # Anthropic session / admin / sk-ant keys — sk-ant-* cover all current variants.
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"),
    # OpenAI project-scoped keys (sk-proj-…).
    re.compile(r"sk-proj-[A-Za-z0-9_\-]{20,}"),
    # OpenAI classic secret keys and OpenAI-compatible deployments.
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    # HuggingFace tokens (hf_…).
    re.compile(r"hf_[A-Za-z0-9]{20,}"),
    # OAuth / proxy bearer tokens (≥16-char value after "Bearer").
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{16,}"),
    # Authorization HTTP header with any scheme (captures scheme + full token value).
    re.compile(r"(?i)authorization:\s*\S+(?:\s+\S+)*"),
    # Generic long hex blobs (SHA/HMAC/session tokens — ≥40 hex chars).
    re.compile(r"\b[A-Fa-f0-9]{40,}\b"),
    # ADR-0010 §D11 (v0.9.6): cloud-provider key patterns (AWS / GitHub / PEM).
    # AWS Access Key ID — exactly 20 chars starting with AKIA.
    re.compile(r"AKIA[A-Z0-9]{16}"),
    # AWS Secret Access Key heuristic — 40-char base64 blob preceded by "aws".
    re.compile(r"(?i)aws.{0,20}[0-9a-zA-Z/+]{40}\b"),
    # GitHub classic PATs: ghp_ (personal), ghu_ (user-to-server), gho_ (OAuth),
    # ghs_ (server-to-server), ghr_ (refresh) — 36-255 alphanum chars.
    re.compile(r"gh[pousr]_[A-Za-z0-9]{36,255}"),
    # GitHub fine-grained PATs — exactly 82 alphanum/underscore chars after prefix.
    re.compile(r"github_pat_[A-Za-z0-9_]{82}"),
    # PEM private keys — any standard flavor (RSA, OPENSSH, DSA, EC, PKCS8).
    re.compile(r"-----BEGIN (?:RSA |OPENSSH |DSA |EC )?PRIVATE KEY-----"),
)

_REDACTED: Final[str] = "[REDACTED]"

# Regex for matching Unix/Windows absolute paths. Windows branch needs `\\`
# (literal backslash after the drive letter) — the earlier `\[` was a typo
# that made every Windows path silently slip past path redaction.
_ABS_PATH_RE: Final[re.Pattern[str]] = re.compile(
    r"(?:/[^\s\"'<>]+|[A-Za-z]:\\[^\s\"'<>]+)",
)

_EXTERNAL_PLACEHOLDER: Final[str] = "<external>"


def redact(msg: str) -> str:
    """Return ``msg`` with every known secret pattern replaced by ``[REDACTED]``."""
    out = msg
    for pattern in _PATTERNS:
        out = pattern.sub(_REDACTED, out)
    return out


def redact_path(msg: str, repo_root: Path | None) -> str:
    """Replace absolute paths outside *repo_root* with ``"<external>"``.

    This is an explicit helper — it is **not** called automatically by
    :func:`redact` to avoid performance overhead and unintended side-effects
    in callers that do not supply a ``repo_root``.

    Args:
        msg: The log message to filter.
        repo_root: Absolute root of the analysed repository. When ``None``
            the function is a no-op (safe default for callers without context).

    Returns:
        The message with external absolute paths replaced.
    """
    if repo_root is None:
        return msg

    repo_str = str(repo_root)

    def _replace(m: re.Match[str]) -> str:
        matched = m.group(0)
        if matched.startswith(repo_str):
            return matched  # Keep paths inside the repo.
        return _EXTERNAL_PLACEHOLDER

    return _ABS_PATH_RE.sub(_replace, msg)


def truncate_source(
    body: str,
    file_hash: str,
    symbol_name: str,
    max_chars: int = 0,
) -> str:
    """Return a compact ``"<hash>:<symbol>"`` reference for a source body.

    Instead of embedding potentially large (and sensitive) source code bodies
    in log lines or structured events, callers can use this reference which
    is sufficient for tracing without leaking implementation details.

    Args:
        body: Full source text (only used in future *partial-include* mode).
        file_hash: Short or full SHA of the containing file.
        symbol_name: Qualified name of the symbol (e.g. ``"MyClass.my_method"``).
        max_chars: Reserved for a future mode that includes a leading excerpt.
            Pass ``0`` (default) to always get the pure ``hash:symbol`` form.

    Returns:
        ``"<file_hash>:<symbol_name>"``.
    """
    return f"{file_hash}:{symbol_name}"


__all__ = ["redact", "redact_path", "truncate_source"]
