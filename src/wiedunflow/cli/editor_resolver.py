# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Editor resolver for ``--review-plan`` (US-016, hardened US-068).

Resolution order per ux-spec §CLI.flags.review-plan:
1. ``$EDITOR``
2. ``$VISUAL``
3. ``code --wait`` (if ``code`` is on PATH)
4. ``notepad`` on Windows, ``vi`` on Unix

Shell-injection hardening (US-068 / ADR-0010):
- Every env-var value is validated through :func:`_validate_editor_cmd`
  before use.
- Values containing shell metacharacters (``;``, ``|``, ``&&``, ``||``,
  backticks, ``$(``, ``>&``) are rejected unconditionally.
- Binaries not found via ``shutil.which`` are rejected (prevents path
  traversal through arbitrary absolute paths supplied by the environment).
- ``subprocess.run`` is always called with ``shell=False``.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

# Metacharacters that indicate attempted shell injection.
_SHELL_METACHARACTERS: tuple[str, ...] = (";", "|", "&&", "||", "`", "$(", ">&")


class EditorResolutionError(RuntimeError):
    """Raised when no safe editor binary can be resolved."""


def _validate_editor_cmd(cmd_str: str) -> list[str] | None:
    """Validate and parse *cmd_str* into a safe argv list.

    Returns ``None`` if the string is empty, contains shell metacharacters,
    cannot be parsed by :mod:`shlex`, or its first token is not found on
    ``PATH`` via :func:`shutil.which`.

    Args:
        cmd_str: Raw value from ``$EDITOR`` or ``$VISUAL``.

    Returns:
        A validated argv list on success, or ``None`` if the input is unsafe.
    """
    stripped = cmd_str.strip()
    if not stripped:
        return None

    # Reject metacharacters BEFORE shlex.split so that cleverly quoted
    # payloads (e.g. ``'vi; rm -rf /'``) are still caught.
    for meta in _SHELL_METACHARACTERS:
        if meta in stripped:
            return None

    try:
        parts = shlex.split(stripped)
    except ValueError:
        # Unbalanced quotes or other shlex parse errors — treat as malicious.
        return None

    if not parts:
        return None

    # Binary must be discoverable on PATH — prevents arbitrary absolute paths
    # from untrusted env vars.
    if shutil.which(parts[0]) is None:
        return None

    return parts


def resolve_editor() -> list[str] | None:  # noqa: PLR0911  # sequential fallback chain
    """Return the resolved editor command as a validated argv-style list.

    Applies :func:`_validate_editor_cmd` to every env-var candidate.
    Falls back through ``code --wait``, then to the OS default editor.
    Returns ``None`` only when *no* safe editor is available at all
    (practically impossible on a normal system but handled for callers).

    Returns:
        A list suitable for ``subprocess.run`` (``shell=False``), or
        ``None`` if no safe editor can be resolved.
    """
    for env_var in ("EDITOR", "VISUAL"):
        raw = os.environ.get(env_var)
        if raw is not None:
            validated = _validate_editor_cmd(raw)
            if validated is not None:
                return validated
            # Unsafe value — fall through to next candidate without error.

    if shutil.which("code") is not None:
        return ["code", "--wait"]

    # OS-specific last resort — use absolute paths as a safety net when PATH
    # is stripped (e.g. in restricted CI environments on Windows).
    if sys.platform.startswith("win"):
        if shutil.which("notepad") is not None:
            return ["notepad"]
        notepad_abs = Path(r"C:\Windows\System32\notepad.exe")
        if notepad_abs.exists():
            return [str(notepad_abs)]
        return None

    if shutil.which("vi") is not None:
        return ["vi"]
    vi_abs = Path("/usr/bin/vi")
    if vi_abs.exists():
        return [str(vi_abs)]
    return None


def open_in_editor(path: Path) -> int:
    """Open ``path`` in the resolved editor and block until the editor exits.

    Args:
        path: File to open.

    Returns:
        The editor's exit code (0 on success).

    Raises:
        EditorResolutionError: When no safe editor binary can be resolved.
    """
    cmd_base = resolve_editor()
    if cmd_base is None:
        raise EditorResolutionError("No safe editor found")
    cmd = [*cmd_base, str(path)]
    completed = subprocess.run(cmd, check=False, shell=False)
    return completed.returncode


__all__ = [
    "EditorResolutionError",
    "open_in_editor",
    "resolve_editor",
]
