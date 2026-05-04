# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Single source of truth for per-lesson word-count floor thresholds.

Thresholds scale with the primary code_ref body span (ADR-0012).
"""

from __future__ import annotations

_SPAN_SINGLE = 1
_SPAN_TRIVIAL_MAX = 9  # inclusive upper bound for trivial tier (< 10 lines)
_SPAN_MODERATE_MAX = 30  # inclusive upper bound for moderate tier (<= 30 lines)

# Word-count floors by span tier.
_FLOOR_TRIVIAL_SINGLE = 50  # span == 1 line
_FLOOR_TRIVIAL = 80  # span 2-9 lines
_FLOOR_MODERATE = 220  # span 10-30 lines
_FLOOR_COMPLEX = 350  # span > 30 lines

# Fatal threshold (Reviewer uses this as hard fail below this count).
# Set at half the warn floor rounded down — lessons below this are useless.
_FATAL_TRIVIAL_SINGLE = 30
_FATAL_TRIVIAL = 50
_FATAL_MODERATE = 80
_FATAL_COMPLEX = 150


def floor_for_span(span_lines: int) -> int:
    """Return the word-count warn floor for a lesson whose primary code_ref has *span_lines* lines.

    Args:
        span_lines: Number of lines in the primary code_ref body
            (``line_end - line_start + 1``).

    Returns:
        Minimum word count for narration to pass the warn check.
    """
    if span_lines <= _SPAN_SINGLE:
        return _FLOOR_TRIVIAL_SINGLE
    if span_lines <= _SPAN_TRIVIAL_MAX:
        return _FLOOR_TRIVIAL
    if span_lines <= _SPAN_MODERATE_MAX:
        return _FLOOR_MODERATE
    return _FLOOR_COMPLEX


def fatal_floor_for_span(span_lines: int) -> int:
    """Return the word-count fatal threshold (lesson fails Reviewer below this).

    Args:
        span_lines: Number of lines in the primary code_ref body
            (``line_end - line_start + 1``).

    Returns:
        Hard-fail minimum word count; lessons below this count are rejected
        without retry.
    """
    if span_lines <= _SPAN_SINGLE:
        return _FATAL_TRIVIAL_SINGLE
    if span_lines <= _SPAN_TRIVIAL_MAX:
        return _FATAL_TRIVIAL
    if span_lines <= _SPAN_MODERATE_MAX:
        return _FATAL_MODERATE
    return _FATAL_COMPLEX
