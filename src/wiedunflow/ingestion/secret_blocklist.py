# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Hard-refuse secret file patterns for the ingestion stage (US-008).

Files whose names match any pattern in ``HARD_REFUSE_PATTERNS`` are silently
dropped during file collection, regardless of ``.gitignore``, ``--include``,
or ``--exclude`` flags.  The only escape hatch is the
``security.allow_secret_files`` list in ``tutorial.config.yaml`` (mapped to
``CodeguideConfig.security_allow_secret_files``), which accepts **exact file
names** (not patterns) that should be un-blocked.

Design rationale (ADR-0010):
- A single hard-coded list is simpler and more auditable than runtime config.
- No CLI flag bypass — the escape hatch is intentionally in the YAML config
  so it requires a deliberate, reviewable decision.
- ``fnmatch.fnmatchcase`` is used for case-sensitive matching, matching
  POSIX filesystem semantics.  Windows users who have case-insensitive
  file systems still benefit from the common-pattern coverage.
"""

from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Final

# ---------------------------------------------------------------------------
# Hard-refuse patterns — add new patterns here; keep the tuple immutable.
# ---------------------------------------------------------------------------

HARD_REFUSE_PATTERNS: Final[tuple[str, ...]] = (
    ".env",
    ".env.*",
    "*.pem",
    "*_rsa",
    "*_rsa.pub",
    "*_ed25519",
    "credentials.*",
    "id_rsa",
    "id_ed25519",
)


def is_hard_refused(
    path: Path,
    *,
    allow_list: frozenset[str] = frozenset(),
) -> bool:
    """Return ``True`` when *path* matches a hard-refuse pattern.

    Args:
        path: The file path to check (only ``path.name`` is used).
        allow_list: Exact file names that override the blocklist (e.g.
            ``frozenset({".env.example"})``) — populated from
            ``CodeguideConfig.security_allow_secret_files``.

    Returns:
        ``True`` when the file name matches at least one pattern in
        ``HARD_REFUSE_PATTERNS`` **and** is not in *allow_list*.
    """
    name = path.name
    if name in allow_list:
        return False
    return any(fnmatch.fnmatchcase(name, pat) for pat in HARD_REFUSE_PATTERNS)
