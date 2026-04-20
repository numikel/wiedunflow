# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator

CodeRefRole = Literal["primary", "referenced", "example"]


class CodeRef(BaseModel):
    """Structured reference to a specific code region within the repository.

    Replaces the S0-S2 opaque ``tuple[str, ...]`` of symbol names: each reference
    now carries enough metadata for the renderer to link back to the exact file
    and line range that the lesson is grounded in.
    """

    model_config = ConfigDict(frozen=True)

    file_path: Path
    symbol: str
    line_start: int
    line_end: int
    role: CodeRefRole = "primary"

    @model_validator(mode="after")
    def validate_lines(self) -> Self:
        if self.line_start < 1:
            raise ValueError(f"line_start must be >= 1, got {self.line_start}")
        if self.line_end < self.line_start:
            raise ValueError(
                f"line_end ({self.line_end}) must be >= line_start ({self.line_start})"
            )
        return self
