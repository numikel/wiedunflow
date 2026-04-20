# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from codeguide.entities.code_ref import CodeRef
from codeguide.entities.lesson_manifest import (
    LessonManifest,
    LessonManifestValidationError,
    LessonSpec,
    ManifestMetadata,
    validate_against_graph,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 4, 20, 0, 0, 0, tzinfo=UTC)


def _make_metadata(total_lessons: int = 1, **overrides: object) -> ManifestMetadata:
    return ManifestMetadata(
        codeguide_version="0.0.3",
        total_lessons=total_lessons,
        generated_at=_NOW,
        has_readme=True,
        **overrides,  # type: ignore[arg-type]
    )


def _make_ref(symbol: str = "mod.fn", *, role: str = "primary") -> CodeRef:
    return CodeRef(
        file_path=Path("mod.py"),
        symbol=symbol,
        line_start=1,
        line_end=5,
        role=role,  # type: ignore[arg-type]
    )


def _make_spec(symbol: str = "mod.fn", lesson_id: str = "lesson-001") -> LessonSpec:
    return LessonSpec(
        id=lesson_id,
        title="Test lesson",
        teaches="Something useful",
        code_refs=(_make_ref(symbol),),
    )


# ---------------------------------------------------------------------------
# ManifestMetadata construction
# ---------------------------------------------------------------------------


def test_manifest_metadata_constructs_successfully() -> None:
    meta = ManifestMetadata(
        codeguide_version="0.0.3",
        total_lessons=3,
        generated_at=_NOW,
        has_readme=True,
    )
    assert meta.schema_version == "1.0.0"
    assert meta.codeguide_version == "0.0.3"
    assert meta.total_lessons == 3
    assert meta.has_readme is True
    assert meta.doc_coverage is None


def test_manifest_metadata_schema_version_wrong_raises() -> None:
    with pytest.raises(ValidationError):
        ManifestMetadata(
            schema_version="2.0.0",  # type: ignore[arg-type]
            codeguide_version="0.0.3",
            total_lessons=1,
            generated_at=_NOW,
        )


# ---------------------------------------------------------------------------
# CodeRef validators
# ---------------------------------------------------------------------------


def test_code_ref_valid() -> None:
    ref = CodeRef(file_path=Path("a.py"), symbol="a.fn", line_start=1, line_end=10)
    assert ref.line_start == 1
    assert ref.role == "primary"


def test_code_ref_line_start_zero_raises() -> None:
    with pytest.raises(ValidationError, match="line_start"):
        CodeRef(file_path=Path("a.py"), symbol="a.fn", line_start=0, line_end=5)


def test_code_ref_line_end_before_start_raises() -> None:
    with pytest.raises(ValidationError, match="line_end"):
        CodeRef(file_path=Path("a.py"), symbol="a.fn", line_start=5, line_end=3)


def test_code_ref_equal_start_end_valid() -> None:
    ref = CodeRef(file_path=Path("a.py"), symbol="a.fn", line_start=5, line_end=5)
    assert ref.line_start == ref.line_end


# ---------------------------------------------------------------------------
# LessonManifest construction and validators
# ---------------------------------------------------------------------------


def test_lesson_manifest_constructs_successfully() -> None:
    spec = _make_spec()
    meta = _make_metadata(total_lessons=1)
    manifest = LessonManifest(schema_version="1.0.0", lessons=(spec,), metadata=meta)
    assert len(manifest.lessons) == 1
    assert manifest.schema_version == "1.0.0"


def test_lesson_manifest_total_lessons_mismatch_raises() -> None:
    spec = _make_spec()
    meta = _make_metadata(total_lessons=99)  # wrong: there is only 1 lesson
    with pytest.raises(ValidationError, match="total_lessons"):
        LessonManifest(schema_version="1.0.0", lessons=(spec,), metadata=meta)


def test_lesson_manifest_empty_lessons_allowed() -> None:
    meta = _make_metadata(total_lessons=0)
    manifest = LessonManifest(schema_version="1.0.0", lessons=(), metadata=meta)
    assert manifest.lessons == ()


# ---------------------------------------------------------------------------
# validate_against_graph
# ---------------------------------------------------------------------------


def test_validate_against_graph_happy_path() -> None:
    spec = _make_spec(symbol="a.fn")
    meta = _make_metadata(total_lessons=1)
    manifest = LessonManifest(schema_version="1.0.0", lessons=(spec,), metadata=meta)
    # Must not raise when the symbol is in the allowed set.
    validate_against_graph(manifest, frozenset({"a.fn", "b.fn"}))


def test_validate_against_graph_missing_symbol_raises() -> None:
    spec = _make_spec(symbol="c")
    meta = _make_metadata(total_lessons=1)
    manifest = LessonManifest(schema_version="1.0.0", lessons=(spec,), metadata=meta)
    with pytest.raises(LessonManifestValidationError) as exc_info:
        validate_against_graph(manifest, frozenset({"a", "b"}))
    assert exc_info.value.invalid_symbols == ["c"]


def test_validate_against_graph_multiple_invalid_symbols() -> None:
    specs = (
        LessonSpec(
            id="lesson-001",
            title="L1",
            teaches="t1",
            code_refs=(
                CodeRef(file_path=Path("a.py"), symbol="a.missing", line_start=1, line_end=2),
                CodeRef(file_path=Path("b.py"), symbol="b.also_missing", line_start=1, line_end=2),
            ),
        ),
    )
    meta = _make_metadata(total_lessons=1)
    manifest = LessonManifest(schema_version="1.0.0", lessons=specs, metadata=meta)
    with pytest.raises(LessonManifestValidationError) as exc_info:
        validate_against_graph(manifest, frozenset({"some.other"}))
    assert set(exc_info.value.invalid_symbols) == {"a.missing", "b.also_missing"}


def test_validate_against_graph_empty_code_refs_always_passes() -> None:
    spec = LessonSpec(id="lesson-001", title="L1", teaches="t1")
    meta = _make_metadata(total_lessons=1)
    manifest = LessonManifest(schema_version="1.0.0", lessons=(spec,), metadata=meta)
    # No code_refs → nothing to check → must not raise even with empty allowed set.
    validate_against_graph(manifest, frozenset())
