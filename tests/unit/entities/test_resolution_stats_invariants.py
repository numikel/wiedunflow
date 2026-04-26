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
