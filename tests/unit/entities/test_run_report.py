# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Unit tests for RunReport entity (Phase 3 cross-cutting)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from codeguide.entities.run_report import RunReport


def _base_kwargs(**overrides: object) -> dict[str, object]:
    """Build a minimal valid RunReport kwargs dict; overrides take precedence."""
    started = datetime(2026, 4, 21, 12, 0, 0, tzinfo=UTC)
    defaults: dict[str, object] = {
        "status": "ok",
        "started_at": started,
        "finished_at": started + timedelta(seconds=42),
        "total_planned_lessons": 10,
        "skipped_lessons_count": 0,
        "retry_count": 0,
        "cache_hit_rate": 0.0,
        "provider": "anthropic",
    }
    defaults.update(overrides)
    return defaults


def test_ok_report_builds_with_defaults() -> None:
    report = RunReport(**_base_kwargs())  # type: ignore[arg-type]
    assert report.schema_version == "1.0.0"
    assert report.status == "ok"
    assert report.exit_code() == 0


def test_degraded_report_maps_to_exit_code_2() -> None:
    report = RunReport(
        **_base_kwargs(  # type: ignore[arg-type]
            status="degraded",
            skipped_lessons_count=4,
            total_planned_lessons=10,
            degraded_ratio=0.4,
        )
    )
    assert report.exit_code() == 2


def test_failed_report_maps_to_exit_code_1() -> None:
    report = RunReport(
        **_base_kwargs(  # type: ignore[arg-type]
            status="failed",
            stack_trace="Traceback...\nRuntimeError: boom",
            failed_at_lesson="lesson-007",
        )
    )
    assert report.exit_code() == 1
    assert report.failed_at_lesson == "lesson-007"


def test_interrupted_report_maps_to_exit_code_130() -> None:
    report = RunReport(**_base_kwargs(status="interrupted"))  # type: ignore[arg-type]
    assert report.exit_code() == 130


def test_skipped_cannot_exceed_planned() -> None:
    with pytest.raises(ValidationError, match="skipped_lessons_count cannot exceed"):
        RunReport(
            **_base_kwargs(  # type: ignore[arg-type]
                total_planned_lessons=5,
                skipped_lessons_count=6,
            )
        )


def test_failed_requires_stack_trace() -> None:
    with pytest.raises(ValidationError, match="requires a stack_trace"):
        RunReport(**_base_kwargs(status="failed"))  # type: ignore[arg-type]


def test_non_failed_cannot_have_failure_payload() -> None:
    with pytest.raises(ValidationError, match="only allowed when status='failed'"):
        RunReport(
            **_base_kwargs(  # type: ignore[arg-type]
                status="ok",
                stack_trace="oops",
            )
        )


def test_finished_before_started_rejected() -> None:
    started = datetime(2026, 4, 21, 12, 0, 0, tzinfo=UTC)
    with pytest.raises(ValidationError, match="finished_at must be >= started_at"):
        RunReport(
            **_base_kwargs(  # type: ignore[arg-type]
                started_at=started,
                finished_at=started - timedelta(seconds=1),
            )
        )


def test_cache_hit_rate_bounded() -> None:
    with pytest.raises(ValidationError):
        RunReport(**_base_kwargs(cache_hit_rate=1.5))  # type: ignore[arg-type]
