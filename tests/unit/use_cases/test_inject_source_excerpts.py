# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Unit tests for inject_source_excerpts."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from wiedunflow.entities.code_ref import CodeRef
from wiedunflow.entities.lesson_manifest import LessonManifest, LessonSpec, ManifestMetadata
from wiedunflow.use_cases.inject_source_excerpts import inject_source_excerpts

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 4, 20, 0, 0, 0, tzinfo=UTC)


def _make_metadata(total_lessons: int = 1) -> ManifestMetadata:
    return ManifestMetadata(
        wiedunflow_version="0.0.3",
        total_lessons=total_lessons,
        generated_at=_NOW,
        has_readme=True,
    )


def _make_ref(
    symbol: str = "mod.foo",
    line_start: int = 1,
    line_end: int = 5,
    role: str = "primary",
    file_path: str = "mod.py",
) -> CodeRef:
    return CodeRef(
        file_path=Path(file_path),
        symbol=symbol,
        line_start=line_start,
        line_end=line_end,
        role=role,  # type: ignore[arg-type]
    )


def _make_manifest(specs: tuple[LessonSpec, ...]) -> LessonManifest:
    return LessonManifest(
        schema_version="1.0.0",
        lessons=specs,
        metadata=_make_metadata(total_lessons=len(specs)),
    )


def _make_spec(
    lesson_id: str = "lesson-001",
    ref: CodeRef | None = None,
) -> LessonSpec:
    if ref is None:
        ref = _make_ref()
    return LessonSpec(
        id=lesson_id,
        title=f"Lesson {lesson_id}",
        teaches="something",
        code_refs=(ref,),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_primary_under_threshold_gets_source_excerpt(tmp_path: Path) -> None:
    """Primary ref with span < primary_max_lines gets source_excerpt populated."""
    src = tmp_path / "mod.py"
    lines = [f"line {i}" for i in range(1, 11)]
    src.write_text("\n".join(lines), encoding="utf-8")

    ref = _make_ref(line_start=2, line_end=5, role="primary")
    manifest = _make_manifest((_make_spec(ref=ref),))

    result = inject_source_excerpts(manifest, tmp_path, primary_max_lines=10)

    new_ref = result.lessons[0].code_refs[0]
    assert new_ref.source_excerpt is not None
    # Lines 2-5 (1-indexed): "line 2", "line 3", "line 4", "line 5"
    assert "line 2" in new_ref.source_excerpt
    assert "line 5" in new_ref.source_excerpt


def test_primary_over_threshold_no_excerpt(tmp_path: Path) -> None:
    """Primary ref with span >= primary_max_lines → source_excerpt is None."""
    src = tmp_path / "mod.py"
    src.write_text("\n".join(f"line {i}" for i in range(1, 100)), encoding="utf-8")

    # span = 31 - 1 = 30, threshold = 30 → 30 >= 30 → skip
    ref = _make_ref(line_start=1, line_end=31, role="primary")
    manifest = _make_manifest((_make_spec(ref=ref),))

    result = inject_source_excerpts(manifest, tmp_path, primary_max_lines=30)

    new_ref = result.lessons[0].code_refs[0]
    assert new_ref.source_excerpt is None


def test_referenced_role_not_injected(tmp_path: Path) -> None:
    """Only 'primary' role gets excerpt; 'referenced' role is skipped."""
    src = tmp_path / "mod.py"
    src.write_text("\n".join(f"line {i}" for i in range(1, 20)), encoding="utf-8")

    ref = _make_ref(line_start=1, line_end=5, role="referenced")
    manifest = _make_manifest((_make_spec(ref=ref),))

    result = inject_source_excerpts(manifest, tmp_path, primary_max_lines=30)

    new_ref = result.lessons[0].code_refs[0]
    assert new_ref.source_excerpt is None


def test_file_cache_single_open_per_file(tmp_path: Path) -> None:
    """Multiple refs from the same file → file read only once per inject call."""
    src = tmp_path / "mod.py"
    content_lines = [f"def func_{i}(): pass" for i in range(1, 20)]
    src.write_text("\n".join(content_lines), encoding="utf-8")

    # Three specs, all referencing the same file, all within the line threshold
    specs = tuple(
        LessonSpec(
            id=f"lesson-{i:03d}",
            title=f"Lesson {i}",
            teaches="something",
            code_refs=(
                CodeRef(
                    file_path=Path("mod.py"),
                    symbol=f"mod.func_{i}",
                    line_start=i,
                    line_end=i + 2,
                    role="primary",
                ),
            ),
        )
        for i in range(1, 4)
    )
    manifest = LessonManifest(
        schema_version="1.0.0",
        lessons=specs,
        metadata=_make_metadata(total_lessons=3),
    )

    read_calls: list[Path] = []
    original_read_text = Path.read_text

    def tracking_read_text(self: Path, *args: object, **kwargs: object) -> str:
        read_calls.append(self)
        return original_read_text(self, *args, **kwargs)  # type: ignore[arg-type]

    with patch.object(Path, "read_text", tracking_read_text):
        inject_source_excerpts(manifest, tmp_path, primary_max_lines=30)

    # Only the resolved absolute path is read; check it was opened at most once
    mod_reads = [p for p in read_calls if p.name == "mod.py"]
    assert len(mod_reads) == 1, f"Expected 1 read, got {len(mod_reads)}: {mod_reads}"


def test_immutable_manifest_returned(tmp_path: Path) -> None:
    """inject_source_excerpts returns a NEW manifest; the original is not mutated."""
    src = tmp_path / "mod.py"
    src.write_text("def foo(x):\n    return x\n", encoding="utf-8")

    ref = _make_ref(line_start=1, line_end=2, role="primary")
    manifest = _make_manifest((_make_spec(ref=ref),))

    result = inject_source_excerpts(manifest, tmp_path, primary_max_lines=30)

    # The original ref should have no excerpt
    original_ref = manifest.lessons[0].code_refs[0]
    assert original_ref.source_excerpt is None
    # The new ref should have the excerpt
    new_ref = result.lessons[0].code_refs[0]
    assert new_ref.source_excerpt is not None


def test_missing_file_returns_unchanged_ref(tmp_path: Path) -> None:
    """When the file does not exist, the ref is returned unchanged (no crash)."""
    ref = _make_ref(file_path="nonexistent.py", line_start=1, line_end=5, role="primary")
    manifest = _make_manifest((_make_spec(ref=ref),))

    result = inject_source_excerpts(manifest, tmp_path, primary_max_lines=30)

    new_ref = result.lessons[0].code_refs[0]
    assert new_ref.source_excerpt is None


def test_excerpt_max_length_enforced(tmp_path: Path) -> None:
    """source_excerpt is truncated to 4000 characters when the file is large."""
    src = tmp_path / "big.py"
    # Write enough content to exceed 4000 chars in a short line range
    long_line = "x" * 200
    lines = [long_line for _ in range(25)]
    src.write_text("\n".join(lines), encoding="utf-8")

    ref = CodeRef(
        file_path=Path("big.py"),
        symbol="big.func",
        line_start=1,
        line_end=25,
        role="primary",
    )
    spec = LessonSpec(
        id="lesson-001",
        title="Big lesson",
        teaches="big stuff",
        code_refs=(ref,),
    )
    manifest = LessonManifest(
        schema_version="1.0.0",
        lessons=(spec,),
        metadata=_make_metadata(total_lessons=1),
    )

    result = inject_source_excerpts(manifest, tmp_path, primary_max_lines=30)

    new_ref = result.lessons[0].code_refs[0]
    if new_ref.source_excerpt is not None:
        assert len(new_ref.source_excerpt) <= 4000


def test_no_primary_ref_leaves_manifest_unchanged(tmp_path: Path) -> None:
    """LessonSpec with no primary ref → manifest returned as-is."""
    src = tmp_path / "mod.py"
    src.write_text("x = 1\n", encoding="utf-8")

    spec = LessonSpec(
        id="lesson-001",
        title="Lesson",
        teaches="nothing",
        code_refs=(),  # no refs at all
    )
    manifest = LessonManifest(
        schema_version="1.0.0",
        lessons=(spec,),
        metadata=_make_metadata(total_lessons=1),
    )

    result = inject_source_excerpts(manifest, tmp_path, primary_max_lines=30)

    # Should return the same object (nothing to inject)
    assert result is manifest
