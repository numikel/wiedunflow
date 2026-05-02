# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

import pytest
from pydantic import ValidationError

from wiedunflow.entities import ResolutionStats


def test_valid_instance():
    stats = ResolutionStats(resolved_pct=87.5, uncertain_count=3, unresolved_count=2)
    assert stats.resolved_pct == 87.5


@pytest.mark.parametrize("pct", [-0.1, 100.1, 200.0, -100.0])
def test_resolved_pct_out_of_range_rejected(pct: float):
    with pytest.raises(ValidationError, match="resolved_pct must be in"):
        ResolutionStats(resolved_pct=pct, uncertain_count=0, unresolved_count=0)


@pytest.mark.parametrize("pct", [0.0, 100.0, 50.0])
def test_resolved_pct_at_edges_accepted(pct: float):
    stats = ResolutionStats(resolved_pct=pct, uncertain_count=0, unresolved_count=0)
    assert stats.resolved_pct == pct


def test_negative_uncertain_rejected():
    with pytest.raises(ValidationError, match="uncertain_count must be >= 0"):
        ResolutionStats(resolved_pct=50.0, uncertain_count=-1, unresolved_count=0)


def test_negative_unresolved_rejected():
    with pytest.raises(ValidationError, match="unresolved_count must be >= 0"):
        ResolutionStats(resolved_pct=50.0, uncertain_count=0, unresolved_count=-5)


def test_is_frozen():
    stats = ResolutionStats(resolved_pct=50.0, uncertain_count=0, unresolved_count=0)
    with pytest.raises(ValidationError):
        stats.resolved_pct = 75.0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Tier 2: resolved_heuristic_count field
# ---------------------------------------------------------------------------


def test_resolved_heuristic_count_defaults_to_zero():
    stats = ResolutionStats(resolved_pct=50.0, uncertain_count=1, unresolved_count=1)
    assert stats.resolved_heuristic_count == 0


def test_resolved_heuristic_count_accepted():
    stats = ResolutionStats(
        resolved_pct=50.0,
        uncertain_count=0,
        unresolved_count=0,
        resolved_heuristic_count=5,
    )
    assert stats.resolved_heuristic_count == 5


def test_negative_resolved_heuristic_rejected():
    with pytest.raises(ValidationError, match="resolved_heuristic_count must be >= 0"):
        ResolutionStats(
            resolved_pct=50.0,
            uncertain_count=0,
            unresolved_count=0,
            resolved_heuristic_count=-1,
        )


# ---------------------------------------------------------------------------
# resolved_pct_with_heuristic computed property
# ---------------------------------------------------------------------------


def test_resolved_pct_with_heuristic_all_strict():
    """All edges strictly resolved → both pcts are 100."""
    stats = ResolutionStats(resolved_pct=100.0, uncertain_count=0, unresolved_count=0)
    assert stats.resolved_pct_with_heuristic == pytest.approx(100.0)


def test_resolved_pct_with_heuristic_zero_edges():
    """Zero-edge graph → 100% (nothing to fail)."""
    stats = ResolutionStats(resolved_pct=100.0, uncertain_count=0, unresolved_count=0)
    assert stats.resolved_pct_with_heuristic == pytest.approx(100.0)


def test_resolved_pct_with_heuristic_adds_heuristic():
    """1 strict + 1 heuristic + 1 unresolved = 3 edges → combined pct = 66.7%."""
    # resolved_pct = 1/3 = 33.33...
    # resolved_heuristic_count = 1
    # uncertain = 0, unresolved = 1
    # total = 3, combined = 2 → 66.67%
    stats = ResolutionStats(
        resolved_pct=100.0 / 3.0,
        uncertain_count=0,
        unresolved_count=1,
        resolved_heuristic_count=1,
    )
    assert stats.resolved_pct_with_heuristic == pytest.approx(200.0 / 3.0, abs=0.1)


def test_resolved_pct_with_heuristic_backward_compat():
    """resolved_pct is unchanged (strict only) — heuristic does not bleed in."""
    stats = ResolutionStats(
        resolved_pct=100.0 / 3.0,
        uncertain_count=0,
        unresolved_count=1,
        resolved_heuristic_count=1,
    )
    assert stats.resolved_pct == pytest.approx(100.0 / 3.0, abs=0.01)


def test_resolved_pct_with_heuristic_no_heuristic_matches_strict():
    """When resolved_heuristic_count=0 the combined pct equals resolved_pct."""
    stats = ResolutionStats(
        resolved_pct=40.0,
        uncertain_count=2,
        unresolved_count=1,
        resolved_heuristic_count=0,
    )
    assert stats.resolved_pct_with_heuristic == pytest.approx(stats.resolved_pct, abs=0.5)
