# AI Rules for CodeGuide

CodeGuide is a Python CLI that turns a local Git repository into a single, self-contained HTML file acting as an interactive, tutorial-style guided tour of the code — opened directly in the browser via `file://`, with no server and no runtime dependencies on the recipient's side. Pipeline: tree-sitter + Jedi → PageRank graph → BM25 RAG → direct-SDK LLM orchestration (BYOK: Anthropic/OpenAI/Ollama) → Jinja2 + Pygments → one HTML. Full product spec: `.ai/mvp-codeguide.md`.

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
- Lint + format: `ruff` (lint + format) as the single source of truth; `mypy --strict` on `src/codeguide/**`
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
6. **Generation** (`generation`): own orchestrator (`use_cases/generate_tutorial.py`); Haiku parallel for leaf-function descriptions, Opus sequential for lesson narration with full prior-lesson context. Checkpoint after every lesson.
7. **Build** (`build`): Pygments pre-rendering, Jinja2 template, inline everything into one HTML.

## LLM_ORCHESTRATION

- **Model routing (default)**: `claude-haiku-4-5` for per-symbol leaf descriptions (parallel), **`claude-opus-4-7`** for lesson narration (sequential, carries `concepts_introduced`). Users may switch to `claude-sonnet-4-6` in `tutorial.config.yaml` for lower cost.
- **Concurrency**: default 10, hard cap 20; configurable via `llm.concurrency` in `tutorial.config.yaml`. Exponential backoff on provider rate limits (Anthropic 429, OpenAI 429).
- **BYOK**: Anthropic SDK (default), OpenAI SDK, OSS endpoints via httpx-based OpenAI-compatible client with `base_url` override. Provider-specific fields (OpenRouter reasoning, DeepSeek `reasoning_content`) require dedicated adapters and are **v2**.
- **Orchestrator state** (canonical shape): `{explored_symbols, lessons_generated, concepts_introduced}`. Every narration prompt for lesson N must be fed `concepts_introduced` so it does not re-teach prior material. Do not rely on the LLM to "remember" coherence — it must come from structured state.
- **Checkpointing**: persist orchestrator state (one SQLite row per completed lesson) so `--resume` continues from the last checkpoint after crash/Ctrl+C.

## GROUNDING_AND_COHERENCE

- **Hybrid grounding (hard rule)**: every function/class/module name referenced in an LLM-generated lesson must exist in the AST snapshot from Stage 1. Post-hoc validation in the `entities` layer rejects any lesson that references a non-existent symbol; the generator retries with a grounding-focused prompt. Target: **0 hallucinated symbols** in output.
- **Narrative coherence**: lesson N must not re-teach what lessons 1..N-1 already covered. Enforced via `concepts_introduced` — correctness invariant, not polish.
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

- **Entry point**: `[project.scripts]` in `pyproject.toml` exposes the CLI (e.g. `codeguide = "codeguide.cli:main"`).
- **Output filename**: default `tutorial.html` in cwd. `<repo-name>-tutorial-<short-commit>.html` is an opt-in flag (better for sharing in Slack).
- **Progress reporting**: stage-level progress bar (7 stages) + LLM call counter. Structured JSON logs behind `--log-format json`; never `print()` in the pipeline.
- **Config resolution order**: CLI flags → `--config <path>` → `./tutorial.config.yaml` → defaults. User `exclude`/`include` patterns are additive over `.gitignore`.
- **Resume**: next run after a crash auto-detects the checkpoint and prompts to resume; `--resume` / `--no-resume` overrides.
- **Audience default**: `tutorial.target_audience = "mid-level Python developer"`; narration language is English-only in MVP (do not add i18n scaffolding speculatively).
- **Output metadata**: footer of the generated HTML must include `commit_hash`, `branch`, `generated_at`, and the CodeGuide version — this is the tutorial versioning contract.

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

CodeGuide ma dwie user-facing surfaces: CLI (`codeguide init` terminal output) i generated `tutorial.html` (offline reader). Pełna spec w `.ai/ux-spec.md`; binarne decyzje zakotwiczone w ADR-0011.

**Triggery**:
- Edytujesz `src/codeguide/renderer/templates/**` (Jinja2, CSS)
- Edytujesz `src/codeguide/cli/**` (rich output, stage rendering, cost gate, run report)
- Design change request ("zmień kolor", "dodaj komponent", "przenieś panel")

**Core rules** (non-negotiable bez nowego ADR):
- **Tutorial reader**: A1 Paper palette only (dove white + graphite), Inter body font only, JetBrains Mono for code, Direction A layout, topbar najciemniejszy / narration najjaśniejszy (~20% closer to white).
- **CLI**: Modern direction, color roles `good/warn/err/accent/link/dim/default/prompt` mapowane na `rich.style.Style`. Stage headers `[N/7] <Name>`, detail lines indented 5 spaces, `✓ done · <summary>` na końcu stage.
- **Offline HTML**: fonts WOFF2 self-hosted inline, Pygments pre-rendered, vanilla JS (no Preact), wszystko w jednym pliku HTML.
- **Exact copy**: CLI stage output, cost gate text, error scenarios — literalnie per `.ai/ux-spec.md` §CLI (źródło: `.claude/skills/codeguide-ux-skill/reference/cli/design/cli-session-data.js`).
- **localStorage keys**: `codeguide:<repo>:last-lesson`, `codeguide:tweak:theme:v2`, `codeguide:tweak:narr-frac:v2`. Namespace `codeguide:*` jest zarezerwowany.

**Critical anti-patterns**:
- ❌ Preact, React, Astro, bundler — vanilla JS binarnie (ADR-0005)
- ❌ External CDN fonts, runtime Pygments/highlight.js
- ❌ A2/A3 palette, direction B, serif/mono body font, Minimal CLI, Retro ASCII (dropped w ADR-0011)
- ❌ Port HTML/CSS/JS z prototypu skilla — to tylko reference; template wdrażamy w Jinja2
- ❌ Nowy komponent UX bez aktualizacji `.ai/ux-spec.md` i matching FR/US

**Pixel-perfect rule**: wszystkie CSS wartości (px, oklch, line-height, letter-spacing) muszą matchować ux-spec — Playwright visual regression test golden-snapshot w S5 blokuje regresje.

> Szczegóły: `.ai/ux-spec.md` (design tokens, per-komponent specs, exact CLI copy, state management, JSON schema)
> ADR: `docs/adr/0011-ux-design-system.md` (binarne decyzje)
> Reference: `.claude/skills/codeguide-ux-skill/` (hi-fi prototypes + READMEs — DO NOT port JS/CSS directly)

## ADR_INDEX

Aktualne architectural decision records (w `docs/adr/`):

- **ADR-0001** — LLM stack: wycięcie LangChain/LangGraph, bezpośrednie SDK za portem `LLMProvider` (2026-04-16).
- **ADR-0002** — RAG w MVP: BM25 (`rank_bm25`) zamiast sqlite-vec + embeddings (2026-04-16).
- **ADR-0003** — Clean Architecture layering: entities/use_cases/interfaces/adapters/cli (2026-04-20).
- **ADR-0004** — UV-exclusive toolchain: pip/pipx/poetry/hatch wykluczone (2026-04-20).
- **ADR-0005** — Frozen vanilla JS output: zero Preact/React/Astro/bundlera w HTML (2026-04-20).
- **ADR-0011** — UX design system: A1 Paper only, Inter only, Direction A only, Modern CLI only (2026-04-19).
