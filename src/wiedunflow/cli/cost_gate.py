# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Interactive cost-gate prompt (US-070, US-084 — Sprint 8; v0.10.0 5-row layout).

Before Stage 5 (Narration) begins, the orchestrator must decide whether to
spend money on LLM calls. v0.1.0 only enforced ``--max-cost`` as a hard kill
switch; v0.2.0 adds a default-on confirmation prompt for TTY users.

The v0.10.0 layout (ADR-0016 clean-up) replaces the two-row plan/narrate
breakdown with five rows: Planning, Orchestrator, Researcher x N, Writer,
and Reviewer — matching the actual v0.9.0+ multi-agent pipeline roles.

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
message via :func:`wiedunflow.cli.output.print_cost_abort`.
"""

from __future__ import annotations

from collections.abc import Callable

import click

from wiedunflow.cli.cost_estimator import CostEstimate
from wiedunflow.cli.output import CostGateRow, render_cost_gate
from wiedunflow.use_cases.errors import CostGateAbortedError

# Re-export so legacy callers importing ``CostGateAbortedError`` from
# :mod:`wiedunflow.cli.cost_gate` keep working. Canonical home is
# :mod:`wiedunflow.use_cases.errors` (ADR-0003 — dependencies point inward).
__all__ = ["CostGateAbortedError", "prompt_cost_gate", "should_skip_prompt"]


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
    confirm_fn: Callable[[str], bool] | None = None,
    plan_model_label: str = "gpt-5.4",
    orchestrator_model_label: str = "gpt-5.4",
    researcher_model_label: str = "gpt-5.4-mini",
    writer_model_label: str = "gpt-5.4",
    reviewer_model_label: str = "gpt-5.4-mini",
) -> bool:
    """Render the cost-gate panel and prompt for confirmation (US-070, US-084).

    Renders a 5-row breakdown -- Planning, Orchestrator, Researcher x N,
    Writer, Reviewer — matching the v0.9.0+ multi-agent pipeline (ADR-0016).

    Args:
        console: Rich console for the panel render.
        estimate: Cost estimate produced by :func:`cost_estimator.estimate`.
        auto_yes: ``--yes`` flag value.
        prompt_disabled: ``--no-cost-prompt`` flag value.
        is_tty: Result of ``stdin.isatty()`` at CLI entry.
        confirm_fn: Optional injected confirm callable (ADR-0013 D#5). The
            menu path passes ``io.confirm`` so the prompt uses questionary;
            CLI path leaves ``None`` and falls back to ``click.confirm``.
            Signature: ``confirm_fn(message: str) -> bool``.
        plan_model_label: Label shown for the Stage-4 planning model.
        orchestrator_model_label: Label shown for the per-lesson orchestrator.
        researcher_model_label: Label shown for the per-lesson researcher.
        writer_model_label: Label shown for the per-lesson writer.
        reviewer_model_label: Label shown for the per-lesson reviewer.

    Returns:
        ``True`` when the run should proceed (bypass condition met or user
        confirmed); ``False`` when the user declined (caller raises
        ``CostGateAbortedError``).
    """
    if should_skip_prompt(auto_yes=auto_yes, prompt_disabled=prompt_disabled, is_tty=is_tty):
        return True

    # Build the 5-row breakdown shown in the table.
    rows = [
        CostGateRow(
            model=plan_model_label,
            stage="Planning (Stage 4)",
            est_tokens=estimate.planning.input_tokens + estimate.planning.output_tokens,
            est_cost_usd=estimate.planning.cost_usd,
        ),
        CostGateRow(
            model=orchestrator_model_label,
            stage="Orchestrator",
            est_tokens=estimate.orchestrator.input_tokens + estimate.orchestrator.output_tokens,
            est_cost_usd=estimate.orchestrator.cost_usd,
        ),
        CostGateRow(
            model=researcher_model_label,
            stage="Researcher x N",
            est_tokens=estimate.researcher.input_tokens + estimate.researcher.output_tokens,
            est_cost_usd=estimate.researcher.cost_usd,
        ),
        CostGateRow(
            model=writer_model_label,
            stage="Writer",
            est_tokens=estimate.writer.input_tokens + estimate.writer.output_tokens,
            est_cost_usd=estimate.writer.cost_usd,
        ),
        CostGateRow(
            model=reviewer_model_label,
            stage="Reviewer",
            est_tokens=estimate.reviewer.input_tokens + estimate.reviewer.output_tokens,
            est_cost_usd=estimate.reviewer.cost_usd,
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
    if confirm_fn is not None:
        return bool(confirm_fn("Proceed?"))
    return click.confirm("Proceed?", default=False)
