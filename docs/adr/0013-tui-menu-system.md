# ADR-0013: Interactive menu-driven TUI ("centrum dowodzenia") for `codeguide`

- **Status**: Accepted
- **Date**: 2026-04-25
- **Deciders**: Michał Kamiński (product owner)
- **Related PRD**: v0.1.2-draft, v0.4.0 sprint plan
- **Supersedes (partial)**: ADR-0011 decision 1 ("CLI direction: Modern only — no heavy TUI")

## Context

CodeGuide v0.2.x was a one-shot CLI: `codeguide init` (5-step Click wizard) and `codeguide generate <repo>` (7-stage pipeline with Rich animations). After UX review on 2026-04-25 the user requested a **menu-driven "command center"** at the entry point — the same pattern shipped by GitHub Copilot CLI, OpenCode, GSD (`Choice [1]:`), and Claude Code's custom-agent picker (numbered list with `↑↓ Enter Esc`). Users of AI tools expect "klikalność" — arrow navigation, Enter, Esc — not memorizing flags.

Two design alternatives were considered and rejected during planning:

1. **Persistent REPL with slash commands** (Claude Code / OpenCode style). Rejected: fragments user attention across the prompt, the scrollback, and a status bar; over-fits a power-user workflow when the primary persona is "developer trying CodeGuide for the first time". Modal sub-wizards dominate the actual work (provider setup, repo picking) — a REPL adds machinery without UX payoff.
2. **Full Textual app** (full-screen takeover). Rejected: kills the scrollback the user wants for the 7-stage pipeline log, requires a separate testing strategy, and disallows the `rich.Live` stage reporter which already shipped in Sprint 8.

The chosen direction — **menu picker (questionary) → sub-wizards → modal pipeline (rich.Live) → return to menu** — keeps the existing pipeline UX and stage_reporter intact while adding a discoverable entry point.

## Decision

**Twelve binary decisions are now final** for v0.4.0:

1. **Hybrid mode**: the menu activates only when `codeguide` is invoked with no arguments AND `sys.stdin.isatty()` AND `sys.stdout.isatty()` AND `CODEGUIDE_NO_MENU` is unset. Every other invocation (`codeguide generate <repo>`, `codeguide init`, `codeguide --version`, non-TTY pipes, `--help`) falls through to the existing Click group bit-exact.
   - Rationale: the Sprint 7 release-gate `pytest -m eval` workflow runs `subprocess.run(["codeguide", "generate", ...])` and depends on the existing exit codes and flag behavior. Breaking that contract would break CI.

2. **questionary 2.x** chosen over InquirerPy (last release 2022, effectively unmaintained) and beaupy (depends on `rich>=12.2` which conflicts with the project's `rich>=13.7` pin and lacks native password/path prompts).
   - Rationale: questionary's only dependency is `prompt_toolkit`, which Click already drags in transitively. Native `select`, `text`, `path`, `password`, `confirm` cover the entire wizard surface. Released August 2025 (active).

3. **Three-sink architecture** (extending Sprint 5's two-sink rule). `rich` lives in `cli/output.py`; `questionary` lives in `cli/menu.py`; plain `print()` lives in `cli/menu_banner.py`. A lint test (`tests/unit/cli/test_no_questionary_outside_menu.py`) enforces the questionary boundary at CI.
   - Rationale: keeps pipeline code (`use_cases/`, `adapters/`) UI-agnostic. Swapping questionary for `textual` or raw `prompt_toolkit` later requires touching only `menu.py`.

4. **Modal pipeline**: `questionary.<prompt>().ask()` returns before `rich.Live` opens. The Generate sub-wizard's §5 Summary screen exits the questionary application, then `_launch_pipeline` constructs the `StageReporter` and runs the existing 7-stage flow. After `✓ done` the menu loop redraws.
   - Rationale: concurrent `prompt_toolkit.Application` + `rich.Live` on the same stdout is undefined behavior on Windows ConPTY; serial execution is safe on every platform.

5. **`MenuIO` Protocol + `FakeMenuIO`** for testing. All questionary calls in `menu.py` go through a `MenuIO` injectable. `QuestionaryMenuIO` is the production impl; `FakeMenuIO` (in `tests/unit/cli/_fake_menu_io.py`) drives prompts deterministically with a queue of pre-supplied responses.
   - Rationale: questionary apps cannot be driven by pytest with `monkeypatch` alone (they wrap a `prompt_toolkit.Application`). The Protocol pattern decouples test setup from library internals — the same pattern as `FakeLLMProvider`.

6. **Esc behavior**: Esc/Ctrl+C from a sub-wizard (`ask()` returns `None`) returns to the parent screen. Esc from the top-level menu prompts a confirm-exit. Esc from the §3 list editor prompts a discard-changes confirm if there are pending edits.
   - Rationale: matches the Claude Code custom-agent picker UX referenced as inspiration. `None` is the universal abort signal — every prompt boundary checks for it.

7. **ADR-0011 decision 1 ("no heavy TUI") explicitly superseded**. v0.4.0 is a conscious product decision that the menu is worth the architectural footprint. Future TUI features (custom keybindings, sidebar pinning, multi-screen navigation) do **not** require a new ADR — they fall under the v0.4.0 regime. A new ADR is required only if the TUI library is replaced or the menu is removed.
   - Rationale: ADR-0011 D#1 was written to prevent speculative TUI complexity, not to block user-validated product features. Reversing decisions when product evidence supports it is healthy.

8. **Generate sub-wizard has 5 sections** (Repo+Output / Provider+Models / Filters / Limits+Audience / Summary), not a linear 14-field flow. Sections 3 and 4 default to "skip" (`Customize? (y/N)` with default N). The §2 express path detects a saved config and offers `Use saved config? (Y/n)` — Yes skips §3 and §4 entirely and jumps to §5.
   - Rationale: most users will run with saved config + just pick a repo. Three keypresses (path, Enter, Enter) reach the cost-aware Summary screen. Power users get the full surface when they want it.

9. **`target_audience` is a Literal 5-level enum** (`noob`, `junior`, `mid`, `senior`, `expert`), default `mid`. **BREAKING CHANGE** in `CodeguideConfig` — previously a free-text `str`. Legacy YAML configs are loaded via a fuzzy-mapping shim in `_load_yaml_flat` (`"mid-level Python developer"` → `mid` with a logged warning). The shim is removed in v1.0.
   - Rationale: 5 levels are needed because the gap between `noob` (Python basics required) and `junior` (knows Python, new to this codebase) is meaningful for narration depth. 3 levels collapse this. The migration shim preserves backward compat through the v1.0 breaking-change window.

10. **v0.4.0 ships with a single shared narration prompt template** for all 5 audience levels. `target_audience` flows into the system prompt preamble and into JSON metadata in the generated HTML, but does not branch the prompt itself.
    - Rationale: shipping 5 untested prompt variants in one sprint is reckless. Per-level prompt branches arrive in v0.5.0 once the 5-level baseline has real usage signal.

11. **Model lists are fetched dynamically from the provider API**, not hardcoded as Pydantic Literals. New port `interfaces/model_catalog.py::ModelCatalog` plus adapters `AnthropicModelCatalog` (via `anthropic.Anthropic().models.list()`) and `OpenAIModelCatalog` (via `openai.OpenAI().models.list()`). OpenAI filter strips `ft:*` (private fine-tunes) and non-chat models (audio, realtime, image, tts, whisper, embedding, moderation, transcribe, dall-e, sora, codex, search, deep-research). 24-hour disk cache via `CachedModelCatalog` decorator at `~/.cache/codeguide/models-<provider>.json`. Hardcoded fallback lists fire only when the API call fails (offline, missing key, rate limit, 5xx).
    - Rationale: model catalogs change monthly; hardcoded enums in v0.4.0 are stale by v0.5.0. SDK `models.list()` is the canonical source of truth. The `ft:*` filter is a privacy guardrail — fine-tuned IDs are user-private and would leak into shared configs/screenshots if surfaced.

12. **OpenAI default model is `gpt-4.1`, not `gpt-4o`**. Affects: `OpenAIModelCatalog._FALLBACK`, `cli/main.py:_build_llm_provider` (openai / openai_compatible / custom branches), `init_wizard` openai defaults, `tutorial.config.yaml.example`. Anthropic defaults unchanged: `claude-sonnet-4-6` (plan), `claude-opus-4-7` (narrate), `claude-haiku-4-5` (cluster/describe).
    - Rationale: project owner preference. `gpt-4.1` has a larger context window, newer training cutoff, and stronger code-understanding than `gpt-4o`, which is a 2024 legacy model in 2026.

## Consequences

**Positive**:
- New users discover features by arrow navigation rather than reading `--help`.
- Saved-config power users get a 3-keystroke Generate flow.
- Model lists stay current without CodeGuide releases.
- Sprint 7 release-gate CI workflow continues to work unchanged.

**Negative / costs**:
- New `questionary>=2.1.1,<3.0` dependency (single-dep transitive footprint via prompt_toolkit which Click already pulls).
- `target_audience` migration shim adds ~30 lines to `_load_yaml_flat` until v1.0.
- ADR-0011 D#1 is partially superseded — anyone reviewing the ADR history must read both documents to understand the current CLI direction.

**Migration impact**:
- No CLI flag changes. No exit-code changes. Eval workflow continues to work without modification.
- Old YAML `target_audience: "mid-level Python developer"` loads as `mid` with a single warning log line.
- Bytecode pipelines that read `~/.cache/codeguide/models-*.json` files will see new 24-hour cache entries — the directory was previously empty for model lists.

## Future work

- v0.5.0: per-level narration prompt branches (5 variants).
- v0.5.0: edit-section jumpback in §5 Summary (Cancel/Launch is the v0.4.0 minimum).
- v0.5.0: optional "Quick Generate (saved config)" top-level menu item if usage data shows the in-§2 express path is buried.
- v0.5.0+: stale-cache warning banner when `~/.cache/codeguide/models-*.json` is older than 24h and a refetch is in flight.
