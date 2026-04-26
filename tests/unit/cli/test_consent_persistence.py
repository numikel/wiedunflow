# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Unit tests for consent persistence and banner gate (US-005/006/007).

Tests verify:
- Banner is shown on first run for cloud providers.
- Banner is skipped when consent was already granted (persistent store).
- bypass=True skips the banner without granting persistent consent.
- Non-TTY without bypass raises ConsentRequiredError.
- User declining raises ConsentDeniedError.
- Banner text matches PRD contract ("Your source code will be sent to <provider>.")
- --no-consent-prompt (bypass=True) does NOT bypass the hard-refuse blocklist.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

import wiedunflow.cli.consent as consent_module
from wiedunflow.adapters.yaml_consent_store import YamlConsentStore
from wiedunflow.cli.consent import (
    ConsentDeniedError,
    ConsentRequiredError,
    _reset_for_tests,
    ensure_consent_granted,
)
from wiedunflow.ingestion.secret_blocklist import is_hard_refused

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_consent_state() -> None:
    """Isolate in-memory consent state between tests."""
    _reset_for_tests()
    yield  # type: ignore[misc]
    _reset_for_tests()


@pytest.fixture()
def fake_store(tmp_path: Path) -> YamlConsentStore:
    """Return a YamlConsentStore backed by a temp directory."""
    return YamlConsentStore(path=tmp_path / "consent.yaml")


# ---------------------------------------------------------------------------
# 1. Banner shown on first cloud run
# ---------------------------------------------------------------------------


def test_banner_shown_first_cloud_run(monkeypatch: pytest.MonkeyPatch, fake_store) -> None:  # type: ignore[no-untyped-def]
    """Banner must be shown when store is empty and tty=True."""
    echoed: list[str] = []
    monkeypatch.setattr(consent_module.click, "echo", lambda msg="", **kw: echoed.append(str(msg)))
    monkeypatch.setattr(consent_module.click, "confirm", lambda *a, **kw: True)

    ensure_consent_granted("anthropic", fake_store, tty=True)

    full_output = "\n".join(echoed)
    assert "anthropic" in full_output, "Banner must mention the provider name"


# ---------------------------------------------------------------------------
# 2. Banner skipped after grant
# ---------------------------------------------------------------------------


def test_banner_skipped_after_grant(monkeypatch: pytest.MonkeyPatch, fake_store) -> None:  # type: ignore[no-untyped-def]
    """After a previous grant, no banner or prompt on subsequent call."""
    fake_store.grant("anthropic", datetime.now(UTC))

    confirm_calls: list[str] = []
    monkeypatch.setattr(
        consent_module.click,
        "confirm",
        lambda *a, **kw: confirm_calls.append("called"),
    )
    monkeypatch.setattr(consent_module.click, "echo", lambda *a, **kw: None)

    ensure_consent_granted("anthropic", fake_store, tty=True)

    assert confirm_calls == [], "No prompt expected when store already has grant"


# ---------------------------------------------------------------------------
# 3. bypass=True skips banner but does not persist grant
# ---------------------------------------------------------------------------


def test_bypass_skips_banner_even_if_ungranted(monkeypatch: pytest.MonkeyPatch, fake_store) -> None:  # type: ignore[no-untyped-def]
    """bypass=True grants in-memory but does NOT require a store interaction."""
    confirm_calls: list[str] = []
    monkeypatch.setattr(
        consent_module.click,
        "confirm",
        lambda *a, **kw: confirm_calls.append("called"),
    )

    ensure_consent_granted("anthropic", fake_store, bypass=True, tty=True)

    assert confirm_calls == [], "bypass=True must not invoke confirm()"
    # bypass does not write to the persistent store.
    assert fake_store.is_granted("anthropic") is False, (
        "bypass=True must not persist grant — no write to consent.yaml"
    )


# ---------------------------------------------------------------------------
# 4. Non-TTY without bypass raises ConsentRequiredError
# ---------------------------------------------------------------------------


def test_non_tty_without_bypass_raises(fake_store) -> None:  # type: ignore[no-untyped-def]
    """Non-TTY and bypass=False must raise ConsentRequiredError."""
    with pytest.raises(ConsentRequiredError, match="Cannot prompt for consent"):
        ensure_consent_granted("anthropic", fake_store, bypass=False, tty=False)


def test_non_tty_with_bypass_succeeds(fake_store) -> None:  # type: ignore[no-untyped-def]
    """bypass=True with non-TTY must succeed without raising."""
    ensure_consent_granted("anthropic", fake_store, bypass=True, tty=False)  # no raise


# ---------------------------------------------------------------------------
# 5. User declines raises ConsentDeniedError
# ---------------------------------------------------------------------------


def test_user_declines_raises_denied(monkeypatch: pytest.MonkeyPatch, fake_store) -> None:  # type: ignore[no-untyped-def]
    """User answering No must raise ConsentDeniedError."""
    monkeypatch.setattr(consent_module.click, "confirm", lambda *a, **kw: False)
    monkeypatch.setattr(consent_module.click, "echo", lambda *a, **kw: None)

    with pytest.raises(ConsentDeniedError, match="anthropic"):
        ensure_consent_granted("anthropic", fake_store, tty=True)


def test_user_declines_does_not_persist_grant(monkeypatch: pytest.MonkeyPatch, fake_store) -> None:  # type: ignore[no-untyped-def]
    """Declined consent must not be written to the persistent store."""
    monkeypatch.setattr(consent_module.click, "confirm", lambda *a, **kw: False)
    monkeypatch.setattr(consent_module.click, "echo", lambda *a, **kw: None)

    with pytest.raises(ConsentDeniedError):
        ensure_consent_granted("anthropic", fake_store, tty=True)

    assert fake_store.is_granted("anthropic") is False


# ---------------------------------------------------------------------------
# 6. Banner text matches PRD contract
# ---------------------------------------------------------------------------


def test_banner_text_matches_prd_contract(monkeypatch: pytest.MonkeyPatch, fake_store) -> None:  # type: ignore[no-untyped-def]
    """Banner must contain the exact PRD string: 'Your source code will be sent to <provider>.'"""
    echoed: list[str] = []
    monkeypatch.setattr(consent_module.click, "echo", lambda msg="", **kw: echoed.append(str(msg)))
    monkeypatch.setattr(consent_module.click, "confirm", lambda *a, **kw: True)

    ensure_consent_granted("anthropic", fake_store, tty=True)

    full_output = "\n".join(echoed)
    assert "Your source code will be sent to anthropic." in full_output, (
        "Banner must contain the exact PRD-mandated string"
    )


# ---------------------------------------------------------------------------
# 7. Backward compat — old signature (no store argument) still works
# ---------------------------------------------------------------------------


def test_old_signature_no_store_arg_bypass(monkeypatch: pytest.MonkeyPatch) -> None:
    """ensure_consent_granted(provider, bypass=True) without store arg must not raise."""
    ensure_consent_granted("anthropic", bypass=True, tty=False)  # no store, bypass=True


# ---------------------------------------------------------------------------
# 8. --no-consent-prompt flag: bypass=True does NOT bypass hard-refuse blocklist
# ---------------------------------------------------------------------------


def test_bypass_does_not_skip_hard_refuse_blocklist() -> None:
    """The hard-refuse blocklist is enforced by the ingestion layer — bypass=True is consent-only."""
    # bypass=True only affects consent banner — blocklist is independent.
    # Verify that is_hard_refused('.env') is still True regardless.
    assert is_hard_refused(Path(".env")) is True, (
        "Hard-refuse blocklist must be enforced independently of bypass flag"
    )
