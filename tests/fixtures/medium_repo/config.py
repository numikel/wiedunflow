# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Application-wide configuration constants."""

DEFAULT_TIMEOUT_SECONDS = 30
MAX_RETRIES = 3
LOG_LEVEL = "INFO"


def get_setting(name: str) -> str:
    """Return a setting by name, falling back to a sensible default."""
    mapping = {"timeout": str(DEFAULT_TIMEOUT_SECONDS), "retries": str(MAX_RETRIES)}
    return mapping.get(name, "")
