# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Tests for ``target_audience`` enum migration (ADR-0013 decision 9, Step 4).

Pre-v0.4.0 ``target_audience`` was a free-text field. v0.4.0 narrows it to
the 5-level Literal enum. Old YAML configs are still loadable via the fuzzy
mapping shim in ``_load_yaml_flat``; the shim is removed in v1.0.

These tests pin the shim contract so the Sprint 7 eval corpus and any
user's pre-existing ``tutorial.config.yaml`` keep loading without manual
edits.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
import yaml

from wiedunflow.cli.config import (
    _normalize_target_audience,
    load_config,
)


def _write_yaml(path: Path, data: dict[str, object]) -> None:
    path.write_text(yaml.safe_dump(data), encoding="utf-8")


# ---------------------------------------------------------------------------
# Direct shim function — pure unit tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("noob", "noob"),
        ("junior", "junior"),
        ("mid", "mid"),
        ("senior", "senior"),
        ("expert", "expert"),
    ],
)
def test_enum_values_pass_through_unchanged(raw: str, expected: str) -> None:
    """Already-valid enum values must not trigger any mapping."""
    assert _normalize_target_audience(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("mid-level Python developer", "mid"),
        ("senior Python developer", "senior"),
        ("junior Python developer", "junior"),
        ("complete beginner", "junior"),
        ("expert engineer", "expert"),
        ("advanced Python user", "expert"),
        ("noob coder", "noob"),
        ("MID-LEVEL DEVELOPER", "mid"),
        ("Senior Engineer", "senior"),
    ],
)
def test_legacy_freetext_maps_to_enum(raw: str, expected: str) -> None:
    """Pre-v0.4.0 free-text values must fuzzy-map to the closest enum level."""
    assert _normalize_target_audience(raw) == expected


def test_unknown_string_falls_back_to_mid_with_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An unmappable value must default to ``mid`` and log a warning."""
    with caplog.at_level(logging.WARNING, logger="wiedunflow.cli.config"):
        result = _normalize_target_audience("astronaut")
    assert result == "mid"
    assert any(
        "did not match any 5-level enum" in rec.message and "astronaut" in rec.message
        for rec in caplog.records
    )


def test_non_string_passes_through_for_pydantic_to_reject() -> None:
    """Non-string inputs must not be silently coerced; let Pydantic surface the error."""
    assert _normalize_target_audience(42) == 42
    assert _normalize_target_audience(None) is None


# ---------------------------------------------------------------------------
# End-to-end: YAML → load_config → resolved enum
# ---------------------------------------------------------------------------


def test_yaml_legacy_freetext_loads_as_enum(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A legacy ``mid-level Python developer`` YAML loads cleanly as ``mid``."""
    monkeypatch.delenv("WIEDUNFLOW_TARGET_AUDIENCE", raising=False)
    cfg_file = tmp_path / "tutorial.config.yaml"
    _write_yaml(cfg_file, {"target_audience": "mid-level Python developer"})

    cfg = load_config(cli_config_path=cfg_file)

    assert cfg.target_audience == "mid"


def test_yaml_enum_value_loads_directly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """v0.4.0 YAML with bare ``senior`` enum value loads without warning."""
    monkeypatch.delenv("WIEDUNFLOW_TARGET_AUDIENCE", raising=False)
    cfg_file = tmp_path / "tutorial.config.yaml"
    _write_yaml(cfg_file, {"target_audience": "senior"})

    cfg = load_config(cli_config_path=cfg_file)

    assert cfg.target_audience == "senior"


def test_default_is_mid_when_not_specified(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Pydantic default must be ``mid`` (not the old free-text default)."""
    monkeypatch.delenv("WIEDUNFLOW_TARGET_AUDIENCE", raising=False)
    cfg_file = tmp_path / "tutorial.config.yaml"
    _write_yaml(cfg_file, {})

    cfg = load_config(cli_config_path=cfg_file)

    assert cfg.target_audience == "mid"
