# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""T-005.EVAL — Sprint 5 smoke on 3 of 5 pinned corpus repos.

Asserts per-US-050/US-048/US-056:
- HTML output < 8 MB for a medium-sized real repository.
- Output embeds ADR-0009 schema_version "1.0.0".
- ``.wiedunflow/run-report.json`` is valid after the run.

**Run policy**: opt-in via ``pytest -m eval``. Requires ``ANTHROPIC_API_KEY``
and the pinned corpus submodules under ``tests/eval/corpus/repos/``. Skips
gracefully (never errors) when either is absent so the default CI matrix
stays green.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = [pytest.mark.eval]

_CORPUS_DIR = Path(__file__).parent / "corpus" / "repos"
_TARGET_REPOS = ("click", "requests", "starlette")
_SIZE_BUDGET_BYTES = 8 * 1024 * 1024


def _api_key_present() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _corpus_exists(name: str) -> bool:
    return (_CORPUS_DIR / name).is_dir() and (_CORPUS_DIR / name / ".git").exists()


@pytest.mark.skipif(
    not _api_key_present(),
    reason="ANTHROPIC_API_KEY required for Sprint 5 mini-eval",
)
@pytest.mark.parametrize("repo_name", _TARGET_REPOS)
def test_s5_size_budget_and_schema(tmp_path: Path, repo_name: str) -> None:
    """End-to-end smoke: repo → tutorial.html → size + schema + run-report."""
    corpus_path = _CORPUS_DIR / repo_name
    if not _corpus_exists(repo_name):
        pytest.skip(f"corpus submodule missing: {corpus_path}")

    # Copy corpus into tmp to keep the submodule clean.
    working_repo = tmp_path / repo_name
    shutil.copytree(corpus_path, working_repo)

    # Run the CLI via subprocess so the smoke mirrors user experience.
    result = subprocess.run(
        [
            "uv",
            "run",
            "wiedunflow",
            str(working_repo),
            "--yes",
            "--no-consent-prompt",
            "--cache-path",
            str(tmp_path / "wiedunflow-cache.sqlite"),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60 * 30,  # 30 min cap for real LLM call
        check=False,
    )
    assert result.returncode in (0, 2), (
        f"wiedunflow exited with {result.returncode} on {repo_name}:\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )

    produced_html = tmp_path / "tutorial.html"
    assert produced_html.exists(), f"tutorial.html missing for {repo_name}"

    size = produced_html.stat().st_size
    assert size < _SIZE_BUDGET_BYTES, (
        f"{repo_name}: tutorial.html size {size / (1024 * 1024):.2f} MB "
        f"exceeds 8 MB budget (US-050)"
    )

    html = produced_html.read_text(encoding="utf-8")
    assert '"schema_version": "1.0.0"' in html or '"schema_version":"1.0.0"' in html, (
        f"{repo_name}: missing schema_version in rendered HTML (US-048/ADR-0009)"
    )

    run_report = working_repo / ".wiedunflow" / "run-report.json"
    assert run_report.exists(), f"{repo_name}: run-report.json missing"
    data = json.loads(run_report.read_text(encoding="utf-8"))
    assert data.get("status") in ("ok", "degraded"), (
        f"{repo_name}: unexpected run-report status: {data.get('status')}"
    )
