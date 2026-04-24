# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Input validators for the service layer."""

from tests.fixtures.medium_repo.exceptions import ValidationError


def validate_email(email: str) -> None:
    """Raise :class:`ValidationError` if *email* is obviously malformed."""
    if "@" not in email or "." not in email:
        raise ValidationError(f"invalid email: {email}")


def validate_name(name: str) -> None:
    """Reject empty / whitespace-only names."""
    if not name.strip():
        raise ValidationError("name must be non-empty")


def validate_amount(cents: int) -> None:
    """Reject non-positive monetary amounts."""
    if cents <= 0:
        raise ValidationError(f"amount must be positive, got {cents}")
