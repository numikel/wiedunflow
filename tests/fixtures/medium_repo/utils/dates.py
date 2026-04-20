"""Date helpers."""

from datetime import UTC, datetime


def utcnow() -> datetime:
    """Return the current UTC time (test-friendly wrapper)."""
    return datetime.now(UTC)


def format_iso(dt: datetime) -> str:
    """Format a datetime in ISO-8601 UTC."""
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
