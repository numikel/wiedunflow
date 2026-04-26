# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""US-057: ensure `.wiedunflow/` gets appended to `.gitignore` idempotently."""

from __future__ import annotations

from pathlib import Path

from wiedunflow.cli.main import ensure_gitignore_entry


def test_creates_gitignore_when_missing(tmp_path: Path) -> None:
    ensure_gitignore_entry(tmp_path)
    content = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert ".wiedunflow/" in content


def test_appends_when_entry_absent(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
    ensure_gitignore_entry(tmp_path)
    content = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert "__pycache__/" in content
    assert ".wiedunflow/" in content


def test_idempotent_when_already_present(tmp_path: Path) -> None:
    original = "node_modules/\n.wiedunflow/\n"
    (tmp_path / ".gitignore").write_text(original, encoding="utf-8")
    ensure_gitignore_entry(tmp_path)
    assert (tmp_path / ".gitignore").read_text(encoding="utf-8") == original


def test_inserts_leading_newline_when_missing(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("existing-entry", encoding="utf-8")
    ensure_gitignore_entry(tmp_path)
    content = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert content.endswith(".wiedunflow/\n")
    assert content == "existing-entry\n.wiedunflow/\n"
