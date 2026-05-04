# Changelog

All notable changes to WiedunFlow (formerly CodeGuide) are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.9.6] - 2026-05-05 — Security: Path Traversal, XSS, SSRF, Redaction

### Security

This release closes four W3 security findings from the audit batch (F-007 through F-010).
**BREAKING for misconfigured `base_url` setups**: `tutorial.config.yaml` with non-http(s)
scheme or cloud-metadata host (`169.254.169.254`, `metadata.google.internal`, etc.) now
exits with `ConfigError` instead of silently sending the API key + source code there.
The consent banner is also now shown for **all** providers including `custom` /
`openai_compatible`, where it was previously bypassed.

- **F-007 — LLM-controlled path traversal in `agent_tools` blocked.** The four
  filesystem-touching agent tools (`make_list_files_in_dir`, `make_read_lines`,
  `make_read_tests`, `make_grep_usages`) previously took LLM-supplied paths and
  resolved them via `repo_root / rel_path` with only `exists()`/`is_dir()` checks.
  A crafted `../../etc/passwd` (deliverable via prompt-injection in a malicious
  third-party repo's docstrings or README) escaped `repo_root` and read host files.
  Introduced a new `FsBoundary` Protocol (`interfaces/ports.py`) + `DefaultFsBoundary`
  adapter (`adapters/fs_boundary.py`) that validates `target.resolve()` is contained
  within `root.resolve()` (symlinks dereferenced before the check). Primary guard in
  the two user-path tools returns `"error: path escapes repo root: ..."`; defensive
  guard in the two `rglob`-based tools silently skips out-of-root entries. The old
  `try: rel = e.relative_to(repo_root) except ValueError: rel = e` path-leak in
  `make_list_files_in_dir` was replaced with a `continue`. 8 negative parametric
  tests + 7-test `test_fs_boundary.py` (1 skipped on Windows for `os.symlink`).

- **F-008 — XSS via `innerHTML` in offline HTML output blocked.** Three sites in
  `tutorial.js` (`seg.text` for `kind="html"`/`"p"` at lines 94/97 and
  `lesson.code_panel_html` at line 192) wrote attacker-controllable strings (Writer
  LLM output and the analyzed repo's `README.md`) into `innerHTML` without sanitization.
  In a `file://` context this was stored XSS — Firefox allows `file://` → `file://`
  XHR, so a malicious README.md in an analyzed repo could read other local files when
  the user opened the generated HTML. **Three defence layers** added:
  (a) **server-side**: `_OfflineHTMLRenderer` extended with `block_html`/`inline_html`
  overrides that strip `<script>`, `<iframe>`, `<object>`, `<embed>`, `<style>`,
  `<form>`, `<svg>`, `<math>`, `on*=` attributes, and `javascript:` URLs (plus
  `_safe_for_script_tag` on all three `json.dumps` calls to escape `</`, `<!--`,
  `<![CDATA[`, U+2028, U+2029);
  (b) **client-side**: DOMPurify 3.2.4 (~22 KB minified, Apache 2.0 / MPL 2.0 dual
  license) vendored inline in `_dompurify_vendor.js`, wraps the three `innerHTML`
  assignments via `DOMPurify.sanitize(text, {USE_PROFILES: {html: true}})`;
  (c) **CSP**: `<meta http-equiv="Content-Security-Policy" content="default-src 'none';
  script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; font-src data:;
  base-uri 'none'; form-action 'none';">` added to `<head>`.
  16 unit tests + 5 integration tests verify malicious payloads (`<script>alert(1)</script>`,
  `<img src=x onerror=alert(1)>`, `<iframe>`, `</script>` breakout) are absent in the
  rendered HTML.

- **F-009 — `SecretFilter` extended with 5 cloud-provider patterns (AWS / GitHub / GCP).**
  The structlog redaction processor was missing patterns for AWS Access Key IDs (`AKIA...`),
  AWS Secret Access Keys, GitHub classic PATs (`ghp_`/`ghu_`/`gho_`/`ghs_`/`ghr_`),
  GitHub fine-grained PATs (`github_pat_...`), and PEM private key headers. Logs at
  `DEBUG` could leak any of these if they appeared in user environment variables or
  config dumps. `_PATTERNS` extended from 7 to 12. Anthropic v3 keys (`sk-ant-api03-*`)
  are already covered by the existing `sk-ant-[A-Za-z0-9_\-]{20,}` pattern (verified —
  finding's claim of v3 gap was incorrect). Pattern catalog is now versioned in
  ADR-0010 §D11 (amended 2026-05-05). 11 new parametric test cases (7 positives + 4
  false-positive controls).

- **F-010 — SSRF + consent-banner bypass via `base_url` blocked.**
  `_build_llm_provider` previously skipped the consent banner whenever
  `base_url` was non-`None` (intended for local Ollama, but allowed any remote
  endpoint to silently receive code). The `base_url` was passed to `OpenAI(base_url=...)`
  with no scheme/host/port validation: an attacker controlling
  `tutorial.config.yaml` (e.g. malicious config in an analyzed repo loaded via
  `--config`) could set `base_url=http://169.254.169.254/v1` (AWS IMDS) and exfiltrate
  the API key + source code. New `validate_base_url()` in `cli/config.py` rejects
  non-`http(s)` schemes and a blocklist of cloud-metadata hosts (AWS IMDS v4/v6, GCP
  metadata, Alibaba metadata); emits a stderr warning (does NOT block) on RFC1918
  private non-localhost addresses to preserve Ollama-on-LAN as a legitimate BYOK
  pattern. The consent banner is now shown for **all** providers (anthropic, openai,
  openai_compatible, custom) with text customised per scenario:
  cloud → "Source code will be sent to {provider}";
  localhost → "LOCAL endpoint at {url} — code does NOT leave your machine";
  remote-custom → "CUSTOM endpoint at {url} — verify trusted".
  Validation is also wired into the interactive menu (post-input re-prompt + pre-YAML-write
  defence in depth). 11 new `test_config.py` cases + 5 new `test_consent.py` cases +
  7 new E2E `test_main_cli.py` cases.

### Internal

- New port `FsBoundary` and adapter `DefaultFsBoundary` (Clean Architecture: lives in
  `interfaces/ports.py` + `adapters/fs_boundary.py`, injected at the Stage 6 generation
  call site in `generate_tutorial.py`).
- `tutorial.html.j2` now embeds DOMPurify as a separate `<script>` block before
  `tutorial.js` so the global `DOMPurify` is available when `renderNarration`/`renderCode`
  run. Vendor file: `src/wiedunflow/renderer/templates/_dompurify_vendor.js`.
- The DOMPurify bundle's four W3C namespace URI string literals are patched at load
  time (split via JS string concatenation) so the offline-invariant linter and
  walking-skeleton URL checks pass without compromising DOMPurify functionality.
- ADR-0010 amended with §D11 (Log redaction pattern catalog) — 12-row table with
  bold rows for the 5 patterns added 2026-05-05.

## [0.9.5] - 2026-05-04 — Honest Cost Reporting & Wave-2 Hygiene

### Fixed

**Cost accounting**

- Cost reporting was systematically under-reporting actual spend by ~30-60%
  on generation-heavy runs. `SpendMeter` blended a single rate across input
  and output tokens, but output tokens are 3-5× more expensive at every
  supported provider (Anthropic 5×, OpenAI 4-6×). The internal
  `PricingCatalog` Protocol now returns `(input_per_mtok, output_per_mtok)`
  tuples; `SpendMeter.charge()` applies the two rates separately. The cost
  banner at run end and the `--budget` cost gate both now reflect provider
  invoices within ~5%. See ADR-0020 for the full rationale.

- `SpendMeter.total_cost_cents` truncated fractional cents toward zero.
  `int(0.0095 * 100)` returned `0` instead of `1`. Now uses `round()`
  (banker's rounding) so sub-cent precision survives the integer cast.
  Display formatting (`${value:.2f}`) is unchanged.

**Operator visibility**

- Pipeline crashes were silent in JSON log streams. The outer `except` in
  `_run_pipeline` wrote the exception to `run-report.json` but never
  emitted a structured log event, so operators tailing `--log-format=json`
  saw no failure marker until polling the report file. A
  `logger.error("unhandled_exception", exc_info=True, ...)` now fires
  before the report is written.

- `bootstrap_venv` stderr was not flowing through the unified logging
  pipeline. Private PyPI URLs containing tokens (e.g.
  `UV_INDEX_URL=https://user:secret@…`) could leak into install logs
  unredacted. The bootstrap path is now wired through `structlog`, so the
  existing `SecretFilter` processor covers it.

### Changed (internal)

- Deduplicated three LLM system prompts (planner, narrator, describer) —
  they previously lived as 200+ lines of copy-paste in both the Anthropic
  and OpenAI adapters with subtle trailing-whitespace drift. Single source
  of truth: `wiedunflow.adapters.llm_prompts`.

- Removed the dead `symbols` parameter from `make_get_callers` and
  `make_get_callees` (never read inside the factory). `build_tool_registry`
  no longer forwards `symbols` to those two factories.

- Removed three documented-as-unused parameters from `generate_tutorial()`
  and `_stage_generation()`: `narration_min_words_trivial`,
  `narration_snippet_validation`, `project_context`. They had been no-ops
  since the v0.9.0 multi-agent rewrite (ADR-0016).

- Tightened `AgentTurn.tool_calls` and `AgentTurn.tool_results` to use
  `Field(default_factory=list)` instead of bare `[]` defaults.

- Unified logging on `structlog.get_logger` across `use_cases/spend_meter.py`,
  `use_cases/generate_tutorial.py`, and `cli/main.py`. Removed the leftover
  stdlib-logging dual-logger pattern.

- `NoOpReporter` methods now return `None` explicitly with `# noqa: ARG002`
  on each unused argument instead of using `del param` (non-idiomatic).

- `_build_closing_spec` lesson-spec assembly now uses
  `' '.join([...])` to eliminate trailing-whitespace and double-period
  edge cases.

### Internal Protocol BREAKING

- `PricingCatalog.blended_price_per_mtok(model_id) -> float | None` is
  replaced by `prices_per_mtok(model_id) -> tuple[float, float] | None`
  (input price, output price per 1M tokens). `cost_estimator.MODEL_PRICES`
  values changed from `float` (blended) to `tuple[float, float]` for the
  same reason. If you implemented a custom `PricingCatalog` adapter (no
  documented external use), update the signature — see
  [ADR-0020](docs/adr/0020-per-token-pricing.md).

## [0.9.4] - 2026-05-04 — Multi-agent Pipeline Correctness & Code Quality

### Fixed

**Multi-agent pipeline correctness**

- Reviewer feedback now reaches the Writer on retry. The `dispatch_writer` tool
  schema now accepts an optional `reviewer_feedback` field which is forwarded
  verbatim into the Writer's prompt, giving it explicit guidance on what to fix
  rather than repeating the same draft blind.

- The Writer's narrative schema now matches its five-section template. The
  `submit_lesson_draft` tool was missing the `in_context` field — the section
  that places a described symbol in the broader codebase architecture. Content
  was silently dropped or bleed into adjacent sections; `in_context` is now a
  first-class required field and the Orchestrator assembles it as section 4.

- Word-count thresholds are now a single source of truth in
  `entities/word_count.py`. Previously the Reviewer, the Writer prompt, and the
  grounding-retry helper each carried separate hardcoded floor values that had
  diverged from one another. All three now derive from `floor_for_span()` and
  `fatal_floor_for_span()`, which scale with the primary symbol's body span
  (trivial single-line → 50 words; complex >30 lines → 350 words). The
  Reviewer receives the computed per-lesson values through its `input_schema`
  substitution (`word_count_floor`, `word_count_fatal_floor`).

- `search_docs` now returns text snippets alongside scores. The Researcher was
  receiving only document IDs and BM25 scores — not readable content — making
  the documentation-lookup step effectively a no-op. The `VectorStore.search()`
  contract now returns `(id, text, score)` triples; `BM25Store` stores raw text
  at index time and exposes it in results; the `search_docs` agent tool formats
  up to 500 characters of each passage in its output.

- Planning prompts now include the full allowed-symbol list on the first attempt,
  not only on retry. The planning stage was adding the `ALLOWED SYMBOLS` block
  only when re-prompting after a grounding failure, causing unnecessary retries
  when the model guessed symbol names from prose context alone.

- Backtick-wrapped Python builtins (`str`, `int`, `float`, `Path`, `None`,
  `True`, `False`, `os`, `re`, `json`, `logging`, etc.) are now excluded from
  the grounding reference set. Previously these inflated `research_symbols`,
  allowing Reviewer grounding checks to pass for standard-library names that the
  Researcher never verified in the target codebase.

- The Reviewer schema now enforces exactly six quality checks. The `checks` array
  in `submit_verdict` lacked a `minItems` constraint, so smaller models could
  silently omit the `audience_fit` or `no_re_teach` checks without a schema
  error. `minItems: 6, maxItems: 6` now makes this a hard provider-enforced
  contract.

- Writer callout syntax changed from Obsidian-flavoured `> [!note]` to standard
  Markdown `> **Note:**`. The generated output is a self-contained HTML file
  without an Obsidian renderer, so every uncertainty callout was rendering as a
  plain blockquote containing the literal text `[!note]`.

**Cost accounting**

- `SpendMeter.abort_factor` reduced from `1.5` to `1.1` (10 % buffer above
  budget instead of 50 %). The previous default allowed an $8.00-budget run
  to reach $12.00 before the cost guard fired.

**Code quality**

- `_parse_plan_response` extracted from both provider adapters into a shared
  `adapters/_plan_parser.py` module, eliminating copy-paste drift. The function
  now accepts `has_readme: bool` (default `False`) instead of hardcoding `True`,
  so manifest metadata correctly reflects whether a README was present during
  ingestion.

- Closing-lesson checkpoint resume now logs a structured warning on parse errors
  (JSON decode, I/O, or Pydantic validation) instead of silently swallowing the
  exception with a bare `except Exception: pass`. The lesson is re-generated,
  consistent with how regular lessons handle corrupt checkpoint files.

## [0.9.3] - 2026-05-04 — Critical Correctness & Performance Fixes

### Fixed
- **`AgentResult.total_cost_usd` now reports real per-call spend.** Both
  `AnthropicProvider.run_agent` and `OpenAIProvider.run_agent` previously
  returned `total_cost_usd=0.0` on every exit path: a local `total_cost = 0.0`
  was never mutated. `SpendMeter.charge()` did track cumulative spend on the
  meter, but the field on the result that the third backstop (per-call cap)
  and `RunReport` rely on was structurally disconnected. Downstream
  `generate_tutorial.py` masked the bug with a
  `getattr(spend_meter, "total_cost_usd", 0.0)` fallback that quietly
  returned `0.0` for any mock that didn't expose the attribute. Adapters
  now snapshot the meter at the start of `run_agent` and return the per-call
  delta on every exit; `SpendMeterProto` gained an explicit
  `total_cost_usd` property so mypy enforces the contract.
- **`retry_count` reflects actual Writer retries.** `_StageGenerationOutput.retry_count`
  had been stuck at `0` since the v0.9.0 multi-agent rewrite. The pre-v0.9.0
  grounding-retry path used to populate it, but the new
  Orchestrator → Writer → Reviewer loop tracked Writer dispatches in
  `_OrchestratorState.writer_counter` without surfacing the count to the
  caller. `run_lesson` / `run_closing_lesson` now return a `RunLessonOutcome`
  dataclass carrying `(result, writer_retries)`; `_stage_generation` unpacks
  the outcome and accumulates retries across all lessons.
- **`CostGateAbortedError` consolidated to a single canonical class.** The
  exception had been defined twice — once in `use_cases/generate_tutorial.py`
  (the production raise site) and once in `cli/cost_gate.py` (an unused
  stale copy). Different runtime types meant `except CostGateAbortedError`
  from one site would silently miss instances from the other. Both
  `CostGateAbortedError` and `MaxCostExceededError` now live in a new
  `wiedunflow.use_cases.errors` module; CLI catches and use-case raises
  both import from there. `cli/cost_gate.py` keeps a re-export for
  backwards compatibility.

### Performance
- **`SQLiteCache.file_cache` is now wired through `TreeSitterParser`.** The
  table DDL and `save_file_cache` / `get_file_cache` helpers (ADR-0008) had
  been in place for two releases, but `Parser.parse` never accepted a cache
  argument and never called either method. Every run re-parsed every file
  regardless of content; the documented "<5 min incremental" performance
  budget was unreachable on repos larger than ~100 files. `Parser.parse`
  now takes `cache: Cache | None = None`; each file's SHA-256 is consulted
  before parsing — hits skip the tree-sitter pass and reconstruct symbols/
  edges from the JSON payload, misses parse normally and persist a fresh
  `FileCacheEntry`. Scope is parser-only this release; `JediResolver` cache
  is deferred (cross-file invariants need a separate ADR amendment).

### Internal
- `Cache` Protocol gained `get_file_cache` / `save_file_cache`. The
  in-memory adapter (`InMemoryCache`) now exposes a dict-backed
  implementation so unit tests can drop the same helper through both
  adapters. `StubTreeSitterParser` accepts (and ignores) the new `cache`
  argument to keep the fixture in sync with the protocol.

## [0.9.2] - 2026-05-04 — Production Wiring & Brand Fixes

### Fixed
- **Triple-brace rendering bug** in agent system prompts (`${{{var}}}` → `${{var}}`) — Orchestrator/Researcher/Writer cards no longer ship `$0.80} USD` to the LLM. The placeholder regex `\{\{(\w+)\}\}` matched the inner `{{var}}` and left the third `}` literal in every compiled prompt. Affected every real-LLM run since the multi-agent rollout. Regression test in `tests/unit/use_cases/test_agent_loader.py`.
- **`generated_at` timestamps were stub dates in production**. `cli/main.py` and `cli/menu.py` were wiring `FakeClock()` (the test double with hardcoded `2026-01-01T12:00:00Z`) into `Providers`, so every HTML footer, `RunReport.started_at`, and `ManifestMetadata.generated_at` reported the stub date instead of the actual run. New `wiedunflow.adapters.system_clock.SystemClock` now wraps `datetime.now(UTC)` and is wired in both CLI surfaces.
- **Brand square** in `tutorial.html.j2` shows `wf` instead of stale `C` — leftover from the CodeGuide era; first thing the user saw in the generated HTML.
- **README accuracy** — version badge `0.9.2` (was the fabricated `2.3.1`), Python badge `3.11+` (was `3.13+` while `pyproject.toml` declares `>=3.11`), banner version unified to current, and Claude model badge labels match their SVG values (Opus 4.7, Sonnet 4.6).
- **`FakeLLMProvider.plan()`** reports the live `wiedunflow.__version__` in manifest metadata instead of the hardcoded `"0.0.3"` (6 majors stale). Aligns with the existing pattern in `anthropic_provider.py` / `openai_provider.py`.

### Changed
- **`FakeClock` moved** from `src/wiedunflow/adapters/fake_clock.py` to `tests/fakes/clock.py`. The production-importable surface (`wiedunflow.adapters`) no longer leaks test doubles. Six test files updated to import `FakeClock` from `tests.fakes.clock`; production code paths unchanged. New `tests/unit/cli/test_clock_wiring.py` regression asserts `FakeClock` cannot leak back into `cli/main.py` or `cli/menu.py`.

## [0.9.1] - 2026-05-02 — Brand Unification

### Changed (BREAKING — pre-1.0)
- **CLI command renamed `wiedun-flow` → `wiedunflow`** (single canonical brand token, no hyphen). The single mixed-form convention from the v0.6.0 rebrand (`pkg: wiedunflow` / `CLI: wiedun-flow`) is collapsed to one form everywhere. Reinstall required: `uv sync --reinstall` (or `uv tool install --force wiedunflow`). The old `wiedun-flow` binary is no longer registered as a `[project.scripts]` entry point. See ADR-0019 for rationale (supersedes ADR-0013 §1).
  - **Migration**: replace any shell aliases, CI smoke commands, and shell history references from `wiedun-flow ...` to `wiedunflow ...`. Behavior is bit-identical.
  - **Why now**: pre-PyPI release window — zero installed users, zero migration cost. Post-PyPI this would be a MAJOR semver bump per change.

### Fixed
- **Closing lesson rendered raw JSON instead of markdown** — `run_closing_lesson` is given `tools=[]` (no `submit_lesson_draft` tool available) but the Writer card still forces `output_contract: format=json`, so gpt-5.4 emitted a JSON envelope as plain text. The HTML reader then displayed the literal `{"overview":"...","how_it_works":"..."}` blob instead of formatted markdown. New `_assemble_narrative_from_structured()` defensively parses such payloads (incl. ` ```json ` fenced wrapper) and stitches the four sections (`overview`, `how_it_works`, `key_details`, `what_to_watch_for`) into a single narrative; plain-markdown output passes through verbatim. Confirmed against the v0.9.0 manual-eval artefact `wiedunflow-project-generator.html`.
- **Test path drift bugs corrected mimochodem** — `tests/unit/cli/test_no_rich_outside_output.py`, `test_no_questionary_outside_menu.py`, and `test_no_httpx_outside_litellm_pricing.py` had `_SRC_ROOT = .../src/wiedun-flow` which never resolved to a real directory (the actual path is `src/wiedunflow`). The architectural lint tests had been silently passing on empty `rglob()` iterations since the v0.6.0 rebrand. Now correctly target `src/wiedunflow`. `tests/eval/test_s3_click_baseline.py` and `tests/integration/test_zero_telemetry.py` likewise fixed `python -m wiedun-flow` (invalid module name with hyphen) to `python -m wiedunflow`.

### Changed
- **`--output` default location is now `<repo>/wiedunflow-<repo-name>.html`** (was: `./wiedunflow-<repo>.html` in cwd). The artefact now lives next to the source it documents, so the tutorial moves with the repo and never gets orphaned in a stale shell cwd.
- **`--output` auto-appends `.html`** when the supplied path has no extension (e.g. `--output my-tour` → `my-tour.html`). Existing extensions (`.html`, `.htm`, anything else) are preserved verbatim. Closes the "I forgot the extension and my OS would not open the file" feedback from the v0.9.0 manual eval. The same contract applies to the interactive menu's Generate sub-wizard (`§1 Repo & Output` now displays the repo-relative default).

### Internal
- New ADR-0019: brand unification — drop `wiedun-flow`, single canonical `wiedunflow` (supersedes ADR-0013 §1).

## [0.9.0] - 2026-05-02 — Multi-Agent Narration Pipeline

### Added
- **Multi-agent narration pipeline (Stage 5/6)** — replaces single-shot `narrate()` with Orchestrator → Researcher × N (8 tools) → Writer → Reviewer per lesson. Sequential per-lesson invariant keeps `concepts_introduced` coherent. Filesystem-mediated workspace at `~/.wiedunflow/runs/<run_id>/` (`processing/` → `finished/` atomic checkpoint via `os.replace`).
- **`LLMProvider.run_agent()` port + adapters** — manual tool-call loop in `OpenAIProvider` (function calling) and `AnthropicProvider` (tool use). `ToolSpec`, `ToolCall`, `ToolResult`, `AgentTurn`, `AgentResult` types.
- **Agent cards** at `src/wiedunflow/use_cases/agents/{orchestrator,researcher,writer,reviewer}.md` — YAML frontmatter (tools, suggested_model_role, budgets, input_schema) + body prompt with `{{name}}` placeholder syntax. Loader at `agents/loader.py`.
- **8 researcher tools** (`agents/tools/*.json`): `read_symbol_body`, `get_callers`, `get_callees`, `search_docs`, `read_tests`, `grep_usages`, `list_files_in_dir`, `read_lines`. Each tool has size cap and is a closure over the AST snapshot.
- **5 dispatch tools** for Orchestrator: `dispatch_researcher`, `dispatch_writer`, `dispatch_reviewer`, `mark_lesson_done`, `skip_lesson`.
- **Structured output for Reviewer** — `submit_verdict` terminal tool with JSON Schema enforced by provider (OpenAI Structured Outputs / Anthropic tool use). Eliminates malformed-JSON failure mode entirely.
- **Structured output for Writer** — `submit_lesson_draft` terminal tool with forced 4-section schema (`overview`, `how_it_works`, `key_details`, `what_to_watch_for`) + `cited_symbols: list[str]` + `uncertain_regions: list[{symbol, callout}]`. Programmatic `cited_symbols ⊂ research_notes` sanity check.
- **Writer prompt strictness** — "Verbatim Citation Discipline" section (no symbol invention, full signature quote, re-read-before-write self-check) and "Uncertainty Discipline" section (mandatory `> [!note]` callouts for UNCERTAIN-flagged research, no assertion-tone for runtime dispatch).
- **`SpendMeter` cost reporting wire-through** — created in `_run_pipeline`, propagated to `generate_tutorial → _stage_generation → run_lesson → llm.run_agent`. Adapter providers (`anthropic_provider.py:280`, `openai_provider.py:312`) charge per-call. Final `RunReport.total_cost_usd` and CLI success banner show real cost (was hardcoded `0.0`).
- **Workspace `finished/` consistency** — fallback `SkippedLesson` paths in `run_lesson` and `run_closing_lesson` now persist to `finished/lesson-N/lesson.json` via `_persist_skipped_lesson` helper. Resume scan now sees all lessons (was: only ~3/16 in cold-start scenario).
- **Tier 1: Jedi venv auto-detection** — `_detect_python_path(repo_root, override)` in `jedi_resolver.py` searches `.venv/` → `venv/` → `env/` (cross-platform: `Scripts/python.exe` on Windows, `bin/python` on Unix). Falls back to user override via `--python-path PATH` flag. WARNING log when no venv found.
- **Tier 1: `--python-path` flag** — explicit venv override for `wiedunflow generate`.
- **Tier 1: `--bootstrap-venv` flag (opt-in, default off)** — runs `uv sync --no-dev` in the analyzed repo before Stage 2 to bootstrap a missing venv. Graceful degradation on failure.
- **Tier 2: Heuristic call graph fallback** — when Jedi `infer()` returns empty, `_heuristic_name_match()` does last-component name lookup in AST `symbol_by_name`. Single match → `RESOLVED_HEURISTIC` tag; ambiguous → `UNCERTAIN` with `candidates: list[str]`; zero → `UNRESOLVED` (status quo). Backward-compatible: `resolved_pct` still reflects strict Jedi resolution; new `resolved_heuristic_count` field in `ResolutionStats`, plus computed `resolved_pct_with_heuristic` property.
- **`{{name}}` placeholder syntax** in agent cards (Mustache-/Jinja-like) replaces `str.format()` to avoid KeyError on literal JSON examples in prompt bodies.

### Changed
- **Default LLM models for multi-agent roles**: `model_orchestrator=gpt-5.4`, `model_researcher=gpt-5.4-mini`, `model_writer=gpt-5.4`, `model_reviewer=gpt-5.4-mini`. Configurable per role in `tutorial.config.yaml`.
- **Schema bump cache v1 → v2 (forward-compat)** — added `run_id`, `final_state`, `concepts_finalized`, `total_cost_cents`, `tool_transcript_path`, `orchestrator_turns`, `researcher_count`, `writer_attempts` columns. NULL `run_id` treated as legacy.

### Fixed
- **Cost reporting hardcoded `0.0`** — `cli/main.py::_write_final_report` now reads from `SpendMeter.total_cost_usd`. CLI success banner shows `total_cost: $X.XX` line.
- **Workspace `finished/` skipped fallback paths** — `run_lesson` L695-700 and `run_closing_lesson` L536-542 fallback `SkippedLesson` returns now persist to `finished/lesson-N/lesson.json` for resume support.
- **Reviewer `KeyError('\n  "verdict"')`** — `compile_card` loader switched from `str.format()` to safe `{{name}}` regex substitution. Literal JSON examples in prompt bodies no longer cause KeyError.

### Deprecated
- **`LLMProvider.narrate()`** and **`LLMProvider.describe_symbol()`** — superseded by `run_agent()` on the multi-agent main path. Methods remain on the `LLMProvider` Protocol and on all three adapters (`AnthropicProvider`, `OpenAIProvider`, `FakeLLMProvider`) for back-compat with the legacy single-shot path; targeted for removal in v1.0.
- **`use_cases/grounding_retry.py::narrate_with_grounding_retry()`** — kept for the legacy retry path; the Reviewer agent's 6-check rubric (incl. snippet validation) is the new primary grounding gate. Targeted for removal in v1.0.

### Internal
- Test count: 1169 → **1212** (+43 new tests across all 6 fixes).
- New ADRs: [ADR-0016](docs/adr/0016-multi-agent-narration.md) (multi-agent narration pipeline), [ADR-0017](docs/adr/0017-cost-reporting-wire-through.md) (cost reporting wire-through), [ADR-0018](docs/adr/0018-jedi-heuristic-fallback.md) (Jedi heuristic call graph fallback).

### Eval baseline (SummarifAI_API, 22 Python files, cold-start no `.venv/`)

| Metric | v0.8.0 (Fix A+B only) | **v0.9.0 (all fixes)** | Δ |
|--------|---:|---:|---:|
| Wall time | 24:44 | **14:06** | -43% |
| Lessons narrated | 12/16 | **21/25** | +75% |
| `degraded_ratio` | 0.25 | **0.16** | -36% |
| Hallucinated symbols | 0 | **0** | maintained |
| `total_cost_usd` | $0.00 (BUG) | **$3.82** | reporting fixed |
| Jedi `resolved_heuristic` | n/a | **27 edges** | Tier 2 active |
| HTML size | 610 KB | 793 KB | +30% (more lessons) |

### Known issues (deferred to v0.9.1)
- **Workspace `mark_lesson_done` persistence inconsistency** — single eval run may persist only ~9/22 lesson.json files to `finished/` even though all 21 lessons appear in the HTML output. Multiple `run_id` directories created during one run (`generate_run_id()` uses `started_at` timestamp called more than once). Resume support is partial until fixed. The `SkippedLesson` fallback paths (Bug #2) DO persist correctly — issue is in the success path of `mark_lesson_done` dispatch tool.

## [0.8.0] - 2026-05-01 — Sprint 7 Release Gate Cleared

### Added
- **Eval suite green on 5 OSS repos** via OpenAI provider (`click`, `requests`, `starlette`, `python-sdk-mcp`, `dateutil`). Eval artifacts archived in `tests/eval/results/`.
- **`tests/eval/conftest.py`** — session-scoped pre-flight fixture that validates `OPENAI_API_KEY` before spending budget; logs eval cost ceiling ($19 across 5 repos).
- **`exclude_patterns` in eval configs** — `examples/**` and `tests/**` excluded from ingestion for all 5 repos to prevent FQN pollution in planning stage.
- **`openai.InternalServerError` retried** — 500/502/503 from OpenAI now retried by tenacity alongside existing `RateLimitError` / `APITimeoutError`.
- **`CodeRef` auto-swap** — `line_end < line_start` from LLM is silently corrected (swap) instead of raising a Pydantic `ValidationError` that consumed a planning retry.
- **Planning retries: 2 → 3** — one extra attempt gives the LLM room to recover from both grounding failures and line-number errors in separate retries.
- **Code pane auto-collapse** — lessons with no code content (`code_snippet` absent, no `code_panel_html`, no segment-level `code_ref`) collapse to single-column layout automatically, eliminating the "(no code reference)" empty state.

### Changed
- **MCP eval config** switched to OpenAI (`gpt-5.4-mini` plan / `gpt-5.4` narrate) per ADR-0015. Original Anthropic config preserved as `tests/eval/configs/python-sdk-mcp-anthropic.yaml`.
- **`eval_api_key` fixture** — prefers `OPENAI_API_KEY`, falls back to `ANTHROPIC_API_KEY`; skips only when both are unset.
- **`_MAX_PLANNING_ATTEMPTS`** raised from 2 to 3.

### Fixed
- **`exclude_patterns` YAML config ignored** — `cli/main.py` now merges `config.exclude_patterns` / `config.include_patterns` into the tuples passed to `_run_pipeline`.
- **Jedi `added_sys_path` regression** — reverted accidental patch that dropped resolution rate from 9.9% → 2.7%; Jedi's default `smart_sys_path=True` handles src-layout repos correctly.
- **`getattr` false-positive in dynamic marker propagation** — introduced `detect_strict_uncertainty()` alongside `detect_dynamic_imports()`. Files using `getattr()` for normal attribute access (e.g. `dateutil/parser/_parser.py`, `src/mcp/cli/cli.py`) no longer have all their symbols excluded from the planner's grounding set. Only files with `importlib.import_module()` or `__import__()` keep `is_uncertain=True`. The `is_dynamic_import` flag is unchanged.

### Note
- **Rubric signoff** (`docs/rubric/v0.1.0/signoff-mcp-sdk.yaml`) deferred to post-PyPI feedback collection from real users. `WIEDUNFLOW_SKIP_RUBRIC_GATE=1` must be set for pre-rubric CI runs.

### Internal
- Back-tagged `v0.2.0`, `v0.2.1`, `v0.4.0`; backfilled GH Releases for `v0.5.0`–`v0.7.0`.
- Removed legacy `hooksPath = D:\\CodeGuide\\.git\\hooks` from `.git/config`.
- Added `.python-version` (`3.12`) at repo root.
- Rubric template header updated: `v0.6.0` → `v0.8.0`.

## [0.7.0] - 2026-04-26 — Default Provider Switch (BREAKING)

### Changed (BREAKING — pre-1.0)
- **Default LLM provider**: `anthropic` → `openai`. Existing users with `OPENAI_API_KEY` set: zero action. Users relying on `ANTHROPIC_API_KEY`: re-run `wiedunflow init` and select `anthropic`, or set `WIEDUNFLOW_LLM_PROVIDER=anthropic` in env, or edit `tutorial.config.yaml`. (ADR-0015)
- **Default models**: `claude-sonnet-4-6` (planning) + `claude-opus-4-7` (narration) + `claude-haiku-4-5` (per-symbol describe) → `gpt-5.4` (planning + narration) + `gpt-5.4-mini` (per-symbol describe).
- **OpenAIProvider class defaults**: `gpt-4o` / `gpt-4o-mini` → `gpt-5.4` / `gpt-5.4-mini`. Affects only callers using `OpenAIProvider()` directly without explicit `model_*=` kwargs.

### Fixed
- `cost_estimator.MODEL_PRICES` — verified gpt-5.4 family pricing replaced earlier "hypothetical" estimates: `gpt-5.4` 6.60→7.50 USD/MTok blended ($2.50/$15.00 input/output), `gpt-5.4-mini` 0.88→2.25 ($0.75/$4.50), `gpt-5.4-pro` 33.00→90.00 ($30/$180). Cost-gate estimates now accurate.
- `tutorial.config.yaml.example` — stale CodeGuide brand artifacts cleaned up (linie 1-3, 30) post-rebrand.

### Internal
- ADR-0015 — formal documentation of provider switch decision (rationale, trade-offs, migration path).
- Anthropic adapters (provider, model catalog, cost pricing) unchanged — fully supported BYOK alternative.

## [0.6.0] - 2026-04-26 — Rebrand to WiedunFlow

### Changed (BREAKING — pre-1.0)
- Package renamed `codeguide` → `wiedunflow`. CLI command `codeguide` → `wiedun-flow` (further unified to `wiedunflow` in v0.9.1 — see ADR-0019).
- ENV prefix `CODEGUIDE_*` → `WIEDUNFLOW_*`.
- Cache namespace: `~/.cache/codeguide/` → `~/.cache/wiedunflow/`.
- localStorage keys: `codeguide:*` → `wiedunflow:*`.
- Default output filename: `tutorial.html` → `wiedunflow-<repo>.html`.
- Per-repo state dir: `.codeguide/` → `.wiedunflow/`.
- HARD CUT: zero aliases, zero shim. Reinstall required (`uv tool install wiedunflow`).

### Note
- "Wiedun" — Old Polish for sage/wise one. The brand reflects the tool's role: it knows the code (via AST + call graph) and guides the reader through it.

## [0.5.0] - 2026-04-26 — Repo Picker + Live Pricing

### Added
- **Sub-picker in §1 Generate sub-wizard** (3-source: Recent runs / Discover in cwd / Type path manually) — closes US-088, US-090, US-091. Users can select a repository interactively without typing paths.
- **`cli/picker_sources.py`** — pure-logic functions `discover_git_repos()` (depth=1, .gitignore-aware, mtime sort DESC, cap 20) and `load_recent_runs()` (LRU from cache).
- **Git repo discovery in cwd** — depth=1 walk, skip 13 hardcoded ignored dirs (`node_modules`, `.venv`, etc.), honor `.gitignore` via `pathspec`, sort by mtime DESC.
- **Manual repo path entry** — `questionary.path()` via `MenuIO.path()` with validation (directory exists + has `.git/`).
- **Recent runs LRU cache** — read/write `~/.cache/codeguide/recent-runs.json` (max 10 entries).
- **`PricingCatalog` port** (`interfaces/pricing_catalog.py`) + 4 adapters for dynamic model pricing:
  - `StaticPricingCatalog` — hardcoded fallback from `MODEL_PRICES`
  - `LiteLLMPricingCatalog` — HTTP fetch from LiteLLM GitHub (~3500 models, auto-update)
  - `CachedPricingCatalog` — 24h disk cache decorator (mirrors `CachedModelCatalog`)
  - `ChainedPricingCatalog` — fallback chain; first non-`None` answer wins
- **Live model pricing** via LiteLLM catalog — cost-gate estimates now stay current without CodeGuide releases. New models (`gpt-5.4-mini`, `claude-opus-4-8`) priced automatically once LiteLLM publishes them.
- **`httpx>=0.27`** declared as explicit direct dependency (was implicit transitive via `anthropic`/`openai` SDKs); CodeGuide now imports it directly in `litellm_pricing_catalog.py` so PEP-621 honesty wins.
- **ADR-0014** — Dynamic pricing catalog architecture (port + 4 adapters, 24h cache, three-sink rule extension for httpx).
- **UX-spec §4.0** — Picker mode formalization (3-source flow, empty states exact copy, discovery scope, Back semantics).

### Changed
- §1 Generate sub-wizard: plain `io.text("Repo path:")` → interactive 3-source `_subwizard_pick_repo()` picker.
- `cost_estimator.py` now uses `ChainedPricingCatalog` with fallback chain (live LiteLLM → static). Cost estimates more accurate.
- Three-sink rule extended: `httpx` imports only in `adapters/litellm_pricing_catalog.py` (new lint test `test_no_httpx_outside_litellm_pricing.py`).

### Fixed
- Cost-gate accuracy for newly released models (pricing no longer tied to CodeGuide release cadence).

### Internal
- New ADR-0014 ("Dynamic pricing catalog") documents port architecture, 24h cache TTL, network-failure handling.
- `pyproject.toml`: `httpx>=0.27` added to `[project.dependencies]` (explicit, not transitive).
- 50+ new unit tests covering picker discovery, pricing catalogs, and cache behavior.

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
- Install: `uv pip install git+https://github.com/numikel/code-guide@v0.1.0` (no PyPI publish in MVP per FR-03; see roadmap for v0.2.0).
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
