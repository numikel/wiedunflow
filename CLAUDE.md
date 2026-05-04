# AI Rules for WiedunFlow

WiedunFlow is a Python CLI that turns a local Git repository into a single, self-contained HTML file acting as an interactive, tutorial-style guided tour of the code — opened directly in the browser via `file://`, with no server and no runtime dependencies on the recipient's side. Pipeline: tree-sitter + Jedi → PageRank graph → BM25 RAG → direct-SDK LLM orchestration (BYOK: Anthropic/OpenAI/Ollama) → Jinja2 + Pygments → one HTML. Full product spec: `.ai/mvp-wiedunflow.md`.

## STACK

- **Language**: Python 3.11+ (CLI and entire pipeline)
- **Parsing**: `tree-sitter-python` (AST), `Jedi` (resolved call graph)
- **Graph**: `networkx` (PageRank, community detection, topological sort)
- **RAG**: `rank_bm25` (BM25Okapi, zero infra). sqlite-vec + embeddings planowane na v2 — patrz ADR-0002.
- **Cache**: SQLite + file-level hash invalidation
- **LLM orchestration**: oficjalne SDK (`anthropic`, `openai`) + `httpx` dla OpenAI-compatible endpoints (Ollama / LM Studio / vLLM). Własny port `LLMProvider` w `interfaces/`. Bez LangChain — patrz ADR-0001.	
- **Rendering**: `Jinja2` (template), `Pygments` (syntax highlighting → inline HTML)
- **Frontend output**: vanilla JS (binarnie, bez Preact) — **everything inlined** into one HTML (the `file://` constraint forbids `fetch()` and ES module imports)
- **Packaging**: `pyproject.toml` → PyPI. No Docker in MVP (roadmap v2+)
- **Testing**: `pytest`
- **License**: Apache 2.0

## CODING_PRACTICES

### Guidelines for SUPPORT_LEVEL

#### SUPPORT_EXPERT

- Favor elegant, maintainable solutions over verbose code. Assume understanding of language idioms and design patterns.
- Highlight potential performance implications and optimization opportunities in suggested code.
- Frame solutions within broader architectural contexts and suggest design alternatives when appropriate.
- Focus comments on 'why' not 'what' - assume code readability through well-named functions and variables.
- Proactively address edge cases, race conditions, and security considerations without being prompted.
- When debugging, provide targeted diagnostic approaches rather than shotgun solutions.
- Suggest comprehensive testing strategies rather than just example tests, including considerations for mocking, test organization, and coverage.

### Guidelines for PYTHON

- Target Python **3.11+** (pattern matching, `tomllib`, improved `TypedDict`, exception groups)
- Type hints are **mandatory** on public APIs of pipeline modules; prefer `from __future__ import annotations`
- Lint + format: `ruff` (lint + format) as the single source of truth; `mypy --strict` on `src/wiedunflow/**`
- Before finishing any coding task, always run a full quality check in this exact order: `uv run ruff format .` -> `uv run ruff check .` -> `uv run mypy src/wiedunflow` -> `uv run pytest`.
- Use `pathlib.Path`, never raw `os.path` strings
- Use async only where it genuinely pays off (concurrent LLM calls in the generation stage) — keep the rest synchronous
- Structured logs (`structlog` or stdlib `logging` with a JSON formatter), never `print()` inside the pipeline
- Configuration via `pydantic.BaseModel` (validates `tutorial.config.yaml`)

### Guidelines for DOCUMENTATION

#### DOC_UPDATES

- Update relevant documentation in /docs when modifying features
- Keep README.md in sync with new capabilities (CLI flags, config options, supported LLM providers)
- Maintain changelog entries in CHANGELOG.md
- `tutorial.config.yaml` schema: if you add a new field, update the Pydantic model, the JSON schema in `/docs`, and the example in README in the same PR

### Guidelines for VERSION_CONTROL

#### GIT

- Use conventional commits to create meaningful commit messages
- Use feature branches with descriptive names following `<type>/<short-kebab-desc>` (e.g. `feat/bm25-rag`, `fix/jedi-cycle-detection`, `chore/pyproject-bump`)
- Write meaningful commit messages that explain why changes were made, not just what
- Keep commits focused on single logical changes to facilitate code review and bisection
- Use interactive rebase to clean up history before merging feature branches
- Leverage git hooks (pre-commit: `ruff`, `mypy`, license header insertion) to enforce code quality checks before commits and pushes
- **DCO sign-off** (`git commit -s`) is required — the project uses Developer Certificate of Origin instead of a CLA (see MVP section 12)

#### GITHUB

- Use pull request templates to standardize information provided for code reviews
- Implement branch protection rules for `main` to enforce quality checks
- Configure required status checks (pytest, ruff, mypy, DCO check) to prevent merging code that fails tests or linting
- Use GitHub Actions for CI/CD workflows to automate testing and deployment to PyPI
- Implement CODEOWNERS files to automatically assign reviewers based on code paths
- Use GitHub Projects for tracking work items and connecting them to code changes

#### CONVENTIONAL_COMMITS

- Follow the format: type(scope): description for all commit messages
- Use consistent types (feat, fix, docs, style, refactor, test, chore) across the project
- Define clear scopes based on pipeline stages: `ingestion`, `analysis`, `graph`, `rag`, `planning`, `generation`, `build`, `cli`, `cache`, `config`
- Include issue references in commit messages to link changes to requirements
- Use breaking change footer (!: or BREAKING CHANGE:) to clearly mark incompatible changes — especially important for the `tutorial.config.yaml` format and the HTML output structure
- Configure commitlint (or `cz-cli`) to automatically enforce conventional commit format

### Guidelines for ARCHITECTURE

#### ADR

- Create ADRs in /docs/adr/{name}.md for:
- 1) Major dependency changes (e.g. swapping Jedi for pyright, tree-sitter → LSP)
- 2) Architectural pattern changes (e.g. changes in orchestrator state shape, cache layout)
- 3) New integration patterns (new LLM provider, new parser language)
- 4) SQLite cache / BM25 index schema changes (with compatibility migrations)

#### CLEAN_ARCHITECTURE

- Strictly separate code into layers: **entities** (`LessonPlan`, `CodeSymbol`, `CallGraph`), **use cases** (`GenerateTutorial`, `RankGraph`, `IndexRepo`), **interfaces** (ports: `LLMProvider`, `Parser`, `VectorStore`, `Cache`), and **frameworks** (adapters: `AnthropicProvider`, `TreeSitterParser`, `Bm25VectorStore`)
- Ensure dependencies point inward, with inner layers having no knowledge of outer layers — the `entities` layer must not know about provider SDKs or SQLite
- Implement domain entities that encapsulate **lesson ordering, narrative coherence invariants, symbol grounding rules, and cache invalidation policies** without framework dependencies
- Use interfaces (ports) and implementations (adapters) to isolate external dependencies — this is exactly what enables BYOK and swapping the parser for TS/JS in v2
- Create use cases that orchestrate entity interactions for specific business operations
- Implement mappers to transform data between layers to maintain separation of concerns

## OUTPUT_ARTIFACT

### Guidelines for SELF_CONTAINED_HTML

- **`file://` constraint**: no `fetch()`, no relative ES module imports, no external CDN. Everything inline (CSS, JS, lesson data as `<script type="application/json">`).
- **Size**: target <8 MB for a medium repo, hard warning at >20 MB.
- **Frontend**: vanilla JS — **no framework, no Preact, no bundler, no React, no Astro**. Decyzja binarna; powrót do frameworka wymaga ADR.
- **Syntax highlighting**: pre-rendered by Pygments during the build stage (not at runtime in the browser) — HTML spans are embedded into lesson data.
- **Metadata**: every HTML output must carry the repo commit hash and branch in the footer (tutorial versioning).
- **Mobile-responsive CSS**: the output must read well on mobile (benchmark: Anthropic Skilljar).

## DEVOPS

### Guidelines for CI_CD

#### GITHUB_ACTIONS

- Check if `pyproject.toml` exists in project root and summarize key scripts/entry points (`[project.scripts]`)
- Check if `.python-version` or `tool.uv` / `tool.poetry` exists in project root
- Check if `.env.example` exists in project root to identify key `env:` variables (e.g. `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`)
- Always use terminal command: `git branch -a | cat` to verify whether we use `main` or `master` branch
- Always use `env:` variables and secrets attached to jobs instead of global workflows
- Use `pip install -e .[dev]` or `uv sync` for dependency setup (not `npm ci` — this is a Python project)
- Run the test matrix on Python 3.11, 3.12, 3.13 × OS (ubuntu, windows, macos) — the CLI tool must work cross-platform
- Extract common steps into composite actions in separate files
- Once you're done, as a final step conduct the following: for each public action always use Run Terminal to see what is the most up-to-date version (use only major version) - extract tag_name from the response:
- ```bash curl -s https://api.github.com/repos/{owner}/{repo}/releases/latest ```
- **PyPI release**: trigger on tag `v*.*.*`, build via `python -m build`, publish via `pypa/gh-action-pypi-publish` with OIDC trusted publishing (no long-lived tokens)

## TESTING

### Guidelines for UNIT

#### PYTEST

- Use fixtures for test setup and dependency injection (in particular: throw-away Git repos, fake `LLMProvider`, in-memory SQLite)
- Implement parameterized tests for **AST parsing edge cases (cycles, dynamic imports, reflection), graph ranking heuristics (PageRank, community detection), orchestration prompt builders, and BM25 retrievers**
- Use `monkeypatch` for mocking dependencies — **but never mock the LLM in end-to-end tests**; use a `FakeLLMProvider` implementing the port with deterministic responses instead
- Golden-file tests for the generated HTML (snapshot) — any template change must be intentional
- Keep narrative-quality eval tests (MVP section 8) in a separate `tests/eval/` directory and run them outside the default `pytest` run (marker `@pytest.mark.eval`) — they require a real API key

## PIPELINE

The generator has 7 ordered stages; conventional-commit scopes mirror them 1:1:

1. **Ingestion** (`ingestion`): language detection, docs discovery, file hashing, cache lookup. `.gitignore` respected by default — user `exclude`/`include` are additive.
2. **Analysis** (`analysis`): tree-sitter AST, Jedi-resolved call graph, docstrings, type hints, entry-point detection, cycle detection, dynamic-import flagging.
3. **Graph** (`graph`): PageRank, community detection, topological sort leaves→roots → "story outline" feeding the planning LLM call.
4. **RAG** (`rag`): BM25 index (`rank_bm25`) over docstrings, `README.md`, `docs/**/*.md`, `CONTRIBUTING.md`, commit messages, inline comments (lower weight). Migration to sqlite-vec + embeddings planned for v2 (ADR-0002).
5. **Planning** (`planning`): single Sonnet call returns `lesson_manifest` JSON — `{lessons: [{id, title, teaches, prerequisites, code_refs, external_context_needed}]}`.
6. **Generation** (`generation`): per-lesson multi-agent pipeline (Orchestrator → Researcher × N → Writer → Reviewer). Sequential to preserve `concepts_introduced` invariant. Workspace at `~/.wiedunflow/runs/<run_id>/`. Atomic checkpoint to `finished/` after each lesson. Closing lesson aggregates trivial helpers via single Writer call.
7. **Build** (`build`): Pygments pre-rendering, Jinja2 template, inline everything into one HTML.

## LLM_ORCHESTRATION

- **Multi-agent pipeline (Stage 5/6, v0.9.0+)**: Orchestrator (smart, gpt-5.4) dispatches Researcher (tool-heavy, gpt-5.4-mini) × N → Writer (gpt-5.4) → Reviewer (gpt-5.4-mini) per lesson. Sequential per-lesson invariant — next lesson starts only after current hits `finished/`. Sub-agents communicate via filesystem (`~/.wiedunflow/runs/<run_id>/{processing,finished,raw,transcript}/`).
- **Model routing** (default OpenAI): `llm.models.{orchestrator: gpt-5.4, researcher: gpt-5.4-mini, writer: gpt-5.4, reviewer: gpt-5.4-mini}`. Anthropic BYOK alternative: `claude-sonnet-4-6` orch + `claude-haiku-4-5` research/review + `claude-opus-4-7` writer.
- **Structured output** (terminal tools with JSON Schema enforced by provider): `submit_verdict` (Reviewer) and `submit_lesson_draft` (Writer). Eliminates malformed-JSON failure mode. Schema enforce'd by OpenAI Structured Outputs / Anthropic tool use natively.
- **Cost guard triple-backstop**: pre-flight estimator (CLI cost gate) → live `SpendMeter.charge()` per call → per-lesson `max_cost_usd` cap on `run_agent()`. `would_exceed()` aborts mid-loop.
- **Concurrency**: Stage 5/6 runs sequentially per lesson (`concepts_introduced` coherence). Stage 4 (Planning) is single Sonnet call. Pre-Stage-4 leaf descriptions can use parallel Haiku (legacy v0.7.0 path, deprecated in v0.9.0 multi-agent flow).
- **BYOK**: OpenAI SDK (default), Anthropic SDK, OSS endpoints via httpx-based OpenAI-compatible client with `base_url` override. Provider-specific fields (OpenRouter reasoning, DeepSeek `reasoning_content`) require dedicated adapters and are **v2**.
- **Orchestrator state** (canonical shape): `_OrchestratorState{lesson_id, result, research_counter, writer_counter, research_paths, last_draft_path}`. Per-lesson scope. Global `concepts_introduced` propagated to each `run_lesson()` call.
- **Checkpointing**: `finished/lesson-N/lesson.json` is atomic checkpoint (`os.replace`). `--resume` scans `finished/` listing and skips already-completed lessons.
- **Anti-hallucination guardrails (4 layers)**: (1) tool-grounded only — Writer/Reviewer cite only research-notes symbols; (2) snippet_validator (legacy v0.2.1) preserved as Reviewer's rubric check #2; (3) Reviewer 6-check rubric (`grounding`/`snippet_match`/`word_count`/`no_re_teach`/`uncertainty_flag`/`audience_fit`) returned as `submit_verdict` structured args; (4) audit trail in `transcript/lesson-N/*.jsonl` for replay.

## GROUNDING_AND_COHERENCE

- **Hybrid grounding (hard rule)**: every function/class/module name referenced in an LLM-generated lesson must exist in the AST snapshot from Stage 1. Post-hoc validation in the `entities` layer rejects any lesson that references a non-existent symbol; the generator retries with a grounding-focused prompt. Target: **0 hallucinated symbols** in output.
- **Source-excerpt injection (v0.2.1)**: for every primary `code_ref` whose body span is <30 lines, populate `source_excerpt` from the AST snapshot before sending to the narration LLM. This eliminates signature hallucinations (the v0.2.0 root cause: LLM received only `{symbol, file, line_start, line_end, role}` and had to guess bodies). See `use_cases/inject_source_excerpts.py`.
- **Snippet validation (v0.2.1, gated by `narration.snippet_validation`)**: post-narration, parse ```python fenced blocks and compare regex-matched `def` lines against `source_excerpt`. Signature mismatches trigger a 1-shot retry with explicit hint `"You quoted: 'def {bad}' — actual signature is 'def {real}'"`. Lenient on body abbreviation, strict on function name + parameter token list. See `use_cases/snippet_validator.py`.
- **Happy-path lesson ordering (v0.2.1, `planning.entry_point_first: auto`)**: post-planning reorder hook moves the entry-point lesson (`def main`/`def cli`/`__main__.py`/`@click.command`/`if __name__ == "__main__":` block) to position 1. Mode `auto` is a no-op when no entry point is detected; `never` preserves raw leaves→roots. See `use_cases/entry_point_detector.py` and `_apply_entry_point_first` in `plan_lesson_manifest.py`.
- **Narrative coherence**: lesson N must not re-teach what lessons 1..N-1 already covered. Enforced via `concepts_introduced` — correctness invariant, not polish.
- **Word-count tiers (v0.2.1)**: narration floor scales with primary `code_ref` body span — 1 line = `narration.min_words_trivial` (default 50), 2-9 lines = 80, 10-30 = 220, >30 = 350. Replaces the v0.2.0 hardcoded 150 that forced bloated narration for one-liners.
- **Skip trivial helpers (v0.2.1, opt-in via `planning.skip_trivial_helpers: true`)**: drop lessons whose primary ref is <3 lines AND not cited as primary elsewhere AND not entry point AND not top-5% PageRank. Skipped helpers folded into closing-lesson "Helper functions you'll see along the way" appendix.
- **Uncertainty markers**: dynamic imports, reflection, runtime polymorphism, and unresolved Jedi references must be flagged `uncertain` in AST metadata and narrated as such (e.g. "this dispatch happens at runtime — see actual callers"). Do not guess resolution.

## EDGE_CASES

- **Cycles in the call graph**: detect via `networkx` and render as one "interdependent modules" cluster. Non-negotiable — without this the topological sort loops.
- **Dynamic imports / reflection / metaclasses**: mark `uncertain`, do not attempt to resolve. Proper type inference is explicitly OUT of MVP scope (v2+).
- **Large repos**: soft-warn at >500 files; hard limit / aggressive pruning at >1000 (pending PRD resolution). Lazy-render lessons in the HTML if the embedded JSON approaches 20 MB.
- **Max lessons**: hard cap at 30 (`tutorial.max_lessons` default) — truncation is preferable to incoherent narrative.

## CACHE

- **Invalidation granularity**: file-level SHA-256 hash. Unchanged files reuse AST, call-graph slice, embeddings, and LLM-generated descriptions verbatim.
- **Storage**: SQLite in a platform-appropriate cache dir (via `platformdirs`), keyed by repo root + commit hash.
- **Incremental guarantee**: second run with <20% of files changed must finish in <5 min. Regressions are bugs — the cache layer owns the fix.
- **Schema evolution**: any cache schema change requires an ADR under `/docs/adr/` with a forward migration.
- **Wiring status (as of v0.9.3)**: `file_cache` table is wired through `TreeSitterParser.parse(..., cache=)` — per-file SHA-256 lookup, hit/miss flow with JSON payload (`Cache.get_file_cache` / `save_file_cache` on the Protocol). `JediResolver` cache is **not yet wired** — cross-file resolved edges need a separate invariant story (planned ADR-0008 amendment, follow-up release). `Cache` Protocol now requires `get_file_cache` / `save_file_cache` methods; both `SQLiteCache` and `InMemoryCache` implement them.

## PERFORMANCE_BUDGETS

| Metric | MVP target | Hard fail |
|---|---|---|
| First run (medium repo) | <30 min | — |
| Incremental run (<20% files changed) | <5 min | — |
| Generation cost per tutorial | <$8 | — |
| Output HTML size (medium repo) | <8 MB | warn at >20 MB |
| Concept coverage vs hand-written reference | ≥70% | — |
| Hallucinated symbols in output | 0 | any occurrence is a regression |

## CLI_UX

- **Entry point**: `[project.scripts]` in `pyproject.toml` exposes the CLI (e.g. `wiedunflow = "wiedunflow.cli:main"`).
- **Output filename**: default `wiedunflow-<repo>.html` in cwd. `<repo-name>-tutorial-<short-commit>.html` is an opt-in flag (better for sharing in Slack).
- **Progress reporting**: stage-level progress bar (7 stages) + LLM call counter. Structured JSON logs behind `--log-format json`; never `print()` in the pipeline.
- **Config resolution order**: CLI flags → `--config <path>` → `./tutorial.config.yaml` → defaults. User `exclude`/`include` patterns are additive over `.gitignore`.
- **Resume**: next run after a crash auto-detects the checkpoint and prompts to resume; `--resume` / `--no-resume` overrides.
- **Audience default**: `tutorial.target_audience = "mid-level Python developer"`; narration language is English-only in MVP (do not add i18n scaffolding speculatively).
- **Output metadata**: footer of the generated HTML must include `commit_hash`, `branch`, `generated_at`, and the WiedunFlow version — this is the tutorial versioning contract.

## EVAL

- **Benchmark corpus**: official Python MCP SDK (https://github.com/modelcontextprotocol/python-sdk) vs Anthropic Skilljar "Building MCP Clients". Keep the reference concept list and expected coverage in `tests/eval/corpus/mcp_python_sdk.yaml`.
- **Robustness set**: 5 randomly chosen OSS Python repos — tool must not crash, uncertain regions must be labeled not hallucinated.
- **Quality gate for releases**: run `pytest -m eval` before tagging `v*.*.*`. Requires a real API key; never run in the default CI matrix.

## PRIVACY_AND_SECURITY

- MVP is 100% offline apart from LLM API calls. **No telemetry, no usage analytics, not even opt-in.** Any PR that adds network calls outside the configured LLM provider is a breaking product change.
- README must prominently document that source code is transmitted to the configured LLM provider. For sensitive code, document Ollama / LM Studio / vLLM as the local-inference path.
- Never log full source bodies at `INFO` level; structured logs include symbol names and file hashes, not verbatim code.
- Treat `tutorial.config.yaml` and env vars as the only legitimate places for API keys — never read from shell history, dotfiles, or OS keychains in MVP.

## UX

WiedunFlow ma dwie user-facing surfaces: CLI (`wiedunflow init` terminal output) i generated `wiedunflow-<repo>.html` (offline reader). Pełna spec w `.ai/ux-spec.md`; binarne decyzje zakotwiczone w ADR-0011.

**Triggery**:
- Edytujesz `src/wiedunflow/renderer/templates/**` (Jinja2, CSS)
- Edytujesz `src/wiedunflow/cli/**` (rich output, stage rendering, cost gate, run report)
- Design change request ("zmień kolor", "dodaj komponent", "przenieś panel")

**Core rules** (non-negotiable bez nowego ADR):
- **Tutorial reader**: A1 Paper palette only (dove white + graphite), Inter body font only, JetBrains Mono for code, Direction A layout, topbar najciemniejszy / narration najjaśniejszy (~20% closer to white).
- **CLI**: Modern direction, color roles `good/warn/err/accent/link/dim/default/prompt` mapowane na `rich.style.Style`. Stage headers `[N/7] <Name>`, detail lines indented 5 spaces, `✓ done · <summary>` na końcu stage. **Animations wired in v0.2.0+** — Stage 2 = replace-line, Stage 6 = scrolling event log, LLM stages = live counters footer (`.ai/ux-spec.md §4.5.1`). Stage names używają obecnego pipeline (Ingestion / Analysis / Graph / RAG / Planning / Generation / Build), NIE spec'owych nazw §4.5 (które są wishful v0.5+).
- **Cost-gate prompt**: domyślnie ON dla TTY w v0.2.0+. Bypass: `--yes`, `--no-cost-prompt`, non-TTY (`stdin.isatty() == False`). ADR-0011 decision 9.
- **Offline HTML**: fonts WOFF2 self-hosted inline, Pygments pre-rendered, vanilla JS (no Preact), wszystko w jednym pliku HTML.
- **Exact copy**: CLI stage output, cost gate text, error scenarios — literalnie per `.ai/ux-spec.md` §CLI (źródło: `.claude/skills/wiedunflow-ux-skill/reference/cli/design/cli-session-data.js`).
- **localStorage keys**: `wiedunflow:<repo>:last-lesson`, `wiedunflow:tweak:theme:v2`, `wiedunflow:tweak:narr-frac:v2`. Namespace `wiedunflow:*` jest zarezerwowany.
- **Three-sink rule (Sprint 5 #6 + ADR-0013)**: rich imports MUSZĄ być TYLKO w `cli/output.py`; questionary imports MUSZĄ być TYLKO w `cli/menu.py`; plain `print()` w `cli/menu_banner.py` (i wszędzie indziej dla diagnostyki). `stage_reporter.py` używa opaque `LiveStageHandle`; `cost_gate.py` przyjmuje `confirm_fn: Callable | None` zamiast `import questionary`; `cli/main.py` traktuje console jako `object`. Testy `test_no_rich_outside_output.py` + `test_no_questionary_outside_menu.py` enforce'ują to.
- **Hybrid CLI / TUI (ADR-0013, v0.4.0+)**: bare `wiedunflow` w TTY → menu (`menu.main_menu_loop`). `wiedunflow generate <repo>` / `wiedunflow init` / non-TTY / `WIEDUNFLOW_NO_MENU=1` → existing Click group bit-exact. Menu nie odpala się bez TTY na stdout AND stdin (Sprint 7 eval workflow polega na tym).

**Critical anti-patterns**:
- ❌ Preact, React, Astro, bundler — vanilla JS binarnie (ADR-0005)
- ❌ External CDN fonts, runtime Pygments/highlight.js
- ❌ A2/A3 palette, direction B, serif/mono body font, Minimal CLI, Retro ASCII (dropped w ADR-0011)
- ❌ Port HTML/CSS/JS z prototypu skilla — to tylko reference; template wdrażamy w Jinja2
- ❌ Nowy komponent UX bez aktualizacji `.ai/ux-spec.md` i matching FR/US

**Pixel-perfect rule**: wszystkie CSS wartości (px, oklch, line-height, letter-spacing) muszą matchować ux-spec — Playwright visual regression test golden-snapshot w S5 blokuje regresje.

> Szczegóły: `.ai/ux-spec.md` (design tokens, per-komponent specs, exact CLI copy, state management, JSON schema)
> ADR: `docs/adr/0011-ux-design-system.md` (binarne decyzje)
> Reference: `.claude/skills/wiedunflow-ux-skill/` (hi-fi prototypes + READMEs — DO NOT port JS/CSS directly)

## ADR_INDEX

Aktualne architectural decision records (w `docs/adr/`):

- **ADR-0001** — LLM stack: wycięcie LangChain/LangGraph, bezpośrednie SDK za portem `LLMProvider` (2026-04-16).
- **ADR-0002** — RAG w MVP: BM25 (`rank_bm25`) zamiast sqlite-vec + embeddings (2026-04-16).
- **ADR-0003** — Clean Architecture layering: entities/use_cases/interfaces/adapters/cli (2026-04-20).
- **ADR-0004** — UV-exclusive toolchain: pip/pipx/poetry/hatch wykluczone (2026-04-20).
- **ADR-0005** — Frozen vanilla JS output: zero Preact/React/Astro/bundlera w HTML (2026-04-20).
- **ADR-0006** — AST snapshot schema: `(IngestionResult, CallGraph, RankedGraph)` triple z invariantami Pydantic jako grounding contract dla Stage 1-3 (2026-04-20).
- **ADR-0007** — Planning prompt contract (Stage 4): Sonnet 4.6 single call, grounding invariant, 1-retry, fatal fail (2026-04-20; revised 2026-04-25 for v0.2.1 — additive `source_excerpt` + happy-path heuristic).
- **ADR-0008** — Cache schema v1: SQLite + WAL, `(repo_abs, commit, lesson_id)` key bez modelu, checkpoint row per lekcja, no-JSON1 design (2026-04-21; parser cache wired in v0.9.3, resolver cache pending v0.10 amendment).
- **ADR-0009** — Output JSON envelope schema v1: `<script type="application/json" id="tutorial-lessons">` block embedded w HTML, contract dla offline reader + post-hoc tooling (commit hash, branch, generated_at, lessons array) (2026-04-21).
- **ADR-0010** — Secret redaction policy + zero-telemetry contract: 7 binary decisions (pattern-only regex, structlog processor scope, separate `consent.yaml`, per-provider persistence, 9-pattern hard-refuse list, dual-layer zero-telemetry test, editor resolver shlex+which+metachar validation) (2026-04-22; amended 2026-05-05 with §D11 — 12-pattern log redaction catalog: Anthropic/OpenAI/HF/Bearer/Auth/hex + AWS AKIA/AWS Secret/GitHub PAT/GitHub fine-grained PAT/PEM private key, v0.9.6 redaction extension).
- **ADR-0011** — UX design system: A1 Paper only, Inter only, Direction A only, Modern CLI only (2026-04-19; +decisions 8 (CLI animation strategy) and 9 (cost-gate default ON for TTY) added Sprint 8 / 2026-04-25).
- **ADR-0012** — Tutorial quality enforcement: `source_excerpt` injection, snippet validator, happy-path ordering, per-tier word counts, skip-trivial helpers (2026-04-25, v0.2.1).
- **ADR-0013** — Interactive menu-driven TUI ("centrum dowodzenia"): hybrid CLI/menu, questionary 2.x, three-sink rule, modal pipeline, `MenuIO` Protocol, 5-section Generate sub-wizard, dynamic `ModelCatalog` port (anthropic/openai SDK fetch + `ft:*` filter + 24h cache), `target_audience` 5-level enum (BREAKING + migration shim), `gpt-4.1` as OpenAI default. Partially supersedes ADR-0011 D#1 (2026-04-25, v0.4.0).
- **ADR-0014** — Dynamic pricing catalog: `PricingCatalog` port + 4 adapters (Static/LiteLLM/Cached/Chained), httpx as explicit hard dep (NIE optional — tautologia po projektowych dyskusjach), three-sink rule extension dla httpx (2026-04-26, v0.5.0).
- **ADR-0015** — Default LLM provider switch from Anthropic to OpenAI (gpt-5.4 + gpt-5.4-mini). Anthropic stays as 100% supported BYOK alternative via config `llm.provider: anthropic` (2026-04-26, v0.7.0).
- **ADR-0016** — Multi-agent narration pipeline (Orchestrator → Researcher × N → Writer → Reviewer): replaces single-shot narrate() with per-lesson agentic loop, structured output via tool calls, filesystem-mediated workspace, sequential per-lesson invariant for concepts_introduced coherence (2026-05-02, v0.9.0 BREAKING).
- **ADR-0017** — Cost reporting wire-through: SpendMeter created in _run_pipeline, propagated through generate_tutorial → run_lesson → llm.run_agent. Adapter providers charge per-call. RunReport.total_cost_usd and CLI banner now show real cost (2026-05-02, v0.9.0).
- **ADR-0018** — Jedi heuristic call graph fallback: when infer() returns empty, last-component name match in AST symbol_by_name. Single match → resolved_heuristic; ambiguous → uncertain + candidates; zero → unresolved. Tier 1 venv detection layered above (`.venv/` > `venv/` > `env/`) (2026-05-02, v0.9.0).
- **ADR-0019** — Brand unification: drop `wiedun-flow`, single canonical `wiedunflow` token everywhere (CLI command, docstrings, prose). `WiedunFlow` CamelCase preserved as proper-noun brand display in prose. Supersedes ADR-0013 §1 (CLI command name) (2026-05-02, v0.9.1 BREAKING — pre-PyPI window, zero user impact).
- **ADR-0020** — Per-token pricing in `PricingCatalog`: `blended_price_per_mtok` → `prices_per_mtok() -> tuple[float, float] | None` (input, output per 1M tokens). `SpendMeter` applies the two rates separately so live cost reporting matches provider invoices within ~5% (was ~30-60% under-report). `cost_estimator.MODEL_PRICES` values change from `float` to `tuple`; preflight estimator composes blended on demand. Refines ADR-0014 §pricing (2026-05-04, v0.9.5 BREAKING — internal Protocol only, no external implementations).
