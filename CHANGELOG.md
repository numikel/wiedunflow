# Changelog

All notable changes to CodeGuide are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.0.4] - 2026-04-21 — Generation + Cache + BYOK + Grounding (Sprint 4)

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
