# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

from pathlib import Path

import pytest

from wiedunflow import __version__
from wiedunflow.adapters import (
    FakeClock,
    FakeLLMProvider,
    InMemoryCache,
    StubBm25Store,
    StubJediResolver,
    StubRanker,
    StubTreeSitterParser,
)
from wiedunflow.use_cases.generate_tutorial import Providers, generate_tutorial

pytestmark = pytest.mark.integration

_TINY_REPO = Path(__file__).parent.parent / "fixtures" / "tiny_repo"


@pytest.fixture(scope="module")
def planning_providers() -> Providers:
    """Fresh provider set for planning integration tests (module-scoped)."""
    return Providers(
        llm=FakeLLMProvider(),
        parser=StubTreeSitterParser(),
        resolver=StubJediResolver(),
        ranker=StubRanker(),
        vector_store=StubBm25Store(),
        cache=InMemoryCache(),
        clock=FakeClock(),
    )


@pytest.fixture(scope="module")
def planning_tutorial_html(
    planning_providers: Providers,
    tmp_path_factory: pytest.TempPathFactory,
) -> Path:
    """Run the full pipeline once for this module's tests."""
    if not _TINY_REPO.exists():
        pytest.skip(f"tiny_repo fixture not found at {_TINY_REPO}")
    out_dir = tmp_path_factory.mktemp("planning_integration")
    output = out_dir / "tutorial.html"
    generate_tutorial(_TINY_REPO, planning_providers, output_path=output)
    return output


def test_planning_integration_output_exists(planning_tutorial_html: Path) -> None:
    assert planning_tutorial_html.exists(), "tutorial.html was not created"


def test_planning_integration_html_has_three_lessons(planning_tutorial_html: Path) -> None:
    html = planning_tutorial_html.read_text(encoding="utf-8")
    assert html.count("lesson-001") >= 1, "lesson-001 not found in output"
    assert html.count("lesson-002") >= 1, "lesson-002 not found in output"
    assert html.count("lesson-003") >= 1, "lesson-003 not found in output"


def test_planning_integration_schema_version_in_output(planning_tutorial_html: Path) -> None:
    """The output HTML must embed the manifest schema_version (US-048)."""
    html = planning_tutorial_html.read_text(encoding="utf-8")
    # schema_version is serialised into the tutorial-data JSON block.
    assert "1.0.0" in html, "schema_version 1.0.0 not found in tutorial HTML"


def test_planning_integration_wiedunflow_version_in_output(planning_tutorial_html: Path) -> None:
    """The footer must carry the current wiedunflow_version."""
    html = planning_tutorial_html.read_text(encoding="utf-8")
    assert __version__ in html, f"wiedunflow_version {__version__} not found in tutorial HTML"
