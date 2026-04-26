# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Sprint 2 robustness eval — analysis-only pipeline on 5 pinned OSS repos.

Opt-in only (marker ``eval_robustness``) — excluded from default CI.  Does NOT
require an API key; uses FakeLLMProvider-level adapters only (parser, resolver,
ranker).  Reports JSON to ``tests/eval/results/s2-robustness-<date>.json``.

Repositories listed in ``tests/eval/corpus/repos.yaml``.  If a repo is not
checked out at ``tests/eval/corpus/repos/<name>/``, the corresponding test is
SKIPPED rather than failing — this keeps the suite green locally while still
gating releases when repos are cloned.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml

from wiedunflow.adapters.jedi_resolver import JediResolver
from wiedunflow.adapters.networkx_ranker import NetworkxRanker
from wiedunflow.adapters.tree_sitter_parser import TreeSitterParser
from wiedunflow.use_cases.ingestion import ingest

pytestmark = pytest.mark.eval_robustness

_CORPUS_YAML = Path(__file__).parent / "corpus" / "repos.yaml"
_CORPUS_ROOT = Path(__file__).parent / "corpus" / "repos"
_RESULTS_DIR = Path(__file__).parent / "results"


def _load_corpus() -> list[dict[str, Any]]:
    with _CORPUS_YAML.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    return list(raw.get("repos", []))


def _repo_ids() -> list[str]:
    return [entry["name"] for entry in _load_corpus()]


@pytest.mark.parametrize("repo_name", _repo_ids())
def test_oss_repo_analysis_no_crash(repo_name: str) -> None:
    """Run Stage 0-2 analysis on each OSS repo; assert no crash, log coverage."""
    repo_path = _CORPUS_ROOT / repo_name
    if not repo_path.exists():
        pytest.skip(f"corpus repo not checked out at {repo_path} — clone to enable")

    result_record: dict[str, Any] = {
        "repo": repo_name,
        "timestamp": datetime.now(UTC).isoformat(),
        "status": "unknown",
    }
    try:
        ingestion = ingest(repo_path)
        parser = TreeSitterParser()
        symbols, raw_graph = parser.parse(list(ingestion.files), ingestion.repo_root)
        resolver = JediResolver()
        resolved = resolver.resolve(symbols, raw_graph, ingestion.repo_root)
        ranker = NetworkxRanker()
        ranked = ranker.rank(resolved)

        result_record.update(
            {
                "status": "ok",
                "files_count": len(ingestion.files),
                "symbols_count": len(symbols),
                "raw_edges_count": len(raw_graph.edges),
                "resolved_edges_count": len(resolved.edges),
                "resolved_pct": (
                    resolved.resolution_stats.resolved_pct if resolved.resolution_stats else None
                ),
                "uncertain_count": (
                    resolved.resolution_stats.uncertain_count if resolved.resolution_stats else None
                ),
                "unresolved_count": (
                    resolved.resolution_stats.unresolved_count
                    if resolved.resolution_stats
                    else None
                ),
                "has_cycles": ranked.has_cycles,
                "cycle_groups_count": len(ranked.cycle_groups),
                "communities_count": len(ranked.communities),
            }
        )
    except Exception as exc:
        result_record.update({"status": "crash", "error": f"{type(exc).__name__}: {exc}"})
        _append_result(result_record)
        raise
    _append_result(result_record)


def _append_result(record: dict[str, Any]) -> None:
    _RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    fname = f"s2-robustness-{datetime.now(UTC).strftime('%Y-%m-%d')}.json"
    fpath = _RESULTS_DIR / fname
    existing: list[dict[str, Any]] = []
    if fpath.exists():
        try:
            existing = json.loads(fpath.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = []
    existing.append(record)
    fpath.write_text(json.dumps(existing, indent=2), encoding="utf-8")
