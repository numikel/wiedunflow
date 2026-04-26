# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator

from wiedunflow.entities.code_symbol import CodeSymbol
from wiedunflow.entities.resolution_stats import ResolutionStats


class CallGraph(BaseModel):
    """Directed call graph produced by the analysis stage.

    Parser produces a "raw" CallGraph where edges may point at textual callee names
    that do not correspond to any known node (cross-file references unresolved).
    Resolver consumes the raw graph, resolves edges via Jedi, drops unresolved ones,
    and attaches ``resolution_stats`` summarising the coverage tiers.
    """

    model_config = ConfigDict(frozen=True)

    # Tuples are used instead of lists for hashability on frozen models.
    nodes: tuple[CodeSymbol, ...]
    edges: tuple[tuple[str, str], ...]  # (caller_name, callee_name)
    # Populated by the Resolver stage; None on the raw graph emitted by Parser.
    resolution_stats: ResolutionStats | None = None

    @model_validator(mode="after")
    def validate_edges_reference_nodes(self) -> Self:
        """Every edge endpoint must correspond to a known node name.

        Applies only when ``resolution_stats`` is set — i.e. after the Resolver has
        pruned unresolved edges. The raw graph emitted by Parser is allowed to carry
        textual callee names that do not resolve to any node yet.
        """
        if self.resolution_stats is None:
            return self
        node_names = {n.name for n in self.nodes}
        for caller, callee in self.edges:
            if caller not in node_names:
                raise ValueError(f"Edge references unknown caller: {caller!r}")
            if callee not in node_names:
                raise ValueError(f"Edge references unknown callee: {callee!r}")
        return self
