# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Unit tests for cli/consent.py — ensure_consent_granted and banner."""

from __future__ import annotations

import pytest

import wiedunflow.cli.consent as consent_module
from wiedunflow.cli.consent import (
    ConsentDeniedError,
    ConsentRequiredError,
    _provider_policy_url,
    _reset_for_tests,
    ensure_consent_granted,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_consent_state():
    """Isolate consent state between tests."""
    _reset_for_tests()
    yield
    _reset_for_tests()


# ---------------------------------------------------------------------------
# 1. bypass=True → no prompt, no error
# ---------------------------------------------------------------------------


def test_bypass_skips_prompt(monkeypatch):
    """bypass=True grants consent immediately, no click.confirm call."""
    confirm_calls: list[str] = []
    monkeypatch.setattr(
        consent_module.click, "confirm", lambda *a, **kw: confirm_calls.append("called")
    )
    ensure_consent_granted("anthropic", bypass=True, tty=True)
    assert confirm_calls == []


def test_bypass_with_non_tty(monkeypatch):
    """bypass=True works even when tty=False (non-interactive environment)."""
    ensure_consent_granted("anthropic", bypass=True, tty=False)
    # No exception raised = pass


# ---------------------------------------------------------------------------
# 2. tty=False, bypass=False → ConsentRequiredError
# ---------------------------------------------------------------------------


def test_non_tty_raises_consent_required():
    """Non-TTY without bypass raises ConsentRequiredError."""
    with pytest.raises(ConsentRequiredError, match="Cannot prompt for consent"):
        ensure_consent_granted("anthropic", bypass=False, tty=False)


# ---------------------------------------------------------------------------
# 3. User confirms → cached, second call skips prompt
# ---------------------------------------------------------------------------


def test_user_confirms_caches_consent(monkeypatch):
    """After confirmation, provider is cached; second call does not prompt."""
    confirm_calls: list[bool] = []

    def fake_confirm(*args, **kwargs) -> bool:
        confirm_calls.append(True)
        return True

    monkeypatch.setattr(consent_module.click, "confirm", fake_confirm)
    monkeypatch.setattr(consent_module.click, "echo", lambda *a, **kw: None)

    # First call — prompts
    ensure_consent_granted("anthropic", bypass=False, tty=True)
    assert len(confirm_calls) == 1

    # Second call — should NOT prompt again
    ensure_consent_granted("anthropic", bypass=False, tty=True)
    assert len(confirm_calls) == 1  # still 1


def test_different_providers_prompt_separately(monkeypatch):
    """Consent for 'anthropic' does not auto-grant consent for 'openai'."""
    calls: list[str] = []

    def fake_confirm(*args, **kwargs) -> bool:
        calls.append("confirm")
        return True

    monkeypatch.setattr(consent_module.click, "confirm", fake_confirm)
    monkeypatch.setattr(consent_module.click, "echo", lambda *a, **kw: None)

    ensure_consent_granted("anthropic", bypass=False, tty=True)
    assert len(calls) == 1

    # openai is a separate provider — should prompt again
    ensure_consent_granted("openai", bypass=False, tty=True)
    assert len(calls) == 2


# ---------------------------------------------------------------------------
# 4. User declines → ConsentDeniedError
# ---------------------------------------------------------------------------


def test_user_declines_raises_consent_denied(monkeypatch):
    """User answering 'No' raises ConsentDeniedError."""
    monkeypatch.setattr(consent_module.click, "confirm", lambda *a, **kw: False)
    monkeypatch.setattr(consent_module.click, "echo", lambda *a, **kw: None)

    with pytest.raises(ConsentDeniedError, match="anthropic"):
        ensure_consent_granted("anthropic", bypass=False, tty=True)


# ---------------------------------------------------------------------------
# 5. Banner content
# ---------------------------------------------------------------------------


def test_banner_contains_provider_name(monkeypatch):
    """The printed banner includes the provider name."""
    echoed: list[str] = []
    monkeypatch.setattr(consent_module.click, "echo", lambda msg="", **kw: echoed.append(str(msg)))
    monkeypatch.setattr(consent_module.click, "confirm", lambda *a, **kw: True)

    ensure_consent_granted("anthropic", bypass=False, tty=True)

    full_output = "\n".join(echoed)
    assert "anthropic" in full_output


def test_banner_contains_policy_url(monkeypatch):
    """The printed banner includes the provider's privacy policy URL."""
    echoed: list[str] = []
    monkeypatch.setattr(consent_module.click, "echo", lambda msg="", **kw: echoed.append(str(msg)))
    monkeypatch.setattr(consent_module.click, "confirm", lambda *a, **kw: True)

    ensure_consent_granted("anthropic", bypass=False, tty=True)

    full_output = "\n".join(echoed)
    assert "anthropic.com" in full_output


def test_banner_contains_no_telemetry_notice(monkeypatch):
    """The printed banner mentions the no-telemetry guarantee."""
    echoed: list[str] = []
    monkeypatch.setattr(consent_module.click, "echo", lambda msg="", **kw: echoed.append(str(msg)))
    monkeypatch.setattr(consent_module.click, "confirm", lambda *a, **kw: True)

    ensure_consent_granted("anthropic", bypass=False, tty=True)

    full_output = "\n".join(echoed)
    assert "telemetry" in full_output.lower() or "analytics" in full_output.lower()


# ---------------------------------------------------------------------------
# 6. _provider_policy_url helper
# ---------------------------------------------------------------------------


def test_provider_policy_url_anthropic():
    assert "anthropic.com" in _provider_policy_url("anthropic")


def test_provider_policy_url_openai():
    assert "openai.com" in _provider_policy_url("openai")


def test_provider_policy_url_unknown():
    url = _provider_policy_url("some_unknown_provider")
    assert url  # Should return a non-empty fallback string
