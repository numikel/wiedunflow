# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Unit tests for scripts/aggregate_rubric.py (US-066)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml


@pytest.fixture
def tmp_rubric_dir(tmp_path: Path) -> Path:
    """Create a temporary rubric directory with standard structure."""
    rubric_dir = tmp_path / "v0.1.0"
    rubric_dir.mkdir(parents=True)
    return rubric_dir


def _write_signoff(
    rubric_dir: Path,
    slug: str,
    *,
    reviewer: str = "Test Reviewer",
    role: str = "trusted_friend",
    coverage: int = 3,
    accuracy: int = 3,
    narrative_flow: int = 3,
) -> None:
    """Helper to write a signoff YAML file."""
    data = {
        "reviewer": reviewer,
        "reviewer_role": role,
        "reviewed_at": "2026-04-24",
        "repo": "modelcontextprotocol/python-sdk",
        "tutorial_hash": "sha256:abc123",
        "scores": {
            "coverage": coverage,
            "accuracy": accuracy,
            "narrative_flow": narrative_flow,
        },
        "rationale": {
            "coverage": "Test coverage.",
            "accuracy": "Test accuracy.",
            "narrative_flow": "Test flow.",
        },
        "comments": "Test comments.",
    }
    path = rubric_dir / f"signoff-{slug}.yaml"
    with open(path, "w") as f:
        yaml.dump(data, f)


def test_gate_passes_with_three_reviewers_avg_4(tmp_rubric_dir: Path) -> None:
    """Gate passes when 1 author + 2 friends all score 4.0."""
    _write_signoff(
        tmp_rubric_dir,
        "author",
        reviewer="Michał Kamiński",
        role="author",
        coverage=4,
        accuracy=4,
        narrative_flow=4,
    )
    _write_signoff(
        tmp_rubric_dir,
        "alice",
        reviewer="Alice",
        role="trusted_friend",
        coverage=4,
        accuracy=4,
        narrative_flow=4,
    )
    _write_signoff(
        tmp_rubric_dir,
        "bob",
        reviewer="Bob",
        role="trusted_friend",
        coverage=4,
        accuracy=4,
        narrative_flow=4,
    )

    result = subprocess.run(
        [sys.executable, "scripts/aggregate_rubric.py", "--dir", str(tmp_rubric_dir)],
        cwd=Path(__file__).parent.parent.parent,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, (
        f"Expected exit 0, got {result.returncode}\nstderr:\n{result.stderr}"
    )

    # Check that aggregator output file exists
    agg_path = tmp_rubric_dir / "signoff-mcp-sdk.yaml"
    assert agg_path.exists()

    with open(agg_path) as f:
        agg = yaml.safe_load(f)

    assert agg["avg_score"] == 4.0
    assert agg["gate_passed"] is True


def test_gate_fails_with_two_reviewers(tmp_rubric_dir: Path) -> None:
    """Gate fails when only 2 sign-offs exist (need 1 author + 2 friends)."""
    _write_signoff(
        tmp_rubric_dir,
        "author",
        reviewer="Michał Kamiński",
        role="author",
        coverage=4,
        accuracy=4,
        narrative_flow=4,
    )
    _write_signoff(
        tmp_rubric_dir,
        "alice",
        reviewer="Alice",
        role="trusted_friend",
        coverage=4,
        accuracy=4,
        narrative_flow=4,
    )

    result = subprocess.run(
        [sys.executable, "scripts/aggregate_rubric.py", "--dir", str(tmp_rubric_dir)],
        cwd=Path(__file__).parent.parent.parent,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1, f"Expected exit 1, got {result.returncode}"
    assert "at least 2 trusted-friend sign-offs required" in result.stderr


def test_gate_fails_with_avg_below_3(tmp_rubric_dir: Path) -> None:
    """Gate fails when average across all reviewers is below 3.0."""
    _write_signoff(
        tmp_rubric_dir,
        "author",
        reviewer="Michał Kamiński",
        role="author",
        coverage=2,
        accuracy=2,
        narrative_flow=2,
    )
    _write_signoff(
        tmp_rubric_dir,
        "alice",
        reviewer="Alice",
        role="trusted_friend",
        coverage=2,
        accuracy=2,
        narrative_flow=2,
    )
    _write_signoff(
        tmp_rubric_dir,
        "bob",
        reviewer="Bob",
        role="trusted_friend",
        coverage=3,
        accuracy=3,
        narrative_flow=3,
    )

    result = subprocess.run(
        [sys.executable, "scripts/aggregate_rubric.py", "--dir", str(tmp_rubric_dir)],
        cwd=Path(__file__).parent.parent.parent,
        capture_output=True,
        text=True,
        check=False,
    )

    # Gate should fail (avg 2.33 < 3.0)
    assert result.returncode == 1

    agg_path = tmp_rubric_dir / "signoff-mcp-sdk.yaml"
    with open(agg_path) as f:
        agg = yaml.safe_load(f)

    assert agg["gate_passed"] is False


def test_gate_requires_author(tmp_rubric_dir: Path) -> None:
    """Gate fails when author sign-off is missing (only friends)."""
    _write_signoff(
        tmp_rubric_dir,
        "alice",
        reviewer="Alice",
        role="trusted_friend",
        coverage=4,
        accuracy=4,
        narrative_flow=4,
    )
    _write_signoff(
        tmp_rubric_dir,
        "bob",
        reviewer="Bob",
        role="trusted_friend",
        coverage=4,
        accuracy=4,
        narrative_flow=4,
    )

    result = subprocess.run(
        [sys.executable, "scripts/aggregate_rubric.py", "--dir", str(tmp_rubric_dir)],
        cwd=Path(__file__).parent.parent.parent,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "at least 1 author sign-off required" in result.stderr


def test_aggregator_emits_summary_yaml(tmp_rubric_dir: Path) -> None:
    """Aggregator writes signoff-mcp-sdk.yaml with correct schema."""
    _write_signoff(
        tmp_rubric_dir,
        "author",
        reviewer="Michał Kamiński",
        role="author",
        coverage=3,
        accuracy=3,
        narrative_flow=3,
    )
    _write_signoff(
        tmp_rubric_dir,
        "alice",
        reviewer="Alice",
        role="trusted_friend",
        coverage=3,
        accuracy=4,
        narrative_flow=3,
    )
    _write_signoff(
        tmp_rubric_dir,
        "bob",
        reviewer="Bob",
        role="trusted_friend",
        coverage=4,
        accuracy=3,
        narrative_flow=3,
    )

    result = subprocess.run(
        [sys.executable, "scripts/aggregate_rubric.py", "--dir", str(tmp_rubric_dir)],
        cwd=Path(__file__).parent.parent.parent,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0

    agg_path = tmp_rubric_dir / "signoff-mcp-sdk.yaml"
    assert agg_path.exists()

    with open(agg_path) as f:
        agg = yaml.safe_load(f)

    # Verify schema
    assert agg["repo"] == "modelcontextprotocol/python-sdk"
    assert "aggregated_at" in agg
    assert len(agg["reviewers"]) == 3
    assert "per_dimension_avg" in agg
    assert "avg_score" in agg
    assert agg["gate_passed"] is True
    assert agg["gate_threshold"] == 3.0
    assert agg["author_count"] == 1
    assert agg["friend_count"] == 2


def test_per_dimension_avg_computed(tmp_rubric_dir: Path) -> None:
    """Per-dimension averages are computed correctly with uneven scores."""
    _write_signoff(
        tmp_rubric_dir,
        "author",
        reviewer="Michał Kamiński",
        role="author",
        coverage=5,
        accuracy=3,
        narrative_flow=2,
    )
    _write_signoff(
        tmp_rubric_dir,
        "alice",
        reviewer="Alice",
        role="trusted_friend",
        coverage=4,
        accuracy=3,
        narrative_flow=3,
    )
    _write_signoff(
        tmp_rubric_dir,
        "bob",
        reviewer="Bob",
        role="trusted_friend",
        coverage=3,
        accuracy=4,
        narrative_flow=4,
    )

    result = subprocess.run(
        [sys.executable, "scripts/aggregate_rubric.py", "--dir", str(tmp_rubric_dir)],
        cwd=Path(__file__).parent.parent.parent,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0

    agg_path = tmp_rubric_dir / "signoff-mcp-sdk.yaml"
    with open(agg_path) as f:
        agg = yaml.safe_load(f)

    # Verify per-dimension averages
    # coverage: (5 + 4 + 3) / 3 = 4.0
    # accuracy: (3 + 3 + 4) / 3 = 3.33
    # narrative_flow: (2 + 3 + 4) / 3 = 3.0
    assert agg["per_dimension_avg"]["coverage"] == 4.0
    assert abs(agg["per_dimension_avg"]["accuracy"] - 3.33) < 0.01
    assert agg["per_dimension_avg"]["narrative_flow"] == 3.0

    # Grand avg: (4.0 + 3.33 + 3.0) / 3 = 3.44
    assert abs(agg["avg_score"] - 3.44) < 0.01
