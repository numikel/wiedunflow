# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Terminal output helpers for the CLI."""

from tests.fixtures.medium_repo.utils.logging_helpers import log_line
from tests.fixtures.medium_repo.utils.text import truncate


def print_info(message: str) -> str:
    """Return an INFO-level log line truncated to 120 chars."""
    return log_line("INFO", truncate(message, 120))


def print_error(message: str) -> str:
    """Return an ERROR-level log line truncated to 120 chars."""
    return log_line("ERROR", truncate(message, 120))
