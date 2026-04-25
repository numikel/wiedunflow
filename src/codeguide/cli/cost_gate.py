# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Interactive cost-gate prompt (US-070, US-084 — Sprint 8).

Before Stage 5 (Narration) begins, the orchestrator must decide whether to
spend money on LLM calls. v0.1.0 only enforced ``--max-cost`` as a hard kill
switch; v0.2.0 adds a default-on confirmation prompt for TTY users.

Bypass conditions (Q4 in plan, Sprint 8):

- ``not stdin.isatty()`` — non-TTY (CI, pipe, redirect): auto-yes, prompt
  would block forever.
- ``--yes`` — explicit auto-confirm flag (already wired in v0.1.0 for the
  consent banner).
- ``--no-cost-prompt`` — new v0.2.0 flag for power users running in TTY who
  want to skip the prompt without auto-yes-ing the consent banner.

When the user declines (``[N]``) the orchestrator raises
:class:`CostGateAbortedError`; the CLI translates this into exit code 0
(user-initiated abort, not a failure) and prints the spec-mandated abort
message via :func:`codeguide.cli.output.print_cost_abort`.
"""

from __future__ import annotations

import click

from codeguide.cli.cost_estimator import CostEstimate
from codeguide.cli.output import CostGateRow, render_cost_gate


class CostGateAbortedError(RuntimeError):
    """Raised when the user declines the cost-gate prompt (US-084).

    The CLI catches this exception, prints the spec-mandated abort message,
    and exits with status code 0 (clean user abort, not a failure).
    """

    def __init__(self, estimate_usd: float, lessons: int) -> None:
        super().__init__(
            f"User aborted at cost gate: estimate ${estimate_usd:.2f} for {lessons} lessons"
        )
        self.estimate_usd = estimate_usd
        self.lessons = lessons


def should_skip_prompt(
    *,
    auto_yes: bool,
    prompt_disabled: bool,
    is_tty: bool,
) -> bool:
    """Return ``True`` when the cost-gate prompt should be bypassed.

    Args:
        auto_yes: ``True`` when the user passed ``--yes`` (auto-confirm all).
        prompt_disabled: ``True`` when the user passed ``--no-cost-prompt``.
        is_tty: ``True`` when ``stdin.isatty()`` (interactive terminal).

    Returns:
        ``True`` if any bypass condition is met. Equivalent to "do not show
        the prompt; proceed as if the user clicked yes".
    """
    return auto_yes or prompt_disabled or not is_tty


def prompt_cost_gate(
    console: object,
    *,
    estimate: CostEstimate,
    auto_yes: bool,
    prompt_disabled: bool,
    is_tty: bool,
) -> bool:
    """Render the cost-gate panel and prompt for confirmation (US-070, US-084).

    Args:
        console: Rich console for the panel render.
        estimate: Cost estimate produced by :func:`cost_estimator.estimate`.
        auto_yes: ``--yes`` flag value.
        prompt_disabled: ``--no-cost-prompt`` flag value.
        is_tty: Result of ``stdin.isatty()`` at CLI entry.

    Returns:
        ``True`` when the run should proceed (bypass condition met or user
        confirmed); ``False`` when the user declined (caller raises
        ``CostGateAbortedError``).
    """
    if should_skip_prompt(auto_yes=auto_yes, prompt_disabled=prompt_disabled, is_tty=is_tty):
        return True

    # Build the rows shown in the table — Sprint 8 keeps the v0.1.0 wording.
    rows = [
        CostGateRow(
            model="haiku",
            stage="stages 1-4 (analyse/cluster)",
            est_tokens=estimate.haiku_tokens,
            est_cost_usd=estimate.haiku_cost_usd,
        ),
        CostGateRow(
            model="opus",
            stage="stages 5-6 (narrate/ground)",
            est_tokens=estimate.sonnet_tokens,
            est_cost_usd=estimate.sonnet_cost_usd,
        ),
    ]
    render_cost_gate(
        console,  # type: ignore[arg-type]
        rows=rows,
        total_tokens=estimate.total_tokens,
        total_cost_usd=estimate.total_cost_usd,
        runtime_min=estimate.runtime_min_minutes,
        runtime_max=estimate.runtime_max_minutes,
        lessons=estimate.lessons,
        clusters=estimate.clusters,
    )

    # ``click.confirm`` honours non-TTY by raising; we already filtered above.
    return click.confirm("Proceed?", default=False)
