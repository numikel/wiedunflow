# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Unit tests for the RAG corpus builder."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from codeguide.entities.code_symbol import CodeSymbol
from codeguide.entities.ingestion_result import IngestionResult
from codeguide.use_cases.rag_corpus import build_and_index, build_corpus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ingestion(
    tmp_path: Path,
    *,
    has_readme: bool = True,
) -> IngestionResult:
    return IngestionResult(
        files=(),
        repo_root=tmp_path,
        commit_hash="abc1234def5678",
        branch="main",
        has_readme=has_readme,
    )


def _make_symbol(name: str, docstring: str | None = None) -> CodeSymbol:
    return CodeSymbol(
        name=name,
        kind="function",
        file_path=Path("src/module.py"),
        lineno=1,
        docstring=docstring,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_build_corpus_symbols_and_readme(tmp_path: Path) -> None:
    """Corpus contains symbol doc entries plus a README entry."""
    readme = tmp_path / "README.md"
    readme.write_text("# My Project\nThis is a test.", encoding="utf-8")

    symbols = [
        _make_symbol("mod.func_a", "Adds two numbers."),
        _make_symbol("mod.func_b", "Multiplies two numbers."),
    ]
    ingestion = _make_ingestion(tmp_path, has_readme=True)
    corpus = build_corpus(tmp_path, ingestion, symbols)

    doc_ids = {d.doc_id for d in corpus.documents}
    assert "symbol:mod.func_a" in doc_ids
    assert "symbol:mod.func_b" in doc_ids
    assert "readme" in doc_ids
    assert len(corpus.documents) >= 3


def test_build_corpus_no_readme_omits_readme_doc(tmp_path: Path) -> None:
    """When has_readme=False, the README document is NOT in the corpus."""
    # Even if the file exists, has_readme=False should prevent inclusion
    symbols = [_make_symbol("mod.func", "Does something.")]
    ingestion = _make_ingestion(tmp_path, has_readme=False)
    corpus = build_corpus(tmp_path, ingestion, symbols)

    doc_ids = {d.doc_id for d in corpus.documents}
    assert "readme" not in doc_ids


def test_build_corpus_symbols_without_docstring_omitted(tmp_path: Path) -> None:
    """Symbols that have no docstring (None or blank) are not indexed."""
    symbols = [
        _make_symbol("mod.documented", "Has a docstring."),
        _make_symbol("mod.undocumented", None),
        _make_symbol("mod.blank", "   "),
    ]
    ingestion = _make_ingestion(tmp_path, has_readme=False)
    corpus = build_corpus(tmp_path, ingestion, symbols)

    doc_ids = {d.doc_id for d in corpus.documents}
    assert "symbol:mod.documented" in doc_ids
    assert "symbol:mod.undocumented" not in doc_ids
    assert "symbol:mod.blank" not in doc_ids


def test_build_and_index_calls_vector_store(tmp_path: Path) -> None:
    """build_and_index passes (doc_id, content) pairs to vector_store.index."""
    readme = tmp_path / "README.md"
    readme.write_text("Readme content.", encoding="utf-8")

    symbols = [_make_symbol("pkg.helper", "Helper function.")]
    ingestion = _make_ingestion(tmp_path, has_readme=True)

    mock_store = MagicMock()
    corpus = build_and_index(tmp_path, ingestion, symbols, mock_store)

    mock_store.index.assert_called_once()
    call_args = mock_store.index.call_args[0][0]  # first positional arg
    # Should be a list of (str, str) tuples
    assert isinstance(call_args, list)
    assert all(isinstance(pair, tuple) and len(pair) == 2 for pair in call_args)
    # The corpus returned must match what was indexed
    indexed_ids = {pair[0] for pair in call_args}
    corpus_ids = {d.doc_id for d in corpus.documents}
    assert indexed_ids == corpus_ids


def test_build_corpus_non_git_dir_no_crash(tmp_path: Path) -> None:
    """Directories without a .git folder don't crash — git log source is skipped."""
    # tmp_path has no .git directory
    symbols = [_make_symbol("mod.func", "A function.")]
    ingestion = _make_ingestion(tmp_path, has_readme=False)
    # Should not raise
    corpus = build_corpus(tmp_path, ingestion, symbols)
    doc_ids = {d.doc_id for d in corpus.documents}
    # No commit: entries
    assert not any(did.startswith("commit:") for did in doc_ids)
    # Symbol doc still present
    assert "symbol:mod.func" in doc_ids
