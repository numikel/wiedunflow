# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class Document(BaseModel):
    """A single document unit in the RAG corpus.

    Attributes:
        doc_id: Stable identifier, e.g. ``"symbol:calculator.add"``,
            ``"readme"``, ``"commit:abc1234"``.
        content: Raw text content used for BM25 indexing.
        weight: ADR-0002 source-tier weight (metadata-only in S3;
            weight-based duplication deferred to S4).
    """

    model_config = ConfigDict(frozen=True)

    doc_id: str
    content: str
    weight: float = 1.0  # TODO: use for corpus duplication strategy (ADR-0002)


class DocumentCorpus(BaseModel):
    """Immutable collection of documents produced by the RAG corpus builder.

    Attributes:
        documents: All documents gathered from symbol docstrings, README,
            ``docs/`` markdown, CONTRIBUTING, and git commit messages.
    """

    model_config = ConfigDict(frozen=True)

    documents: tuple[Document, ...]
