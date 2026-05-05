# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Tests for path redaction in the structlog processor (ADR-0010 §D12)."""

from __future__ import annotations

from pathlib import Path

import pytest
import structlog

from wiedunflow.cli.logging import _make_redact_processor


@pytest.fixture(autouse=True)
def _reset_structlog() -> None:
    """Restore structlog defaults between tests to avoid bleeding configuration."""
    yield
    structlog.reset_defaults()


def test_processor_redacts_external_paths(tmp_path: Path) -> None:
    repo = tmp_path / "myrepo"
    repo.mkdir()
    proc = _make_redact_processor(redact_secrets=True, redact_paths=True, repo_root=repo)
    event: dict[str, object] = {
        "event": "loaded",
        "path": "/home/alice/private/secret.py",
    }
    out = proc(None, "info", event)
    assert out["path"] == "<external>"


def test_processor_keeps_repo_internal_paths(tmp_path: Path) -> None:
    repo = tmp_path / "myrepo"
    repo.mkdir()
    proc = _make_redact_processor(redact_secrets=True, redact_paths=True, repo_root=repo)
    internal = str(repo / "src" / "main.py")
    event: dict[str, object] = {"path": internal}
    out = proc(None, "info", event)
    assert out["path"] == internal


def test_processor_no_op_when_paths_disabled(tmp_path: Path) -> None:
    proc = _make_redact_processor(redact_secrets=True, redact_paths=False, repo_root=tmp_path)
    event: dict[str, object] = {"path": "/home/alice/foo.py"}
    out = proc(None, "info", event)
    assert out["path"] == "/home/alice/foo.py"


def test_processor_no_op_when_repo_root_none(tmp_path: Path) -> None:
    """Path redaction requires repo_root context; without it, no-op."""
    proc = _make_redact_processor(redact_secrets=True, redact_paths=True, repo_root=None)
    event: dict[str, object] = {"path": "/home/alice/foo.py"}
    out = proc(None, "info", event)
    assert out["path"] == "/home/alice/foo.py"


def test_processor_redacts_secret_and_path(tmp_path: Path) -> None:
    repo = tmp_path / "myrepo"
    repo.mkdir()
    proc = _make_redact_processor(redact_secrets=True, redact_paths=True, repo_root=repo)
    event: dict[str, object] = {
        "msg": "ANTHROPIC_API_KEY=sk-ant-api03-XYZ123abcdefghijklmnopqrst in /home/alice/file.py",
    }
    out = proc(None, "info", event)
    out_msg = out["msg"]
    assert isinstance(out_msg, str)
    assert "sk-ant-api03" not in out_msg
    assert "/home/alice" not in out_msg
