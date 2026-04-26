# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Unit tests for Bm25Store and the _tokenize helper."""

from __future__ import annotations

import pytest

from wiedunflow.adapters.bm25_store import Bm25Store, _tokenize

# ---------------------------------------------------------------------------
# Tokeniser tests
# ---------------------------------------------------------------------------


def test_tokenize_snake_case() -> None:
    """Snake-case identifiers are split on underscore boundaries."""
    result = _tokenize("snake_case_name")
    assert result == ["snake", "case", "name"]


def test_tokenize_camel_case() -> None:
    """camelCase identifiers are split at case-boundary transitions."""
    result = _tokenize("camelCaseName")
    assert result == ["camel", "case", "name"]


def test_tokenize_stopwords_only() -> None:
    """Strings consisting entirely of stopwords produce an empty token list."""
    result = _tokenize("The return import self")
    assert result == []


def test_tokenize_mixed_real_content() -> None:
    """Realistic identifier with mixed casing, underscores, and stopwords."""
    result = _tokenize("build_DocumentCorpus_from_files")
    # "from" and "files" are not stopwords; "build", "document", "corpus" stay
    assert "build" in result
    assert "document" in result
    assert "corpus" in result
    # "from" is a stopword
    assert "from" not in result


# ---------------------------------------------------------------------------
# Bm25Store behaviour
# ---------------------------------------------------------------------------


def test_empty_store_search_returns_empty_list() -> None:
    """Searching an un-indexed store yields an empty list (not an error)."""
    store = Bm25Store()
    assert store.search("anything", k=5) == []


def test_index_and_search_returns_top_k_sorted_desc() -> None:
    """After indexing, search returns up to k results sorted by score descending."""
    store = Bm25Store()
    store.index(
        [
            ("doc_a", "python parser ast tree sitter"),
            ("doc_b", "bm25 retrieval search index ranking"),
            ("doc_c", "bm25 search relevance scoring retrieval index"),
        ]
    )
    results = store.search("bm25 search", k=2)
    assert len(results) == 2
    # Both top results should be from the BM25-related documents
    ids = [r[0] for r in results]
    assert "doc_c" in ids or "doc_b" in ids
    # Scores must be sorted descending
    assert results[0][1] >= results[1][1]


def test_index_empty_documents_clears_store() -> None:
    """Re-indexing with an empty list clears the store; subsequent search is empty."""
    store = Bm25Store()
    store.index([("doc_a", "hello world")])
    store.index([])  # clear
    assert store.search("hello", k=5) == []


def test_bm25_parameters_k1_b() -> None:
    """BM25Okapi is constructed with k1=1.5, b=0.75 as required by ADR-0002."""
    store = Bm25Store()
    store.index([("doc_a", "sample document content")])
    assert store._bm25 is not None
    assert store._bm25.k1 == pytest.approx(1.5)
    assert store._bm25.b == pytest.approx(0.75)


def test_search_k_limits_results() -> None:
    """search respects the k parameter and never returns more than k results."""
    store = Bm25Store()
    store.index(
        [
            ("a", "retrieval search index"),
            ("b", "retrieval index bm25"),
            ("c", "search engine index"),
            ("d", "document retrieval pipeline"),
        ]
    )
    results = store.search("retrieval index", k=2)
    assert len(results) <= 2
