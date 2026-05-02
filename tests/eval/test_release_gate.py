# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Release-gate eval suite (US-065 / US-066).

Requires ``ANTHROPIC_API_KEY`` in the environment and all 5 git submodules checked
out under ``tests/eval/corpus/repos/<name>/``.  Excluded from the default CI
matrix -- run explicitly via ``uv run pytest -m eval``.

Test inventory:
    1. test_repo_generates_without_crash   -- full pipeline exits 0.
    2. test_repo_hallucinations            -- run-report.json shows 0 hallucinated symbols.
    3. test_repo_skipped_ratio             -- fewer than 30 % of lessons were skipped.
    4. test_mcp_concept_coverage           -- MCP SDK output covers >= 70 % of weight-1.0 concepts.
    5. test_mcp_rubric_archive_exists      -- signoff YAML present with avg_score >= 3.0.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.eval

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_EVAL_DIR = Path(__file__).parent
_CORPUS_YAML = _EVAL_DIR / "corpus" / "repos.yaml"
_CORPUS_ROOT = _EVAL_DIR / "corpus" / "repos"
_CONFIGS_DIR = _EVAL_DIR / "configs"
_MCP_CONCEPTS_YAML = _EVAL_DIR / "corpus" / "mcp_python_sdk.yaml"
_RUBRIC_SIGNOFF = (
    Path(__file__).parent.parent.parent / "docs" / "rubric" / "v0.1.0" / "signoff-mcp-sdk.yaml"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_repos() -> list[dict[str, Any]]:
    with _CORPUS_YAML.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    return list(raw.get("repos", []))


def _repo_names() -> list[str]:
    return [r["name"] for r in _load_repos()]


def _repo_by_name(name: str) -> dict[str, Any]:
    return next(r for r in _load_repos() if r["name"] == name)


def _run_report_path(repo_path: Path) -> Path:
    return repo_path / ".wiedunflow" / "run-report.json"


# ---------------------------------------------------------------------------
# Session-scoped fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def eval_api_key() -> str:
    """Skip the entire eval suite when no API key is available.

    Prefers OPENAI_API_KEY (default per ADR-0015); falls back to
    ANTHROPIC_API_KEY for Anthropic-provider eval runs.
    """
    key = os.environ.get("OPENAI_API_KEY", "") or os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        pytest.skip(
            "Neither OPENAI_API_KEY nor ANTHROPIC_API_KEY is set -- eval suite "
            "requires a real API key. Set the variable and re-run with "
            "`uv run pytest -m eval`."
        )
    return key


@pytest.fixture(scope="session")
def eval_repos() -> dict[str, dict[str, Any]]:
    """Load the repos.yaml corpus; skip when submodules are not checked out."""
    repos = _load_repos()
    result: dict[str, dict[str, Any]] = {}
    for entry in repos:
        repo_path = _CORPUS_ROOT / entry["name"]
        if not repo_path.exists() or not any(repo_path.iterdir()):
            pytest.skip(
                f"Submodule {entry['name']} not checked out at {repo_path}. "
                "Run `git submodule update --init` and retry."
            )
        result[entry["name"]] = {**entry, "path": repo_path}
    return result


# ---------------------------------------------------------------------------
# T1 -- full pipeline exits 0
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("repo_name", _repo_names())
def test_repo_generates_without_crash(
    repo_name: str,
    eval_api_key: str,
    eval_repos: dict[str, dict[str, Any]],
) -> None:
    """Run the full WiedunFlow pipeline on a pinned OSS repo; assert exit code 0.

    Uses the per-repo config override in ``tests/eval/configs/<name>.yaml`` to
    route narration to the correct model (Opus for MCP SDK, Sonnet for others).
    The ``--yes`` flag bypasses the consent prompt in non-interactive CI.
    """
    repo_info = eval_repos[repo_name]
    repo_path: Path = repo_info["path"]
    config_path = _CONFIGS_DIR / f"{repo_name}.yaml"
    max_cost = repo_info.get("max_cost_usd", 6.0)

    cmd = [
        sys.executable,
        "-m",
        "wiedunflow",
        "generate",
        str(repo_path),
        "--yes",
        "--config",
        str(config_path),
        "--max-cost",
        str(max_cost),
        "--log-format",
        "json",
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=1800,  # 30 min hard ceiling per repo
        check=False,
    )
    assert result.returncode == 0, (
        f"wiedunflow generate exited {result.returncode} for repo '{repo_name}'.\n"
        f"stderr:\n{result.stderr[-4000:]}\n"
        f"stdout:\n{result.stdout[-2000:]}"
    )


# ---------------------------------------------------------------------------
# T2 -- hallucinated symbols == 0
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("repo_name", _repo_names())
def test_repo_hallucinations(
    repo_name: str,
    eval_api_key: str,
    eval_repos: dict[str, dict[str, Any]],
) -> None:
    """Assert run-report.json records zero hallucinated symbols (US-065 hard gate).

    Depends on T1 having run first (report file must exist).  In the parametrised
    session the fixture ensures T1 runs before T2 for the same repo.
    """
    repo_path: Path = eval_repos[repo_name]["path"]
    report_file = _run_report_path(repo_path)

    if not report_file.exists():
        pytest.skip(f"run-report.json not found for '{repo_name}' -- run T1 first")

    payload = json.loads(report_file.read_text(encoding="utf-8"))
    count = payload.get("hallucinated_symbols_count", None)

    assert count is not None, (
        "run-report.json is missing 'hallucinated_symbols_count' field. "
        "Ensure src/wiedunflow/entities/run_report.py is up to date."
    )
    assert count == 0, (
        f"Repo '{repo_name}' produced {count} hallucinated symbols: "
        f"{payload.get('hallucinated_symbols', [])}"
    )


# ---------------------------------------------------------------------------
# T3 -- skipped lesson ratio < 30 %
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("repo_name", _repo_names())
def test_repo_skipped_ratio(
    repo_name: str,
    eval_api_key: str,
    eval_repos: dict[str, dict[str, Any]],
) -> None:
    """Assert that fewer than 30 % of planned lessons were skipped (US-032 health).

    A skip ratio above the threshold is a sign of systematic grounding failures
    that prevent a quality tutorial -- this blocks release even if the process
    exited 0 (DEGRADED status).
    """
    repo_path: Path = eval_repos[repo_name]["path"]
    report_file = _run_report_path(repo_path)

    if not report_file.exists():
        pytest.skip(f"run-report.json not found for '{repo_name}' -- run T1 first")

    payload = json.loads(report_file.read_text(encoding="utf-8"))
    skipped = payload.get("skipped_lessons_count", 0)
    total = payload.get("total_planned_lessons", 0)

    if total == 0:
        pytest.skip(f"No lessons planned for '{repo_name}' -- nothing to check")

    ratio = skipped / total
    assert ratio < 0.30, (
        f"Repo '{repo_name}' skipped ratio {ratio:.1%} >= 30% ({skipped}/{total} lessons skipped)."
    )


# ---------------------------------------------------------------------------
# T4 -- MCP SDK concept coverage >= 70 %
# ---------------------------------------------------------------------------


def _extract_concepts_from_output(repo_path: Path) -> set[str]:
    """Collect concept strings from lesson data JSON embedded in the generated HTML.

    Searches (in order):
    1. ``wiedunflow-<repo_name>.html`` in CWD (default output filename).
    2. ``tutorial*.html`` in *repo_path* (legacy pattern, kept for compatibility).

    Extracts text from the ``tutorial-lessons`` script tag (current format) which
    holds a JSON array of lesson objects.  For each lesson the ``title`` and the
    first 1 000 characters of ``narrative`` are added as searchable strings so
    that the YAML pattern regexes can match them.  The legacy ``teaches`` /
    ``concepts_introduced`` fields are also collected when present.
    """
    concepts: set[str] = set()

    repo_name = repo_path.name
    cwd_html = Path.cwd() / f"wiedunflow-{repo_name}.html"
    html_candidates: list[Path] = []
    if cwd_html.exists():
        html_candidates.append(cwd_html)
    html_candidates.extend(repo_path.glob("tutorial*.html"))

    for html_path in html_candidates:
        text = html_path.read_text(encoding="utf-8", errors="replace")
        # Current format: <script … id="tutorial-lessons">JSON array</script>
        match = re.search(
            r'<script[^>]+id=["\']tutorial-lessons["\'][^>]*>(.*?)</script>',
            text,
            re.DOTALL | re.IGNORECASE,
        )
        # Legacy fallback: id="lesson-data" with {lessons: [...]} wrapper
        if not match:
            match = re.search(
                r'<script[^>]+id=["\']lesson-data["\'][^>]*>(.*?)</script>',
                text,
                re.DOTALL | re.IGNORECASE,
            )
        if match:
            try:
                raw = json.loads(match.group(1))
                lessons: list[dict[str, Any]] = (
                    raw if isinstance(raw, list) else raw.get("lessons", [])
                )
                for lesson in lessons:
                    # Current format: title + narrative text
                    title = lesson.get("title", "")
                    if title:
                        concepts.add(title.lower())
                    narrative = lesson.get("narrative", "")
                    if narrative:
                        concepts.add(narrative[:1000].lower())
                    # Legacy fields (kept for compatibility)
                    teaches = lesson.get("teaches", "")
                    if teaches:
                        concepts.add(teaches.lower())
                    for c in lesson.get("concepts_introduced", []):
                        concepts.add(str(c).lower())
            except json.JSONDecodeError:
                pass

    return concepts


def test_mcp_concept_coverage(
    eval_api_key: str,
    eval_repos: dict[str, dict[str, Any]],
) -> None:
    """MCP SDK output must cover >= 70 % of weight-1.0 concepts from the checklist.

    The checklist lives in ``tests/eval/corpus/mcp_python_sdk.yaml``.  Each
    concept is matched by running its ``expected_lesson_pattern`` regex against
    the combined ``teaches`` and ``concepts_introduced`` strings from the
    generated tutorial.
    """
    mcp_path: Path = eval_repos["python-sdk-mcp"]["path"]

    if not _MCP_CONCEPTS_YAML.exists():
        pytest.skip(f"Concept checklist not found at {_MCP_CONCEPTS_YAML}")

    with _MCP_CONCEPTS_YAML.open("r", encoding="utf-8") as fh:
        spec = yaml.safe_load(fh)

    coverage_target: float = spec.get("coverage_target", 0.70)
    concepts: list[dict[str, Any]] = spec.get("expected_concepts", [])
    mandatory = [c for c in concepts if float(c.get("weight", 1.0)) >= 1.0]

    if not mandatory:
        pytest.skip("No weight-1.0 concepts defined in mcp_python_sdk.yaml")

    generated_concepts = _extract_concepts_from_output(mcp_path)

    covered: list[str] = []
    missed: list[str] = []
    for concept in mandatory:
        pattern = concept.get("expected_lesson_pattern", "")
        if pattern and any(re.search(pattern, c) for c in generated_concepts):
            covered.append(concept["id"])
        else:
            missed.append(concept["id"])

    ratio = len(covered) / len(mandatory)
    assert ratio >= coverage_target, (
        f"MCP SDK concept coverage {ratio:.1%} < {coverage_target:.0%} target. "
        f"Missed concepts: {missed}"
    )


# ---------------------------------------------------------------------------
# T5 -- rubric signoff archive exists
# ---------------------------------------------------------------------------


def test_mcp_rubric_archive_exists() -> None:
    """Rubric signoff YAML must exist and report avg_score >= 3.0 (US-066).

    When ``WIEDUNFLOW_SKIP_RUBRIC_GATE=1`` is set (pre-rubric-collection CI
    runs), the test is skipped rather than failed.  In release gating, the
    variable must be unset so the absence of the file is a hard failure.
    """
    skip_gate = os.environ.get("WIEDUNFLOW_SKIP_RUBRIC_GATE", "0") == "1"

    if not _RUBRIC_SIGNOFF.exists():
        if skip_gate:
            pytest.skip(
                f"Rubric signoff not yet collected at {_RUBRIC_SIGNOFF} "
                "(WIEDUNFLOW_SKIP_RUBRIC_GATE=1 -- skipping for pre-rubric CI run)"
            )
        pytest.fail(
            f"Rubric signoff YAML not found at {_RUBRIC_SIGNOFF}. "
            "Collect the rubric before tagging a release (unset WIEDUNFLOW_SKIP_RUBRIC_GATE)."
        )

    with _RUBRIC_SIGNOFF.open("r", encoding="utf-8") as fh:
        signoff = yaml.safe_load(fh)

    avg_score = float(signoff.get("avg_score", 0.0))
    assert avg_score >= 3.0, (
        f"Rubric avg_score {avg_score:.2f} < 3.0 minimum. "
        f"See {_RUBRIC_SIGNOFF} for per-lesson scores."
    )
