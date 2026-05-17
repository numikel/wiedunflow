# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Unit tests for FakeLLMProvider — deterministic stub used in e2e tests."""

from __future__ import annotations

from wiedunflow.adapters.fake_llm_provider import FakeLLMProvider
from wiedunflow.interfaces.ports import LLMProvider


def test_fake_satisfies_llm_provider_protocol() -> None:
    """FakeLLMProvider must structurally match the LLMProvider Protocol."""
    fake = FakeLLMProvider()
    assert isinstance(fake, LLMProvider)


def test_fake_llm_provider_uses_current_version() -> None:
    """F-017 regression: hardcoded `0.0.3` was 6 majors stale."""
    from wiedunflow import __version__

    fake = FakeLLMProvider()
    manifest = fake.plan(outline="ignored")
    assert manifest.metadata.wiedunflow_version == __version__
