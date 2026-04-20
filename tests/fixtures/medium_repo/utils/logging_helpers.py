"""Structured logging helpers."""

from tests.fixtures.medium_repo.config import get_setting


def build_prefix(level: str) -> str:
    """Return a ``[LEVEL timeout=<n>]`` prefix for log lines."""
    timeout = get_setting("timeout")
    return f"[{level} timeout={timeout}]"


def log_line(level: str, message: str) -> str:
    """Prefix *message* with a level tag and return the full line."""
    return f"{build_prefix(level)} {message}"
