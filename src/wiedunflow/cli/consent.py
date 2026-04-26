# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Consent banner and persistent consent state for LLM provider usage (US-005/007).

Consent is persisted per-provider via the :class:`~wiedunflow.interfaces.consent_store.ConsentStore`
port.  The default adapter is :class:`~wiedunflow.adapters.yaml_consent_store.YamlConsentStore`
which writes to ``<user_config_dir>/wiedunflow/consent.yaml`` with ``0o600`` permissions.

The session-scoped in-memory ``_granted`` set is kept for backward compatibility:
tests that call :func:`_reset_for_tests` still work.  After a successful grant
the provider is added to both the in-memory set and the persistent store.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import click
import platformdirs

from wiedunflow.interfaces.consent_store import ConsentStore


class ConsentRequiredError(Exception):
    """Raised when consent is required but cannot be obtained (e.g. non-TTY)."""


class ConsentDeniedError(Exception):
    """Raised when the user explicitly declined consent."""


# Session-scoped in-memory state — kept for backward compatibility with
# existing tests; also acts as a fast short-circuit within a single process.
_granted: set[str] = set()

# Module-level store override — populated by _reset_for_tests() so existing
# tests that do not pass a store explicitly get a fresh in-memory-like store
# instead of the real consent.yaml on disk.
# A single-element list acts as a mutable cell that avoids the `global` statement.
_test_store_cell: list[ConsentStore | None] = [None]


class _NullConsentStore:
    """In-memory no-op consent store used during tests (never persists to disk)."""

    def __init__(self) -> None:
        self._data: dict[str, bool] = {}

    def is_granted(self, provider: str) -> bool:
        return self._data.get(provider, False)

    def grant(self, provider: str, timestamp: datetime) -> None:
        self._data[provider] = True

    def revoke(self, provider: str) -> None:
        self._data.pop(provider, None)


def _reset_for_tests() -> None:
    """Clear session-scoped consent state.

    Call from test fixtures to isolate consent state between tests.  This
    function is intentionally preserved for backward compatibility with the
    S3/S5 test suite.  It also installs a fresh in-memory store override so
    tests that do not supply an explicit store do not accidentally read the
    real user-level ``consent.yaml``.
    """
    _granted.clear()
    _test_store_cell[0] = _NullConsentStore()


def _default_store() -> ConsentStore:
    """Return the active :class:`~wiedunflow.interfaces.consent_store.ConsentStore`.

    During tests (after :func:`_reset_for_tests` is called) returns a fresh
    in-memory ``_NullConsentStore`` so real YAML state is not polluted.
    Outside tests returns a ``YamlConsentStore`` pointing at the
    platform-appropriate consent file.
    """
    override = _test_store_cell[0]
    if override is not None:
        return override

    from wiedunflow.adapters.yaml_consent_store import YamlConsentStore  # noqa: PLC0415

    consent_path = Path(platformdirs.user_config_dir("wiedunflow")) / "consent.yaml"
    return YamlConsentStore(path=consent_path)


def ensure_consent_granted(
    provider: str,
    store: ConsentStore | None = None,
    *,
    bypass: bool = False,
    tty: bool = True,
) -> None:
    """Ensure the user has consented to sending code to ``provider``.

    Consent is checked in two layers:
    1. Session-scoped in-memory cache (fast path, reset between processes).
    2. Persistent :class:`~wiedunflow.interfaces.consent_store.ConsentStore`
       (survives across runs).

    After a successful interactive confirmation the grant is written to both
    layers.

    Args:
        provider: Provider name, e.g. ``"anthropic"`` or ``"openai"``.
        store: Consent store instance.  When ``None``, the default
            :class:`~wiedunflow.adapters.yaml_consent_store.YamlConsentStore`
            is used.
        bypass: Skip the interactive prompt — equivalent to ``--yes`` /
            ``--no-consent-prompt``.
        tty: Whether stdin is a terminal.  Non-TTY without ``bypass`` raises
            :class:`ConsentRequiredError`.

    Raises:
        ConsentRequiredError: Non-TTY and ``bypass`` is ``False``.
        ConsentDeniedError: User answered "No" at the interactive prompt.
    """
    resolved_store = store if store is not None else _default_store()

    # Fast path: bypass flag or already granted in this process.
    if bypass or provider in _granted:
        _granted.add(provider)
        return

    # Persistent layer: previously granted in a past run.
    if resolved_store.is_granted(provider):
        _granted.add(provider)
        return

    # Non-TTY without bypass — cannot prompt.
    if not tty:
        raise ConsentRequiredError(
            "Cannot prompt for consent (non-TTY). Use --no-consent-prompt or --yes to bypass."
        )

    # Interactive banner + prompt.
    _print_banner(provider)
    if click.confirm("Continue?", default=False):
        _granted.add(provider)
        resolved_store.grant(provider, datetime.now(UTC))
        return

    raise ConsentDeniedError(f"User declined consent for provider {provider!r}")


def _print_banner(provider: str) -> None:
    click.echo("")
    click.echo("=" * 60)
    click.echo(f"  Your source code will be sent to {provider}.")
    click.echo("=" * 60)
    click.echo("")
    click.echo("  - WiedunFlow reads your local repository and sends")
    click.echo(f"    excerpts to the {provider} LLM API for analysis.")
    click.echo("  - No telemetry or analytics is collected by WiedunFlow.")
    click.echo(f"  - Review the provider's data policy: {_provider_policy_url(provider)}")
    click.echo("  - Bypass in future runs with --no-consent-prompt or --yes.")
    click.echo("")


def _provider_policy_url(provider: str) -> str:
    return {
        "anthropic": "https://www.anthropic.com/legal/privacy",
        "openai": "https://openai.com/policies/privacy-policy",
        "openai_compatible": "(configurable endpoint — refer to your provider)",
    }.get(provider, "(unknown provider)")
