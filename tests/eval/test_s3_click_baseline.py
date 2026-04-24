# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Sprint 3 canary eval — real Anthropic run on ``pallets/click``.

Run with: ``uv run pytest -m eval -k s3_click`` + ``ANTHROPIC_API_KEY`` in env.

Skipped when either the API key or the git submodule is missing, so the default
``pytest`` invocation (and the CI matrix without secrets) stays green.

Writes a JSON baseline to ``tests/eval/results/s3-click-baseline.json`` so that
future sprints can track drift in lesson count, elapsed time, and hallucinated-
symbol count.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

pytestmark = pytest.mark.eval

_CLICK_SUBMODULE = Path(__file__).parent / "corpus" / "repos" / "click"
_BASELINE_PATH = Path(__file__).parent / "results" / "s3-click-baseline.json"


def _click_commit() -> str:
    """Return the short SHA the submodule is pinned to, or ``"unpinned"``."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=_CLICK_SUBMODULE,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return "unpinned"
    if result.returncode != 0:
        return "unpinned"
    return result.stdout.strip() or "unpinned"


@pytest.fixture()
def click_repo_path() -> Path:
    """Resolve the click submodule, skipping the test if it has not been cloned."""
    if not _CLICK_SUBMODULE.is_dir() or not (_CLICK_SUBMODULE / "src").is_dir():
        pytest.skip(
            f"click submodule not found at {_CLICK_SUBMODULE}. "
            "Run: git submodule update --init tests/eval/corpus/repos/click"
        )
    return _CLICK_SUBMODULE


def test_s3_click_baseline(tmp_path: Path, click_repo_path: Path) -> None:
    """Run the full CodeGuide pipeline on click with a real Anthropic key."""
    if "ANTHROPIC_API_KEY" not in os.environ:
        pytest.skip("ANTHROPIC_API_KEY not set — eval tests require a real API key")

    output = tmp_path / "tutorial.html"
    start = time.monotonic()
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "codeguide.cli.main",
            str(click_repo_path),
            "--yes",
            "--no-consent-prompt",
            "--output",
            str(output),
        ],
        env={**os.environ},
        capture_output=True,
        text=True,
        check=False,
        timeout=1800,  # 30-minute hard ceiling (FR performance budget)
    )
    elapsed = time.monotonic() - start

    assert proc.returncode == 0, f"CLI exited {proc.returncode}; stderr:\n{proc.stderr}"
    assert output.is_file(), "tutorial.html was not written"

    html = output.read_text(encoding="utf-8")
    assert '"schema_version":"1.0.0"' in html or '"schema_version": "1.0.0"' in html

    # The hallucinated-symbol count is enforced structurally by
    # ``validate_against_graph`` during planning (ADR-0007 — any violation
    # aborts the run).  A successful run therefore implies zero hallucinations.
    baseline = {
        "sprint": "s3",
        "repo": "pallets/click",
        "commit": _click_commit(),
        "date": datetime.now(UTC).isoformat(),
        "elapsed_s": round(elapsed, 2),
        "html_size_bytes": output.stat().st_size,
        "hallucinated_symbols_count": 0,
    }
    _BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _BASELINE_PATH.write_text(json.dumps(baseline, indent=2) + "\n", encoding="utf-8")
