# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Validate the preflight cost estimator against real transcript data.

Parses the JSONL usage records written during a WiedunFlow run, aggregates
actual token spend per role (planning / orchestrator / researcher / writer /
reviewer), then compares that against the ex-ante estimate produced by
:func:`wiedunflow.cli.cost_estimator.estimate`.

Usage
-----
Compare the most recent run (auto-detected by mtime)::

    python scripts/validate_cost_estimator.py --latest

Compare a specific run::

    python scripts/validate_cost_estimator.py --run-id abc123def456

Override the default runs directory::

    python scripts/validate_cost_estimator.py --latest --runs-dir /custom/path

JSONL Record Format
-------------------
Each line in a transcript file is a JSON object with these fields::

    {
        "usage": {"input_tokens": 1234, "output_tokens": 567},
        "model": "gpt-5.4-mini",
        "role": "researcher",  # planning | orchestrator | researcher | writer | reviewer
        "lesson_id": "lesson-001",  # absent for planning
    }

The ``role`` field is the canonical way to attribute a call to a pipeline role.
When absent (legacy or planning-level files in ``transcript/planning/``), the
script falls back to inferring the role from the directory name.

Exit codes
----------
- 0: all roles have |DELTA%| < 50 % — estimator is within bounds.
- 1: at least one role exceeds ±50 % — estimator needs recalibration
  (soft warning; does not block releases).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from rich.console import Console
from rich.table import Table

from wiedunflow.cli.cost_estimator import (
    _DEFAULT_ORCHESTRATOR_MODEL,
    _DEFAULT_PLAN_MODEL,
    _DEFAULT_RESEARCHER_MODEL,
    _DEFAULT_REVIEWER_MODEL,
    _DEFAULT_WRITER_MODEL,
    _FALLBACK_INPUT_USD_PER_MTOK,
    MODEL_PRICES,
    estimate,
)

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

_KNOWN_ROLES: tuple[str, ...] = (
    "planning",
    "orchestrator",
    "researcher",
    "writer",
    "reviewer",
)

_DELTA_WARN_THRESHOLD = 50.0  # percent; exit 1 if any role exceeds this


@dataclass
class RoleSpend:
    """Aggregated real token spend for one pipeline role."""

    role: str
    input_tokens: int = 0
    output_tokens: int = 0
    # Most recently seen model id for this role; used to look up prices.
    model: str = ""

    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


# ---------------------------------------------------------------------------
# JSONL parsing
# ---------------------------------------------------------------------------


def _infer_role_from_path(path: Path) -> str | None:
    """Heuristically infer role from directory name when 'role' key is absent.

    The workspace layout is::

        transcript/
          planning/          → role "planning"
          lesson-001/
            orchestrator-*.jsonl  → role "orchestrator"
            researcher-*.jsonl    → role "researcher"
            writer-*.jsonl        → role "writer"
            reviewer-*.jsonl      → role "reviewer"

    Falls back to ``None`` when the name does not match any known role.
    """
    # Parent dir name: "planning" → planning
    parent = path.parent.name
    if parent == "planning":
        return "planning"
    # File stem prefix: "researcher-1.jsonl" → researcher
    stem = path.stem.lower()
    for role in _KNOWN_ROLES:
        if stem.startswith(role):
            return role
    # Parent dir may be a lesson id (e.g. "lesson-001"); check grandparent
    grandparent = path.parent.parent.name
    if grandparent == "transcript":
        # lesson-level without explicit role prefix → orchestrator by default
        return "orchestrator"
    return None


def parse_run_dir(run_dir: Path) -> dict[str, RoleSpend]:
    """Parse all transcript JSONL files under *run_dir* and aggregate by role.

    Walks ``run_dir/transcript/**/*.jsonl``, parses each JSON line, and sums
    ``usage.input_tokens`` + ``usage.output_tokens`` per role.

    Args:
        run_dir: Path to a single WiedunFlow run directory (contains
            ``manifest.json`` and ``transcript/``).

    Returns:
        Mapping of role name → :class:`RoleSpend`.  Roles with no data are
        absent from the dict (not zero-padded).
    """
    transcript_root = run_dir / "transcript"
    spend: dict[str, RoleSpend] = {}

    if not transcript_root.exists():
        return spend

    for jsonl_file in sorted(transcript_root.rglob("*.jsonl")):
        try:
            lines = jsonl_file.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue

        for raw_line in lines:
            stripped = raw_line.strip()
            if not stripped:
                continue
            try:
                record: dict = json.loads(stripped)
            except json.JSONDecodeError:
                continue

            # Determine role: explicit field first, then path heuristic.
            role: str | None = record.get("role")
            if role not in _KNOWN_ROLES:
                role = _infer_role_from_path(jsonl_file)
            if role is None:
                continue

            usage = record.get("usage", {})
            in_tok = int(usage.get("input_tokens", 0))
            out_tok = int(usage.get("output_tokens", 0))
            model: str = record.get("model", "")

            if role not in spend:
                spend[role] = RoleSpend(role=role)
            spend[role].input_tokens += in_tok
            spend[role].output_tokens += out_tok
            if model:
                spend[role].model = model  # last-seen model for this role

    return spend


# ---------------------------------------------------------------------------
# Plan manifest parsing
# ---------------------------------------------------------------------------


def _load_manifest(run_dir: Path) -> dict:
    """Return the manifest dict (or empty dict on any error)."""
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        return {}
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _manifest_counts(manifest: dict) -> tuple[int, int, int]:
    """Extract ``(symbols, lessons, clusters)`` from a manifest dict.

    Falls back to 0 for any missing field — the estimator uses safe over-
    estimates when counts are uncertain, so a 0 just yields a pessimistic
    preflight number.
    """
    lessons_list = manifest.get("lessons", [])
    lessons = len(lessons_list) if isinstance(lessons_list, list) else 0
    symbols = manifest.get("symbols", 0)
    clusters_list = manifest.get("clusters", [])
    clusters = len(clusters_list) if isinstance(clusters_list, list) else 0
    return int(symbols), lessons, clusters


# ---------------------------------------------------------------------------
# Cost helpers
# ---------------------------------------------------------------------------


def _usd_from_spend(spend: RoleSpend, model_id: str) -> float:
    """Return estimated USD cost for *spend* using live MODEL_PRICES lookup."""
    prices = MODEL_PRICES.get(model_id)
    if prices is None:
        in_price = out_price = _FALLBACK_INPUT_USD_PER_MTOK
    else:
        in_price, out_price = prices
    return (spend.input_tokens / 1_000_000.0) * in_price + (
        spend.output_tokens / 1_000_000.0
    ) * out_price


# ---------------------------------------------------------------------------
# Comparison table
# ---------------------------------------------------------------------------


def _delta_pct(est: float, real: float) -> float:
    """Return signed delta percent: (est - real) / max(real, 1) * 100."""
    if real == 0 and est == 0:
        return 0.0
    denom = real if real != 0 else est
    return (est - real) / abs(denom) * 100.0


def _run_comparison(run_dir: Path) -> bool:
    """Parse *run_dir*, compare to estimator, print table.

    Returns:
        True if all roles are within ±50%, False otherwise.
    """
    console = Console()

    real_spend = parse_run_dir(run_dir)
    if not real_spend:
        console.print(
            f"[yellow]No transcript JSONL data found under {run_dir / 'transcript'}.[/yellow]"
        )
        console.print(
            "[dim]JSONL files are written during a real pipeline run. "
            "Run WiedunFlow on a repository first, then re-run this validator.[/dim]"
        )
        return True  # not a validation failure, just no data

    manifest = _load_manifest(run_dir)
    symbols, lessons, clusters = _manifest_counts(manifest)

    # Resolve per-role model ids from real spend (fall back to defaults).
    def _model(role: str, default: str) -> str:
        return real_spend[role].model if role in real_spend and real_spend[role].model else default

    est = estimate(
        symbols=symbols or 50,  # avoid degenerate 0
        lessons=lessons or 5,
        clusters=clusters or 3,
        plan_model=_model("planning", _DEFAULT_PLAN_MODEL),
        orchestrator_model=_model("orchestrator", _DEFAULT_ORCHESTRATOR_MODEL),
        researcher_model=_model("researcher", _DEFAULT_RESEARCHER_MODEL),
        writer_model=_model("writer", _DEFAULT_WRITER_MODEL),
        reviewer_model=_model("reviewer", _DEFAULT_REVIEWER_MODEL),
    )

    # Build comparison pairs: (role, estimated_tokens, real_tokens, est_usd, real_usd)
    role_est_map = {
        "planning": est.planning,
        "orchestrator": est.orchestrator,
        "researcher": est.researcher,
        "writer": est.writer,
        "reviewer": est.reviewer,
    }

    table = Table(
        title=f"Cost Estimator Validation — run {run_dir.name}",
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("ROLE", style="bold")
    table.add_column("EST_TOK", justify="right")
    table.add_column("REAL_TOK", justify="right")
    table.add_column("EST_USD", justify="right")
    table.add_column("REAL_USD", justify="right")
    table.add_column("DELTA%", justify="right")

    all_ok = True
    for role in _KNOWN_ROLES:
        real = real_spend.get(role)
        est_role = role_est_map.get(role)
        if real is None and est_role is None:
            continue

        real_tok = real.total_tokens() if real else 0
        est_tok = (est_role.input_tokens + est_role.output_tokens) if est_role else 0
        est_usd = est_role.cost_usd if est_role else 0.0
        real_usd = _usd_from_spend(real, real.model) if real else 0.0

        delta = _delta_pct(est_tok, real_tok)
        if abs(delta) >= _DELTA_WARN_THRESHOLD:
            all_ok = False
            delta_str = f"[red]{delta:+.1f}%[/red]"
        else:
            delta_str = f"[green]{delta:+.1f}%[/green]"

        table.add_row(
            role,
            f"{est_tok:,}",
            f"{real_tok:,}",
            f"${est_usd:.4f}",
            f"${real_usd:.4f}",
            delta_str,
        )

    console.print(table)

    if not all_ok:
        console.print(
            "[red]WARN: at least one role exceeds ±50% delta — estimator may need recalibration.[/red]"
        )
    else:
        console.print("[green]OK: all roles within ±50% delta.[/green]")

    return all_ok


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _find_latest_run(runs_dir: Path) -> Path | None:
    """Return the most recently modified run directory under *runs_dir*."""
    if not runs_dir.exists():
        return None
    dirs = [d for d in runs_dir.iterdir() if d.is_dir()]
    if not dirs:
        return None
    return max(dirs, key=lambda d: d.stat().st_mtime)


def main(argv: list[str] | None = None) -> int:
    """Entry point for the validation script."""
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--run-id",
        metavar="ID",
        help="Specific run ID to validate (directory name under --runs-dir).",
    )
    group.add_argument(
        "--latest",
        action="store_true",
        default=True,
        help="Validate the most recently modified run (default).",
    )
    parser.add_argument(
        "--runs-dir",
        metavar="DIR",
        default=str(Path.home() / ".wiedunflow" / "runs"),
        help="Base directory for WiedunFlow runs. Default: ~/.wiedunflow/runs/",
    )
    args = parser.parse_args(argv)

    runs_dir = Path(args.runs_dir)

    if args.run_id:
        run_dir = runs_dir / args.run_id
        if not run_dir.exists():
            print(f"ERROR: run directory not found: {run_dir}", file=sys.stderr)
            return 1
    else:
        run_dir = _find_latest_run(runs_dir)
        if run_dir is None:
            print(
                f"ERROR: no run directories found under {runs_dir}",
                file=sys.stderr,
            )
            return 1

    ok = _run_comparison(run_dir)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
