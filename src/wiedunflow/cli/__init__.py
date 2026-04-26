# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""WiedunFlow CLI package.

Intentionally does NOT re-export :func:`wiedunflow.cli.main.main` — doing so
would overwrite the ``wiedunflow.cli.main`` submodule attribute on the
``wiedunflow.cli`` package with the Click ``Command`` object, breaking
:mod:`pytest.monkeypatch` paths like ``wiedunflow.cli.main._build_llm_provider``.

The ``[project.scripts]`` entry point ``wiedun-flow = "wiedunflow.cli.main:main"``
targets the submodule directly and does not rely on this package exposing the
symbol.
"""

from __future__ import annotations

__all__: list[str] = []
