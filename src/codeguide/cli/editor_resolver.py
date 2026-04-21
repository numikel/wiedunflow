# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Editor resolver for ``--review-plan`` (US-016).

Resolution order per ux-spec §CLI.flags.review-plan:
1. ``$EDITOR``
2. ``$VISUAL``
3. ``code --wait`` (if ``code`` is on PATH)
4. ``notepad`` on Windows, ``vi`` on Unix
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def resolve_editor() -> list[str]:
    """Return the resolved editor command as an argv-style list.

    Returns:
        A list suitable for ``subprocess.run`` — e.g. ``["code", "--wait"]``.
    """
    editor = os.environ.get("EDITOR")
    if editor:
        return editor.split()

    visual = os.environ.get("VISUAL")
    if visual:
        return visual.split()

    if shutil.which("code") is not None:
        return ["code", "--wait"]

    if sys.platform.startswith("win"):
        return ["notepad"]
    return ["vi"]


def open_in_editor(path: Path) -> int:
    """Open ``path`` in the resolved editor and block until the editor exits.

    Returns:
        The editor's exit code (0 on success).
    """
    cmd = [*resolve_editor(), str(path)]
    completed = subprocess.run(cmd, check=False)
    return completed.returncode
