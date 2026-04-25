# Changelog

All notable changes to CodeGuide are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.4.0] - 2026-04-25 — Interactive Menu-Driven TUI ("centrum dowodzenia")

### Added
- **Interactive top-level menu** when `codeguide` is invoked with no arguments
  in a TTY. ASCII welcome banner + 7-item picker with arrow navigation
  (`↑↓ Enter Esc`): `Initialize config`, `Generate tutorial`, `Show config`,
  `Estimate cost`, `Resume last run`, `Help`, `Exit`. Inspired by GitHub
  Copilot CLI, OpenCode, and Claude Code's custom-agent picker. The
  established `codeguide generate <repo>` and `codeguide init` CLI
  invocations are unchanged — Sprint 7 release-gate CI is unaffected.
- **Generate sub-wizard with 5 sections**: §1 Repo+Output, §2 Provider+Models
  (with **express path** that auto-fills from saved config and skips §3-§4),
  §3 File Filters (optional, dynamic add/edit/remove list manager),
  §4 Limits & Audience (optional, with the new 5-level audience enum),
  §5 Summary & Launch (file-count cost heuristic + Cancel/Launch). After
  Launch the existing `rich.Live` 7-stage pipeline takes over the terminal;
  on completion the menu loop redraws.
- **`ModelCatalog` port + dynamic model fetch** (ADR-0013 D#11). The
  Provider+Models section pulls live model lists from
  `anthropic.Anthropic().models.list()` and `openai.OpenAI().models.list()`
  with 24-hour disk cache at `~/.cache/codeguide/models-<provider>.json`.
  OpenAI filter strips `ft:*` (private fine-tunes) and non-chat models
  (audio, realtime, image, tts, whisper, embedding, moderation, transcribe,
  dall-e, sora, codex, search, deep-research). Hardcoded fallbacks fire
  only when the API call fails (offline, missing key, rate limit, 5xx).
  New menu entry `[r] Refresh now` bypasses the cache.
- **`SQLiteCache.has_checkpoint(repo_abs)`** — fast presence check used by
  the menu's `Resume last run` action to surface "no checkpoint found"
  before launching the resume flow.
- **`render_generate_summary` / `render_info_panel`** in `cli/output.py` —
  Rich panels for the Generate sub-wizard §5 review and the menu's
  `Show config` / `Estimate cost` / `Help` views.
- **Three-sink architecture** (extending Sprint 5's two-sink rule). New
  lint test `tests/unit/cli/test_no_questionary_outside_menu.py` enforces
  that `import questionary` lives only in `cli/menu.py`.
- **Emergency escape hatch** — `CODEGUIDE_NO_MENU=1` env var disables
  the menu even in a TTY. For scripts that want bare `codeguide` to be
  a no-op without bumping the subcommand into argv.

### BREAKING (perceptual, pre-1.0)
- **`target_audience` is now a Literal 5-level enum**: `noob`, `junior`,
  `mid`, `senior`, `expert` (default `mid`). Previously a free-text `str`
  field defaulting to `"mid-level Python developer"`. Existing YAML
  configs continue to load via a fuzzy-mapping shim in `_load_yaml_flat`
  (`"mid-level Python developer"` → `mid` with a logged warning;
  `"senior engineer"` → `senior`; etc.). The shim is removed in v1.0.
  Per-level narration prompt branches arrive in v0.5.0; v0.4.0 ships a
  shared template that flows audience into the system preamble and HTML
  metadata.
- **OpenAI defaults switched from `gpt-4o` to `gpt-4.1`** (ADR-0013 D#12).
  Affects: `OpenAIModelCatalog._FALLBACK`, `cli/main.py:_build_llm_provider`
  (openai / openai_compatible / custom branches), `tutorial.config.yaml.example`.
  Anthropic defaults unchanged. CLI users with `--model-plan gpt-4o` or YAML
  `model_plan: gpt-4o` keep their explicit selection — only the implicit
  fallback path changes.

### Changed
- `prompt_cost_gate(...)` accepts a new optional `confirm_fn:
  Callable[[str], bool] | None` parameter. When `None` (CLI path),
  the prompt falls back to `click.confirm`; when set (menu path), the
  injected callable replaces the prompt — used by the menu to drive the
  cost gate via `MenuIO.confirm` (questionary).
- `cli/main.py:main()` gains a 3-line guard before delegating to the Click
  group: bare `codeguide` in a TTY launches `main_menu_loop`. All other
  invocations flow through the existing Click dispatcher.

### Internal
- New ADR-0013 ("Interactive menu-driven TUI") captures the 12 binary
  decisions for the menu surface. Partially supersedes ADR-0011 D#1
  ("no heavy TUI"). Reasons documented inline.
- New port `interfaces/model_catalog.py::ModelCatalog`. New adapters:
  `adapters/anthropic_model_catalog.py`, `adapters/openai_model_catalog.py`,
  `adapters/cached_model_catalog.py` (24h TTL decorator).
- New CLI modules: `cli/menu.py` (~900 lines, single questionary sink),
  `cli/menu_banner.py` (ASCII art only).
- New test fixtures: `tests/unit/cli/_fake_menu_io.py` (deterministic
  `MenuIO` test double for sub-wizard testing).
- New tests: `test_no_questionary_outside_menu.py`, `test_should_launch_menu.py`,
  `test_menu_loop.py`, `test_config_target_audience_migration.py`,
  `test_anthropic_model_catalog.py`, `test_openai_model_catalog.py`,
  `test_cached_model_catalog.py`, `test_generate_subwizard.py`,
  `test_filters_subwizard.py`, `test_limits_summary_subwizard.py`,
  `test_menu_remaining_actions.py` — ~190 new test cases total.

## [0.3.0] - 2026-04-25 — Tutorial Quality Enforcement

### Fixed
- **Hallucinated function signatures** in narration prompts. The narration LLM
  previously received only `{symbol, file, line_start, line_end, role}` per
  code reference and had to guess function bodies — this produced fabricated
  signatures (e.g. `load_json_content` → `return json.loads(content)` instead
  of the actual `return {"content": content, "file_path": None}`, and
  `write_markdown_file("README.md", "...")` with reversed parameter order).
  Now `code_refs` carry an optional `source_excerpt` field populated from the
  AST snapshot for any primary reference shorter than 30 lines, and the
  narration prompt requires verbatim signature quoting from `source_excerpt`.
  A post-narration snippet validator parses ```python fenced blocks, matches
  signatures against `source_excerpt`, and triggers a 1-shot retry on
  mismatch (`use_cases/snippet_validator.py`, gated by
  `narration.snippet_validation`).
- **Tutorial metadata `total_lessons` mismatch** — the count emitted in
  `tutorial-meta` no longer drifts from the actual rendered lesson count
  after skip-trivial filtering or post-planning reordering.

### Added
- **Happy-path lesson ordering**. New heuristic moves the entry-point lesson
  (detected via `def main`/`def cli`/`def run_*`, `if __name__ == "__main__":`
  blocks, `@click.command`/`@app.command` decorators, or `__main__.py` modules)
  to position 1, preserves leaves→roots flow for lessons 2..N-2, top-level
  orchestration at N-1, closing lesson at N. Configurable via
  `planning.entry_point_first: auto|always|never` (default `auto`;
  `auto` is a no-op when no entry point is detected). The planning prompt
  was updated symmetrically in both Anthropic and OpenAI adapters
  (`use_cases/entry_point_detector.py`, `use_cases/plan_lesson_manifest.py`).
- **Per-tier word-count floors for narration**. Replaces the hardcoded
  150-word minimum that forced verbose, watered-down narration for one-line
  helpers. New floors: 1-line span = 50 (configurable via
  `narration.min_words_trivial`), 2–9 lines = 80, 10–30 lines = 220, >30
  lines = 350 (`use_cases/grounding_retry.py`).
- **Skip-trivial helpers**. Optional pass that drops lessons whose primary
  reference is <3 lines AND not cited as primary in any other lesson AND not
  an entry point AND not in the top 5% by PageRank. Skipped helpers are
  rolled up into a "Helper functions you'll see along the way" appendix on
  the closing lesson. Enable with `planning.skip_trivial_helpers: true`
  (`use_cases/skip_trivial.py`).
- **Standalone "Project README" lesson** appended to the TOC when the repo
  ships a README. The narration column carries a one-line pointer; the right
  pane (normally the code reference) is replaced with the rendered README so
  the reader treats it as reference reading rather than a primary lesson.
- **Single-column layout for the closing lesson.** "Where to go next" no
  longer leaves an empty code panel — the right pane and the splitter
  collapse so the closing narrative spans the full content row. Toggled via
  ``Lesson.layout = "single"`` (renderer adds the ``layout-single`` class).
- **Lesson progress UI in the generated tutorial.html**:
  - Thin (4 px) horizontal progress bar pinned under the topbar that fills
    as the reader advances through lessons.
  - Textual chip "Lesson N / M" inside the topbar nav-group (already-present
    `#tutorial-progress-label` element, ADR-0009 freeze respected).
  - Sidebar TOC checkmarks marking visited lessons. A lesson is marked as
    visited after 5 s of attention OR an explicit Next click. State is
    persisted across sessions via
    `localStorage["codeguide:<repo>:visited-lessons:v1"]` and gracefully
    degrades in private-mode browsers.
- **Four new opt-in config keys** in `tutorial.config.yaml`:
  `planning.entry_point_first`, `planning.skip_trivial_helpers`,
  `narration.min_words_trivial`, `narration.snippet_validation`. All
  defaults preserve v0.2.0 behaviour.

### Changed
- `LessonManifest.code_refs[*]` gained an additive optional field
  `source_excerpt: str | None` (max 4000 chars). Schema version remains
  1.0.0 — older cache JSON deserialises without migration. ADR-0007 was
  updated to document the additive change.
- `Lesson` entity gained additive optional fields ``layout`` (``"split"`` /
  ``"single"``) and ``code_panel_html`` (pre-rendered HTML for the right
  pane), used by the new standalone README lesson and single-column closing.
- Footer documentation-coverage label is now ``Docs N%`` (was ``Jedi N%``).
  The metric measures the share of symbols with a non-empty docstring;
  the previous label confusingly suggested it was a Jedi-resolution rate.

### Internal
- New use-case modules: `inject_source_excerpts.py`, `snippet_validator.py`,
  `entry_point_detector.py`, `skip_trivial.py`. Symmetric updates to
  `adapters/anthropic_provider.py` and `adapters/openai_provider.py`
  prompt templates.
- New ADR-0012 ("Tutorial quality enforcement") captures the binary
  decisions for source-excerpt injection, post-hoc snippet validation,
  per-tier word-count floors, and skip-trivial heuristics.
- Test suite expanded: `test_snippet_validator.py`,
  `test_entry_point_detector.py`, `test_skip_trivial.py`, extensions to
  `test_grounding_retry.py` and `test_plan_lesson_manifest.py`,
  Playwright coverage for progress bar UI under
  `tests/unit/renderer/test_progress_bar.py`.

## [0.2.0] - 2026-04-25 — Animated CLI + Cost Gate Prompt (Sprint 8)

### BREAKING (perceptual, pre-1.0)
- **Cost-gate prompt is now ON by default for TTY users.** Before Stage 5
  (Planning) finalises the manifest, the CLI shows the estimated cost panel
  and asks `Proceed? [y/N]`. Declining aborts cleanly with exit code `0` and
  no API calls. Non-TTY callers (CI, pipes, redirect) auto-confirm — no
  pipeline change required. Power users running interactively can pass
  `--no-cost-prompt` to skip the prompt without bypassing the consent banner.
  v0.1.0 only enforced `--max-cost` as a hard kill switch; that flag is
  unchanged and still raises `MaxCostExceededError` independently of the
  prompt (US-070, US-084).

### Added
- **Animated stage progress** (`src/codeguide/cli/stage_reporter.py`).
  `StageReporter` is now wired into `generate_tutorial()` and renders one
  header per stage (`[N/7] <Name>`) plus a `✓ done · <summary>` line at the
  end of each stage. New methods drive a stateful `rich.live.Live` region:
  - `progress_line(text)` — replace-line update for mass-scan stages
    (Stage 2 Analysis: `parsing AST + resolving call graph for N files`).
  - `lesson_event(idx, total, title)` — append-only scrolling event log for
    Stage 6 Generation (each narrated lesson stays in the transcript).
  - `tick_counters(tokens_in, tokens_out, cost_usd, elapsed_s)` — running
    counters footer (US-083).
  - `NoOpReporter` null-object sentinel for headless callers
    (`--log-format=json`, library use, tests) (US-081, US-082).
- **Startup banner** (`render_banner()` in `cli/output.py`). Printed before
  preflight on TTY runs, suppressed on non-TTY and `--log-format=json`.
  Format: `CodeGuide vX.Y.Z` plus tagline (US-086).
- **Run-report card** at every exit path. The v0.1.0 one-liner
  `Tutorial written to: …` is replaced with a `rich.panel.Panel` card
  showing `lessons / retries / elapsed / output` rows (or `failed at /
  reason` for error paths). Mirrors the spec'd `✓ success` / `⚠ degraded`
  / `✗ failed` headers from `.ai/ux-spec.md §4.8` (US-085).
- **`cli/cost_gate.py`** — `prompt_cost_gate()` + `should_skip_prompt()` +
  `CostGateAbortedError`. Bypass conditions: `--yes`, `--no-cost-prompt`,
  `not stdin.isatty()`. Caller in `_run_pipeline` translates the abort to
  exit `0` and prints the spec abort line via `print_cost_abort()`.
- **`--no-cost-prompt` flag** for `codeguide generate` — skips the
  interactive cost prompt without auto-confirming the consent banner.
- **`generate_tutorial()` API** gained two optional parameters:
  - `progress: StageReporter | NoOpReporter | None` — receives stage
    lifecycle events. Defaults to `NoOpReporter` so existing library
    callers and tests keep working.
  - `cost_gate_callback: Callable[[CostEstimate], bool] | None` —
    invoked after Stage 5 with the cost estimate; returning `False`
    raises `CostGateAbortedError`.
- 28 new unit tests under `tests/unit/cli/`:
  `test_stage_reporter_animations.py` (12), `test_cost_gate_prompt.py` (12),
  `test_banner.py` (4).

### Changed
- `_run_pipeline()` now creates a `StageReporter` (or skips it for JSON
  mode), builds a `_cost_gate` closure, and threads both through
  `generate_tutorial()`. All four exit paths (success, degraded, failed,
  interrupted, cost-gate-abort) render via `render_run_report()` /
  `print_cost_abort()` instead of plain `click.echo`.
- Stage names in `stage_reporter._STAGE_NAMES` aligned with the actual
  pipeline (Ingestion, Analysis, Graph, RAG, Planning, Generation, Build).
  `.ai/ux-spec.md §4.5` still describes a wishful v0.5+ pipeline with
  separate clustering / outlining / narration / grounding stages;
  reconciliation tracked for a future sprint.
- `init_console()` now reconfigures `sys.stdout` to UTF-8 (errors=replace)
  on Windows code pages — fixes `UnicodeEncodeError` when printing
  `✓` / `─` / `┏` glyphs in PowerShell with cp1250/cp1252 default.
- `pyproject.toml` and `__init__.py` version 0.1.0 → 0.2.0.

### Fixed (renderer follow-up)
- **Independent per-panel scroll** in `tutorial.html`. The narration column
  and code panel are now bounded by the viewport (`#tutorial-content`
  uses `height` + `overflow: hidden`, replacing the v0.1.0 `min-height` that
  let the grid grow with content). Each child has its own
  `overflow-y: auto`, so scrolling one panel no longer drags the other.
- **Disabled cross-panel scroll sync** (`tutorial.js:initScrollSync`).
  Earlier behaviour mirrored narration scroll into the code panel; users
  found it disorienting. Function is kept as a placeholder for a future
  opt-in toggle.
- **Higher-contrast Pygments highlighting**. Added `tok-builtin`,
  `tok-deco`, `tok-op` token classes (previously folded into `tok-cls` /
  `tok-fn`), bumped chroma from 0.13–0.16 to 0.18–0.22 (light) / 0.16–0.18
  (dark), added `font-weight: 500` to function and class tokens so they
  visually separate from body text. `Token.Name.Builtin.Pseudo`
  (`self`, `cls`, `True`, `False`, `None`) gets its own color.
- **Narration block-level CSS hierarchy.** Added rules for
  `#tutorial-narration .prose h2 / h3 / h4 / blockquote / pre / hr / a /
  table / strong`. Pre-fix the LLM's `## Subheading` and `> **Note:** …`
  Markdown rendered at browser defaults (tiny H2, no blockquote border),
  making lessons feel like notepad output.
- **Updated narration prompt** in both `AnthropicProvider` and
  `OpenAIProvider` to instruct the LLM to use `## / ###` subheadings,
  `> **Note:** / **Tip:** / **Warning:**` callout blockquotes, and
  fenced ```python``` example blocks. Existing tutorials must be
  regenerated to benefit from the richer Markdown structure.

### Added (continued)
- **`--output PATH` / `-o PATH`** flag for `codeguide generate`. Override
  the tutorial output filename / location. Relative paths resolve against
  cwd; absolute paths are used verbatim. Default remains `./tutorial.html`.
- **`output_path:` field** in `tutorial.config.yaml` (top-level). CLI
  flag wins; YAML provides per-project default. 9 new tests in
  `tests/unit/cli/test_output_path_config.py`.

### Sprint 8 follow-up (deferred to Sprint 9)
- Interactive repo picker (`codeguide` without arguments in TTY launches a
  questionary-based picker). Plan in `~/.claude/plans/`.

## [0.1.0] - 2026-04-24 — Release Candidate + Release Gate (Sprint 7)

### Added
- Full eval corpus pinned as git submodules (5 repos: requests, click, starlette, MCP Python SDK, dateutil) — `tests/eval/corpus/repos/`.
- `tests/eval/test_release_gate.py` — release-gate suite gated by `pytest -m eval` (US-064, US-065).
- `hallucinated_symbols_count` and `hallucinated_symbols` fields in `run-report.json` (backward-compatible addition per ADR-0009).
- `docs/rubric/RUBRIC.md` + `docs/rubric/v0.1.0/` — rubric scoring template, reviewer kit, author + 2 trusted-friends sign-off archive (US-066, FR-76).
- `scripts/aggregate_rubric.py` — rubric gate enforcement (exit 1 if avg <3.0 or <3 reviewers).
- `tests/eval/configs/*.yaml` — per-repo model routing overrides (MCP → Opus-4-7, others → Sonnet-4-6).
- Release workflow: `uv build` → sdist + wheel uploaded as GitHub Release assets (US-062, US-067).
- `.github/release-notes-template.md` — structured release notes placeholder.

### Changed
- PRD `.ai/prd.md` 0.1.2-draft → 0.1.0 (MVP specification locked; subsequent changes bump to 0.1.1-draft).
- Tech stack `.ai/tech-stack.md` 0.1.2-draft → 0.1.0 (aligned with product version).
- `pyproject.toml` version 0.0.6 → 0.1.0.
- Release workflow: NOTICE check promoted from soft warning to hard gate (US-062).
- CI matrix: `fail-fast: false`, `timeout-minutes: 15` per job.

### Security
- `pip-audit` runs on every tag push and blocks release on HIGH+ unfixed vulnerabilities (US-067).
- NOTICE auto-aggregation gate enforces Apache-2.0 dependency attribution at release time (US-062).

### Migration notes
- Install: `uv pip install git+https://github.com/numikel/codeguide@v0.1.0` (no PyPI publish in MVP per FR-03; see roadmap for v0.2.0).
- Existing `run-report.json` consumers: new fields are additive. Schema version remains 1.0.0.

## [0.0.6] - 2026-04-24 — Privacy + Config + Hardening (Sprint 6)

### BREAKING
- **First cloud-provider run now blocks on a persistent consent banner.** Previous versions cached acceptance only for the current process; Sprint 6 persists it in `<user_config_dir>/codeguide/consent.yaml` per provider (US-005 / US-007). CI pipelines that previously relied on a silent first run must now pass `--no-consent-prompt` or pre-provision the `consent.yaml` file. Acceptance is still one-time per provider per machine.
- **Hard-refuse secret list silently excludes `.env*`, `*.pem`, `id_rsa`, `id_ed25519`, `*_rsa`, `*_rsa.pub`, `*_ed25519`, `credentials.*` from ingestion before `.gitignore` and before `--include`/`--exclude` patterns** (US-008). Tutorials for repos that previously indexed those files will have strictly fewer files in the AST snapshot. Project-level opt-in for a specific filename via `tutorial.config.yaml`:
  ```yaml
  security:
    allow_secret_files: [".env.example"]
  ```
- **Log output is redacted by default.** API-key-shaped substrings (Anthropic `sk-ant-...`, OpenAI `sk-...` / `sk-proj-...`, HuggingFace `hf_...`, generic `Bearer ...`, `Authorization: ...` headers, 40+ char hex blobs) are replaced with `[REDACTED]` before hitting the log sink (US-069). The `--no-log-redaction` flag exists as a dev escape hatch but is **hidden from `--help`**.

### Added
- **`codeguide init` wizard** — interactive first-run setup that writes the nested-YAML user-level `config.yaml` (`~/.config/codeguide/config.yaml` Linux/macOS, `%APPDATA%\codeguide\config.yaml` Windows). All prompts skip on matching flags (`--provider`, `--model-plan`, `--model-narrate`, `--api-key`, `--base-url`). `--force` overwrites an existing file; otherwise the wizard refuses. File permissions set to `0o600` on POSIX (US-002, US-003).
- **CLI restructured to a click group.** Subcommands `codeguide init` and `codeguide generate <repo>` replace the previous single command. `codeguide <repo>` still works as an alias — a custom `_DefaultToGenerate` class rewrites an unrecognised first positional to `generate <positional>`.
- **Consent persistence** (`src/codeguide/adapters/yaml_consent_store.py`) — per-provider state keyed by `granted` / `granted_at` timestamps. Implements the new `ConsentStore` port (`interfaces/consent_store.py`). File is written with `0o600` (POSIX) (US-007).
- **Exact banner copy** per PRD contract: `"Your source code will be sent to <provider>. Continue? [y/N]"`. Rewrite of `cli/consent.py` keeps backward compat for `_reset_for_tests()` through a module-level cell pattern.
- **Config precedence chain formalised** (US-004) — six layers (CLI > env > `--config` YAML > `./tutorial.config.yaml` > user-level config > built-in defaults) covered by `tests/integration/test_config_precedence.py` (8 boundary tests). DEBUG log emits `config resolved: <key>=<value> from <source>` per field when `--log-format=json`.
- **Hard-refuse secret list** (`src/codeguide/ingestion/secret_blocklist.py`, `ingestion/file_filter.py`) — 9 patterns, evaluated before `.gitignore`. Integrated into `use_cases/ingestion.py::_collect_files` through a new `should_include_file()` gate (US-008).
- **Zero-telemetry integration test** (`tests/integration/test_zero_telemetry.py`) — dual-layer verification: Linux-only netns (`pytest.mark.netns`, requires user namespaces) plus cross-platform `pytest-socket` disabling. Tutorial HTML carries the exact offline-guarantee footer `"Generated by CodeGuide vX.Y.Z (Apache 2.0) — this document is fully offline."` (US-011).
- **SecretFilter** (`src/codeguide/cli/secret_filter.py`) — authoritative pattern list (7 regexes) + `redact_path()` helper replacing absolute paths outside the repo with `"<external>"` + `truncate_source()` returning `"<hash>:<symbol>"` references instead of embedding raw source bodies in logs (US-069 AC3/AC4).
- **Editor resolver hardening** (`src/codeguide/cli/editor_resolver.py`) — `$EDITOR`/`$VISUAL` values are validated through `shlex.split` + `shutil.which` + a metacharacter deny-list (`;`, `|`, `&&`, `||`, backtick, `$(`, `>&`) before `subprocess.run(..., shell=False)`. Malicious values fall through to the next candidate (US-068).
- **`scripts/aggregate_notice.py`** — enumerates Apache-2.0 runtime dependencies via `importlib.metadata`, aggregates their embedded `NOTICE` files into the project `NOTICE` with the `Copyright 2026 Michał Kamiński` header. `--check` mode exits 1 when NOTICE is out of date (release gate) (US-062).
- **`.github/workflows/release.yml`** — tag-push triggered (`v*.*.*`) + manual dispatch. Runs pip-audit against OSV (`--vulnerability-service osv`), parses JSON output, fails release when any vulnerability has no fix version (heuristic for HIGH+). Vulnerabilities with a fix available emit warning only (US-067). NOTICE check runs in a separate job.
- **CONTRIBUTING.md DCO section** — `git commit -s` requirement surfaced above `Development Setup` with developercertificate.org link and the GitHub Action context (US-060).
- **ADR-0010** — Secret redaction + zero-telemetry contract (7 binary decisions: pattern-only redaction, structlog processor scope, consent storage location, consent granularity, hard-refuse pattern list, dual-layer zero-telemetry test, editor validation strategy).
- **Port interfaces** — `interfaces/consent_store.py`, `interfaces/secret_filter.py` — enable Clean Architecture swap-in of alternative stores / filters for tests and future deployments.
- **Dev deps**: `pytest-socket>=0.7` (cross-platform zero-telemetry test), `pip-audit>=2.7` (release-gate CVE scan).
- **Pytest markers**: `netns` (Linux-only zero-telemetry namespace test).
- **Documentation** — `README.md` new `## Configuration precedence` table; `docs/config-precedence.md` ASCII flow diagram + field reference.

### Changed
- `src/codeguide/cli/main.py` restructured from single `@click.command` to `@click.group` with `init` + `generate` subcommands. Integration tests updated to import `cli` (group) instead of `main` (function).
- `src/codeguide/cli/consent.py` rewritten — `_NullConsentStore` in-process cell keeps `_reset_for_tests()` backward-compatible for S3/S5 tests.
- `src/codeguide/cli/config.py` gains `security_allow_secret_files: frozenset[str]` field with `security.allow_secret_files` YAML mapping. DEBUG log lines added per resolved field.
- `src/codeguide/use_cases/ingestion.py` gains an optional `security_allow_secret_files` parameter plumbed from `CodeguideConfig`. `_collect_files` now routes every candidate through `should_include_file()` so the blocklist check runs before `.gitignore`.
- **`codeguide` version string** bumped from `0.0.5` → `0.0.6` (`pyproject.toml` + `src/codeguide/__init__.py`).

### Security
- API-key-shaped substrings redacted from all log output by default (US-069).
- Editor resolver rejects 13+ attack vectors including command chaining, pipes, backticks, command substitution, redirections, and unbalanced quotes (US-068).
- DCO trailer enforced on every PR via `.github/workflows/dco.yml` + CONTRIBUTING.md documentation (US-060).
- Release workflow blocks on HIGH+ CVE advisories via pip-audit OSV (US-067).

### Migration notes
- **CI users**: add `--no-consent-prompt` to any `codeguide` invocation in scripts, or pre-create `~/.config/codeguide/consent.yaml` with the relevant providers set to `{granted: true, granted_at: <ISO>}`.
- **Repos with `.env.example` / dotenv docs**: add
  ```yaml
  security:
    allow_secret_files: [".env.example"]
  ```
  to `tutorial.config.yaml` to keep them in ingestion.
- **Golden-file / snapshot tests** that assert log strings: update expectations to account for `[REDACTED]` replacements, or disable redaction in the test via `--no-log-redaction`.

## [0.0.5] - 2026-04-21 — Output HTML + Run modes + Reporting (Sprint 5)

### Added
- **Pixel-perfect tutorial template** (`src/codeguide/renderer/templates/tutorial.html.j2` + `tutorial.css`) — A1 Paper palette light + dark, Inter body font, JetBrains Mono code, Direction A three-column layout (topbar 52 px, sidebar 280 px, narration, splitter 28–72 %, code panel) honouring ADR-0011. Replaces the Sprint 1 walking-skeleton template (US-075).
- **Vanilla JS navigation** (`tutorial.js`, no framework, no bundler) — clustered TOC click + IntersectionObserver highlight (US-043), hash routing `#/lesson/<id>` with fallback + console.warn on unknown ids (US-044), ArrowLeft/ArrowRight navigation with boundary no-op and input-focus guard (US-045), `codeguide:<repo>:last-lesson` localStorage persistence (US-046), `schema_version` mismatch warning (US-048), Pointer Events splitter drag clamped to 28–72 % stored in `codeguide:tweak:narr-frac:v2` (US-076), Tweaks panel with light/dark theme toggle persisted in `codeguide:tweak:theme:v2` (US-077). Jednokierunkowy scroll-sync (narration → code) per Sprint 5 decision #3.
- **Interleaved mobile layout** (`<1024 px`) — `matchMedia('(min-width:1024px)')` switches between desktop split-view and stacked interleaved paragraph → code rendering (US-042, decision #5).
- **Confidence pill** (HIGH/MEDIUM/LOW) styled with dedicated oklch tiers in `tokens.css` (US-080).
- **Degraded banner** inserted at the top of the HTML when `run_status == "degraded"` (US-079).
- **Skipped-lesson placeholder** with dashed border + hatching background + SKIPPED pill rendered inline when `lesson.status == "skipped"` (US-078).
- **Offline-guarantee footer** statement: "Generated by CodeGuide vX.Y.Z (Apache 2.0) — this document is fully offline." + `branch@sha` + `generated_at` + Jedi coverage badge (US-047).
- **`CodeGuideHtmlFormatter`** (`adapters.pygments_highlighter`) — custom `HtmlFormatter` subclass mapping Pygments token types to `.tok-kw/.tok-str/.tok-com/.tok-fn/.tok-cls/.tok-num` CSS classes (decision #4). Replaces the Sprint 1 inline-style Pygments output (US-058).
- **Inline WOFF2 fonts** — `adapters.jinja_renderer._load_tokens_css_with_inline_fonts()` replaces every `url("../fonts/*.woff2")` in `tokens.css` with a `data:font/woff2;base64,...` URI so the rendered HTML ships offline in a single file (US-040).
- **Output schema v1.0.0** (ADR-0009) — three separate JSON payloads (`#tutorial-meta`, `#tutorial-clusters`, `#tutorial-lessons`) embedded as `<script type="application/json">`. Envelope carries `schema_version`, `codeguide_version`, `repo`, `sha`, `branch`, `generated_at`, `run_status`, plus per-lesson `segments[]` with optional `code_ref` for the structured-narration path. Forward-compat policy: unknown versions emit `console.warn` and best-effort render (US-048).
- **`NarrationSegment` + `CodeRef`** entities (`entities.lesson`) — structured narration stream with `kind: "p" | "code"` + optional `code_ref` (file, lang, lines, highlight). Desktop renders `code_ref`-carrying segments in the sticky code panel; mobile interleaves them inline per decision #5.
- **`Lesson.confidence`** field (`HIGH` | `MEDIUM` | `LOW`, default `MEDIUM`) drives the confidence pill in the meta row (US-080).
- **`html_external_deps_linter.assert_no_external_refs`** (`adapters.html_external_deps_linter`) — regex battery rejecting external `<script src>`, `<link href>`, `<img src>`, `@import url()`, `fetch(`, `XMLHttpRequest`, prefetch/preconnect hints, and dynamic `import('https://...')`. Data URIs remain allowed (US-040).
- **`html_size_validator.validate_size`** (`adapters.html_size_validator`) — three-tier verdict (`ok` / `over_soft_budget` @ > 8 MB / `over_hard_budget` @ > 20 MB). Soft-budget warning is mandatory, hard-budget line is a pre-release regression gate (US-050).
- **`cli/output.py`** — Rich-based user-facing sink (decision #6). Exposes `init_console(json_mode, legacy_windows=False)`, `make_theme()` with the 8-role palette (default/dim/good/warn/err/accent/link/prompt — US-074), boxed cost-gate panel via `rich.panel.Panel.fit(box=HEAVY)` (US-070), framed run-report card with status-coloured border (US-072), 5-space-indented stage detail/done lines (US-071), HTTP 429 backoff display with `attempt K/5` counter (US-073), and OSC 8 hyperlink helper for `file://` links (US-055).
- **`cli/logging.py`** — structlog JSON sink (decision #6) configurable via `--log-format={text,json}`. Every event carries `ts`, `level`, `stage`, `msg` at minimum; renames structlog `event`→`msg` and `timestamp`→`ts` per ux-spec contract (US-022).
- **`cli/cost_estimator.py`** — heuristic `(symbols × 500 × haiku_price + lessons × 8000 × sonnet_price) × 1.3` returning per-model token/cost breakdown plus a runtime window in minutes. Feeds the cost gate (US-012).
- **`cli/stage_reporter.py`** — 7-stage reporter (`[N/7] <Name>` headers, 5-space indented detail lines, `✓ done · <summary>` completion) with the exact stage names from `.ai/ux-spec.md §CLI.stages` (US-071).
- **`cli/editor_resolver.py`** — `$EDITOR → $VISUAL → code --wait → notepad` (Windows) / `vi` (Unix). Drives `--review-plan` editor launching (US-016).
- **`cli/history_rotator.py`** — copies each `run-report.json` into `<repo>/.codeguide/history/run-report-<ISO>Z.json` and prunes to `keep_latest=10`. Filenames use microsecond-precision ISO-8601 so rapid successive runs stay monotonic (US-058).
- **CLI flags** on `codeguide`: `--dry-run` (scaffolded — stages 5-7 will be short-circuited in the Phase 4 generation wiring, US-015), `--review-plan` (scaffolded, US-016), `--log-format={text,json}` (live on stderr, US-022).
- **`ensure_gitignore_entry`** (`cli.main`) — idempotent `.codeguide/` append on every run, creates `.gitignore` when absent (US-057).
- **`rotate_run_report_history`** (`cli.main`) — bridges the CLI into the history rotator; failure is logged at `warning` and never blocks the pipeline (US-058).
- **ADR-0009** — Output JSON schema v1.0.0 with DOM-ID contract, JS namespace (`window.CodeGuide.init()` / `_errors`), localStorage keys, and forward-compat strategy.
- **Sprint 5 test suites (Track A + B + C)**:
  - `tests/unit/cli/` — `test_output_color_roles`, `test_logging_json_format`, `test_no_rich_outside_output` (decision #6 lint), `test_cost_estimator`, `test_cost_gate_panel`, `test_run_card_rendering`, `test_osc8_hyperlink`, `test_editor_resolver`, `test_history_rotation`, `test_gitignore_append`.
  - `tests/unit/adapters/` — `test_html_external_deps_linter`, `test_html_size_validator`, `test_pygments_noclasses` (retargeted at `.tok-*` output).
  - `tests/unit/entities/` — `test_narration_segments`.
  - `tests/integration/test_track_c_navigation.py` — 9 Playwright tests covering US-041/042/043/044/045/046/048/076/077 on file:// with network routing blocked.
  - Updated `tests/integration/test_walking_skeleton.py`, `test_html_file_url.py`, `test_generate_tutorial_stages.py`, `test_closing_lesson.py` to the ADR-0009 envelope and keyboard-driven navigation.

### Changed
- **`tutorial_minimal.html.j2`** is retired in favour of `tutorial.html.j2`; the `JinjaRenderer.render()` signature is now keyword-only for every non-positional argument and accepts optional `clusters` metadata.
- **Pygments output** no longer uses `noclasses=True` — spans now carry `class="tok-*"` matching `tokens.css`. Reduces tutorial HTML size by embedding one CSS block instead of per-span `style=` attributes.
- **`tokens.css`** extends the A1 Paper palette with confidence-pill tints, degraded-banner colours, syntax-token colours (`.tok-*`), and the font stack (`--font-sans`, `--font-mono`). Fonts referenced via `url("../fonts/*.woff2")` in the source file are replaced with inline `data:` URIs at render time.
- **`codeguide` version string** bumped from `0.0.4` → `0.0.5` (`pyproject.toml` + `src/codeguide/__init__.py`).
- **Golden-file tests** and walking-skeleton assertions retargeted at the new DOM IDs (`#tutorial-meta`, `#tutorial-lessons`, `#tutorial-narration-body`, `#tutorial-code`, `#tweaks-panel`) and the new keyboard-driven navigation (no `#btn-prev`/`#btn-next`).

### Fixed
- **Rich `box=HEAVY` rendering on Windows** — `init_console()` sets `legacy_windows=False` so HEAVY box characters (`┏ ━ ┓ / ┗ ━ ┛`) render correctly in the cost-gate panel and run-report card across all supported CI runners.
- **structlog test bleed** — `configure(json_mode=True)` no longer leaks into sibling suites (autouse `reset_defaults` fixture on `tests/unit/cli/test_logging_json_format.py`).
- **`run-report` history clash** — rotated filenames now use `%Y%m%dT%H%M%S_%fZ` so 15 back-to-back rotations retain 10 distinct files (US-058 AC).

### Dependencies
- Added: `rich>=13.7` (cost gate, run card, stage output).



### Added
- **`LLMProvider.describe_symbol`** port method (`codeguide.interfaces.ports`) — per-symbol leaf description semantics separated from `narrate`. `AnthropicProvider` uses `claude-haiku-4-5` (max_tokens=300) by default; `FakeLLMProvider` returns a deterministic stub. Phase 1 blocker preceding all other S4 work.
- **`OpenAIProvider`** (`codeguide.adapters.openai_provider`) — single adapter covering both the hosted OpenAI API (default `base_url=None`) and OSS endpoints (Ollama, LM Studio, vLLM) via `base_url` override. Uses `openai` SDK with `max_retries=0` so `tenacity` owns all retry policy (exponential backoff on `RateLimitError` / `APITimeoutError`, scope never widens to `BaseException`). OSS endpoints accept any placeholder API key and skip the consent banner (US-052, US-053).
- **`SQLiteCache`** (`codeguide.adapters.sqlite_cache`) — durable, cross-platform cache backed by SQLite with WAL journal mode and `check_same_thread=False` + `threading.Lock` for safe parallel writes. Tables: `schema_version`, `checkpoints`, `plan_cache`, `file_cache`, `pagerank_snapshots`. Cache key excludes model name by design — switching providers requires explicit `--regenerate-plan` (US-017, US-018, US-020, US-023, US-025, US-026). ADR-0008.
- **`cache_key.build_cache_key` / `build_plan_key`** helpers — SHA-256 over `(repo_abs_path, commit, lesson_id | "plan")`.
- **Grounding retry + skipped placeholder + DEGRADED marker** (`codeguide.use_cases.grounding_retry`, `entities.skipped_lesson`) — Stage 5 per-lesson retry (1 attempt on the same model with a reinforcement prompt echoing invalid symbols and allowed list), then skip with a `SkippedLesson(lesson_id, missing_symbols)` marker. Rendered as a dashed-border placeholder in the HTML (ux-spec). `skipped_count / total_planned_lessons > 0.30` (strict) flips the run to `status="degraded"` with exit code 2 and an orange banner at the top of the tutorial (US-030, US-031, US-032).
- **Word-count validator** (150–1200 words) — narrations under 150 words trigger the single grounding retry budget; narrations over 1200 are truncated at a sentence boundary (US-034).
- **30-lesson cap enforcement + "Where to go next" closing lesson** — Stage 4 planner is prompted to stay ≤ 30 regular lessons; a synthetic closing lesson (`LessonSpec.is_closing=True`, empty `code_refs`, no grounding validation) is appended after Stage 5 regardless of the cap, producing 31 lessons total for a full-sized run (US-035, US-049).
- **`RunReport`** entity (`codeguide.entities.run_report`) + atomic writer (`codeguide.cli.run_report_writer`) — structured `.codeguide/run-report.json` with `status`, `started_at`/`finished_at`, `total_planned_lessons`, `skipped_lessons_count`, `retry_count`, `cache_hit_rate`, `total_cost_usd`, `provider`, `failed_at_lesson`, `stack_trace`, `degraded_ratio`. Pydantic cross-field validators enforce `skipped ≤ planned`, `failed ⇒ stack_trace`, `non-failed ⇒ no failure payload`, `finished ≥ started`. Written via `tmp + Path.replace()` for crash-safe atomicity (US-029, US-032, US-056).
- **`SigintHandler`** (`codeguide.cli.signals`) — two-phase Ctrl+C: first SIGINT sets `should_finish` event + stderr banner + 90s safety timer; second SIGINT within 2s calls `os._exit(130)`. Timer and `signal.signal` are both restored on `.restore()` for test hygiene (US-027, US-028).
- **New CLI options** (`codeguide.cli.main`): `--base-url URL`, `--resume/--no-resume`, `--regenerate-plan`, `--cache-path FILE`, `--max-cost USD`. `--provider` now accepts `custom` for BYOK OSS endpoints.
- **CLI exit-code contract**: `0` ok, `1` fatal (unhandled + config errors, US-029), `2` degraded (US-032), `130` interrupted (US-027/028). All paths write `run-report.json` before exiting.
- **`GenerationResult`** return type for `generate_tutorial` — replaces the raw `Path`. Carries `output_path`, `skipped_lessons`, `degraded`, `degraded_ratio`, `total_planned`, `retry_count` so the CLI can build the run report without re-deriving state.
- **Graceful-abort plumbing** — `generate_tutorial(should_abort=...)` polls the predicate between stages and inside Stage 5 between lessons; raises `KeyboardInterrupt` to unwind cleanly.
- **ADR-0008** — SQLite cache schema v1 (tables, WAL, model-NOT-in-key decision, forward migration stub).
- **Tests**: 24 new tests — `test_run_report.py` (9), `test_run_report_writer.py` (7), `test_signals.py` (8 including fake-clock SIGINT scenarios), plus the Phase 2 suites shipped earlier in Sprint 4 (`test_grounding_retry.py`, `test_resume_run.py`, `test_graph_diff.py`, `test_sqlite_cache.py`, `test_openai_provider.py`, `test_cache_key.py`, `test_closing_lesson.py`, updated `test_config.py` / `test_fake_llm_provider.py` / `test_anthropic_provider.py`).

### Changed
- **`LessonSpec.is_closing: bool = False`** field added (was referenced by `_build_closing_spec` without being declared on the model — Phase 2 gap).
- **`FakeLLMProvider.narrate`** — stub narrative extended to ≥ 150 words so the walking-skeleton pipeline satisfies the new word-count validator (US-034) without invoking a real LLM.
- **`cli/main.py`** — wired to `SQLiteCache` (was `InMemoryCache`), `OpenAIProvider` branch for all three non-Anthropic providers, `SigintHandler` lifecycle, and top-level `try/except` that always emits `run-report.json`.
- **`generate_tutorial`** signature now returns `GenerationResult` and accepts `should_abort: Callable[[], bool] | None`.
- **`tutorial.html` template** — DEGRADED banner slot at the top, skipped-lesson placeholder rendered inline per `status="skipped"` (jinja renderer + template updates from Phase 2 Track A).
- **Golden HTML snapshot** (`tests/integration/__snapshots__/test_walking_skeleton.ambr`) regenerated for the new DEGRADED-banner markup (body `flex-direction: column` + `.banner-degraded` styles).

### Fixed
- Closing-lesson generation no longer crashes on `LessonSpec(is_closing=True)` — previously raised `Unexpected keyword argument` at runtime because the field was missing on the Pydantic model.
- **CI**: pin `astral-sh/setup-uv` to `@v7` (was `@v8`, which does not exist as a major tag — only `v8.1.0` release without moving alias). Resolves all matrix jobs failing at "Set up job" with `Unable to resolve action astral-sh/setup-uv@v8`.
- **CI**: install Chromium via `uv run playwright install chromium` before the `Test` step and cache `~/.playwright-browsers` per `runner.os` + `uv.lock` hash. Fixes `BrowserType.launch: Executable doesn't exist` on `test_html_file_url.py` (US-040 regression gate).

## [0.0.3] - 2026-04-20 — RAG + Planning + Anthropic (Sprint 3)

### Added
- **`AnthropicProvider`** (`codeguide.adapters.anthropic_provider`) — first real `LLMProvider` implementation.  Uses `claude-sonnet-4-6` for planning, `claude-opus-4-7` for narration.  Retries `RateLimitError` with `tenacity` exponential backoff + jitter (initial=2s, max=60s, 5 attempts) and a `before_sleep` callback that emits a structlog `anthropic_backoff` warning.
- **`Bm25Store`** (`codeguide.adapters.bm25_store`) — real `VectorStore` backed by `rank_bm25.BM25Okapi` (k1=1.5, b=0.75).  Custom tokenizer splits `snake_case` + `camelCase`, lowercases, and strips a curated stopword list.  Replaces `StubBm25Store` (kept as a backward-compat alias).
- **Corpus assembler** (`codeguide.use_cases.rag_corpus.build_corpus` / `build_and_index`) — indexes docstrings (weight 1.0), `README.md` (1.0), `docs/**/*.md` (1.0), `CONTRIBUTING.md` (1.0), last 50 git-log messages (0.8).  Missing files are skipped with a structlog info event (US-036 AC#1).
- **Doc coverage entity + use case** (`entities.doc_coverage.DocCoverage`, `use_cases.doc_coverage.compute_doc_coverage`) — surfaces `is_low` when `< 20 %` of symbols have docstrings; drives the tutorial footer warning banner (US-038).
- **No-README banner** (US-036 AC#3) — `IngestionResult.has_readme` propagates through `ManifestMetadata` to an info banner in the rendered HTML.
- **`compute_structural_change` / `is_structural_change`** (`codeguide.use_cases.graph_diff`) — pure top-N PageRank diff; infrastructure for the Sprint 4 cache-invalidation layer (US-024).
- **`plan_with_retry`** (`codeguide.use_cases.plan_lesson_manifest`) — single retry with a reinforcement prompt that echoes the offending symbols + the allowed-symbols list.  Raises `PlanningFatalError` after the second failure (ADR-0007).
- **Grounding validator** (`entities.lesson_manifest.validate_against_graph`) — enforces the Sprint 1 invariant: every `code_refs[*].symbol` must exist in the AST snapshot.  Raises `LessonManifestValidationError` listing the ungrounded symbols.
- **Config precedence chain** (`codeguide.cli.config`) — `pydantic-settings` + custom YAML loader.  Merge order: CLI flags → `CODEGUIDE_*` env → `--config <path>` → `./tutorial.config.yaml` → `platformdirs` user config → defaults.  US-004 pulled forward from Sprint 6.
- **Consent banner** (`codeguide.cli.consent`) — in-memory, per-session `[y/N]` prompt before the first Anthropic call.  `--yes` / `--no-consent-prompt` bypass for CI; `ConsentRequiredError` on non-TTY without bypass.  Persistence deferred to Sprint 6.
- **New CLI options**: `--config PATH`, `--no-consent-prompt`, `--yes`, `--provider {anthropic,openai,openai_compatible}`, `--model-plan`, `--model-narrate`.
- **ADR-0007** — Planning prompt contract: single Sonnet call, strict JSON schema, grounding invariant, 1-retry budget, fatal fail semantics.
- **`tutorial.config.yaml.example`** — reference config at repo root.
- **Mini-eval harness** (`tests/eval/test_s3_click_baseline.py`) — `@pytest.mark.eval` end-to-end run on `pallets/click`; skips gracefully without `ANTHROPIC_API_KEY` or the submodule.  Writes a baseline JSON to `tests/eval/results/s3-click-baseline.json`.

### Changed
- **`LessonSpec.code_refs`** (breaking, pre-v0.1.0): `tuple[str, ...]` → `tuple[CodeRef, ...]`.  `CodeRef` (`entities.code_ref`) carries `file_path`, `symbol`, `line_start`, `line_end`, `role ∈ {primary, referenced, example}`.
- **`LessonManifest`** — now requires a `metadata: ManifestMetadata` field with `schema_version: "1.0.0"`, `codeguide_version`, `total_lessons`, `generated_at`, `has_readme`, `doc_coverage`.  `total_lessons` must match `len(lessons)` (Pydantic `model_validator`).
- **CLI pipeline** now wires `TreeSitterParser` + `JediResolver` + `NetworkxRanker` + `Bm25Store` by default; `FakeLLMProvider` is used only when `--provider` selects a non-Anthropic backend (Sprint 4).
- **`FakeLLMProvider`** rebuilt for the new manifest schema (full `ManifestMetadata` + `CodeRef` emission) so the default (keyless) CLI path still produces a valid tutorial.
- Golden snapshot refreshed for the new banner CSS classes and the enriched manifest shape.

### Dependencies
- Added: `anthropic>=0.40.0`, `rank-bm25>=0.2.2`, `tenacity>=9.0.0`, `pydantic-settings>=2.6.0`, `platformdirs>=4.3.0`, `pyyaml>=6.0`, `numpy>=1.24`.

### Deprecated
- `StubBm25Store` — import still works via the `adapters/__init__.py` alias but points at the real `Bm25Store`.  Remove the alias in v0.1.0.

## [0.0.2] - 2026-04-20 — Analysis + Graph real (Sprint 2)

### Added
- **Real tree-sitter Python parser** (`TreeSitterParser`) — emits `CodeSymbol` nodes and a raw `CallGraph` with unresolved textual callees, replacing the Sprint 1 stub on the CLI path.
- **Real Jedi-based resolver** (`JediResolver`) — consumes the raw graph and returns a resolved `CallGraph` with a 3-tier `ResolutionStats` (resolved / uncertain / unresolved).  Emits a structlog warning when `resolved_pct < 50.0` and when docstring coverage `< 30%`.
- **Real networkx ranker** (`NetworkxRanker`) — PageRank (α=0.85), Louvain communities (seed=42), cycle detection (`simple_cycles`), SCC-condensed topological sort.
- **Ingestion use case** (`codeguide.use_cases.ingestion.ingest`) — `.gitignore`-respecting file discovery via `pathspec.GitIgnoreSpec`, additive `--exclude` / `--include` patterns, monorepo subtree auto-detect, `--root` override.
- **Git context adapter** (`codeguide.adapters.git_context`) — `subprocess`-based `git rev-parse HEAD` + branch with `"unknown"` fallback for non-git directories.
- **Helpers**: `detect_dynamic_imports` (AST-based heuristic for `importlib.import_module`, `__import__`, `globals()`, `getattr`, `locals()` patterns) and `detect_cycles` (thin wrapper over `networkx.simple_cycles`).
- **New domain entities**: `IngestionResult`, `ResolutionStats`, `RankedGraph`, `RankedSymbol` — Pydantic v2 frozen, with full invariant coverage in `tests/unit/entities/`.
- **New ports** in `codeguide.interfaces.ports`: `Resolver`, `Ranker`.
- **CLI flags**: `--exclude PATTERN` (repeatable), `--include PATTERN` (repeatable), `--root PATH` for monorepo subtree overrides.
- `outline_builder.build_outline` — extracted + hardened outline construction consumed by Stage 5 planning.
- `tests/fixtures/medium_repo/` — 20-file synthetic Python project with cross-module calls, used by the new integration test.
- `tests/integration/test_analysis_pipeline.py` — cross-track integration test exercising the real parser + resolver + ranker on `medium_repo`.
- `tests/eval/test_analysis_robustness.py` — opt-in (`-m eval_robustness`) robustness harness over 5 pinned OSS repos; log-only JSON output.
- **ADR-0006** — AST snapshot schema (grounding contract for Stage 1-3).

### Changed
- **`Parser.parse` signature** (breaking, pre-v0.1.0): `parse(files: list[Path], repo_root: Path) -> tuple[list[CodeSymbol], CallGraph]`.  The raw graph now has `resolution_stats=None`; the resolver fills it.
- **`Providers` dataclass** in `generate_tutorial.py` now requires `resolver: Resolver` and `ranker: Ranker`.
- **`CallGraph`** gains optional `resolution_stats: ResolutionStats | None`; the "edges reference known nodes" validator now runs only when the stats field is populated (so the parser can emit unresolved edges).
- **`CodeSymbol`** gains `is_dynamic_import: bool = False`.
- Pipeline Stage 1-2 flow: Ingestion → full file walk → parser → resolver → ranker (FakeLLMProvider unchanged).
- Tutorial footer now carries real `commit_hash` + `branch` from `IngestionResult` instead of hardcoded `"deadbeef"`/`"main"`.
- Golden snapshot re-generated post-pipeline changes; footer `<code>branch@hash</code>` is normalized in the snapshot test to keep the fixture stable across commits.

### Dependencies
- Added: `tree-sitter>=0.25.0`, `tree-sitter-python>=0.25.0`, `jedi>=0.19.2`, `networkx>=3.3`, `pathspec>=0.12.1`, `structlog>=24.1`.
- Dev-added: `pyyaml>=6.0`, `types-pyyaml>=6.0` (eval_robustness corpus loader).

### Fixed
- N/A (new functionality, not bug fixes).

## [0.0.1] - 2026-04-20 — Walking Skeleton (Sprint 1)

### Added
- 7-stage pipeline (ingestion → analysis → graph → RAG → planning → generation → build) running end-to-end with `FakeLLMProvider`.
- Domain entities (Pydantic v2): `CodeSymbol`, `CallGraph`, `Lesson`, `LessonPlan`, `LessonManifest`.
- Port interfaces (Protocol): `LLMProvider`, `Parser`, `VectorStore`, `Cache`, `Clock`.
- Stub adapters: `FakeLLMProvider`, `StubTreeSitterParser`, `StubBm25Store`, `InMemoryCache`, `FakeClock`.
- `JinjaRenderer` — minimal self-contained HTML template (`tutorial_minimal.html.j2`).
- `PygmentsHighlighter` — Python syntax highlighting with inline CSS (`noclasses=True`).
- `validate_offline_invariant()` — validates generated HTML against `file://` protocol invariants.
- CLI entrypoint: `codeguide <repo_path>` — generates `tutorial.html` in cwd.
- Golden snapshot tests (pytest-syrupy) for HTML output.
- Playwright e2e tests: headless Chromium + network-disabled `file://` opening.
- Test fixture: `tests/fixtures/tiny_repo/` (3-module Python calculator package).
- ADR-0005: Frozen vanilla JS output — zero Preact/React/Astro/bundler in generated HTML.

### Changed
- CLI now accepts `<REPO_PATH>` argument and runs the full pipeline.
- Version bumped from `0.0.0` to `0.0.1`.

## [0.0.0] - 2026-04-20 — Foundation (Sprint 0)

### Added
- Initial `pyproject.toml` with UV-exclusive toolchain (hatchling backend).
- `src/codeguide/` Clean Architecture skeleton (entities, use_cases, interfaces, adapters, renderer, cli).
- CLI stub: `codeguide --version` prints `codeguide 0.0.0 (scaffold)`.
- Pre-commit hooks: ruff (check + format), mypy --strict, insert-license (SPDX), commitlint.
- CI matrix: Python 3.11/3.12/3.13 × Ubuntu/Windows/macOS.
- DCO GitHub Action.
- Issue templates: bug_report, feature_request, eval_regression.
- Apache 2.0 LICENSE + NOTICE (skeleton).
- Inter + JetBrains Mono WOFF2 fonts placeholder (OFL, to be downloaded in T-000.14).
- Design tokens CSS stub (`src/codeguide/renderer/templates/tokens.css`) — A1 Paper light + dark palette.
- Eval corpus scaffold (`tests/eval/corpus/repos.yaml` — submodules deferred to Sprint 3).
- ADR-0003 (Clean Architecture layering), ADR-0004 (UV-exclusive toolchain).
