# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Lint rule (ADR-0014 / three-sink extension): httpx imports confined to
``adapters/litellm_pricing_catalog.py``.

The three-sink architecture (rich → output.py, questionary → menu.py,
httpx → litellm_pricing_catalog.py, plain print → menu_banner.py) keeps
pipeline and CLI code free of network dependencies.  Any ``import httpx`` or
``from httpx`` anywhere outside the single allowed module is a regression —
it bypasses the optional-dependency guard and exposes un-guarded network
calls.
"""

from __future__ import annotations

from pathlib import Path

_SRC_ROOT = Path(__file__).parent.parent.parent.parent / "src" / "codeguide"
_ALLOWLIST = {
    # Pricing catalog — the sole intentional live-fetch consumer of httpx for pricing.
    "src/codeguide/adapters/litellm_pricing_catalog.py",
    # OpenAI provider — uses httpx for configuring OpenAI-compatible base_url transports
    # (Ollama, LM Studio, vLLM).  This is an OpenAI SDK integration concern, not pricing.
    "src/codeguide/adapters/openai_provider.py",
}


def test_no_httpx_outside_litellm_pricing() -> None:
    offenders: list[str] = []
    for py_file in _SRC_ROOT.rglob("*.py"):
        rel = py_file.relative_to(_SRC_ROOT.parent.parent).as_posix()
        if rel in _ALLOWLIST:
            continue
        text = py_file.read_text(encoding="utf-8")
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("import httpx") or stripped.startswith("from httpx"):
                offenders.append(f"{rel}: {stripped}")
    assert offenders == [], (
        "httpx imports must live in src/codeguide/adapters/litellm_pricing_catalog.py only; "
        "offenders:\n" + "\n".join(offenders)
    )
