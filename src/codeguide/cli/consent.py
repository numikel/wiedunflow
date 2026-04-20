# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Consent banner and session-scoped consent state for LLM provider usage."""

from __future__ import annotations

import click


class ConsentRequiredError(Exception):
    """Raised when consent is required but cannot be obtained (e.g. non-TTY)."""


class ConsentDeniedError(Exception):
    """Raised when the user explicitly declined consent."""


# Session-scoped in-memory state — reset for each process; no persistence in S3.
_granted: set[str] = set()


def _reset_for_tests() -> None:
    """Clear session-scoped consent state. Call from test fixtures."""
    _granted.clear()


def ensure_consent_granted(
    provider: str,
    *,
    bypass: bool = False,
    tty: bool = True,
) -> None:
    """Ensure the user has consented to sending code to ``provider``.

    Consent is cached in-process: after the first confirmation the banner is
    not shown again within the same CodeGuide run.

    Args:
        provider: Provider name, e.g. ``"anthropic"`` or ``"openai"``.
        bypass: Skip the interactive prompt (equivalent to ``--yes`` / ``--no-consent-prompt``).
        tty: Whether stdin is a terminal. Non-TTY without ``bypass`` raises
            ``ConsentRequiredError``.

    Raises:
        ConsentRequiredError: Non-TTY and ``bypass`` is False.
        ConsentDeniedError: User answered "No" at the interactive prompt.
    """
    if bypass or provider in _granted:
        _granted.add(provider)
        return
    if not tty:
        raise ConsentRequiredError(
            "Cannot prompt for consent (non-TTY). Use --no-consent-prompt or --yes to bypass."
        )
    _print_banner(provider)
    if click.confirm("Continue?", default=False):
        _granted.add(provider)
        return
    raise ConsentDeniedError(f"User declined consent for provider {provider!r}")


def _print_banner(provider: str) -> None:
    click.echo("")
    click.echo("=" * 60)
    click.echo(f"  Privacy notice: your source code will be sent to {provider}.")
    click.echo("=" * 60)
    click.echo("")
    click.echo("  - CodeGuide reads your local repository and sends")
    click.echo(f"    excerpts to the {provider} LLM API for analysis.")
    click.echo("  - No telemetry or analytics is collected by CodeGuide.")
    click.echo(f"  - Review the provider's data policy: {_provider_policy_url(provider)}")
    click.echo("  - Bypass in future runs with --no-consent-prompt or --yes.")
    click.echo("")


def _provider_policy_url(provider: str) -> str:
    return {
        "anthropic": "https://www.anthropic.com/legal/privacy",
        "openai": "https://openai.com/policies/privacy-policy",
        "openai_compatible": "(configurable endpoint — refer to your provider)",
    }.get(provider, "(unknown provider)")
