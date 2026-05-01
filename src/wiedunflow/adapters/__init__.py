# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

from wiedunflow.adapters.bm25_store import Bm25Store
from wiedunflow.adapters.cycle_detector import detect_cycles
from wiedunflow.adapters.dynamic_import_detector import (
    detect_dynamic_imports,
    detect_strict_uncertainty,
)
from wiedunflow.adapters.fake_clock import FakeClock
from wiedunflow.adapters.fake_llm_provider import FakeLLMProvider
from wiedunflow.adapters.git_context import get_git_context
from wiedunflow.adapters.in_memory_cache import InMemoryCache
from wiedunflow.adapters.jedi_resolver import JediResolver
from wiedunflow.adapters.networkx_ranker import NetworkxRanker
from wiedunflow.adapters.stub_jedi_resolver import StubJediResolver
from wiedunflow.adapters.stub_ranker import StubRanker
from wiedunflow.adapters.stub_tree_sitter import StubTreeSitterParser
from wiedunflow.adapters.tree_sitter_parser import TreeSitterParser
from wiedunflow.adapters.yaml_consent_store import YamlConsentStore

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
    "YamlConsentStore",
    "detect_cycles",
    "detect_dynamic_imports",
    "detect_strict_uncertainty",
    "get_git_context",
]
