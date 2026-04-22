# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Phase 1 stub for ``codeguide init`` (US-002 / US-003).

The Track A agent replaces this with the full interactive wizard. The stub
is kept minimal so Phase 1 CI stays green: calling ``codeguide init`` now
echoes a clear "not yet implemented" notice and exits non-zero.
"""

from __future__ import annotations

import click


def run_init_wizard(
    *,
    provider: str | None = None,
    model_plan: str | None = None,
    model_narrate: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    force: bool = False,
) -> int:
    """Run the interactive (or non-interactive) first-run wizard.

    Arguments are the US-003 skip-wizard flags (all optional). Returns a
    process exit code.

    This is a Phase 1 stub. Track A will replace the body with real prompts,
    YAML writing via :func:`codeguide.cli.config.user_config_path`, and
    validation through ``CodeguideConfig``.
    """
    # Arguments are accepted so the CLI signature is stable; acknowledge them
    # to keep static analysers quiet until Track A replaces the body.
    del provider, model_plan, model_narrate, api_key, base_url, force
    click.echo(
        "codeguide init: not yet implemented (Sprint 6 Track A). "
        "Configure ~/.config/codeguide/config.yaml manually for now.",
        err=True,
    )
    return 1
