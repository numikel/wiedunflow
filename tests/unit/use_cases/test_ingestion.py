# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Unit tests for the ingestion use case."""

from __future__ import annotations

import subprocess
from pathlib import Path

from wiedunflow.entities.ingestion_result import IngestionResult
from wiedunflow.use_cases.ingestion import ingest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_repo(tmp_path: Path, files: dict[str, str]) -> Path:
    """Create a directory tree from *files* mapping relative-path → content."""
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return tmp_path


def _init_git(path: Path) -> None:
    """Initialise a minimal git repo in *path* with a single commit."""
    subprocess.run(["git", "init", "-b", "main", str(path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "t@t.com"],
        cwd=path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "T"],
        cwd=path,
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "add", "."], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=path,
        check=True,
        capture_output=True,
    )


def _rel_names(result: IngestionResult) -> set[str]:
    """Return the set of relative-path strings from an IngestionResult."""
    return {f.relative_to(result.repo_root).as_posix() for f in result.files}


# ---------------------------------------------------------------------------
# Basic file discovery
# ---------------------------------------------------------------------------


def test_finds_python_files(tmp_path: Path) -> None:
    """All .py files in the repo root are discovered."""
    _make_repo(tmp_path, {"a.py": "", "b.py": "", "README.md": ""})
    result = ingest(tmp_path)
    assert "a.py" in _rel_names(result)
    assert "b.py" in _rel_names(result)


def test_finds_nested_python_files(tmp_path: Path) -> None:
    """Python files in sub-directories are included."""
    _make_repo(tmp_path, {"pkg/mod.py": "", "pkg/sub/util.py": ""})
    result = ingest(tmp_path)
    names = _rel_names(result)
    assert "pkg/mod.py" in names
    assert "pkg/sub/util.py" in names


def test_non_python_files_excluded(tmp_path: Path) -> None:
    """Non-.py files are never included."""
    _make_repo(tmp_path, {"script.py": "", "config.yaml": "", "notes.txt": ""})
    result = ingest(tmp_path)
    names = _rel_names(result)
    assert all(n.endswith(".py") for n in names)


# ---------------------------------------------------------------------------
# __pycache__ and dotted directory skipping
# ---------------------------------------------------------------------------


def test_pycache_skipped(tmp_path: Path) -> None:
    """``__pycache__`` directories are always excluded."""
    _make_repo(
        tmp_path,
        {
            "src/app.py": "",
            "src/__pycache__/app.cpython-311.pyc": "",  # not .py, but belt-and-suspenders
            "src/__pycache__/compiled.py": "",  # .py file in __pycache__
        },
    )
    result = ingest(tmp_path)
    names = _rel_names(result)
    assert not any("__pycache__" in n for n in names)


def test_dotted_directories_skipped(tmp_path: Path) -> None:
    """Hidden directories (dotted names) are always excluded."""
    _make_repo(
        tmp_path,
        {
            "src/main.py": "",
            ".venv/lib/site-packages/pkg.py": "",
            ".git/hooks/post-commit.py": "",
        },
    )
    result = ingest(tmp_path)
    names = _rel_names(result)
    assert "src/main.py" in names
    assert not any(n.startswith(".") for n in names)


# ---------------------------------------------------------------------------
# .gitignore filtering
# ---------------------------------------------------------------------------


def test_gitignore_patterns_respected(tmp_path: Path) -> None:
    """Files matching .gitignore patterns are excluded."""
    _make_repo(
        tmp_path,
        {
            "src/app.py": "",
            "tests/test_app.py": "",
            "build/output.py": "",
            ".gitignore": "build/\n",
        },
    )
    result = ingest(tmp_path)
    names = _rel_names(result)
    assert "src/app.py" in names
    assert "tests/test_app.py" in names
    assert not any("build/" in n for n in names)


def test_gitignore_star_pattern(tmp_path: Path) -> None:
    """Glob patterns in .gitignore are respected."""
    _make_repo(
        tmp_path,
        {
            "app.py": "",
            "generated_code.py": "",
            ".gitignore": "generated_*.py\n",
        },
    )
    result = ingest(tmp_path)
    names = _rel_names(result)
    assert "app.py" in names
    assert "generated_code.py" not in names


# ---------------------------------------------------------------------------
# Additive excludes
# ---------------------------------------------------------------------------


def test_additive_excludes(tmp_path: Path) -> None:
    """User-supplied excludes are applied on top of .gitignore."""
    _make_repo(
        tmp_path,
        {
            "src/main.py": "",
            "tests/test_main.py": "",
        },
    )
    result = ingest(tmp_path, excludes=("tests/",))
    names = _rel_names(result)
    assert "src/main.py" in names
    assert "tests/test_main.py" not in names


def test_multiple_excludes(tmp_path: Path) -> None:
    """Multiple exclude patterns each independently filter files."""
    _make_repo(
        tmp_path,
        {
            "src/main.py": "",
            "tests/test.py": "",
            "bench/perf.py": "",
        },
    )
    result = ingest(tmp_path, excludes=("tests/", "bench/"))
    names = _rel_names(result)
    assert "src/main.py" in names
    assert "tests/test.py" not in names
    assert "bench/perf.py" not in names


# ---------------------------------------------------------------------------
# Include (un-ignore) patterns
# ---------------------------------------------------------------------------


def test_includes_un_ignore(tmp_path: Path) -> None:
    """An include pattern negates a gitignore exclusion."""
    _make_repo(
        tmp_path,
        {
            "src/app.py": "",
            "generated/special.py": "",
            ".gitignore": "generated/\n",
        },
    )
    result = ingest(tmp_path, includes=("generated/special.py",))
    names = _rel_names(result)
    assert "src/app.py" in names
    assert "generated/special.py" in names


# ---------------------------------------------------------------------------
# Monorepo detection
# ---------------------------------------------------------------------------


def test_monorepo_no_root_marker_detects_subtree(tmp_path: Path) -> None:
    """When root has no pyproject.toml but a subdirectory does, subtree is set."""
    _make_repo(
        tmp_path,
        {
            "mypackage/pyproject.toml": "[project]\nname='mypackage'\n",
            "mypackage/src/main.py": "",
        },
    )
    result = ingest(tmp_path)
    assert result.detected_subtree is not None
    assert result.detected_subtree.name == "mypackage"


def test_monorepo_root_has_marker_no_subtree(tmp_path: Path) -> None:
    """When repo root already has pyproject.toml, detected_subtree is None."""
    _make_repo(
        tmp_path,
        {
            "pyproject.toml": "[project]\nname='main'\n",
            "src/main.py": "",
        },
    )
    result = ingest(tmp_path)
    assert result.detected_subtree is None


def test_monorepo_multiple_candidates_no_subtree(tmp_path: Path) -> None:
    """Multiple candidate subdirectories → conservative fallback to None."""
    _make_repo(
        tmp_path,
        {
            "pkg_a/pyproject.toml": "",
            "pkg_b/pyproject.toml": "",
        },
    )
    result = ingest(tmp_path)
    assert result.detected_subtree is None


# ---------------------------------------------------------------------------
# root_override
# ---------------------------------------------------------------------------


def test_root_override_sets_repo_root(tmp_path: Path) -> None:
    """root_override makes ingestion treat a subdirectory as the repo root."""
    sub = tmp_path / "subpkg"
    sub.mkdir()
    (sub / "mod.py").write_text("", encoding="utf-8")
    (tmp_path / "unrelated.py").write_text("", encoding="utf-8")

    result = ingest(tmp_path, root_override=sub)
    assert result.repo_root == sub
    names = _rel_names(result)
    assert "mod.py" in names
    # The unrelated file at repo root level is outside the override scope.
    assert "unrelated.py" not in names


def test_root_override_disables_subtree_detection(tmp_path: Path) -> None:
    """When root_override is given, detected_subtree is always None."""
    sub = tmp_path / "subpkg"
    sub.mkdir()
    (sub / "pyproject.toml").write_text("", encoding="utf-8")
    (sub / "main.py").write_text("", encoding="utf-8")

    result = ingest(tmp_path, root_override=sub)
    assert result.detected_subtree is None


# ---------------------------------------------------------------------------
# Git context wiring
# ---------------------------------------------------------------------------


def test_non_git_dir_returns_unknown_context(tmp_path: Path) -> None:
    """Ingesting a plain directory (no .git) populates 'unknown' git fields."""
    _make_repo(tmp_path, {"app.py": ""})
    result = ingest(tmp_path)
    assert result.commit_hash == "unknown"
    assert result.branch == "unknown"


def test_git_repo_returns_real_context(tmp_path: Path) -> None:
    """A real git repo yields a non-'unknown' commit hash and branch."""
    _make_repo(tmp_path, {"app.py": ""})
    _init_git(tmp_path)
    result = ingest(tmp_path)
    assert result.commit_hash != "unknown"
    assert result.branch == "main"


# ---------------------------------------------------------------------------
# excluded_count
# ---------------------------------------------------------------------------


def test_excluded_count_reflects_filtered_files(tmp_path: Path) -> None:
    """excluded_count equals the number of .py files that were filtered out."""
    _make_repo(
        tmp_path,
        {
            "src/keep.py": "",
            "tests/skip.py": "",
        },
    )
    result = ingest(tmp_path, excludes=("tests/",))
    assert result.excluded_count >= 1


# ---------------------------------------------------------------------------
# Return type invariants
# ---------------------------------------------------------------------------


def test_files_are_sorted(tmp_path: Path) -> None:
    """Returned files tuple is sorted (deterministic ordering)."""
    _make_repo(tmp_path, {"z.py": "", "a.py": "", "m.py": ""})
    result = ingest(tmp_path)
    file_list = list(result.files)
    assert file_list == sorted(file_list)


def test_files_are_absolute(tmp_path: Path) -> None:
    """All paths in the result are absolute."""
    _make_repo(tmp_path, {"src/mod.py": ""})
    result = ingest(tmp_path)
    assert all(f.is_absolute() for f in result.files)


# ---------------------------------------------------------------------------
# rglob("*.py") optimisation — non-.py files never stat'd / collected
# ---------------------------------------------------------------------------


def test_non_py_files_not_collected_in_large_repo(tmp_path: Path) -> None:
    """With 50 non-.py files and 5 .py files, only the 5 .py files are collected.

    This test validates that rglob('*.py') eliminates non-Python files before
    any stat() call rather than filtering them post-stat.
    """
    # Create 50 non-.py files of various types.
    non_py_extensions = [".md", ".txt", ".yaml", ".json", ".toml", ".rst", ".cfg"]
    for i in range(50):
        ext = non_py_extensions[i % len(non_py_extensions)]
        (tmp_path / f"file_{i}{ext}").write_text("content", encoding="utf-8")

    # Create 5 .py files.
    for i in range(5):
        (tmp_path / f"module_{i}.py").write_text(f"def fn_{i}(): pass\n", encoding="utf-8")

    result = ingest(tmp_path)

    # Only .py files collected.
    assert len(result.files) == 5
    assert all(f.suffix == ".py" for f in result.files)


def test_rglob_still_finds_nested_py_files(tmp_path: Path) -> None:
    """rglob('*.py') must recurse into subdirectories, not just the root."""
    _make_repo(
        tmp_path,
        {
            "src/core/logic.py": "",
            "src/utils/helpers.py": "",
            "README.md": "docs",
            "data/config.yaml": "cfg",
        },
    )
    result = ingest(tmp_path)
    names = _rel_names(result)
    assert "src/core/logic.py" in names
    assert "src/utils/helpers.py" in names
    # Non-.py files must not appear.
    assert not any(not n.endswith(".py") for n in names)


def test_pycache_py_files_excluded_by_rglob_filter(tmp_path: Path) -> None:
    """__pycache__/*.py files matched by rglob('*.py') are still skipped by _should_skip_path."""
    _make_repo(
        tmp_path,
        {
            "src/app.py": "",
            "src/__pycache__/app.cpython-311.pyc": "compiled",
            "src/__pycache__/util.py": "compiled_py",  # .py inside __pycache__
        },
    )
    result = ingest(tmp_path)
    names = _rel_names(result)
    # Only src/app.py should be collected; __pycache__/util.py must be skipped.
    assert "src/app.py" in names
    assert not any("__pycache__" in n for n in names)
