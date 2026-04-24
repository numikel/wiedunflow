# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""US-022: --log-format=json emits one JSON object per line with ts/level/stage/msg."""

from __future__ import annotations

import json

import pytest
import structlog

from codeguide.cli.logging import configure, get_logger


@pytest.fixture(autouse=True)
def _reset_structlog() -> None:
    """Restore structlog defaults between tests to avoid bleeding JSON config."""
    yield
    structlog.reset_defaults()


def test_json_mode_writes_jsonlines_with_required_keys(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure(json_mode=True)
    logger = get_logger(stage="test-stage")
    logger.info("hello_world", detail="something")
    captured = capsys.readouterr()
    line = captured.err.strip().splitlines()[-1]
    payload = json.loads(line)
    assert payload["msg"] == "hello_world"
    assert payload["stage"] == "test-stage"
    assert payload["level"] == "info"
    assert "ts" in payload
    assert payload["detail"] == "something"


def test_text_mode_does_not_emit_json(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure(json_mode=False)
    logger = get_logger(stage="test")
    logger.info("plain_event", key="val")
    captured = capsys.readouterr()
    out = captured.err + captured.out
    assert "plain_event" in out
    # Should not be valid JSON since ConsoleRenderer emits key=value format.
    try:
        json.loads(out.strip().splitlines()[-1])
        raised = False
    except json.JSONDecodeError:
        raised = True
    assert raised, f"Expected non-JSON output in text mode, got: {out}"
