# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""SIGINT handler for the codeguide CLI (US-027, US-028).

Two-phase Ctrl+C behaviour:

1. **First SIGINT** — sets ``should_finish_current=True`` so the orchestrator
   can flush a checkpoint after the current lesson (cap: 90s hard timer).
   A user-facing banner is printed to stderr.
2. **Second SIGINT within 2 seconds** — hard-aborts via ``os._exit(130)``.

The handler is intentionally *not* tied to ``asyncio`` because the pipeline is
sync.  It never catches ``KeyboardInterrupt`` — the adapter retry layer must
scope its ``except`` to ``Exception`` (never ``BaseException``) so SIGINT
propagates cleanly.
"""

from __future__ import annotations

import os
import signal
import sys
import threading
import time
from collections.abc import Callable
from types import FrameType
from typing import Any

__all__ = ["SigintHandler", "install_sigint_handler"]

# Window within which a second SIGINT is treated as a hard-abort request.
_SECOND_SIGINT_WINDOW_S: float = 2.0

# Safety cap after which the first SIGINT is escalated to a hard-abort even if
# the second signal never arrives (US-027 AC2: "capped at 90 seconds").
_GRACEFUL_TIMEOUT_S: float = 90.0


class SigintHandler:
    """Installable SIGINT handler with graceful-then-hard semantics.

    Use :meth:`install` to register; use :meth:`should_finish_current` /
    :attr:`should_finish` in the orchestrator loop to check whether a graceful
    shutdown was requested.  A single instance is sufficient — the handler
    reuses itself for both SIGINTs.

    Attributes:
        should_finish: ``threading.Event`` set after the first SIGINT.
        first_sigint_at: Monotonic timestamp of the first SIGINT (``None``
            when the handler has not fired).
    """

    def __init__(
        self,
        *,
        stderr: Any = sys.stderr,
        hard_abort: Callable[[int], None] | None = None,
    ) -> None:
        self.should_finish: threading.Event = threading.Event()
        self.first_sigint_at: float | None = None
        self._stderr = stderr
        # Indirection so tests can swap ``os._exit`` with a spy.
        self._hard_abort: Callable[[int], None] = hard_abort or os._exit
        self._timer: threading.Timer | None = None
        self._previous_handler: Any = None

    def install(self) -> None:
        """Register the handler as the process-wide ``SIGINT`` callback."""
        self._previous_handler = signal.signal(signal.SIGINT, self._handle)

    def restore(self) -> None:
        """Restore the previous ``SIGINT`` handler and cancel any pending timer."""
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        if self._previous_handler is not None:
            signal.signal(signal.SIGINT, self._previous_handler)
            self._previous_handler = None

    def _handle(self, signum: int, frame: FrameType | None) -> None:
        """Actual signal-handler callback installed on SIGINT."""
        now = time.monotonic()
        if (
            self.first_sigint_at is not None
            and (now - self.first_sigint_at) < _SECOND_SIGINT_WINDOW_S
        ):
            # US-028: second Ctrl+C within the window — hard abort.
            self._print("\nAborting immediately (second Ctrl+C).")
            self._hard_abort(130)
            return

        # US-027: first (or late-duplicate) SIGINT — request graceful finish.
        self.first_sigint_at = now
        self.should_finish.set()
        self._print(
            "\nFinishing current lesson... press Ctrl+C again within 2s to abort immediately."
        )
        # Safety timer: even without a second SIGINT, escalate after 90s.
        self._timer = threading.Timer(_GRACEFUL_TIMEOUT_S, lambda: self._hard_abort(130))
        self._timer.daemon = True
        self._timer.start()

    def _print(self, message: str) -> None:
        try:
            self._stderr.write(message + "\n")
            self._stderr.flush()
        except Exception:  # pragma: no cover — I/O failures on stderr are non-fatal
            pass


def install_sigint_handler(**kwargs: Any) -> SigintHandler:
    """Shorthand: construct + install a ``SigintHandler`` and return it."""
    handler = SigintHandler(**kwargs)
    handler.install()
    return handler
