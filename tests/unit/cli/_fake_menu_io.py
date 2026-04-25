# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Deterministic ``MenuIO`` test double (ADR-0013 decision 5).

Drives ``main_menu_loop`` and sub-wizards in pytest without invoking the
real prompt_toolkit application. Each prompt method pops the next response
from a pre-supplied list; ``None`` simulates Esc/Ctrl+C.

Reused by all menu-related tests — keep the API stable.
"""

from __future__ import annotations

from typing import Any


class FakeMenuIO:
    """Test ``MenuIO`` impl backed by a queue of pre-supplied responses.

    Args:
        responses: Sequence of values returned by the next prompt call,
            in invocation order. Use ``None`` to simulate Esc/Ctrl+C.

    Each prompt call records ``(method_name, message, response)`` in
    ``self.calls`` for assertion. Raises ``IndexError`` if the queue is
    exhausted — usually means the menu loop didn't terminate.
    """

    def __init__(self, responses: list[Any]) -> None:
        self._responses: list[Any] = list(responses)
        self.calls: list[tuple[str, str, Any]] = []

    def _pop(self, method: str, message: str) -> Any:
        if not self._responses:
            raise IndexError(
                f"FakeMenuIO ran out of responses; last call was {method}({message!r})"
            )
        value = self._responses.pop(0)
        self.calls.append((method, message, value))
        return value

    def select(self, message: str, choices: list[str], default: str | None = None) -> Any:
        return self._pop("select", message)

    def text(self, message: str, default: str = "") -> Any:
        return self._pop("text", message)

    def path(self, message: str, only_directories: bool = False, default: str = "") -> Any:
        return self._pop("path", message)

    def password(self, message: str) -> Any:
        return self._pop("password", message)

    def confirm(self, message: str, default: bool = False) -> Any:
        return self._pop("confirm", message)
