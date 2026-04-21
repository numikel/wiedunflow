# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Structured logging sink — JSON lines (US-022) or plain text (default).

Two-sinks architecture (Sprint 5 decision #6):
- ``cli/output.py`` renders user-facing UI via Rich.
- This module emits machine-readable events via structlog.

When ``--log-format=json`` is active, every event becomes a JSON line on
stderr with at minimum ``ts``, ``level``, ``stage`` and ``msg`` keys.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import MutableMapping
from typing import Any

import structlog

_state: dict[str, bool] = {"configured": False}


def _add_stage(
    _: object, __: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Ensure every event carries a ``stage`` key (defaults to ``"cli"``)."""
    event_dict.setdefault("stage", event_dict.get("stage", "cli"))
    return event_dict


def _rename_event_to_msg(
    _: object, __: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Rename the default structlog ``event`` key to ``msg`` (ux-spec §CLI.logging)."""
    if "event" in event_dict and "msg" not in event_dict:
        event_dict["msg"] = event_dict.pop("event")
    return event_dict


def _rename_timestamp_to_ts(
    _: object, __: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Rename ``timestamp`` to ``ts`` to match AC US-022."""
    if "timestamp" in event_dict and "ts" not in event_dict:
        event_dict["ts"] = event_dict.pop("timestamp")
    return event_dict


def configure(*, json_mode: bool, level: int = logging.INFO) -> None:
    """Configure the global structlog logger for the current run.

    Args:
        json_mode: When ``True``, render each event as a JSON line to stderr
            (``--log-format=json``). When ``False``, render a human-friendly
            key=value line.
        level: stdlib logging level threshold (DEBUG/INFO/WARNING/...).
    """
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _rename_timestamp_to_ts,
        _add_stage,
        _rename_event_to_msg,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if json_mode:
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer(
            sort_keys=True,
        )
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=False)

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=False,
    )
    _state["configured"] = True


def get_logger(**initial_values: object) -> structlog.stdlib.BoundLogger:
    """Return a bound logger, configuring structlog with defaults if not yet done."""
    if not _state["configured"]:
        configure(json_mode=False)
    return structlog.get_logger(**initial_values)  # type: ignore[no-any-return]
