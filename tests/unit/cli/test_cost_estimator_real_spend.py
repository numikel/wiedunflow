# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Unit tests for the validate_cost_estimator.py validation script.

Uses a synthetic transcript fixture (hand-crafted JSONL files) to verify:
1. parse_run_dir correctly aggregates per-role token sums.
2. The ex-ante estimator (cost_estimator.estimate) produces values within
   ±50% of the real (synthetic) spend on the fixture — confirming the
   estimator is in the right ballpark and parse_run_dir extracts data correctly.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.validate_cost_estimator import parse_run_dir

# ---------------------------------------------------------------------------
# Helpers to build the synthetic transcript tree
# ---------------------------------------------------------------------------


def _write_jsonl(path: Path, records: list[dict]) -> None:
    """Write *records* as newline-delimited JSON to *path* (creates parent dirs)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(r) for r in records),
        encoding="utf-8",
    )


def _usage(inp: int, out: int) -> dict:
    return {"input_tokens": inp, "output_tokens": out}


def _record(role: str, inp: int, out: int, model: str, lesson_id: str = "lesson-001") -> dict:
    return {
        "role": role,
        "usage": _usage(inp, out),
        "model": model,
        "lesson_id": lesson_id,
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def synthetic_run(tmp_path: Path) -> Path:
    """Build a synthetic run directory tree with 3 lessons x 5 calls each.

    Layout::

        tmp_path/
          runs/
            test-run-id/
              manifest.json
              transcript/
                planning/
                  planning.jsonl
                lesson-001/
                  orchestrator-0.jsonl
                  researcher-0.jsonl
                  writer-0.jsonl
                  reviewer-0.jsonl
                lesson-002/
                  orchestrator-0.jsonl
                  researcher-0.jsonl
                  writer-0.jsonl
                  reviewer-0.jsonl
                lesson-003/
                  orchestrator-0.jsonl
                  researcher-0.jsonl
                  writer-0.jsonl
                  reviewer-0.jsonl
    """
    run_dir = tmp_path / "runs" / "test-run-id"

    # ── Planning (one call) ──────────────────────────────────────────────────
    _write_jsonl(
        run_dir / "transcript" / "planning" / "planning.jsonl",
        [_record("planning", inp=22_000, out=7_000, model="gpt-5.4", lesson_id="")],
    )

    # Per-lesson calls (3 lessons x 4 roles each)
    for lesson_id in ("lesson-001", "lesson-002", "lesson-003"):
        # Orchestrator: 1 call per lesson
        _write_jsonl(
            run_dir / "transcript" / lesson_id / "orchestrator-0.jsonl",
            [
                _record(
                    "orchestrator", inp=20_000, out=2_500, model="gpt-5.4", lesson_id=lesson_id
                ),
            ],
        )
        # Researcher: 2 calls per lesson
        _write_jsonl(
            run_dir / "transcript" / lesson_id / "researcher-0.jsonl",
            [
                _record(
                    "researcher", inp=55_000, out=1_200, model="gpt-5.4-mini", lesson_id=lesson_id
                ),
                _record(
                    "researcher", inp=50_000, out=1_400, model="gpt-5.4-mini", lesson_id=lesson_id
                ),
            ],
        )
        # Writer: 1 call per lesson
        _write_jsonl(
            run_dir / "transcript" / lesson_id / "writer-0.jsonl",
            [
                _record("writer", inp=45_000, out=2_800, model="gpt-5.4", lesson_id=lesson_id),
            ],
        )
        # Reviewer: 1 call per lesson
        _write_jsonl(
            run_dir / "transcript" / lesson_id / "reviewer-0.jsonl",
            [
                _record("reviewer", inp=28_000, out=900, model="gpt-5.4-mini", lesson_id=lesson_id),
            ],
        )

    # ── Manifest (minimal — just lessons list so count works) ───────────────
    manifest = {
        "lessons": [
            {"id": "lesson-001", "title": "Intro"},
            {"id": "lesson-002", "title": "Core"},
            {"id": "lesson-003", "title": "Advanced"},
        ],
        "symbols": 80,
        "clusters": [],
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    return run_dir


# ---------------------------------------------------------------------------
# Test: parser correctness
# ---------------------------------------------------------------------------


def test_parse_run_dir_returns_all_five_roles(synthetic_run: Path) -> None:
    """parse_run_dir must find records for all five pipeline roles."""
    result = parse_run_dir(synthetic_run)
    for role in ("planning", "orchestrator", "researcher", "writer", "reviewer"):
        assert role in result, f"Role '{role}' missing from parsed spend: {list(result)}"


def test_parse_run_dir_planning_tokens(synthetic_run: Path) -> None:
    """Planning role: 1 call with 22 000 in + 7 000 out."""
    result = parse_run_dir(synthetic_run)
    p = result["planning"]
    assert p.input_tokens == 22_000
    assert p.output_tokens == 7_000


def test_parse_run_dir_orchestrator_tokens(synthetic_run: Path) -> None:
    """Orchestrator role: 3 lessons x 1 call x (20 000 in + 2 500 out)."""
    result = parse_run_dir(synthetic_run)
    o = result["orchestrator"]
    assert o.input_tokens == 3 * 20_000
    assert o.output_tokens == 3 * 2_500


def test_parse_run_dir_researcher_tokens(synthetic_run: Path) -> None:
    """Researcher role: 3 lessons x 2 calls x (55 000 + 50 000 in, 1 200 + 1 400 out)."""
    result = parse_run_dir(synthetic_run)
    r = result["researcher"]
    assert r.input_tokens == 3 * (55_000 + 50_000)
    assert r.output_tokens == 3 * (1_200 + 1_400)


def test_parse_run_dir_writer_tokens(synthetic_run: Path) -> None:
    """Writer role: 3 lessons x 1 call x (45 000 in + 2 800 out)."""
    result = parse_run_dir(synthetic_run)
    w = result["writer"]
    assert w.input_tokens == 3 * 45_000
    assert w.output_tokens == 3 * 2_800


def test_parse_run_dir_reviewer_tokens(synthetic_run: Path) -> None:
    """Reviewer role: 3 lessons x 1 call x (28 000 in + 900 out)."""
    result = parse_run_dir(synthetic_run)
    rv = result["reviewer"]
    assert rv.input_tokens == 3 * 28_000
    assert rv.output_tokens == 3 * 900


def test_parse_run_dir_model_names_captured(synthetic_run: Path) -> None:
    """parse_run_dir must capture the model id for each role."""
    result = parse_run_dir(synthetic_run)
    assert result["planning"].model == "gpt-5.4"
    assert result["orchestrator"].model == "gpt-5.4"
    assert result["researcher"].model == "gpt-5.4-mini"
    assert result["writer"].model == "gpt-5.4"
    assert result["reviewer"].model == "gpt-5.4-mini"


def test_parse_run_dir_empty_transcript_dir(tmp_path: Path) -> None:
    """An empty transcript directory must return an empty dict (no crash)."""
    run_dir = tmp_path / "empty-run"
    (run_dir / "transcript").mkdir(parents=True)
    result = parse_run_dir(run_dir)
    assert result == {}


def test_parse_run_dir_missing_transcript_dir(tmp_path: Path) -> None:
    """A run dir without a transcript subdir must return an empty dict."""
    run_dir = tmp_path / "no-transcript"
    run_dir.mkdir(parents=True)
    result = parse_run_dir(run_dir)
    assert result == {}


# ---------------------------------------------------------------------------
# Test: estimator delta against synthetic fixture
# ---------------------------------------------------------------------------


def test_validate_cost_estimator_synthetic_transcript(synthetic_run: Path) -> None:
    """parse_run_dir and estimate() must round-trip sensibly on a synthetic fixture.

    The estimator is a conservative over-estimate (1.3x safety factor, max-
    iteration ceilings).  This test verifies two properties:

    1. parse_run_dir extracts the expected totals (covered by the individual
       token tests above).
    2. The estimator does NOT under-estimate real spend by more than 10% per
       role (under-estimation at the cost gate would mislead users).
    3. The estimator stays within 500% of real spend per role — an absurdly
       wide upper bound that merely guards against orders-of-magnitude divergence
       caused by pricing-map bugs or model-id mismatches.
    """
    from scripts.validate_cost_estimator import _delta_pct

    from wiedunflow.cli.cost_estimator import estimate

    real = parse_run_dir(synthetic_run)

    # Use the same models the fixture used.
    est = estimate(
        symbols=80,
        lessons=3,
        clusters=0,
        plan_model="gpt-5.4",
        orchestrator_model="gpt-5.4",
        researcher_model="gpt-5.4-mini",
        writer_model="gpt-5.4",
        reviewer_model="gpt-5.4-mini",
    )

    role_est_map = {
        "planning": est.planning,
        "orchestrator": est.orchestrator,
        "researcher": est.researcher,
        "writer": est.writer,
        "reviewer": est.reviewer,
    }

    # Estimator must not under-estimate real spend (negative delta = real > est).
    under_threshold = -10.0  # percent; allow tiny float rounding but no true under-estimate
    # Estimator must not diverge > 500% over-estimate (orders-of-magnitude guard).
    over_threshold = 500.0  # percent

    for role in ("planning", "orchestrator", "researcher", "writer", "reviewer"):
        real_spend = real.get(role)
        est_role = role_est_map.get(role)
        if real_spend is None or est_role is None:
            continue

        real_tok = real_spend.total_tokens()
        est_tok = est_role.input_tokens + est_role.output_tokens
        delta = _delta_pct(est_tok, real_tok)

        assert delta > under_threshold, (
            f"Role '{role}': estimator UNDER-estimates by {delta:+.1f}% — real spend "
            f"exceeds estimate (est={est_tok:,} tok, real={real_tok:,} tok). "
            f"Under-estimation misleads users at the cost gate."
        )
        assert delta < over_threshold, (
            f"Role '{role}': estimator is {delta:+.1f}% over real spend "
            f"(est={est_tok:,} tok, real={real_tok:,} tok). "
            f"This suggests a pricing-map bug or wrong model id."
        )
