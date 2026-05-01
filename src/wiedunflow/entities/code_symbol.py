# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

SymbolKind = Literal["function", "class", "method", "module", "variable"]


class CodeSymbol(BaseModel):
    """A single named symbol extracted from source code by the analysis stage."""

    model_config = ConfigDict(frozen=True)

    name: str  # fully qualified: e.g. "calculator.add"
    kind: SymbolKind
    file_path: Path  # relative to repo root
    lineno: int  # 1-indexed
    end_lineno: int | None = None  # 1-indexed; None for parsers that do not report span
    docstring: str | None = None
    is_uncertain: bool = (
        False  # True only when the *module itself* is dynamic (importlib/__import__)
    )
    is_dynamic_import: bool = False  # True for any dynamic dispatch pattern (getattr, importlib, …)
