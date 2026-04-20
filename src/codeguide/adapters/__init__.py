# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

from codeguide.adapters.bm25_store import Bm25Store
from codeguide.adapters.cycle_detector import detect_cycles
from codeguide.adapters.dynamic_import_detector import detect_dynamic_imports
from codeguide.adapters.fake_clock import FakeClock
from codeguide.adapters.fake_llm_provider import FakeLLMProvider
from codeguide.adapters.git_context import get_git_context
from codeguide.adapters.in_memory_cache import InMemoryCache
from codeguide.adapters.jedi_resolver import JediResolver
from codeguide.adapters.networkx_ranker import NetworkxRanker
from codeguide.adapters.stub_jedi_resolver import StubJediResolver
from codeguide.adapters.stub_ranker import StubRanker
from codeguide.adapters.stub_tree_sitter import StubTreeSitterParser
from codeguide.adapters.tree_sitter_parser import TreeSitterParser

# Backward-compat alias — Sprint 1 stubs; callers should migrate to Bm25Store.
StubBm25Store = Bm25Store

__all__ = [
    "Bm25Store",
    "FakeClock",
    "FakeLLMProvider",
    "InMemoryCache",
    "JediResolver",
    "NetworkxRanker",
    "StubBm25Store",
    "StubJediResolver",
    "StubRanker",
    "StubTreeSitterParser",
    "TreeSitterParser",
    "detect_cycles",
    "detect_dynamic_imports",
    "get_git_context",
]
