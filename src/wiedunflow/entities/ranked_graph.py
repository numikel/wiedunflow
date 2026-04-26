# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator


class RankedSymbol(BaseModel):
    """A CodeSymbol annotated with Stage 2 ranking output."""

    model_config = ConfigDict(frozen=True)

    symbol_name: str  # matches CodeSymbol.name
    pagerank_score: float  # >= 0.0
    community_id: int  # >= 0

    @model_validator(mode="after")
    def validate_pagerank_non_negative(self) -> Self:
        if self.pagerank_score < 0.0:
            raise ValueError(f"pagerank_score must be >= 0.0, got {self.pagerank_score}")
        return self

    @model_validator(mode="after")
    def validate_community_id_non_negative(self) -> Self:
        if self.community_id < 0:
            raise ValueError(f"community_id must be >= 0, got {self.community_id}")
        return self


class RankedGraph(BaseModel):
    """Stage 2 output: PageRank + Louvain communities + topological order + cycle metadata.

    Consumed by Stage 4 (planning) as a story outline seed.
    """

    model_config = ConfigDict(frozen=True)

    ranked_symbols: tuple[RankedSymbol, ...]
    communities: tuple[frozenset[str], ...]
    topological_order: tuple[str, ...]  # SCC-condensed topo order (by symbol_name)
    has_cycles: bool
    cycle_groups: tuple[tuple[str, ...], ...] = ()

    @model_validator(mode="after")
    def validate_topological_symbols_known(self) -> Self:
        known = {s.symbol_name for s in self.ranked_symbols}
        for name in self.topological_order:
            if name not in known:
                raise ValueError(
                    f"topological_order references unknown symbol {name!r}; "
                    "every entry must be in ranked_symbols"
                )
        return self

    @model_validator(mode="after")
    def validate_community_membership(self) -> Self:
        known = {s.symbol_name for s in self.ranked_symbols}
        for idx, community in enumerate(self.communities):
            for member in community:
                if member not in known:
                    raise ValueError(
                        f"community #{idx} contains unknown symbol {member!r}; "
                        "every member must be in ranked_symbols"
                    )
        return self

    @model_validator(mode="after")
    def validate_cycle_groups_consistent_with_flag(self) -> Self:
        if self.has_cycles and not self.cycle_groups:
            raise ValueError("has_cycles=True requires at least one entry in cycle_groups")
        if not self.has_cycles and self.cycle_groups:
            raise ValueError("has_cycles=False forbids cycle_groups entries")
        return self
