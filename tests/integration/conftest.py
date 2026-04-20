# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

from pathlib import Path

import pytest

from codeguide.adapters import (
    FakeClock,
    FakeLLMProvider,
    InMemoryCache,
    StubBm25Store,
    StubTreeSitterParser,
)
from codeguide.use_cases.generate_tutorial import Providers, generate_tutorial

TINY_REPO = Path(__file__).parent.parent / "fixtures" / "tiny_repo"


@pytest.fixture(scope="session")
def tiny_repo_path() -> Path:
    assert TINY_REPO.exists(), f"tiny_repo fixture not found at {TINY_REPO}"
    return TINY_REPO


@pytest.fixture(scope="session")
def providers() -> Providers:
    return Providers(
        llm=FakeLLMProvider(),
        parser=StubTreeSitterParser(),
        vector_store=StubBm25Store(),
        cache=InMemoryCache(),
        clock=FakeClock(),
    )


@pytest.fixture(scope="session")
def tutorial_html(
    tiny_repo_path: Path,
    providers: Providers,
    tmp_path_factory: pytest.TempPathFactory,
) -> Path:
    """Run the full pipeline once per test session; return path to tutorial.html."""
    out_dir = tmp_path_factory.mktemp("tutorial")
    output = out_dir / "tutorial.html"
    generate_tutorial(tiny_repo_path, providers, output_path=output)
    assert output.exists()
    return output
