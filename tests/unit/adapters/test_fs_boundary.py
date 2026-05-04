# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Unit tests for DefaultFsBoundary (F-007: LLM path-traversal guard)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from wiedunflow.adapters.fs_boundary import DefaultFsBoundary
from wiedunflow.interfaces.ports import PathOutsideRootError

# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_root_must_be_absolute_raises_value_error(tmp_path: Path) -> None:
    """DefaultFsBoundary rejects a relative root path at construction time."""
    relative = Path("some/relative/path")
    with pytest.raises(ValueError, match="root must be absolute"):
        DefaultFsBoundary(root=relative)


def test_root_absolute_construction_succeeds(tmp_path: Path) -> None:
    """An absolute root path is accepted without error."""
    boundary = DefaultFsBoundary(root=tmp_path)
    assert boundary.root == tmp_path


# ---------------------------------------------------------------------------
# ensure_within_root — happy paths
# ---------------------------------------------------------------------------


def test_path_inside_root_returns_resolved_path(tmp_path: Path) -> None:
    """A path inside the root is resolved and returned."""
    inside = tmp_path / "subdir" / "file.py"
    inside.parent.mkdir(parents=True)
    inside.write_text("# ok\n", encoding="utf-8")

    boundary = DefaultFsBoundary(root=tmp_path)
    result = boundary.ensure_within_root(inside)

    assert result == inside.resolve()
    assert result.is_relative_to(tmp_path)


def test_path_equal_to_root_is_allowed(tmp_path: Path) -> None:
    """The root itself is a valid target (e.g. listing the root dir)."""
    boundary = DefaultFsBoundary(root=tmp_path)
    result = boundary.ensure_within_root(tmp_path)
    assert result == tmp_path.resolve()


# ---------------------------------------------------------------------------
# ensure_within_root — rejection paths
# ---------------------------------------------------------------------------


def test_path_outside_root_raises_path_outside_root_error(tmp_path: Path) -> None:
    """An absolute path outside the root raises PathOutsideRootError."""
    # Use a path that is guaranteed to exist but lives outside tmp_path.
    outside = Path(tmp_path.root)  # filesystem root (/ on Unix, C:\ on Windows)
    boundary = DefaultFsBoundary(root=tmp_path)
    with pytest.raises(PathOutsideRootError, match="escapes repo root"):
        boundary.ensure_within_root(outside)


def test_relative_traversal_resolves_outside_raises(tmp_path: Path) -> None:
    """``../../etc/passwd``-style relative traversal is caught after resolution."""
    # Construct a path that starts inside tmp_path but traverses out.
    traversal = tmp_path / "subdir" / ".." / ".." / "etc" / "passwd"
    boundary = DefaultFsBoundary(root=tmp_path)
    with pytest.raises(PathOutsideRootError, match="escapes repo root"):
        boundary.ensure_within_root(traversal)


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="os.symlink may require elevated privileges on Windows",
)
def test_symlink_to_outside_root_raises(tmp_path: Path) -> None:
    """A symlink inside the repo that points outside the root is caught.

    ``Path.resolve()`` dereferences symlinks before the containment check,
    so the escape is detected even though the symlink itself lives inside
    ``tmp_path``.
    """
    # Create a directory to act as the "outside" target.
    outside_dir = tmp_path.parent / "outside_target"
    outside_dir.mkdir(exist_ok=True)
    try:
        # Create a symlink inside the repo pointing outside.
        link_inside = tmp_path / "evil_link"
        os.symlink(outside_dir, link_inside)

        boundary = DefaultFsBoundary(root=tmp_path)
        with pytest.raises(PathOutsideRootError, match="escapes repo root"):
            boundary.ensure_within_root(link_inside)
    finally:
        # Clean up to avoid polluting other tests.
        if (tmp_path / "evil_link").exists() or (tmp_path / "evil_link").is_symlink():
            (tmp_path / "evil_link").unlink(missing_ok=True)
        if outside_dir.exists():
            outside_dir.rmdir()


# ---------------------------------------------------------------------------
# PathOutsideRootError inheritance
# ---------------------------------------------------------------------------


def test_path_outside_root_error_is_permission_error() -> None:
    """PathOutsideRootError inherits from PermissionError for broad catch compatibility."""
    exc = PathOutsideRootError("test message")
    assert isinstance(exc, PermissionError)
    assert "test message" in str(exc)
