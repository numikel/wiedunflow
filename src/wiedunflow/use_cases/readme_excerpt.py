# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Load a README excerpt for project-level context injection (v0.2.1+).

Used by:
- Narration prompt enrichment (`use_cases.grounding_retry._spec_to_json`).
  Every lesson narration receives the project intent so the LLM can tighten
  one-liner descriptions instead of waterring with generic prose.
- Closing lesson "Project README" appendix (rendered when present).

Sizing rule (per user decision 2026-04-25):
- README ≤ ``max_lines`` lines → return verbatim.
- README > ``max_lines`` lines → return head (200) + truncation marker +
  tail (30) so the LLM still sees both intent (top of README) and
  pointers/footnotes (bottom).
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["load_readme_excerpt"]

# Case-insensitive candidates checked in order. README.rst / README.txt and
# other variants are post-MVP — track separately if requested.
_README_CANDIDATES: tuple[str, ...] = (
    "README.md",
    "Readme.md",
    "readme.md",
    "README.MD",
)

_HEAD_LINES = 200
_TAIL_LINES = 30


def load_readme_excerpt(repo_root: Path, *, max_lines: int = 250) -> str | None:
    """Return README content as text, or ``None`` when no README exists.

    Args:
        repo_root: Repository root path.
        max_lines: Lines threshold below which the README is returned verbatim.
            Above the threshold, the function returns
            ``<first 200 lines>\\n\\n<!-- ... (N lines omitted) ... -->\\n\\n<last 30 lines>``
            so both the project intent (top of README) and any reference
            pointers (bottom) survive the truncation.

    Returns:
        Text content (verbatim or head/tail), or ``None`` when no README is found.
    """
    for name in _README_CANDIDATES:
        path = repo_root / name
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="replace")
            lines = text.splitlines()
            if len(lines) <= max_lines:
                return text
            # Guard: callers passing ``max_lines`` below ``_HEAD_LINES + _TAIL_LINES``
            # must not see a negative ``omitted`` count or duplicate slices. ``max(0, ...)``
            # keeps the marker accurate; the head/tail slices clamp themselves naturally.
            omitted = max(0, len(lines) - _HEAD_LINES - _TAIL_LINES)
            head = "\n".join(lines[:_HEAD_LINES])
            tail = "\n".join(lines[-_TAIL_LINES:])
            return f"{head}\n\n<!-- ... ({omitted} lines omitted) ... -->\n\n{tail}"
    return None
