# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Fixtures for visual regression tests.

These are separated from ``tests/integration/conftest.py`` so the main
integration suite doesn't pay the cost of booting the full renderer on every
run. The ``tutorial_html`` fixture here is session-scoped and produces the
same output as the integration one so assertions stay consistent.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.fakes.clock import FakeClock
from wiedunflow.adapters import (
    FakeLLMProvider,
    InMemoryCache,
    StubBm25Store,
    StubJediResolver,
    StubRanker,
    StubTreeSitterParser,
)
from wiedunflow.use_cases.generate_tutorial import Providers, generate_tutorial

_TINY_REPO = Path(__file__).parent.parent / "fixtures" / "tiny_repo"


@pytest.fixture(scope="session")
def visual_tutorial_html(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Generate a fresh tutorial.html for visual regression tests."""
    providers = Providers(
        llm=FakeLLMProvider(),
        parser=StubTreeSitterParser(),
        resolver=StubJediResolver(),
        ranker=StubRanker(),
        vector_store=StubBm25Store(),
        cache=InMemoryCache(),
        clock=FakeClock(),
    )
    out_dir = tmp_path_factory.mktemp("visual")
    output = out_dir / "tutorial.html"
    generate_tutorial(_TINY_REPO, providers, output_path=output)
    assert output.exists()
    return output
