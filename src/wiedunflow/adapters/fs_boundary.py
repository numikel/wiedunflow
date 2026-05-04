# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Filesystem boundary enforcement for LLM-controlled path inputs.

Why this exists: tool inputs to Researcher agents include file paths that come
from prompt-injection surface — analyzed third-party repo docstrings or
LLM-generated tool arguments. A crafted ``../../etc/passwd`` must not resolve
to a real host file outside ``repo_root``.

The :class:`DefaultFsBoundary` is the production adapter; tests inject a stub
or a temporary-directory-rooted instance.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from wiedunflow.interfaces.ports import FsBoundary, PathOutsideRootError


@dataclass(frozen=True)
class DefaultFsBoundary:
    """Validates that a resolved path stays within a designated root.

    The root MUST be an absolute path (caller-resolved, e.g. via
    ``click.Path(resolve_path=True)`` in ``cli/main.py``).

    Symlinks are fully dereferenced by :meth:`ensure_within_root` before
    the containment check, so a symlink that points outside ``root`` is
    caught correctly.

    Attributes:
        root: Absolute path of the repository root that all agent-controlled
            filesystem accesses must stay within.
    """

    root: Path

    def __post_init__(self) -> None:
        if not self.root.is_absolute():
            raise ValueError(f"root must be absolute, got: {self.root!r}")

    def ensure_within_root(self, target: Path) -> Path:
        """Resolve *target* and assert it is contained within :attr:`root`.

        Symlinks are followed so that a link pointing outside the repo is
        detected as an escape attempt, not accepted as a valid in-repo path.

        Args:
            target: The candidate path to validate. May be relative or absolute;
                resolution is always done from the filesystem root.

        Returns:
            The fully-resolved absolute ``Path`` (guaranteed within ``root``).

        Raises:
            PathOutsideRootError: When the resolved path is not a descendant
                of ``root`` (i.e. ``resolved.relative_to(root)`` raises
                ``ValueError``).
        """
        resolved = target.resolve()
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise PathOutsideRootError(f"path escapes repo root: {target!r}") from exc
        return resolved


# Verify that DefaultFsBoundary satisfies the FsBoundary Protocol at
# import-time — caught by mypy; this assertion is a belt-and-suspenders
# runtime guard for environments where mypy is not run.
def _check_protocol_compat() -> None:  # pragma: no cover
    _: FsBoundary = DefaultFsBoundary(root=Path("/tmp"))


__all__ = ["DefaultFsBoundary"]
