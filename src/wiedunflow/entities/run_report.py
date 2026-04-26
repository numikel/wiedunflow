# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""RunReport entity — structured record of a codeguide run emitted as run-report.json.

Produced at the end of every invocation (successful, degraded, failed, or
interrupted) and written atomically to ``.codeguide/run-report.json`` by
:mod:`wiedunflow.cli.run_report_writer`.

Acceptance criteria covered:
- US-029: ``status="failed"`` carries ``failed_at_lesson`` + ``stack_trace``
- US-032: ``status="degraded"`` when > 30% of planned lessons were skipped
- US-027/028: ``status="interrupted"`` after first/second Ctrl+C
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

RunStatus = Literal["ok", "degraded", "failed", "interrupted"]


class RunReport(BaseModel):
    """Structured record of a single ``codeguide`` invocation.

    Serialised to ``.codeguide/run-report.json`` via the v1 schema.  The schema
    version is pinned so downstream tooling can evolve without breaking old
    reports.

    Attributes:
        schema_version: Pinned ``"1.0.0"``.  Bump on breaking changes.
        status: Terminal status of the run (maps to CLI exit codes).
        started_at: UTC timestamp of invocation start.
        finished_at: UTC timestamp when the report was finalised.
        total_planned_lessons: Regular lessons the planner proposed (post-cap).
            Denominator for the DEGRADED ratio (US-032).  ``0`` when planning
            failed before producing a manifest.
        skipped_lessons_count: Count of lessons that failed grounding retry
            and were rendered as placeholders (US-031).
        retry_count: Number of lessons that required a grounding retry
            (regardless of final outcome -- see US-030 AC2).
        cache_hit_rate: Ratio ``cached / (cached + computed)`` for the S5/S6
            cache.  ``0.0`` on the first run for a given ``(repo, commit)``.
        total_cost_usd: Aggregate LLM cost in USD across all providers.
        failed_at_lesson: Lesson ID at which an unhandled exception occurred
            (US-029).  ``None`` unless ``status == "failed"``.
        stack_trace: ``traceback.format_exc()`` output (US-029).  ``None``
            unless ``status == "failed"``.
        provider: ``"anthropic" | "openai" | "openai_compatible" | "fake"``.
        degraded_ratio: Exact ratio ``skipped / total_planned`` (0.0 to 1.0).
        hallucinated_symbols_count: Total count of symbol names that appeared in
            any LLM narration attempt but were absent from the AST snapshot.
            Covers both attempt-1 failures (including those recovered after
            retry) and attempt-2 failures.  The hard-pass gate is 0 (US-065).
        hallucinated_symbols: Deduplicated, sorted list of the offending symbol
            names.  Empty list when ``hallucinated_symbols_count == 0``.
    """

    model_config = ConfigDict(frozen=True)

    schema_version: Literal["1.0.0"] = "1.0.0"
    status: RunStatus
    started_at: datetime
    finished_at: datetime
    total_planned_lessons: int = Field(ge=0)
    skipped_lessons_count: int = Field(ge=0)
    retry_count: int = Field(ge=0)
    cache_hit_rate: float = Field(ge=0.0, le=1.0)
    total_cost_usd: float = Field(ge=0.0, default=0.0)
    provider: str = "fake"
    failed_at_lesson: str | None = None
    stack_trace: str | None = None
    degraded_ratio: float = Field(ge=0.0, le=1.0, default=0.0)
    hallucinated_symbols_count: int = Field(ge=0, default=0)
    hallucinated_symbols: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _check_consistency(self) -> RunReport:
        """Enforce cross-field invariants between status and payload fields."""
        if self.skipped_lessons_count > self.total_planned_lessons:
            raise ValueError(
                "skipped_lessons_count cannot exceed total_planned_lessons "
                f"({self.skipped_lessons_count} > {self.total_planned_lessons})"
            )
        if self.status == "failed":
            if self.stack_trace is None:
                raise ValueError("status='failed' requires a stack_trace")
        elif self.stack_trace is not None or self.failed_at_lesson is not None:
            raise ValueError(
                "failed_at_lesson and stack_trace are only allowed when status='failed'"
            )
        if self.finished_at < self.started_at:
            raise ValueError("finished_at must be >= started_at")
        if self.hallucinated_symbols_count != len(self.hallucinated_symbols):
            raise ValueError(
                "hallucinated_symbols_count must equal len(hallucinated_symbols) "
                f"({self.hallucinated_symbols_count} != {len(self.hallucinated_symbols)})"
            )
        return self

    def exit_code(self) -> int:
        """Map the terminal status to the CLI exit code contract (0/1/2/130)."""
        return {
            "ok": 0,
            "failed": 1,
            "degraded": 2,
            "interrupted": 130,
        }[self.status]
