# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Real BM25 adapter implementing the VectorStore port via rank_bm25.

Replaces ``stub_bm25_store.py`` introduced in Sprint 1.  Tokeniser follows the
ADR-0002 custom pipeline: camelCase splitting → lower-case → non-alphanumeric
splitting → stopword removal → minimum length filter.

BM25Okapi parameters: ``k1=1.5, b=0.75`` (library defaults, also the values
recommended for general-purpose code-search corpora in the BM25 literature).
"""

from __future__ import annotations

import re

from rank_bm25 import BM25Okapi

# ---------------------------------------------------------------------------
# Tokeniser
# ---------------------------------------------------------------------------

_CAMEL_RE = re.compile(r"([a-z0-9])([A-Z])")
# Split on any character that is not a lowercase letter or digit.
# Underscores are treated as word separators (like snake_case boundaries);
# the subsequent strip("_") handles residual leading/trailing underscores
# on tokens that start/end with them (e.g. __init__ → "init").
_SPLIT_RE = re.compile(r"[^a-z0-9]+")

_STOPWORDS: frozenset[str] = frozenset(
    {
        "a",
        "an",
        "the",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "and",
        "or",
        "not",
        "but",
        "if",
        "then",
        "else",
        "for",
        "to",
        "of",
        "in",
        "on",
        "at",
        "by",
        "from",
        "with",
        "about",
        "as",
        "into",
        "over",
        "self",
        "cls",
        "def",
        "class",
        "import",
        "return",
        "yield",
        "pass",
        "none",
        "true",
        "false",
        "lambda",
        "raise",
        "try",
        "except",
        "todo",
        "fixme",
        "xxx",
        "note",
    }
)


def _tokenize(text: str) -> list[str]:
    """Convert text to a list of meaningful tokens suitable for BM25 indexing.

    Steps:
    1. Split camelCase boundaries with a space (``camelCase`` → ``camel Case``).
    2. Lower-case the whole string.
    3. Split on any non-alphanumeric character (including underscores, so
       ``snake_case`` → ``["snake", "case"]``).
    4. Strip residual leading/trailing underscores from each raw token.
    5. Remove single-character tokens, stopwords, and empty strings.

    Args:
        text: Raw string from a docstring, README chunk, or commit message.

    Returns:
        List of normalised, meaningful tokens.
    """
    text = _CAMEL_RE.sub(r"\1 \2", text).lower()
    raw_tokens = _SPLIT_RE.split(text)
    tokens: list[str] = []
    for raw_tok in raw_tokens:
        cleaned = raw_tok.strip("_")
        if cleaned and cleaned not in _STOPWORDS and len(cleaned) > 1:
            tokens.append(cleaned)
    return tokens


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class Bm25Store:
    """BM25-powered VectorStore adapter backed by ``rank_bm25.BM25Okapi``.

    Implements the :class:`~wiedunflow.interfaces.ports.VectorStore` protocol via
    duck typing (no explicit base class to keep the entities layer clean).

    The store is *not* thread-safe — callers must serialise ``index`` and
    ``search`` calls if used from multiple threads.

    Example::

        store = Bm25Store()
        store.index([("readme", "Install with pip install codeguide")])
        results = store.search("install codeguide", k=3)
        # [("readme", 0.832...)]
    """

    def __init__(self) -> None:
        self._doc_ids: list[str] = []
        self._bm25: BM25Okapi | None = None

    # ------------------------------------------------------------------
    # VectorStore protocol
    # ------------------------------------------------------------------

    def index(self, documents: list[tuple[str, str]]) -> None:
        """Build the BM25 index from ``(doc_id, content)`` pairs.

        Replaces any previously built index.  When *documents* is empty the
        internal index is cleared and subsequent ``search`` calls return ``[]``.

        Args:
            documents: Sequence of ``(doc_id, content)`` pairs.  ``doc_id``
                must be a non-empty string that is stable across runs (used as
                the return value in ``search`` results).
        """
        if not documents:
            self._doc_ids = []
            self._bm25 = None
            return

        self._doc_ids = [doc_id for doc_id, _ in documents]
        tokenized_corpus = [_tokenize(content) for _, content in documents]
        self._bm25 = BM25Okapi(tokenized_corpus, k1=1.5, b=0.75)

    def search(self, query: str, k: int = 5) -> list[tuple[str, float]]:
        """Return up to *k* ``(doc_id, score)`` pairs ranked by relevance.

        Returns an empty list when the store has not been indexed or the
        tokenised query is empty (all tokens are stopwords / single chars).

        Args:
            query: Free-text search string.
            k: Maximum number of results to return.

        Returns:
            List of ``(doc_id, score)`` pairs sorted by score descending.
            Scores are raw BM25 values (non-negative floats).
        """
        if self._bm25 is None or not self._doc_ids:
            return []

        tokenized_query = _tokenize(query)
        if not tokenized_query:
            return []

        scores = self._bm25.get_scores(tokenized_query)
        # Pair each doc_id with its score, sort descending, take top-k.
        ranked = sorted(
            zip(self._doc_ids, (float(s) for s in scores), strict=True),
            key=lambda pair: pair[1],
            reverse=True,
        )
        return ranked[:k]
