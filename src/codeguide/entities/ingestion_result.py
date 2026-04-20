# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator


class IngestionResult(BaseModel):
    """Output of Stage 0 (ingestion): enumerated Python source files plus git context.

    Consumed by Stage 1 (parser) and Stage 6 (build — footer metadata).
    """

    model_config = ConfigDict(frozen=True)

    files: tuple[Path, ...]
    repo_root: Path
    commit_hash: str
    branch: str
    detected_subtree: Path | None = None  # monorepo subtree; None when repo_root is the tree
    excluded_count: int = 0

    @model_validator(mode="after")
    def validate_commit_hash_non_empty(self) -> Self:
        if not self.commit_hash.strip():
            raise ValueError("commit_hash must be non-empty (use 'unknown' for non-git dirs)")
        return self

    @model_validator(mode="after")
    def validate_branch_non_empty(self) -> Self:
        if not self.branch.strip():
            raise ValueError("branch must be non-empty (use 'unknown' for non-git dirs)")
        return self

    @model_validator(mode="after")
    def validate_subtree_under_root(self) -> Self:
        if self.detected_subtree is None:
            return self
        try:
            self.detected_subtree.resolve().relative_to(self.repo_root.resolve())
        except ValueError as exc:
            raise ValueError(
                f"detected_subtree ({self.detected_subtree}) must be under repo_root "
                f"({self.repo_root})"
            ) from exc
        return self

    @model_validator(mode="after")
    def validate_excluded_count_non_negative(self) -> Self:
        if self.excluded_count < 0:
            raise ValueError("excluded_count must be >= 0")
        return self
