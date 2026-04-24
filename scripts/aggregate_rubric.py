# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Aggregate rubric sign-offs and enforce the release gate (US-066).

Used by the release workflow to verify that the v0.1.0 quality rubric
has been signed off by the author and two trusted developer friends.

The gate passes when:
  1. At least 3 sign-off files exist (1 author, 2+ trusted_friends)
  2. Average score across all reviewers and dimensions >= 3.0

Usage:
    # Aggregate and enforce the gate
    uv run python scripts/aggregate_rubric.py --dir docs/rubric/v0.1.0

    # Exit code: 0 (gate passed) or 1 (gate failed)
    # Writes: docs/rubric/v0.1.0/signoff-mcp-sdk.yaml
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

# Score range for the 5-point rubric (US-066, FR-76).
MIN_SCORE = 1
MAX_SCORE = 5

# Release-gate reviewer requirements.
MIN_AUTHORS = 1
MIN_FRIENDS = 2
GATE_THRESHOLD = 3.0


@dataclass
class ReviewScore:
    """Single reviewer's score on one dimension."""

    reviewer: str
    role: str
    coverage: int
    accuracy: int
    narrative_flow: int

    @property
    def avg(self) -> float:
        """Mean across all three dimensions."""
        return (self.coverage + self.accuracy + self.narrative_flow) / 3.0


@dataclass
class RubricResult:
    """Aggregated gate result."""

    repo: str
    aggregated_at: str
    reviewers: list[dict[str, Any]] = field(default_factory=list)
    per_dimension_avg: dict[str, float] = field(default_factory=dict)
    avg_score: float = 0.0
    gate_passed: bool = False
    gate_threshold: float = 3.0
    author_count: int = 0
    friend_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a YAML-friendly dict."""
        return {
            "repo": self.repo,
            "aggregated_at": self.aggregated_at,
            "reviewers": self.reviewers,
            "per_dimension_avg": self.per_dimension_avg,
            "avg_score": self.avg_score,
            "gate_passed": self.gate_passed,
            "gate_threshold": self.gate_threshold,
            "author_count": self.author_count,
            "friend_count": self.friend_count,
        }


def _load_signoff(path: Path) -> ReviewScore | None:
    """Load a single sign-off YAML and return a ReviewScore.

    Returns None if the file is malformed or the role is invalid.
    """
    try:
        with open(path) as f:
            data = yaml.safe_load(f)
    except Exception as e:
        print(f"  error: failed to parse {path.name}: {e}", file=sys.stderr)
        return None

    if not isinstance(data, dict):
        print(f"  error: {path.name} is not a YAML dict", file=sys.stderr)
        return None

    try:
        reviewer = data.get("reviewer", "unknown")
        role = data.get("reviewer_role", "unknown")
        scores = data.get("scores", {})

        if role not in ("author", "trusted_friend"):
            print(
                f"  error: {path.name} has invalid reviewer_role '{role}'",
                file=sys.stderr,
            )
            return None

        coverage = int(scores.get("coverage", 0))
        accuracy = int(scores.get("accuracy", 0))
        narrative_flow = int(scores.get("narrative_flow", 0))

        all_in_range = all(
            MIN_SCORE <= s <= MAX_SCORE for s in (coverage, accuracy, narrative_flow)
        )
        if not all_in_range:
            print(
                f"  error: {path.name} has scores outside {MIN_SCORE}-{MAX_SCORE} range",
                file=sys.stderr,
            )
            return None

        return ReviewScore(
            reviewer=reviewer,
            role=role,
            coverage=coverage,
            accuracy=accuracy,
            narrative_flow=narrative_flow,
        )
    except (KeyError, ValueError, TypeError) as e:
        print(f"  error: {path.name} is missing required fields: {e}", file=sys.stderr)
        return None


def aggregate(rubric_dir: Path) -> int:  # noqa: PLR0915
    """Aggregate all signoff-*.yaml files in rubric_dir and enforce the gate.

    Skips signoff-mcp-sdk.yaml (the aggregator output itself).

    Returns:
        0 if gate passed, 1 if gate failed or error occurred.
    """
    rubric_dir_abs = rubric_dir.resolve()
    if not rubric_dir_abs.is_dir():
        print(f"error: {rubric_dir_abs} is not a directory", file=sys.stderr)
        return 1

    # Discover all signoff-*.yaml files, excluding the aggregator output
    signoff_files = sorted(
        f for f in rubric_dir_abs.glob("signoff-*.yaml") if f.name != "signoff-mcp-sdk.yaml"
    )

    if not signoff_files:
        print(
            f"error: no sign-off files found in {rubric_dir_abs}",
            file=sys.stderr,
        )
        return 1

    # Load all scores
    scores: list[ReviewScore] = []
    for path in signoff_files:
        score = _load_signoff(path)
        if score is not None:
            scores.append(score)

    if not scores:
        print("error: no valid sign-off files could be parsed", file=sys.stderr)
        return 1

    # Validate reviewer role distribution
    author_count = sum(1 for s in scores if s.role == "author")
    friend_count = sum(1 for s in scores if s.role == "trusted_friend")

    if author_count < MIN_AUTHORS:
        print(
            f"error: at least {MIN_AUTHORS} author sign-off required (found {author_count})",
            file=sys.stderr,
        )
        return 1

    if friend_count < MIN_FRIENDS:
        print(
            f"error: at least {MIN_FRIENDS} trusted-friend sign-offs required "
            f"(found {friend_count})",
            file=sys.stderr,
        )
        return 1

    # Compute per-dimension averages
    coverage_scores = [s.coverage for s in scores]
    accuracy_scores = [s.accuracy for s in scores]
    flow_scores = [s.narrative_flow for s in scores]

    avg_coverage = sum(coverage_scores) / len(coverage_scores)
    avg_accuracy = sum(accuracy_scores) / len(accuracy_scores)
    avg_flow = sum(flow_scores) / len(flow_scores)

    # Compute grand average
    grand_avg = (avg_coverage + avg_accuracy + avg_flow) / 3.0

    # Build the aggregator result
    result = RubricResult(
        repo="modelcontextprotocol/python-sdk",
        aggregated_at=datetime.now(UTC).isoformat(),
        author_count=author_count,
        friend_count=friend_count,
        per_dimension_avg={
            "coverage": round(avg_coverage, 2),
            "accuracy": round(avg_accuracy, 2),
            "narrative_flow": round(avg_flow, 2),
        },
        avg_score=round(grand_avg, 2),
        gate_threshold=GATE_THRESHOLD,
    )

    # Populate reviewer summaries
    for score in scores:
        result.reviewers.append(
            {
                "reviewer": score.reviewer,
                "role": score.role,
                "avg": round(score.avg, 2),
            }
        )

    # Check gate
    result.gate_passed = result.avg_score >= result.gate_threshold

    # Write aggregator output
    output_path = rubric_dir_abs / "signoff-mcp-sdk.yaml"
    with open(output_path, "w") as f:
        yaml.dump(result.to_dict(), f, default_flow_style=False, sort_keys=False)

    # Print human-readable summary
    print()
    print("=" * 70)
    print(f"RUBRIC AGGREGATION — {result.repo}")
    print("=" * 70)
    print(f"Aggregated at: {result.aggregated_at}")
    print(f"Sign-offs: {len(scores)} total ({author_count} author, {friend_count} friends)")
    print()
    print("Per-dimension averages:")
    print(f"  Coverage:      {result.per_dimension_avg['coverage']:.2f}")
    print(f"  Accuracy:      {result.per_dimension_avg['accuracy']:.2f}")
    print(f"  Narrative flow: {result.per_dimension_avg['narrative_flow']:.2f}")
    print()
    print(f"Grand average: {result.avg_score:.2f}")
    print(f"Gate threshold: {result.gate_threshold:.2f}")
    print()
    if result.gate_passed:
        print("[PASS] GATE PASSED - release approved")
    else:
        print("[FAIL] GATE FAILED - review required or more sign-offs needed")
    print()
    print(f"Aggregator output: {output_path}")
    print("=" * 70)
    print()

    return 0 if result.gate_passed else 1


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Aggregate release-gate rubric sign-offs and enforce gate (US-066).",
    )
    parser.add_argument(
        "--dir",
        type=Path,
        default=Path("docs/rubric/v0.1.0"),
        help="Directory containing signoff-*.yaml files (default: docs/rubric/v0.1.0).",
    )
    args = parser.parse_args()
    return aggregate(args.dir)


if __name__ == "__main__":
    raise SystemExit(main())
