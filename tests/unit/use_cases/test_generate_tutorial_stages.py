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

_TINY_REPO = Path(__file__).parent.parent.parent / "fixtures" / "tiny_repo"


@pytest.fixture
def all_providers() -> Providers:
    return Providers(
        llm=FakeLLMProvider(),
        parser=StubTreeSitterParser(),
        vector_store=StubBm25Store(),
        cache=InMemoryCache(),
        clock=FakeClock(),
    )


def test_generate_tutorial_returns_html_path(all_providers: Providers, tmp_path: Path) -> None:
    output = tmp_path / "test_tutorial.html"
    result = generate_tutorial(_TINY_REPO, all_providers, output_path=output)
    assert result == output
    assert output.exists()


def test_generate_tutorial_html_valid_utf8(all_providers: Providers, tmp_path: Path) -> None:
    output = tmp_path / "test_tutorial.html"
    generate_tutorial(_TINY_REPO, all_providers, output_path=output)
    content = output.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in content
    assert "tutorial-data" in content


def test_generate_tutorial_produces_three_lessons(all_providers: Providers, tmp_path: Path) -> None:
    output = tmp_path / "test_tutorial.html"
    generate_tutorial(_TINY_REPO, all_providers, output_path=output)
    html = output.read_text(encoding="utf-8")
    assert html.count("lesson-001") >= 1
    assert html.count("lesson-002") >= 1
    assert html.count("lesson-003") >= 1
