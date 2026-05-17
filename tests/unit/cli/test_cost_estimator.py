# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""US-012: ex-ante cost estimator — v0.9.0+ multi-agent pipeline model.

Tests cover the per-role accounting introduced in ADR-0016 / ADR-0020:
Orchestrator + Researcher x N + Writer + Reviewer per-lesson plus a single
Planning call, all with per-token-class pricing and a 1.3 safety factor.
"""

from __future__ import annotations

import math
from dataclasses import FrozenInstanceError

import pytest

from wiedunflow.cli.cost_estimator import (
    _ORCH_INPUT_PER_LESSON,
    _ORCH_OUTPUT_PER_LESSON,
    _PLANNING_BASE_INPUT_TOKENS,
    _PLANNING_OUTPUT_TOKENS,
    _PLANNING_PER_SYMBOL_INPUT_TOKENS,
    _RESEARCH_CALLS_PER_LESSON,
    _RESEARCH_INPUT_PER_CALL,
    _RESEARCH_OUTPUT_PER_CALL,
    _REVIEWER_CALLS_PER_LESSON,
    _REVIEWER_INPUT_PER_CALL,
    _REVIEWER_OUTPUT_PER_CALL,
    _RUNTIME_MAX_PER_LESSON_SEC,
    _RUNTIME_MIN_PER_LESSON_SEC,
    _SAFETY_FACTOR,
    _WRITER_CALLS_PER_LESSON,
    _WRITER_INPUT_PER_CALL,
    _WRITER_OUTPUT_PER_CALL,
    MODEL_PRICES,
    estimate,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _gpt54_in() -> float:
    return MODEL_PRICES["gpt-5.4"][0]  # 2.50


def _gpt54_out() -> float:
    return MODEL_PRICES["gpt-5.4"][1]  # 15.00


def _gpt54mini_in() -> float:
    return MODEL_PRICES["gpt-5.4-mini"][0]  # 0.75


def _gpt54mini_out() -> float:
    return MODEL_PRICES["gpt-5.4-mini"][1]  # 4.50


def _role_cost_formula(
    input_tokens: int, output_tokens: int, in_price: float, out_price: float
) -> float:
    """Mirror the internal formula for golden-value assertions."""
    raw = (input_tokens / 1_000_000.0) * in_price + (output_tokens / 1_000_000.0) * out_price
    return raw * _SAFETY_FACTOR


# ---------------------------------------------------------------------------
# Test case 1 — minimal (symbols=5, lessons=1, all defaults)
# ---------------------------------------------------------------------------


def test_minimal_planning_cost() -> None:
    """Planning: 25_500 in + 8_000 out at gpt-5.4 prices * 1.3."""
    result = estimate(symbols=5, lessons=1, clusters=1)
    # planning_input = 25_000 + 5 * 100 = 25_500
    assert result.planning.input_tokens == 25_500
    assert result.planning.output_tokens == _PLANNING_OUTPUT_TOKENS

    expected_cost = _role_cost_formula(25_500, 8_000, _gpt54_in(), _gpt54_out())
    assert abs(result.planning.cost_usd - expected_cost) < 0.001


def test_minimal_orchestrator_cost() -> None:
    """Orchestrator: 1 lesson * per-lesson tokens at gpt-5.4 prices."""
    result = estimate(symbols=5, lessons=1, clusters=1)
    assert result.orchestrator.input_tokens == 1 * _ORCH_INPUT_PER_LESSON
    assert result.orchestrator.output_tokens == 1 * _ORCH_OUTPUT_PER_LESSON

    expected = _role_cost_formula(
        1 * _ORCH_INPUT_PER_LESSON, 1 * _ORCH_OUTPUT_PER_LESSON, _gpt54_in(), _gpt54_out()
    )
    assert abs(result.orchestrator.cost_usd - expected) < 0.001


def test_minimal_researcher_cost() -> None:
    """Researcher: ceil(1 * 3) = 3 calls at gpt-5.4-mini prices."""
    result = estimate(symbols=5, lessons=1, clusters=1)
    expected_calls = math.ceil(1 * _RESEARCH_CALLS_PER_LESSON)
    assert result.researcher.input_tokens == expected_calls * _RESEARCH_INPUT_PER_CALL
    assert result.researcher.output_tokens == expected_calls * _RESEARCH_OUTPUT_PER_CALL

    expected = _role_cost_formula(
        expected_calls * _RESEARCH_INPUT_PER_CALL,
        expected_calls * _RESEARCH_OUTPUT_PER_CALL,
        _gpt54mini_in(),
        _gpt54mini_out(),
    )
    assert abs(result.researcher.cost_usd - expected) < 0.001


def test_minimal_writer_cost() -> None:
    """Writer: ceil(1 * 1.5) = 2 calls at gpt-5.4 prices."""
    result = estimate(symbols=5, lessons=1, clusters=1)
    expected_calls = math.ceil(1 * _WRITER_CALLS_PER_LESSON)
    assert result.writer.input_tokens == expected_calls * _WRITER_INPUT_PER_CALL
    assert result.writer.output_tokens == expected_calls * _WRITER_OUTPUT_PER_CALL


def test_minimal_reviewer_cost() -> None:
    """Reviewer: ceil(1 * 1.5) = 2 calls at gpt-5.4-mini prices."""
    result = estimate(symbols=5, lessons=1, clusters=1)
    expected_calls = math.ceil(1 * _REVIEWER_CALLS_PER_LESSON)
    assert result.reviewer.input_tokens == expected_calls * _REVIEWER_INPUT_PER_CALL
    assert result.reviewer.output_tokens == expected_calls * _REVIEWER_OUTPUT_PER_CALL


def test_minimal_runtime() -> None:
    result = estimate(symbols=5, lessons=1, clusters=1)
    assert result.runtime_min_minutes >= 1
    assert result.runtime_max_minutes > result.runtime_min_minutes
    # 1 lesson: min = max(1, 90//60) = 1; max = max(2, 240//60) = 4
    assert result.runtime_min_minutes == max(1, 1 * _RUNTIME_MIN_PER_LESSON_SEC // 60)
    assert result.runtime_max_minutes == max(2, 1 * _RUNTIME_MAX_PER_LESSON_SEC // 60)


def test_minimal_total_cost_positive() -> None:
    result = estimate(symbols=5, lessons=1, clusters=1)
    assert result.total_cost_usd > 0
    # Rough sanity: minimal run well under $5 with defaults
    assert result.total_cost_usd < 5.0


# ---------------------------------------------------------------------------
# Test case 2 — typical (symbols=200, lessons=20, clusters=3)
# ---------------------------------------------------------------------------


def test_typical_total_cost_range() -> None:
    """Typical run cost should be in the $5-$50 range with default models."""
    result = estimate(symbols=200, lessons=20, clusters=3)
    assert result.total_cost_usd > 5.0, f"Expected >$5, got ${result.total_cost_usd}"
    assert result.total_cost_usd < 50.0, f"Expected <$50, got ${result.total_cost_usd}"


def test_typical_runtime_range() -> None:
    """20 lessons: min 30 min, max 80 min."""
    result = estimate(symbols=200, lessons=20, clusters=3)
    expected_min = max(1, 20 * _RUNTIME_MIN_PER_LESSON_SEC // 60)  # 30
    expected_max = max(2, 20 * _RUNTIME_MAX_PER_LESSON_SEC // 60)  # 80
    assert result.runtime_min_minutes == expected_min
    assert result.runtime_max_minutes == expected_max


def test_typical_model_labels() -> None:
    """Default model ids are reflected in RoleCost.model fields."""
    result = estimate(symbols=200, lessons=20, clusters=3)
    assert result.planning.model == "gpt-5.4"
    assert result.orchestrator.model == "gpt-5.4"
    assert result.researcher.model == "gpt-5.4-mini"
    assert result.writer.model == "gpt-5.4"
    assert result.reviewer.model == "gpt-5.4-mini"


# ---------------------------------------------------------------------------
# Test case 3 — hard cap edge (symbols=1000, lessons=30, clusters=10)
# ---------------------------------------------------------------------------


def test_large_repo_no_overflow() -> None:
    """1000 symbols, 30 lessons should produce finite, positive estimates."""
    result = estimate(symbols=1000, lessons=30, clusters=10)
    assert result.total_cost_usd > 0
    assert result.total_tokens > 0
    assert result.runtime_max_minutes > result.runtime_min_minutes
    # Sanity ceiling — at default prices, even 30 lessons shouldn't exceed $200
    assert result.total_cost_usd < 200.0


def test_large_repo_planning_scales_with_symbols() -> None:
    """Planning input must scale linearly: base + symbols * per_symbol."""
    result = estimate(symbols=1000, lessons=30, clusters=10)
    expected_planning_input = _PLANNING_BASE_INPUT_TOKENS + 1000 * _PLANNING_PER_SYMBOL_INPUT_TOKENS
    assert result.planning.input_tokens == expected_planning_input


# ---------------------------------------------------------------------------
# Test case 4 — per-role accounting invariant
# ---------------------------------------------------------------------------


def test_total_tokens_equals_sum_of_role_tokens() -> None:
    """total_tokens must equal the exact sum of all per-role input + output."""
    result = estimate(symbols=200, lessons=20, clusters=3)
    expected_total = sum(
        role.input_tokens + role.output_tokens
        for role in (
            result.planning,
            result.orchestrator,
            result.researcher,
            result.writer,
            result.reviewer,
        )
    )
    assert result.total_tokens == expected_total


def test_total_tokens_equals_sum_of_role_tokens_minimal() -> None:
    result = estimate(symbols=5, lessons=1, clusters=1)
    expected_total = sum(
        role.input_tokens + role.output_tokens
        for role in (
            result.planning,
            result.orchestrator,
            result.researcher,
            result.writer,
            result.reviewer,
        )
    )
    assert result.total_tokens == expected_total


def test_total_cost_equals_sum_of_role_costs() -> None:
    """total_cost_usd == round(sum(role.cost_usd), 2) across all roles."""
    result = estimate(symbols=200, lessons=20, clusters=3)
    sum_of_roles = round(
        result.planning.cost_usd
        + result.orchestrator.cost_usd
        + result.researcher.cost_usd
        + result.writer.cost_usd
        + result.reviewer.cost_usd,
        2,
    )
    assert result.total_cost_usd == sum_of_roles


# ---------------------------------------------------------------------------
# Test case 5 — pricing fallback for unknown model id
# ---------------------------------------------------------------------------


def test_unknown_model_falls_back_without_crash() -> None:
    """An unknown model id must not raise; conservative fallback prices apply."""
    result = estimate(
        symbols=50,
        lessons=5,
        clusters=1,
        orchestrator_model="unknown-model-xyz-9999",
        researcher_model="another-unknown-model",
    )
    # Must produce a valid estimate without crashing.
    assert result.total_cost_usd > 0
    assert result.total_tokens > 0
    # Unknown model ids preserved verbatim in the RoleCost fields.
    assert result.orchestrator.model == "unknown-model-xyz-9999"
    assert result.researcher.model == "another-unknown-model"


def test_none_model_uses_defaults() -> None:
    """Passing None for any role model should resolve to the built-in default."""
    result_none = estimate(
        symbols=100,
        lessons=10,
        clusters=2,
        orchestrator_model=None,
        writer_model=None,
    )
    result_explicit = estimate(
        symbols=100,
        lessons=10,
        clusters=2,
        orchestrator_model="gpt-5.4",
        writer_model="gpt-5.4",
    )
    assert result_none.orchestrator.model == result_explicit.orchestrator.model
    assert result_none.writer.model == result_explicit.writer.model
    assert result_none.total_cost_usd == result_explicit.total_cost_usd


# ---------------------------------------------------------------------------
# Test case 6 — CostEstimate and RoleCost are frozen
# ---------------------------------------------------------------------------


def test_cost_estimate_is_frozen() -> None:
    """CostEstimate must be immutable — attribute assignment raises."""
    result = estimate(symbols=10, lessons=2, clusters=1)
    with pytest.raises(FrozenInstanceError):
        result.total_cost_usd = 0.0  # type: ignore[misc]


def test_role_cost_is_frozen() -> None:
    """RoleCost must be immutable — attribute assignment raises."""
    result = estimate(symbols=10, lessons=2, clusters=1)
    with pytest.raises(FrozenInstanceError):
        result.planning.cost_usd = 0.0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Regression: zero symbols / zero lessons edge cases
# ---------------------------------------------------------------------------


def test_zero_symbols_valid() -> None:
    """symbols=0 must produce a valid estimate (no division by zero)."""
    result = estimate(symbols=0, lessons=3, clusters=1)
    assert result.planning.input_tokens == _PLANNING_BASE_INPUT_TOKENS
    assert result.total_cost_usd > 0


def test_zero_lessons_valid() -> None:
    """lessons=0 produces only a planning call cost; no narration cost."""
    result = estimate(symbols=50, lessons=0, clusters=1)
    assert result.orchestrator.input_tokens == 0
    assert result.researcher.input_tokens == 0
    assert result.writer.input_tokens == 0
    assert result.reviewer.input_tokens == 0
    # Planning cost still non-zero even with 0 lessons.
    assert result.planning.cost_usd > 0
    # Runtime is clamped to minimums.
    assert result.runtime_min_minutes >= 1
    assert result.runtime_max_minutes >= 2
