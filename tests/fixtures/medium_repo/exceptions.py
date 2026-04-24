# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Domain-specific exception hierarchy."""


class DomainError(Exception):
    """Base class for all domain-level errors."""


class ValidationError(DomainError):
    """Raised when user input fails validation."""


class NotFoundError(DomainError):
    """Raised when a repository lookup returns nothing."""
