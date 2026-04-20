# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator

from codeguide.entities.code_symbol import CodeSymbol


class CallGraph(BaseModel):
    """Directed call graph produced by the analysis stage."""

    model_config = ConfigDict(frozen=True)

    # Tuples are used instead of lists for hashability on frozen models.
    nodes: tuple[CodeSymbol, ...]
    edges: tuple[tuple[str, str], ...]  # (caller_name, callee_name)

    @model_validator(mode="after")
    def validate_edges_reference_nodes(self) -> Self:
        """Every edge endpoint must correspond to a known node name."""
        node_names = {n.name for n in self.nodes}
        for caller, callee in self.edges:
            if caller not in node_names:
                raise ValueError(f"Edge references unknown caller: {caller!r}")
            if callee not in node_names:
                raise ValueError(f"Edge references unknown callee: {callee!r}")
        return self
