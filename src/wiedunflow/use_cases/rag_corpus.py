# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""RAG corpus builder — Stage 3 of the CodeGuide pipeline.

Gathers documents from multiple sources (symbol docstrings, README, docs/**,
CONTRIBUTING, git commit messages) and optionally indexes them into a
VectorStore for BM25 retrieval.

Weight strategy note (ADR-0002): weights are stored as ``Document.weight``
metadata for future optimisation (e.g. corpus duplication / re-weighting).
In S3 the BM25Okapi index treats all documents equally — weight is metadata-only.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import structlog

from codeguide.entities.code_symbol import CodeSymbol
from codeguide.entities.corpus import Document, DocumentCorpus
from codeguide.entities.ingestion_result import IngestionResult
from codeguide.interfaces.ports import VectorStore

logger = structlog.get_logger(__name__)


def build_corpus(
    repo_root: Path,
    ingestion: IngestionResult,
    symbols: list[CodeSymbol],
) -> DocumentCorpus:
    """Collect all text sources and return an immutable :class:`DocumentCorpus`.

    Sources and weights (ADR-0002):
    - Symbol docstrings: weight=1.0, doc_id ``"symbol:<name>"``.
    - README.md (when ``ingestion.has_readme``): weight=1.0, doc_id ``"readme"``.
    - ``docs/**/*.md``: weight=1.0, doc_id ``"doc:<relpath>"``.
    - ``CONTRIBUTING.md``: weight=1.0, doc_id ``"contributing"``.
    - Git log (last 50 commits, ``%H %s``): weight=0.8, doc_id ``"commit:<sha8>"``.
      Missing git or non-repo silently skipped (no exception raised).

    Inline comments from tree-sitter are deferred to Sprint 4 (entity has no
    ``inline_comments`` field yet).

    Args:
        repo_root: Absolute path to the repository root.
        ingestion: Populated ingestion result (carries ``has_readme`` flag).
        symbols: Symbols produced by the analysis stage.

    Returns:
        Immutable :class:`DocumentCorpus` containing all discovered documents.
    """
    docs: list[Document] = []

    # ------------------------------------------------------------------
    # 1. Symbol docstrings
    # ------------------------------------------------------------------
    symbols_with_docs = 0
    for sym in symbols:
        if sym.docstring and sym.docstring.strip():
            docs.append(
                Document(
                    doc_id=f"symbol:{sym.name}",
                    content=sym.docstring,
                    weight=1.0,
                )
            )
            symbols_with_docs += 1

    # ------------------------------------------------------------------
    # 2. README.md
    # ------------------------------------------------------------------
    if ingestion.has_readme:
        readme_path = _find_readme(repo_root)
        if readme_path is not None:
            docs.append(
                Document(
                    doc_id="readme",
                    content=readme_path.read_text(encoding="utf-8", errors="replace"),
                    weight=1.0,
                )
            )
    else:
        logger.info("missing_doc", kind="readme")

    # ------------------------------------------------------------------
    # 3. docs/**/*.md
    # ------------------------------------------------------------------
    docs_dir = repo_root / "docs"
    if docs_dir.is_dir():
        for md_file in sorted(docs_dir.rglob("*.md")):
            rel = md_file.relative_to(repo_root)
            docs.append(
                Document(
                    doc_id=f"doc:{rel.as_posix()}",
                    content=md_file.read_text(encoding="utf-8", errors="replace"),
                    weight=1.0,
                )
            )

    # ------------------------------------------------------------------
    # 4. CONTRIBUTING.md
    # ------------------------------------------------------------------
    contributing = repo_root / "CONTRIBUTING.md"
    if contributing.is_file():
        docs.append(
            Document(
                doc_id="contributing",
                content=contributing.read_text(encoding="utf-8", errors="replace"),
                weight=1.0,
            )
        )

    # ------------------------------------------------------------------
    # 5. Git commit messages (last 50)
    # ------------------------------------------------------------------
    _append_git_commits(repo_root, docs)

    corpus = DocumentCorpus(documents=tuple(docs))
    logger.info(
        "rag_corpus_built",
        doc_count=len(corpus.documents),
        has_readme=ingestion.has_readme,
        symbols_with_docs=symbols_with_docs,
    )
    return corpus


def build_and_index(
    repo_root: Path,
    ingestion: IngestionResult,
    symbols: list[CodeSymbol],
    vector_store: VectorStore,
) -> DocumentCorpus:
    """Build the corpus and immediately index it into *vector_store*.

    Convenience wrapper that calls :func:`build_corpus` and then
    ``vector_store.index([(doc_id, content), ...])``.

    Args:
        repo_root: Absolute path to the repository root.
        ingestion: Populated ingestion result.
        symbols: Symbols from the analysis stage.
        vector_store: VectorStore implementation to populate.

    Returns:
        The constructed :class:`DocumentCorpus` (same as ``build_corpus``).
    """
    corpus = build_corpus(repo_root, ingestion, symbols)
    index_pairs = [(d.doc_id, d.content) for d in corpus.documents]
    vector_store.index(index_pairs)
    return corpus


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _find_readme(repo_root: Path) -> Path | None:
    """Return the first README variant found at repo root, or ``None``."""
    for name in ("README.md", "README.rst", "README.txt", "README"):
        candidate = repo_root / name
        if candidate.is_file():
            return candidate
    return None


def _append_git_commits(repo_root: Path, docs: list[Document]) -> None:
    """Run ``git log`` and append commit-message documents.

    Silently skips when ``git`` is not on PATH or *repo_root* is not a git
    repository (``subprocess`` returns non-zero or raises ``FileNotFoundError``).

    Args:
        repo_root: Repository root for ``cwd`` of the subprocess.
        docs: Mutable list to which commit :class:`Document` objects are appended.
    """
    try:
        result = subprocess.run(
            ["git", "log", "-n", "50", "--pretty=%H %s"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except FileNotFoundError:
        # git not on PATH
        return

    if result.returncode != 0:
        # Not a git repo or other git error
        return

    for raw_line in result.stdout.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        parts = stripped.split(" ", 1)
        if len(parts) != 2:  # noqa: PLR2004
            continue
        sha, message = parts
        docs.append(
            Document(
                doc_id=f"commit:{sha[:8]}",
                content=message,
                weight=0.8,
            )
        )
