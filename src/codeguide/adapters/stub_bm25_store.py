# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations


class StubBm25Store:
    """No-op VectorStore stub — returns empty search results.

    Implements the VectorStore Protocol via duck typing.  The real BM25
    adapter (Sprint 3) will replace this with rank_bm25 indexing.
    """

    def index(self, documents: list[tuple[str, str]]) -> None:
        """Accept documents without storing them.

        Args:
            documents: List of (id, text) pairs to index (ignored in stub).
        """
        # Intentional no-op: walking skeleton does not need retrieval.

    def search(self, query: str, k: int = 5) -> list[tuple[str, float]]:
        """Return an empty result set for any query.

        Args:
            query: Search query string (ignored in stub).
            k: Maximum number of results to return (ignored in stub).

        Returns:
            An empty list — no retrieval in S1.
        """
        return []
