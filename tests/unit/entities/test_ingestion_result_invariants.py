# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from wiedunflow.entities import IngestionResult


def test_minimal_valid_instance():
    result = IngestionResult(
        files=(Path("a.py"),),
        repo_root=Path("/tmp/repo"),
        commit_hash="abc123",
        branch="main",
    )
    assert result.detected_subtree is None
    assert result.excluded_count == 0


def test_empty_files_tuple_is_valid():
    # Accept empty ingestion (repo with no python files) — Stage 0 emits it; later
    # stages decide whether to treat it as a soft failure.
    result = IngestionResult(
        files=(),
        repo_root=Path("/tmp/repo"),
        commit_hash="abc",
        branch="main",
    )
    assert result.files == ()


def test_commit_hash_must_be_non_empty():
    with pytest.raises(ValidationError, match="commit_hash must be non-empty"):
        IngestionResult(
            files=(Path("a.py"),),
            repo_root=Path("/tmp/repo"),
            commit_hash="   ",
            branch="main",
        )


def test_branch_must_be_non_empty():
    with pytest.raises(ValidationError, match="branch must be non-empty"):
        IngestionResult(
            files=(Path("a.py"),),
            repo_root=Path("/tmp/repo"),
            commit_hash="abc",
            branch="",
        )


def test_negative_excluded_count_rejected():
    with pytest.raises(ValidationError, match="excluded_count must be >= 0"):
        IngestionResult(
            files=(),
            repo_root=Path("/tmp/repo"),
            commit_hash="abc",
            branch="main",
            excluded_count=-1,
        )


def test_subtree_outside_repo_root_rejected(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    with pytest.raises(ValidationError, match="must be under repo_root"):
        IngestionResult(
            files=(),
            repo_root=repo,
            commit_hash="abc",
            branch="main",
            detected_subtree=outside,
        )


def test_subtree_under_repo_root_accepted(tmp_path: Path):
    repo = tmp_path / "repo"
    subtree = repo / "packages" / "core"
    subtree.mkdir(parents=True)
    result = IngestionResult(
        files=(),
        repo_root=repo,
        commit_hash="abc",
        branch="main",
        detected_subtree=subtree,
    )
    assert result.detected_subtree == subtree


def test_is_frozen():
    result = IngestionResult(
        files=(),
        repo_root=Path("/tmp/repo"),
        commit_hash="abc",
        branch="main",
    )
    with pytest.raises(ValidationError):
        result.commit_hash = "deadbeef"  # type: ignore[misc]
