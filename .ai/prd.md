# Product Requirements Document (PRD) - WiedunFlow

Document version: 0.1.3-draft
Last updated: 2026-04-26
Owner: Michał Kamiński
Target release: WiedunFlow v0.6.0 (Rebranding from WiedunFlow)

> **Version note (2026-04-26)**: Specification is iterative. Version bump from 0.1.0 → 0.1.3 reflects Sprint 9 additions (repo picker, pricing catalog).

## 1. Product Overview

**WiedunFlow** is a Python 3.11+ command-line tool that transforms a local Git repository into a single, self-contained, offline-capable HTML file delivering an interactive, tutorial-style guided tour of the codebase. The output opens directly in any modern browser via `file://` — no server, no runtime dependencies on the recipient's side, no network calls after generation.

The generation pipeline is seven ordered stages:

1. Ingestion — language detection, docs discovery, file hashing, cache lookup, `.gitignore` enforcement.
2. Static analysis — `tree-sitter-python` AST, `Jedi`-resolved call graph, docstrings, type hints, entry points, cycle detection, dynamic-import flagging.
3. Graph ranking — `networkx` PageRank, community detection, topological sort leaves-to-roots.
4. Documentation indexing — BM25 (rank_bm25) over docstrings, README.md, docs/**/*.md, CONTRIBUTING.md, commit messages, inline comments.
5. Lesson planning — one Sonnet call returns a `lesson_manifest` JSON.
6. Content generation — custom orchestrator over the LLMProvider port with structured state (explored_symbols, lessons_generated, concepts_introduced); Haiku 4.5 in parallel for leaf-function descriptions, Opus 4.7 sequential for lesson narration. Checkpoint after every lesson via SQLite.
7. Artifact build — `Pygments` pre-rendering, `Jinja2` template, full inlining into one HTML.

Distribution is a bare Git repository installable via `uvx wiedun-flow`. No PyPI release is part of the MVP. The toolchain is UV-exclusive; `pip` and `pipx` are not supported anywhere in the project.

The product is licensed under Apache 2.0. Contribution is governed by the Developer Certificate of Origin (DCO) enforced as a GitHub Action, not by a CLA.

Primary persona: a developer who sits down to an unfamiliar repository (open source or corporate) and wants to understand it for themselves. Not a maintainer authoring onboarding material. Every UX trade-off favors time-to-first-tutorial over sharing or collaboration features.

Bring-your-own-key (BYOK) providers supported in MVP: Anthropic (default), OpenAI, and OpenAI-compatible OSS endpoints (Ollama, LM Studio, vLLM) via a direct httpx-based OpenAI-compatible client with a base_url override. Provider-specific reasoning fields (OpenRouter, DeepSeek) are explicitly v2.

CLI language and tutorial narration language are English only in MVP.

## 2. User Problem

Onboarding a developer to a medium or large repository currently takes days or weeks. Existing developer tools fall into two buckets, neither of which solves the problem:

- Code-writing assistants (Cursor, Sourcegraph Cody, Aider) help a developer write new code against an existing codebase, but they do not teach the existing code in a course format. The developer still has to construct a mental model on their own by reading source files in a non-pedagogical order.
- Manual tutorial authoring tools (Swimm, CodeTour) produce high-quality guided tours, but only when a senior engineer spends days writing them. The manually authored tutorials drift out of sync with the code shortly after publication, and most repositories never get such a tutorial in the first place.

There is no tool that automatically generates an interactive, tutorial-style guided tour of an arbitrary repository, in the style of structured courseware such as Anthropic Skilljar, without manual authorship.

The concrete pain this causes the primary persona (developer exploring an unfamiliar repository for themselves):

- No canonical reading order. The developer has to decide where to start and what is important, without knowing the code.
- No narrative. Source files explain what the code does; they do not explain why the architecture is shaped that way or how features compose.
- Fragmented context. Docstrings, README, `CONTRIBUTING.md`, commit messages, and inline comments all contain partial explanations that the developer must stitch together manually.
- Time pressure. Developers exploring an unfamiliar codebase are usually on a deadline (investigating an open-source library before adopting it, joining a new project, debugging a vendor integration). Multi-day exploration does not fit the window.

WiedunFlow addresses this by producing a single HTML tutorial that orders lessons pedagogically (leaves to roots, guided by PageRank and community detection), grounds every symbol reference in the AST, and embeds narration explaining both what the code does and why. The tutorial is shareable as a single file, works offline forever, and versioned against the exact commit it was generated from.

Detailed UX specification (design tokens, exact CLI copy, component dimensions, state-management contracts) lives in `.ai/ux-spec.md`, anchored by ADR-0011 binary design decisions.

## 3. Functional Requirements

### 3.1 Installation and distribution

FR-01. The project is distributed as a bare Git repository. The documented install path is `uvx wiedun-flow`.
FR-02. The toolchain is UV-exclusive. `pyproject.toml` uses `[tool.uv]` configuration. `uv sync` is the documented dev-setup command. All documentation, CI, and example snippets reference `uv` or `uvx`. `pip`, `pipx`, `poetry`, and `hatch` are not used anywhere.
FR-03. No PyPI package is published as part of the MVP. A PyPI release is explicitly deferred to v2.
FR-04. The CI matrix runs on Python 3.11, 3.12, 3.13 across Ubuntu, Windows, and macOS. UV is installed via `astral-sh/setup-uv`.

### 3.2 First-run setup and configuration

FR-05. A `wiedun-flow init` wizard interactively collects provider, model, and API key on first use and writes a user-level config (`~/.config/wiedunflow/config.yaml` on Linux/macOS, `%APPDATA%\wiedunflow\config.yaml` on Windows).
FR-06. Configuration precedence, highest to lowest, is: CLI flags > environment variables > `--config <path>` > `./tutorial.config.yaml` > user-level config > built-in defaults. The chain is documented verbatim in the README.
FR-07. The wizard is optional. CI and power users may skip it entirely by supplying the same settings via CLI flags or environment variables.
FR-08. `tutorial.config.yaml` is validated by a `pydantic.BaseModel`. Invalid fields produce actionable error messages referencing the offending path.

### 3.3 Privacy, consent, and secret protection

FR-09. A hard-refuse file list is applied before any content leaves the process: `.env*`, `*.pem`, `*_rsa`, `*_rsa.pub`, `*_ed25519`, `credentials.*`, `id_rsa`, `id_ed25519`. These patterns are enforced even if the files are not listed in `.gitignore`.
FR-10. On the first run against a cloud provider (Anthropic or OpenAI), a blocking consent banner is displayed before any source code leaves the process: "Your source code will be sent to <provider>. Continue? [y/N]". The run is aborted if the user declines.
FR-11. Consent, once accepted, is persisted per-provider in the user-level config as `consent.<provider>: accepted`. The banner is not shown again for that provider on that machine regardless of which repository is being processed.
FR-12. `--no-consent-prompt` bypasses the banner for scripted usage. The flag has no effect on the hard-refuse list.
FR-13. No telemetry of any kind is emitted. No analytics, no opt-in usage reporting, no crash reports phoned home. The only outbound network calls are to the configured LLM provider.
FR-14. The output HTML performs zero network calls: no `fetch()`, no `Image()`, no `<link rel="prefetch">`, no external CDN. A template-time linter fails the build if any of these tokens appear in the final artifact.

### 3.4 Cost and time estimation

FR-15. Before Stage 4 (planning), a heuristic cost and time estimate is displayed ("X files, ~$Y cost, ~Z minutes") and a `y/N` confirmation is required.
FR-16. The estimation formula is purely heuristic — no pre-flight LLM calls. Formula: cost ≈ (symbols × 500 tokens × $haiku_price) + (lessons × 8000 tokens × $opus_price) multiplied by 1.3 for variance buffer. The formula is documented in the README so users can verify it.
FR-17. `--yes` bypasses the confirmation for CI and scripted usage.

### 3.5 Run modes

FR-18. Default mode executes all seven pipeline stages and produces `wiedunflow-<repo>.html` in the current working directory.
FR-19. `--dry-run` executes Stages 0 through 4 inclusive (including the Stage 4 Sonnet planning call, approximately $0.05 cost), skips Stage 5 and Stage 6, and writes `wiedunflow-<repo>-preview.html` containing proposed lesson titles, the final cost estimate, and a graph-structure visualization.
FR-20. `--review-plan` opens the generated `lesson_manifest` in the user's editor between Stage 4 and Stage 5. The editor is resolved in this order: `$EDITOR` → `$VISUAL` → `code --wait` (if available on PATH) → `notepad` (Windows fallback) / `vi` (Unix fallback). The user may delete lessons, reorder them, and edit titles and descriptions. On save, the pipeline resumes with the edited manifest. The editor binary is launched via subprocess with shell=False and shlex-split arguments; a malformed $EDITOR/$VISUAL value falls back to the next resolver step rather than being shell-interpreted (see FR-79).
FR-21. `--resume` continues from the last checkpoint, skipping already-cached lessons.
FR-22. `--regenerate-plan` discards the cached `lesson_manifest` and forces regeneration.
FR-23. `--max-cost=<USD>` applies a hard budget cap. After each lesson, accumulated cost is compared to the cap; on overrun the pipeline checkpoints, writes the run report, and exits with a "Generated N/M lessons. Resume with --resume --max-cost=X" message.
FR-24. `--cache-path=<path>` overrides the default cache location for power users.
FR-25. `--root=<path>` overrides the auto-detected Python subtree in monorepos.
FR-26. `--log-format=json` emits structured logs; default is human-readable. All logs pass through a SecretFilter (see FR-80) which redacts file paths and token-like substrings before emission.

FR-81. Cost gate presented as a boxed panel (`rich.panel`) with model / stage / estimated-tokens / estimated-cost columns; default answer is No. Prompt: `Proceed? [y/N]`. On No: print `aborted by user. no API calls were made.` and `total cost: $0.00 · elapsed MM:SS`, exit 0. Exact copy and layout per `.ai/ux-spec.md` §CLI.cost-gate.

FR-82. Stage output uses `[N/7] <Stage name>` headers (accent color), 5-space indented detail lines, and a final `  ✓ done · <summary>` per stage (good color). Live counters (elapsed MM:SS, cumulative cost $X.XX, tokens in/out) are displayed during all LLM stages. Exact copy and color roles per `.ai/ux-spec.md` §CLI.stages and §CLI.color-roles.

### 3.6 Incremental runs

FR-27. On re-run, the tool computes a PageRank-graph structural diff versus the previous run. If more than 20% of the top-ranked symbols changed, the full `lesson_manifest` is regenerated. Otherwise the manifest is reused and only lessons touching changed files are regenerated.
FR-28. Cache is keyed by <repo_absolute_path>+<commit_hash>. Unchanged files reuse their AST, call-graph slice, BM25 document vectors, and LLM-generated descriptions verbatim.
FR-29. Cache invalidation granularity is per-file via SHA-256.
FR-30. Cache location uses `platformdirs` per-user paths: `~/.cache/wiedunflow/` (Linux), `%LOCALAPPDATA%\wiedunflow\Cache` (Windows), `~/Library/Caches/wiedunflow` (macOS). Cross-platform correctness is a hard requirement.
FR-31. An incremental run with fewer than 20% of files changed completes in under 5 minutes. Regressions against this target are release blockers.

### 3.7 Lesson contract and grounding

FR-32. Each lesson contains 150 to 1200 words of narration. Lessons below 150 words are rejected by the post-hoc validator and trigger regeneration. Lessons above 1200 words are truncated at a sentence boundary.
FR-33. Prompt guidance to the narration LLM: "3–8 paragraphs, 2–4 minutes reading time".
FR-34. Each lesson exposes `estimated_read_time_minutes` in its JSON metadata.
FR-35. Each lesson exposes `code_refs[]`, an array of objects with the schema `{file_path, symbol, line_start, line_end, role}` where `role ∈ {primary, referenced, example}`. Line ranges are optional in MVP.
FR-36. Every `symbol` in `code_refs[]` must exist in the Stage 1 AST snapshot. This is the sole enforcement point for grounding validation.
FR-37. On grounding failure, a single retry is attempted with an explicit prompt: "Your previous response referenced these non-existent symbols: [X, Y]. Rewrite the lesson using ONLY symbols from this AST slice: [allowed_symbols]."
FR-38. If the retry also fails, the lesson is skipped and replaced with a placeholder block in the output HTML: "This lesson was skipped due to grounding failures — see symbol X in the code". `skipped_lessons_count` is exposed in footer metadata and the run report.
FR-39. A tutorial may contain at most 30 lessons. The cap is configurable via `tutorial.max_lessons` and truncation is preferred to incoherent narrative.
FR-40. The final lesson is a "Where to go next" lesson generated by one additional Sonnet call at the end of Stage 5. It contains external doc links parsed from `README.md`, the top five highest-ranked files omitted from lessons, and `git log` hints about actively changing subdirectories.

### 3.8 Degraded-run policy

FR-41. Pipeline stages never abort the full run on partial failure. Skipped lessons, reduced Jedi resolution coverage, and missing documentation are all graceful degradations surfaced in the run report and the HTML footer.
FR-42. If more than 30% of planned lessons are skipped due to grounding failures, the run is marked `DEGRADED`, `run-report.json` sets `status: "degraded"`, and the process exits with code 2 (success-with-warnings). The HTML is still produced.
FR-43. Stage 4 (planning) failures — invalid JSON, references to symbols not in the graph — trigger one retry with a reinforcement prompt. If the retry also fails, the process exits with a fatal error. Planning cannot be degraded; downstream stages have no input to work from.

FR-88. When `run_status == "degraded"`, a degraded banner is rendered at the top of the generated HTML — orange-tinted (`oklch(0.94 0.10 40)` background), displaying `⚠ N of M lessons skipped — grounding failed`. Style details per `.ai/ux-spec.md` §Tutorial.components.degraded-banner.

FR-90. CLI 429 (`rate_limit_error`) handling prints `  ⚠ HTTP 429 rate_limit_error (tokens-per-minute)` + `  ⟳ backoff Ns (attempt K/5)` per retry, up to 5 attempts with exponential backoff (2s→4s→8s). On recovery: `  ✓ resumed · rate-limit window cleared`. Exact copy per `.ai/ux-spec.md` §CLI.error-scenarios.rate-limited.

### 3.9 Atypical repositories

FR-44. Missing `README.md`: the RAG stage skips it without crashing; narration explicitly flags "no README — descriptions derived from code only".
FR-45. Monorepo with mixed languages: the tool auto-detects the deepest directory containing at least 20 `.py` files. On a tie at the same depth, the alphabetically first path wins. The CLI prints "Detected Python subtree: <path> (<N> files). Override with --root=.".
FR-46. Zero docstrings or documentation: the pipeline continues; Stage 4 adds a "low documentation coverage — tutorial quality may be degraded" warning that renders in the HTML footer.
FR-47. Jedi partial resolution is always continued, never aborted. Resolution coverage is reported in three tiers: >80% resolved = high (green indicator), 50–80% = medium (amber warning), <50% = low (red warning plus recommendation: "consider pyright adapter — v2+"). `resolution_coverage_pct` is exposed in the run report JSON.

### 3.10 Interrupt and crash semantics

FR-48. First `Ctrl+C`: the CLI prints "Finishing current lesson (N/M)... press Ctrl+C again to abort immediately.", finishes the active lesson (capped at approximately 90 seconds), checkpoints, and exits with code 130.
FR-49. Second `Ctrl+C`: the CLI performs a hard abort, marks the active lesson as `interrupted` in the run report, checkpoints, and exits with code 130.
FR-50. Unhandled exception: the process persists "failed at lesson N" state plus a full stack trace to `.wiedunflow/run-report.json` and exits with code 1. `--resume` picks up from the last completed lesson.

### 3.11 Output HTML

FR-51. The output is a single `.html` file with all CSS, JavaScript, lesson JSON, and pre-rendered Pygments HTML inlined.
FR-52. Default output filename is `tutorial.html` in the current working directory. A flag (e.g. `--versioned-name`) opts in to `<repo-name>-tutorial-<short-commit>.html`.
FR-53. Layout breakpoint is 1024 px. At ≥1024 px the layout is split-view: narration on the left, code on the right, 50/50, with scroll-sync. At <1024 px the layout is stacked inline: narration paragraph → relevant code block → next paragraph → next code block. Both paths are driven by the same embedded JSON.
FR-54. Navigation: clickable table of contents in the sidebar; deep-links via URL hash `#/lesson/<id>`; keyboard shortcuts `←` and `→`.
FR-55. `localStorage` is used for last-viewed lesson and session progress. Purely client-side persistence; no network side effects.
FR-56. Embedded JSON carries `metadata.schema_version` (hardcoded to `"1.0.0"` in MVP) and `metadata.wiedunflow_version` (the package version). Template JavaScript branches on `schema_version` for future breaking changes.
FR-57. The footer contains: repository commit hash, branch, `generated_at` timestamp, WiedunFlow version, Jedi resolution confidence tier, and the offline guarantee statement "Generated by WiedunFlow vX.Y.Z (Apache 2.0) — this document is fully offline.".
FR-58. Pygments pre-renders syntax highlighting at build time. The browser does no syntax highlighting at runtime.
FR-59. Target output size for a medium repo (≤500 `.py` files) is under 8 MB. A hard warning is printed at sizes above 20 MB.

FR-83. Layout, typography, and color tokens in the generated HTML match `.ai/ux-spec.md` §Tutorial.tokens pixel-for-pixel. A1 Paper palette only. Topbar is the darkest surface; narration panel is the lightest (~20% closer to white than page background). This hierarchy is a non-negotiable constraint (ADR-0011).

FR-84. Tutorial reader embeds a resizable splitter between the narration panel and the code panel. Range: 28–72% of content width (narration fraction). Persisted to `localStorage` key `wiedunflow:tweak:narr-frac:v2`. Splitter is disabled (hidden) on viewports narrower than 1024px. Details per `.ai/ux-spec.md` §Tutorial.components.splitter.

FR-85. Fonts (Inter 400/500/600/700; JetBrains Mono 400/500/600) are self-hosted as WOFF2, base64-encoded inside the generated HTML (or referenced via relative paths if the HTML is in a directory alongside the fonts). System fallbacks (`ui-sans-serif, system-ui, …` / `ui-monospace, SF Mono, Menlo, Consolas`) apply if WOFF2 embedding fails. No external CDN font requests. Details per `.ai/ux-spec.md` §Tutorial.assets.

FR-86. Reader-side Tweaks panel (toggled via `⚙` icon in topbar) exposes theme selection (light/dark) only. Palette, body font, and narrative direction are fixed (A1 Paper + Inter + Direction A) — no runtime toggles for these. Panel state persisted in `localStorage`. Details per `.ai/ux-spec.md` §Tutorial.components.tweaks.

FR-87. Skipped-lesson placeholder rendered inline for each lesson where `lesson.status == "skipped"`. Visual: dashed border (`border: 2px dashed var(--warn)`), diagonal hatching background, centered SKIPPED pill. Style details per `.ai/ux-spec.md` §Tutorial.components.skipped-placeholder.

### 3.12 Post-run reporting

FR-60. A human-readable summary is printed to stdout: files generated, lessons generated, lessons skipped, cost broken down by Haiku and Sonnet, elapsed time, cache hit rate, and the `file://` URL to open the result.
FR-61. A machine-readable `run-report.json` is written to `.wiedunflow/` with the keys: `status ∈ {ok, degraded, failed}`, `cost`, `elapsed_seconds`, `lessons_generated`, `skipped_lessons_count`, `resolution_coverage_pct`, `cache_hit_rate`, `commit_hash`, `branch`, `wiedunflow_version`.
FR-62. `.wiedunflow/` is auto-added to `.gitignore` on first run if the directory does not already appear there.
FR-63. The last 10 `run-report.json` files are retained in `.wiedunflow/history/run-report-<timestamp>.json`. Older reports are pruned automatically.

FR-89. CLI run report rendered as a framed card with left-border color encoding status: green (success), amber (degraded), red (failed). Common fields: lessons (e.g. `12 of 12 narrated`), files analysed (e.g. `47 python files · 87% symbol coverage`), elapsed, cost breakdown, tokens in/out, clickable `file://…/tutorial.html` link. Failed runs show: failed-at stage, reason, cleanup hint (`./wiedunflow-output/.cache/`), resume command. Layout per `.ai/ux-spec.md` §CLI.run-report.

### 3.13 LLM providers (BYOK)

FR-64. Default provider is Anthropic. Default models: claude-haiku-4-5 for leaf-function descriptions (parallel), claude-opus-4-7 for narration (sequential). The Anthropic SDK is used directly; no LangChain dependency.
FR-65. OpenAI is supported via the official openai Python SDK with documented model choices.
FR-66. OpenAI-compatible OSS endpoints (Ollama, LM Studio, vLLM) are supported via the openai SDK with base_url override, or a direct httpx-based OpenAI-compatible client. The README contains a documented config example.
FR-67. Concurrency defaults to 10 and is hard-capped at 20. Configurable via `llm.concurrency` in `tutorial.config.yaml`.
FR-68. Exponential backoff is applied to HTTP 429 responses from any provider.

### 3.14 Repository setup and contribution

FR-69. The pre-commit stack is: `ruff check`, `ruff format`, `mypy --strict src/wiedunflow/**`, `insert-license` (Apache 2.0 headers), and `commitlint` (conventional commits via `cz-cli`). `pytest` is CI-only. `bandit` and `reuse lint` are deferred to v2. pip-audit (or uv audit when stable) runs in the release workflow only, not in pre-commit; details in FR-78.
FR-70. DCO sign-off is enforced as a GitHub Action check on pull requests, not as a local pre-commit hook.
FR-71. The repository contains `.github/ISSUE_TEMPLATE/bug_report.yml`, `feature_request.yml`, and `eval_regression.yml`.
FR-72. `NOTICE` is aggregated automatically from Apache-licensed dependencies during the release process. The project copyright holder is Michał Kamiński (individual).
FR-73. The README contains the following required sections: installation via `uvx`, three-step quickstart, `tutorial.config.yaml` example, troubleshooting ("API key not found", "Jedi can't resolve"), license note, `CONTRIBUTING.md` link, and the provider data-transmission disclosure (source code is sent to the configured LLM provider unless Ollama or an equivalent local endpoint is used).

### 3.15 Eval corpus and release gate

FR-74. The eval corpus is pinned in `tests/eval/corpus/repos.yaml` with five repositories fixed to specific commits via Git submodule:
    - `kennethreitz/requests` — stable, well-documented.
    - `pallets/click` — canonical CLI.
    - `encode/starlette` — async with strong type hints.
    - `modelcontextprotocol/python-sdk` — primary benchmark versus the Anthropic Skilljar reference.
    - `dateutil/dateutil` — large utility-function surface.
FR-75. The smoke test requires zero crashes across all five repositories and fewer than 5% hallucinated symbols per tutorial.
FR-76. The release gate for `v0.1.0` is `pytest -m eval` passing on the full five-repo corpus, plus a quality rubric sign-off by the author and two trusted developer friends. The rubric uses a 5-point scale on coverage, accuracy, and narrative flow, with these anchor definitions:
    - 1 = unusable, would not publish.
    - 2 = requires significant rewriting to be useful.
    - 3 = usable with caveats.
    - 4 = close to hand-written quality.
    - 5 = matches or exceeds the hand-written reference.
    Release requires an average score ≥3 across all three axes on the MCP Python SDK tutorial.
FR-77. `pytest -m eval` requires a real API key and is never run in the default CI matrix.

### 3.16 Supply chain and runtime hardening

FR-78. Dependency vulnerability scanning runs in the release workflow via pip-audit (or uv audit when stable). Known CVEs with severity ≥ HIGH fail the release. Advisory-only (LOW/MEDIUM) CVEs produce a warning summary but do not fail the release.
FR-79. External-process invocations (editor resolution in FR-20, any future git/subprocess calls) use shell=False and shlex-split argument vectors. Environment-sourced command strings ($EDITOR, $VISUAL) are validated to resolve to an existing executable before invocation; invalid values fall back to the next resolver step rather than error.
FR-80. A SecretFilter component in the logging chain redacts before emission: API-key-shaped strings (patterns for Anthropic, OpenAI, generic 32+ hex), absolute file paths outside the working repo, and any verbatim source content at level INFO or above. The filter is applied to both human-readable and --log-format=json outputs. A hidden --no-log-redaction flag exists for developer debugging only and is omitted from --help.

## 4. Product Boundaries

### 4.1 Hard scope (in MVP)

- Python 3.11+ CLI, UV-exclusive toolchain.
- Python-only source parsing (architecture is plugin-ready for other languages).
- English-only CLI and narration.
- Local Git repository as input; the user clones the repo themselves.
- Single self-contained HTML output via `file://` in any modern browser.
- BYOK for Anthropic, OpenAI, and OpenAI-compatible OSS endpoints.
- Apache 2.0 license, DCO contribution model.
- Cross-platform: Linux, Windows, macOS.
- Five-repo eval corpus pinned via Git submodule.

### 4.2 Out of scope (v2+)

- PyPI release.
- Docker image.
- TypeScript/JavaScript or any non-Python parser.
- `pyright` adapter.
- Polymorphism and dynamic-dispatch resolution.
- Direct GitHub URL input (the user clones the repo themselves).
- Non-English narration.
- Provider-specific reasoning fields (OpenRouter, DeepSeek `reasoning_content`).
- Hosted SaaS, VS Code extension, GitHub Pages auto-deploy.
- Framework-specific understanding (Django, FastAPI, Flask).
- Auto-update on push or CI-integrated regeneration.
- Multi-user collaboration, comments, sharing infrastructure.
- Full-text search inside the output HTML.
- Mind-map / graph visualization of repository structure.
- Shared or committed caches.
- Telemetry, usage analytics, crash reporting (even opt-in).

### 4.3 Constraints and definitions

- "Medium repo" is defined as ≤500 `.py` files. Performance targets (<30 min first run, <$8 per tutorial) apply to this size class.
- Output HTML is subject to the `file://` constraint: no `fetch()`, no ES module relative imports, no external CDN.
- Maximum lessons per tutorial: 30 (configurable).
- Lesson narration length: 150 to 1200 words (validator-enforced).
- Maximum concurrency for LLM calls: 20 (default 10).
- Cache lookups are cross-platform via `platformdirs`. No POSIX-only assumptions.
- UX binary decisions (A1 Paper, Inter, Direction A, Modern CLI) are anchored in ADR-0011. Any change to palette, body font, CLI direction, or narrative layout requires a new ADR superseding ADR-0011. No single-PR UX regressions.

## 5. User Stories

### Installation and first-run setup

US-001
Title: Install WiedunFlow via uvx from Git.
Description: As a developer, I want to install WiedunFlow with one command using UV so that I do not need to manage a Python environment manually.
Acceptance Criteria:
- `uvx --from git+https://github.com/<org>/wiedunflow wiedunflow --version` prints the current version on Linux, macOS, and Windows.
- Installation fails with a clear message if UV is not installed on PATH.
- No `pip`, `pipx`, `poetry`, or `hatch` commands appear anywhere in the README, CONTRIBUTING, or CI configuration.
- `pyproject.toml` contains `[tool.uv]` configuration.

US-002
Title: Run first-run setup wizard via `wiedun-flow init`.
Description: As a first-time user, I want an interactive wizard that collects provider, model, and API key so that I can start without reading documentation.
Acceptance Criteria:
- `wiedun-flow init` prompts sequentially for provider (default: anthropic), model, and API key.
- On completion, the wizard writes a valid YAML config to the user-level config path (`~/.config/wiedunflow/config.yaml` on Linux/macOS, `%APPDATA%\wiedunflow\config.yaml` on Windows).
- Running `wiedunflow <repo>` afterward uses the wizard's settings without prompting again.
- The wizard is never triggered automatically; it runs only on explicit invocation.

US-003
Title: Skip the wizard with CLI flags and environment variables.
Description: As a CI user or power user, I want to pass all configuration via flags and environment variables so that no interactive prompt ever blocks my pipeline.
Acceptance Criteria:
- `ANTHROPIC_API_KEY=... wiedunflow <repo> --yes` completes without any interactive prompt when a cloud provider is used and consent has been accepted.
- CLI flags override environment variables; environment variables override the user-level config.
- The resolved configuration is logged at DEBUG level so the user can diagnose precedence issues.

US-004
Title: Honor the documented configuration precedence chain.
Description: As a user mixing per-project and global settings, I want a deterministic precedence order so that I know which setting applies.
Acceptance Criteria:
- Precedence order, highest to lowest: CLI flags > env vars > `--config <path>` > `./tutorial.config.yaml` > user-level config > built-in defaults.
- An integration test verifies each precedence boundary by setting conflicting values and asserting the winner.
- The README documents the chain verbatim.

### Privacy, consent, and secret protection

US-005
Title: Block startup with a consent banner on first cloud-provider run.
Description: As a privacy-sensitive user, I want an explicit consent banner the first time my code will be sent to a cloud provider so that I can decline if the repo is sensitive.
Acceptance Criteria:
- On the first run against Anthropic or OpenAI on a given machine, the CLI prints "Your source code will be sent to <provider>. Continue? [y/N]" and blocks for input.
- A response other than `y` or `Y` aborts the run with exit code 0 and no files written.
- An accepted response writes `consent.<provider>: accepted` into the user-level config.

US-006
Title: Bypass the consent prompt in scripted usage.
Description: As a CI user, I want a flag that disables the consent prompt so that my pipeline does not hang on input.
Acceptance Criteria:
- `--no-consent-prompt` suppresses the banner and proceeds.
- `--no-consent-prompt` does not disable the hard-refuse secret list.
- The flag is documented in `wiedunflow --help` and in the README under "CI usage".

US-007
Title: Persist consent per provider, not per repository.
Description: As a user who works on many repositories, I want to accept the consent prompt once per provider so that I am not re-prompted on every repository.
Acceptance Criteria:
- After accepting the prompt for Anthropic once, subsequent runs using Anthropic across any repository on the same machine do not show the banner.
- Switching to OpenAI for the first time on the same machine shows the banner again (provider-level granularity).
- Clearing the user-level config re-enables the prompt for all providers.

US-008
Title: Never send secret files to the LLM.
Description: As any user, I want the tool to refuse to read credential and key files even if my `.gitignore` is misconfigured so that I do not accidentally leak secrets.
Acceptance Criteria:
- Files matching `.env*`, `*.pem`, `*_rsa`, `*_rsa.pub`, `*_ed25519`, `credentials.*`, `id_rsa`, `id_ed25519` are excluded from ingestion regardless of `.gitignore` contents.
- A test plants a `.env` file inside a repo that is not in `.gitignore` and asserts that the file appears in neither the AST snapshot nor any LLM prompt payload.
- The hard-refuse list applies before any other filter (include/exclude patterns cannot re-include these files).

US-009
Title: Respect `.gitignore` by default.
Description: As a user, I want the tool to skip files ignored by Git by default so that build artifacts and local files are not analyzed.
Acceptance Criteria:
- The ingestion stage parses `.gitignore` (including nested ones) and excludes matched files.
- A test plants a `build/` directory in `.gitignore` and asserts no files from `build/` appear in the AST snapshot.
- `.gitignore` is honored even when no `tutorial.config.yaml` exists.

US-010
Title: Extend file filtering with additive exclude and include patterns.
Description: As a user with uncommon layouts, I want to tell the tool to skip additional directories (tests, migrations) or focus on specific modules so that the tutorial reflects what matters to me.
Acceptance Criteria:
- `tutorial.config.yaml` accepts `files.exclude` and `files.include` as glob lists.
- User-provided `exclude` patterns are additive on top of `.gitignore`.
- User-provided `include` patterns restrict the set to the whitelist when non-empty; when empty (default), everything not excluded is processed.
- `focus_modules` boosts the PageRank weight of matching files, documented in Stage 2 behavior.

US-011
Title: Guarantee zero telemetry.
Description: As a privacy-conscious user, I want a verifiable guarantee that no telemetry is emitted by the CLI or the output HTML so that I can use WiedunFlow on sensitive code.
Acceptance Criteria:
- An integration test runs the CLI against a fixture repo with its network namespace restricted to the configured LLM provider's host. The run completes successfully.
- A template-time linter scans the final HTML for `fetch(`, `Image(`, `<link rel="prefetch"`, `<link rel="preconnect"`, and any `http://` or `https://` URL that is not a comment or whitelisted attribution, failing the build if any are found.
- The HTML footer contains the literal text "Generated by WiedunFlow vX.Y.Z (Apache 2.0) — this document is fully offline.".

### Cost estimation and confirmation

US-012
Title: See an ex-ante cost and time estimate before paying for LLM calls.
Description: As a BYOK user, I want to know the estimated cost and duration before Stage 4 so that I can abort if the repository is larger than expected.
Acceptance Criteria:
- After Stage 3 and before Stage 4, the CLI prints "<N> files, ~$<cost> cost, ~<minutes> minutes" and prompts `[y/N]`.
- Declining exits with code 0 and no LLM calls beyond those required to compute the estimate (which is heuristic — zero pre-flight LLM calls).
- Accepting proceeds to Stage 4.
- The formula is `(symbols × 500 tokens × $haiku_price) + (lessons × 8000 tokens × $sonnet_price)` times 1.3, documented in the README.
- Cost gate is printed as a boxed panel (`rich.panel`) per ux-spec §CLI.cost-gate. Prompt is `Proceed? [y/N]` with default No; bare Enter aborts.

US-013
Title: Bypass the cost confirmation prompt in CI.
Description: As a CI user, I want `--yes` to bypass all interactive prompts so that my pipeline runs non-interactively.
Acceptance Criteria:
- `--yes` suppresses the cost-confirmation prompt.
- `--yes` does not suppress the consent banner (those are separate concerns); however, combining `--yes` with `--no-consent-prompt` yields fully non-interactive behavior.
- Integration test: running with both flags in a subprocess with closed stdin completes successfully.

### Run modes

US-014
Title: Generate a tutorial end-to-end (default mode).
Description: As a primary-persona developer, I want to run the full pipeline with a single command and receive a `tutorial.html` that I can open in the browser.
Acceptance Criteria:
- `wiedunflow <repo>` executes Stages 0 through 6 and writes `tutorial.html` in the current working directory on success.
- A stage-level progress indicator (7 stages) and an LLM-call counter are shown.
- On success, stdout prints the path to open via `file://`.
- The exit code is 0 on success.

US-015
Title: Preview the plan with `--dry-run`.
Description: As a cost-anxious evaluator, I want to see proposed lesson titles, estimated cost, and a graph visualization before committing to a full run.
Acceptance Criteria:
- `wiedunflow <repo> --dry-run` executes Stages 0 through 4 inclusive and writes `tutorial-preview.html` containing the proposed lesson titles, the final cost estimate, and a graph-structure visualization.
- The dry-run cost is under $0.10 for a medium repo (approximately $0.05 for the Stage 4 Sonnet call).
- Stages 5 and 6 are skipped; no content generation occurs.
- The preview HTML states clearly "This is a preview — no lesson content has been generated yet.".

US-016
Title: Edit the lesson manifest interactively with `--review-plan`.
Description: As a repo expert, I want to edit, reorder, or delete proposed lessons before content generation so that the tutorial matches my mental model.
Acceptance Criteria:
- `wiedunflow <repo> --review-plan` pauses after Stage 4 and opens the manifest in the resolved editor.
- The editor resolution order is: `$EDITOR` → `$VISUAL` → `code --wait` (if on PATH) → `notepad` (Windows) / `vi` (Unix).
- On save and close, the edited manifest is validated against the schema; Stage 5 resumes with the edited manifest.
- An invalid manifest (broken JSON, removed required fields) reopens the editor with an error banner.

US-017
Title: Resume from the last checkpoint.
Description: As a user whose long run was interrupted, I want to continue without regenerating already-completed lessons.
Acceptance Criteria:
- `wiedunflow <repo> --resume` detects the latest checkpoint and re-enters Stage 5 at the first incomplete lesson.
- Lessons already in the cache are not regenerated and their cost is not re-billed.
- The run report reflects `cache_hit_rate` > 0 for a resumed run.
- `--no-resume` forces a clean run even when a checkpoint exists.

US-018
Title: Force a fresh plan with `--regenerate-plan`.
Description: As a user whose previous plan was bad, I want to discard the cached manifest and force Stage 4 to run again.
Acceptance Criteria:
- `--regenerate-plan` deletes the cached `lesson_manifest` for the current repo+commit key.
- Stage 4 runs again and produces a new manifest.
- Previously cached lesson content is also invalidated (because lesson IDs may differ).

US-019
Title: Enforce a hard budget cap with `--max-cost`.
Description: As a BYOK user worried about runaway bills, I want a hard cap that stops the run on overrun without losing completed work.
Acceptance Criteria:
- `--max-cost=<USD>` is respected after each lesson. When accumulated cost exceeds the cap, the process checkpoints, writes the run report, and exits with a non-zero code.
- The exit message reads "Generated N/M lessons. Resume with --resume --max-cost=X".
- A subsequent `--resume --max-cost=<higher>` continues from the last completed lesson.
- The max-cost value is floating point USD, validated to be > 0.

US-020
Title: Override cache path with `--cache-path`.
Description: As a power user, I want to direct the cache to a custom location (for example, a fast SSD).
Acceptance Criteria:
- `--cache-path=<path>` overrides the `platformdirs` default.
- The tool creates the directory if it does not exist.
- Invalid paths (non-writable, not a directory) fail with a clear error.

US-021
Title: Override the Python subtree in monorepos with `--root`.
Description: As a user of a monorepo, I want to override the auto-detected Python subtree when the heuristic picks the wrong directory.
Acceptance Criteria:
- `--root=<path>` is resolved relative to the repo root and used as the ingestion scope.
- An invalid path (non-existent or outside the repo) fails with a clear error.
- The auto-detection CLI message informs the user how to override: "Detected Python subtree: <path> (<N> files). Override with --root=.".

US-022
Title: Emit structured logs on demand.
Description: As a CI user, I want machine-readable logs so that I can parse them in downstream tooling.
Acceptance Criteria:
- `--log-format=json` emits one JSON object per line to stderr.
- Each log line contains at minimum `ts`, `level`, `stage`, and `msg`.
- The human-readable default is unchanged.
- No `print()` calls occur inside the pipeline; all output goes through the logger.

### Incremental runs and caching

US-023
Title: Complete an incremental run in under 5 minutes.
Description: As a user iterating on a project, I want the second run (after small changes) to be significantly faster than the first.
Acceptance Criteria:
- For a medium repo with fewer than 20% of files changed, an incremental run completes in under 5 minutes on a benchmark machine.
- Unchanged files reuse AST, call-graph slice, embeddings, and generated descriptions from cache.
- `run-report.json` reflects a non-zero `cache_hit_rate`.

US-024
Title: Detect structural change via PageRank graph diff.
Description: As a user, I want the tool to reuse the lesson manifest unless the architecture has meaningfully changed so that small edits do not trigger full regeneration.
Acceptance Criteria:
- If fewer than 20% of the top-ranked symbols in Stage 2 differ from the cached PageRank snapshot, the manifest is reused and only lessons touching changed files are regenerated.
- If 20% or more differ, the CLI prints a message explaining the structural change and regenerates the full manifest.
- A unit test pins two graph snapshots (below and above threshold) and asserts the branch taken.

US-025
Title: Store the cache in the platform-appropriate user-level directory.
Description: As a user on any platform, I want my cache stored in a conventional location so that it does not clutter my project.
Acceptance Criteria:
- On Linux the default cache lives under `~/.cache/wiedunflow/`.
- On Windows the default cache lives under `%LOCALAPPDATA%\wiedunflow\Cache`.
- On macOS the default cache lives under `~/Library/Caches/wiedunflow`.
- The cache is keyed by `<repo_absolute_path>+<commit_hash>`.
- Cross-platform tests verify each default location.

US-026
Title: Invalidate the cache at file granularity.
Description: As a user, I want only modified files to be reanalyzed so that small edits do not invalidate the whole cache.
Acceptance Criteria:
- Each file's cache entry is keyed by SHA-256 of its content.
- Modifying one file triggers reanalysis of that file only (and of lessons transitively referencing its symbols).
- A unit test modifies a single file, runs twice, and asserts exactly one file was reprocessed.

### Interrupt and crash semantics

US-027
Title: Finish the current lesson on first Ctrl+C.
Description: As a user who needs to stop soon, I want a graceful first Ctrl+C that does not waste the lesson currently being generated.
Acceptance Criteria:
- The first `SIGINT` causes the CLI to print "Finishing current lesson (N/M)... press Ctrl+C again to abort immediately.".
- The active lesson finishes (capped at 90 seconds) and is checkpointed.
- The process exits with code 130.
- `--resume` on the next invocation continues from the checkpoint.

US-028
Title: Hard-abort on second Ctrl+C.
Description: As a user in a hurry, I want a second Ctrl+C to abort immediately.
Acceptance Criteria:
- A second `SIGINT` within 2 seconds of the first triggers an immediate abort.
- The active lesson is marked `interrupted` in the run report.
- The process exits with code 130.
- The checkpoint reflects the last fully completed lesson.

US-029
Title: Capture crash state and stack trace in the run report.
Description: As a user hitting an unexpected bug, I want the crash state persisted so that I can resume and/or file a useful bug report.
Acceptance Criteria:
- Unhandled exceptions during Stage 5 write `{"status": "failed", "failed_at_lesson": N, "stack_trace": "..."}` to `.wiedunflow/run-report.json`.
- The process exits with code 1.
- `--resume` on the next invocation continues from the last completed lesson.
- A test injects an exception during lesson generation and asserts the report contents.

### Degraded runs and grounding

US-030
Title: Retry a lesson when grounding fails.
Description: As a user, I want the tool to retry a lesson that references non-existent symbols with a grounding-focused prompt so that one transient LLM failure does not skip content.
Acceptance Criteria:
- After the first grounding validation failure, the lesson is retried exactly once with the prompt "Your previous response referenced these non-existent symbols: [X, Y]. Rewrite the lesson using ONLY symbols from this AST slice: [allowed_symbols]".
- On success after retry, the lesson is accepted and the retry is counted in the run report.
- On failure after retry, the lesson is skipped per US-031.

US-031
Title: Skip a lesson with a placeholder after repeated grounding failures.
Description: As a user, I want a clear placeholder in the tutorial for any lesson that could not be grounded so that I know something is missing.
Acceptance Criteria:
- Skipped lessons appear in the HTML as a placeholder block with the text "This lesson was skipped due to grounding failures — see symbol X in the code".
- `skipped_lessons_count` is incremented in `run-report.json`.
- The footer of the HTML surfaces the skipped-lessons count.
- The rest of the tutorial renders normally.
- Skipped-lesson placeholder visual follows ux-spec §Tutorial.components.skipped-placeholder — dashed border, diagonal hatching, centered SKIPPED pill.

US-032
Title: Mark the run as DEGRADED when too many lessons are skipped.
Description: As a user, I want an explicit signal when the quality of the generated tutorial has been compromised so that I can decide whether to keep the output.
Acceptance Criteria:
- When `skipped_lessons_count / total_planned_lessons > 0.30`, the run is marked `status: "degraded"` in `run-report.json`.
- The process exits with code 2 even though the HTML was produced.
- A "DEGRADED" banner is rendered in the HTML footer.
- Stdout prints a clear warning line before exit.
- Degraded banner rendered top of HTML per ux-spec §Tutorial.components.degraded-banner; orange-tinted background; displays N of M skipped count.

US-033
Title: Fatal-fail on Stage 4 planning failure after one retry.
Description: As a user, I want the pipeline to stop if the planning call cannot produce a valid manifest so that I do not incur Stage 5 cost on bad input.
Acceptance Criteria:
- An invalid Stage 4 response (broken JSON, references to symbols not in the graph) triggers one retry with a reinforcement prompt.
- If the retry also fails, the pipeline exits with a non-zero code and a clear message "Planning failed after 1 retry — see ./.wiedunflow/run-report.json for details".
- No Stage 5 LLM calls are made when planning fails.

US-034
Title: Validate lesson narration length (150–1200 words).
Description: As a user, I want each lesson to be a digestible size so that the tutorial reads well.
Acceptance Criteria:
- A post-hoc validator rejects lessons under 150 words and triggers regeneration (within the single-retry budget of US-030).
- Lessons over 1200 words are truncated at a sentence boundary.
- A unit test with fixture outputs verifies both bounds.

US-035
Title: Cap the tutorial at 30 lessons.
Description: As a user, I want a predictable upper bound on tutorial length so that the narrative does not become incoherent.
Acceptance Criteria:
- `tutorial.max_lessons` defaults to 30.
- If Stage 4 proposes more than `max_lessons`, the planner is instructed to merge or drop lessons until the cap is satisfied.
- The cap is configurable in `tutorial.config.yaml`.

### Atypical repositories

US-036
Title: Generate a tutorial for a repo with no `README.md`.
Description: As a user of a thinly documented repo, I want the tool to continue without a README and flag the gap in the narration.
Acceptance Criteria:
- A repo without `README.md` does not cause a crash or abort.
- The RAG index excludes the missing file without error.
- The narration explicitly flags "no README — descriptions derived from code only" in at least the first lesson.

US-037
Title: Auto-detect the Python subtree in a monorepo.
Description: As a user of a polyglot monorepo, I want the tool to pick the right Python subtree automatically so that I do not have to configure it.
Acceptance Criteria:
- The tool scans the repo for directories containing `.py` files and selects the deepest directory with at least 20 `.py` files.
- On a tie at the same depth, the alphabetically first path wins.
- The CLI prints "Detected Python subtree: <path> (<N> files). Override with --root=.".
- `--root=<path>` overrides the auto-detection.

US-038
Title: Warn about low documentation coverage.
Description: As a user of a repo with no docstrings, I want a visible warning that tutorial quality may be degraded.
Acceptance Criteria:
- When the ratio of symbols with docstrings to total symbols is below a documented threshold (e.g., 20%), the HTML footer renders a "low documentation coverage — tutorial quality may be degraded" banner.
- The warning is also surfaced in stdout and in the run report.

US-039
Title: Surface Jedi resolution confidence in three tiers.
Description: As a user, I want to know how confident the call-graph resolution was so that I can calibrate my trust in the tutorial.
Acceptance Criteria:
- Resolution coverage is computed as `resolved_call_sites / total_call_sites`.
- Tier mapping: >80% = high (green indicator in footer), 50–80% = medium (amber warning in footer), <50% = low (red warning in footer plus "consider pyright adapter — v2+" recommendation).
- `resolution_coverage_pct` is exposed in `run-report.json`.

### Output HTML and navigation

US-040
Title: Open the tutorial via `file://` with zero external dependencies.
Description: As an end-user receiving a tutorial, I want to open the file locally in any modern browser without installing anything.
Acceptance Criteria:
- The HTML contains all CSS, JavaScript, lesson JSON, and syntax-highlighted code inline.
- A test loads the HTML in a headless Chromium session via `file://` with network disabled and verifies the tutorial renders, navigation works, and no console errors are emitted.
- No `<script src=>`, `<link href=>` with external URL, `fetch(`, or `import(` appears in the output.

US-041
Title: Render split-view on wide screens.
Description: As a desktop user, I want narration and code side-by-side with scroll sync so that I can follow along.
Acceptance Criteria:
- At viewport width ≥1024 px the layout is 50/50 split: narration left, code right.
- Scrolling the narration column updates the code column to the matching `code_refs` anchor.
- A headless Chromium test at 1440×900 viewport verifies the two-column layout is visible.
- Layout follows ux-spec §Tutorial.layout — topbar 52px, sidebar 280px, code panel sticky, splitter range 28–72%.

US-042
Title: Render stacked layout on narrow screens.
Description: As a mobile user, I want narration paragraphs interleaved with the relevant code blocks so that content is readable on a phone.
Acceptance Criteria:
- At viewport width <1024 px the layout is a single stacked column: narration paragraph → relevant code block → next paragraph → next code block.
- Both rendering paths are driven by the same embedded JSON.
- A headless Chromium test at 375×812 viewport (iPhone-ish) verifies the stacked layout.

US-043
Title: Navigate the tutorial with a clickable table of contents.
Description: As a reader, I want to jump to a specific lesson via a TOC in the sidebar.
Acceptance Criteria:
- The sidebar contains a clickable list of all lesson titles.
- Clicking a lesson navigates to it and updates the URL hash.
- The current lesson is visually highlighted in the TOC.

US-044
Title: Deep-link to a lesson via URL hash.
Description: As a reader, I want to share a link to a specific lesson.
Acceptance Criteria:
- `tutorial.html#/lesson/<id>` opens directly at the specified lesson.
- Navigating changes the hash in place without a page reload.
- An invalid lesson id falls back to lesson 1 with a console warning.

US-045
Title: Navigate with arrow keys.
Description: As a reader, I want keyboard shortcuts for Previous/Next so that I can read without a mouse.
Acceptance Criteria:
- `←` moves to the previous lesson; `→` moves to the next.
- At the boundaries (first lesson `←`, last lesson `→`), no navigation happens and no error is thrown.
- Focus on a text input disables the shortcuts.

US-046
Title: Remember the last-viewed lesson via localStorage.
Description: As a reader, I want to reopen the tutorial later and pick up where I left off.
Acceptance Criteria:
- The last-viewed lesson id is written to `localStorage` under a namespaced key (`wiedunflow:<tutorial-id>:last-lesson`).
- On reload, the tutorial navigates to the stored id.
- No network call is involved.
- Clearing `localStorage` reverts to lesson 1.

US-047
Title: Render the offline-guarantee footer statement.
Description: As a reader, I want to see a clear statement that the tutorial is fully offline.
Acceptance Criteria:
- The footer contains the literal string "Generated by WiedunFlow vX.Y.Z (Apache 2.0) — this document is fully offline." with the actual version substituted.
- The footer also contains the repo commit hash, branch, `generated_at` timestamp, and the Jedi resolution tier.

US-048
Title: Embed schema versioning in the output JSON.
Description: As the project maintainer, I want future template JavaScript to recognize the schema version and branch appropriately so that v2 changes remain backward-compatible.
Acceptance Criteria:
- The embedded JSON contains `metadata.schema_version = "1.0.0"` and `metadata.wiedunflow_version = "<package_version>"`.
- The template JavaScript reads `schema_version` and logs a console warning on unknown versions.
- A unit test asserts the presence and format of both fields.

US-049
Title: Generate a "Where to go next" closing lesson.
Description: As a reader finishing the tutorial, I want pointers to further reading so that I know what to explore on my own.
Acceptance Criteria:
- The final lesson is generated by one additional Sonnet call at the end of Stage 5.
- It contains external doc links parsed from `README.md`, the top five highest-ranked files omitted from earlier lessons, and `git log` hints about actively changing subdirectories.
- The closing lesson is subject to the same grounding validation as other lessons.

US-050
Title: Keep the output HTML under 8 MB for a medium repo.
Description: As a reader, I want the tutorial to open quickly and be shareable.
Acceptance Criteria:
- For a medium repo (≤500 `.py` files) the output is under 8 MB.
- The build stage prints a warning line when the output exceeds 20 MB.
- A CI assertion on the MCP Python SDK tutorial verifies the size budget.

### BYOK providers

US-051
Title: Use OpenAI as the default LLM provider.
Description: As a default user, I want OpenAI to work out of the box with an API key.
Acceptance Criteria:
- With `OPENAI_API_KEY` set and no other configuration, the pipeline succeeds using `gpt-5.4` for planning and narration, plus `gpt-5.4-mini` for per-symbol leaf descriptions.
- Model IDs are configurable in `tutorial.config.yaml` under `llm.model_plan` and `llm.model_narrate`.
- Anthropic is available as a fully-supported alternative: setting `llm.provider: anthropic` with `ANTHROPIC_API_KEY` yields `claude-sonnet-4-6` (planning) + `claude-opus-4-7` (narration) + `claude-haiku-4-5` (per-symbol).

_BREAKING change in v0.7.0 per ADR-0015 — default provider switched from Anthropic to OpenAI for rate-limit relief and cost parity._

US-052
Title: Use OpenAI as an alternative provider.
Description: As an OpenAI-preferring user, I want to switch providers via config.
Acceptance Criteria:
- Setting `llm.provider: openai` and `OPENAI_API_KEY` routes all LLM calls through the official `openai` Python SDK.
- The documented model choices (both descriptions and narration) work end-to-end against the eval smoke test.

US-053
Title: Use a local OSS endpoint (Ollama, LM Studio, vLLM).
Description: As a user with sensitive code, I want to route all inference to a local OSS endpoint so that no code leaves my machine.
Acceptance Criteria:
- Setting `llm.provider: custom`, `llm.base_url: http://localhost:11434/v1`, and `llm.api_key_env: <env var>` routes all LLM calls through the `openai` SDK with `base_url` override (or the httpx-based OpenAI-compatible client for endpoints that reject the SDK).
- No consent banner is shown for local endpoints.
- The README contains a tested example config for Ollama.

US-054
Title: Apply exponential backoff on 429 responses.
Description: As a user hitting rate limits, I want the tool to retry intelligently without crashing.
Acceptance Criteria:
- HTTP 429 responses trigger exponential backoff with jitter up to a documented cap (e.g., 60 s).
- After the final retry budget is exhausted, the lesson is treated as a failure and the standard degraded-run policy applies.
- A unit test mocks a 429 response and asserts the backoff behavior.
- Backoff displays `⟳ backoff Ns (attempt K/5)` per ux-spec §CLI.error-scenarios.rate-limited.

### Reporting

US-055
Title: Print a human-readable summary after every run.
Description: As a user, I want a quick stdout summary at the end of a run.
Acceptance Criteria:
- Stdout contains: files generated, lessons generated, lessons skipped, cost (Haiku and Sonnet breakdown), elapsed time, cache hit rate, and the `file://` URL.
- The URL is clickable in terminals that support OSC 8 hyperlinks.
- Summary rendered as framed card per ux-spec §CLI.run-report; left-border color encodes status (green/amber/red).

US-056
Title: Write a machine-readable run report.
Description: As a CI user, I want a JSON run report I can parse downstream.
Acceptance Criteria:
- `.wiedunflow/run-report.json` is written with the keys `status`, `cost`, `elapsed_seconds`, `lessons_generated`, `skipped_lessons_count`, `resolution_coverage_pct`, `cache_hit_rate`, `commit_hash`, `branch`, `wiedunflow_version`.
- `status` is one of `ok`, `degraded`, `failed`.
- A schema-validation test pins the shape.

US-057
Title: Add `.wiedunflow/` to `.gitignore` automatically.
Description: As a user, I do not want the run report to accidentally be committed.
Acceptance Criteria:
- On first run, if `.wiedunflow` is not already present in `.gitignore`, the line `.wiedunflow/` is appended.
- If `.gitignore` does not exist, it is created containing only `.wiedunflow/`.
- Idempotent on subsequent runs.

US-058
Title: Rotate run reports, keeping the last 10.
Description: As a user iterating over time, I want history of my runs without unbounded disk growth.
Acceptance Criteria:
- Each run writes a timestamped copy to `.wiedunflow/history/run-report-<ISO8601>.json`.
- On every run, older files beyond the 10 most recent are deleted.
- The current `run-report.json` is always the latest run (not inside `history/`).

### Repository hygiene, CI, and release

US-059
Title: Enforce pre-commit checks.
Description: As a contributor, I want fast local checks to keep the codebase clean.
Acceptance Criteria:
- `pre-commit` hooks run: `ruff check`, `ruff format`, `mypy --strict src/wiedunflow/**`, `insert-license`, `commitlint`.
- `pytest` is not in the pre-commit stack.
- The `insert-license` hook adds the Apache 2.0 header to any new `.py` file that lacks one.

US-060
Title: Enforce DCO sign-off on pull requests.
Description: As a project maintainer, I want every contribution to carry a DCO sign-off so that we do not need a CLA.
Acceptance Criteria:
- A GitHub Action rejects any PR whose commits do not contain `Signed-off-by:` lines.
- The check does not run as a local pre-commit hook.
- The README and `CONTRIBUTING.md` document the sign-off requirement and the `git commit -s` command.

US-061
Title: Run the CI matrix across Python versions and operating systems.
Description: As a cross-platform user, I want CI to verify the tool on all supported platforms.
Acceptance Criteria:
- GitHub Actions runs `pytest` (without `-m eval`) on Python 3.11, 3.12, 3.13 across Ubuntu, Windows, and macOS.
- UV is installed via `astral-sh/setup-uv`.
- Failures on any combination block the merge to `main`.

US-062
Title: Aggregate Apache NOTICE content automatically.
Description: As a maintainer, I want the `NOTICE` file built from dependency licenses automatically so that compliance does not drift.
Acceptance Criteria:
- A release-time script scans installed Apache-licensed dependencies, extracts their `NOTICE` content, and aggregates it into the project `NOTICE` file.
- The script runs in the release workflow and fails the release if an Apache-licensed dependency's `NOTICE` could not be located.
- The top of `NOTICE` contains "Copyright 2026 Michał Kamiński".

US-063
Title: Provide GitHub issue templates.
Description: As a contributor, I want structured templates for bugs, features, and eval regressions.
Acceptance Criteria:
- `.github/ISSUE_TEMPLATE/bug_report.yml`, `feature_request.yml`, and `eval_regression.yml` exist.
- Each template captures at minimum: environment, reproduction steps, expected vs actual behavior.
- `eval_regression.yml` requires the eval repo name, commit hash, and hallucinated-symbol counts.

US-064
Title: Gate releases behind the eval corpus.
Description: As a maintainer, I want `pytest -m eval` to pass on the pinned five-repo corpus before tagging a release.
Acceptance Criteria:
- The release runbook requires `pytest -m eval` to pass, consuming a real API key.
- `pytest -m eval` is not part of the default CI matrix (it costs money and requires a secret).
- Failures on any of the five pinned repos block the release.

US-065
Title: Smoke-test the eval corpus on pinned commits.
Description: As a maintainer, I want reproducible robustness testing so that eval results are comparable across runs.
Acceptance Criteria:
- `tests/eval/corpus/repos.yaml` lists the five pinned repos with exact commit hashes.
- Each repo is included via Git submodule pinned to the same commit.
- The smoke test asserts zero crashes and under 5% hallucinated symbols per tutorial.

US-066
Title: Pass the pre-release quality rubric.
Description: As a maintainer, I want a concrete quality gate before `v0.1.0`.
Acceptance Criteria:
- The author plus two trusted developer friends independently score the MCP Python SDK tutorial on coverage, accuracy, and narrative flow using the 5-point rubric.
- Rubric anchors: 1 = unusable; 2 = requires significant rewriting; 3 = usable with caveats; 4 = close to hand-written quality; 5 = matches or exceeds the hand-written reference.
- Release requires the average score across all three axes to be at least 3.
- The individual scores and rationales are archived alongside the release.

US-067
Title: Scan dependencies for known CVEs in the release workflow.
Description: As a maintainer, I want pip-audit to run in the release workflow so that known CVEs with HIGH+ severity block tagging.
Acceptance Criteria:
- The release workflow runs `uv export | pip-audit` (or equivalent) before the eval gate.
- A planted HIGH-severity CVE in a test branch causes the workflow to fail.
- LOW/MEDIUM findings are surfaced in the workflow summary but do not fail the release.
- The check is not part of the default CI matrix (too slow and too noisy for per-PR).

US-068
Title: Harden --review-plan editor invocation against shell injection.
Description: As a security-conscious user, I want the --review-plan editor resolver to refuse shell-interpretable $EDITOR values so that a malicious environment cannot execute arbitrary code.
Acceptance Criteria:
- $EDITOR="rm -rf /" or similar is rejected with a clear message and falls through to $VISUAL.
- The subprocess call uses shell=False and shlex.split.
- A unit test plants malicious env values and asserts no shell execution occurs.
- The resolver also validates the binary exists on PATH before invocation.

US-069
Title: Redact secrets and source bodies from logs.
Description: As a privacy-sensitive user, I want the logger to redact API keys, external paths, and verbatim source code before emission so that accidental log uploads do not leak.
Acceptance Criteria:
- A SecretFilter is attached to both human-readable and JSON log handlers.
- A unit test feeds a log record containing an API-key-shaped string and asserts the output contains "[REDACTED]".
- Absolute paths outside the working repo are replaced with "<external>".
- Verbatim source-file content at INFO or above is truncated to file hash + symbol name.
- --no-log-redaction flag exists but is undocumented in --help (developer use only).

US-070
Title: CLI prints boxed cost-gate estimate with `rich.panel`
_Mapped to: FR-81 | Sprint: S5 track B | Owner: python-pro_
Description: As a developer running `wiedun-flow init`, I want to see a formatted cost estimate before any API calls, so I can make an informed go/no-go decision.
Acceptance Criteria:
- Cost gate printed as `rich.panel` with HEAVY border, accent title `ESTIMATED COST`
- Table rows: Model, Stage, Est. tokens, Est. cost; totals row; runtime estimate
- Prompt `Proceed? [y/N]`; bare Enter = No
- On No: `aborted by user. no API calls were made.` + total cost $0.00 + elapsed
- Pixel values and copy match ux-spec §CLI.cost-gate

US-071
Title: CLI emits 7-stage output with exact copy and live counters
_Mapped to: FR-82 | Sprint: S5 track B | Owner: python-pro + ai-engineer_
Description: As a developer running `wiedun-flow init`, I want to see clear stage progress with real-time cost/token counters.
Acceptance Criteria:
- Stage header: `[N/7] <Stage name>` in accent color
- Detail lines: 5-space indent
- Stage end: `  ✓ done · <summary>` in good color
- Live counters visible during LLM stages: elapsed MM:SS, cumulative cost, tokens in/out
- Stage names and detail copy match ux-spec §CLI.stages exactly

US-072
Title: CLI run report rendered as framed status-colored card
_Mapped to: FR-89 | Sprint: S5 track B | Owner: python-pro_
Description: As a developer who finished a `wiedun-flow init` run, I want a concise final summary card with status indication.
Acceptance Criteria:
- Framed card via `rich.panel`; left-border green (success) / amber (degraded) / red (failed)
- Success/degraded fields: lessons narrated, files analysed, elapsed, cost, tokens, clickable tutorial link
- Failed fields: failed-at stage, reason, cleanup hint, resume command
- Layout matches ux-spec §CLI.run-report

US-073
Title: CLI 429 backoff displayed with attempt/5 counter
_Mapped to: FR-90 | Sprint: S5 track B | Owner: python-pro_
Description: As a developer running `wiedun-flow init`, I want transparent feedback when rate-limited, so I know the tool is retrying not hung.
Acceptance Criteria:
- Each 429: `  ⚠ HTTP 429 rate_limit_error (tokens-per-minute)` (warn)
- Each retry: `  ⟳ backoff Ns (attempt K/5)` (warn)
- On success: `  ✓ resumed · rate-limit window cleared` (good)
- Up to 5 attempts; exhaustion triggers pipeline abort per FR-90
- Copy matches ux-spec §CLI.error-scenarios.rate-limited

US-074
Title: CLI color roles follow ux-spec §CLI.color-roles
_Mapped to: FR-81..FR-90 | Sprint: S5 track B | Owner: python-pro_
Description: As a developer reading CLI output, I want consistent color semantics across all stages and error paths.
Acceptance Criteria:
- 8 roles implemented as `rich.style.Style` constants: default, dim, good, warn, err, accent, link, prompt
- Bold used only for links (link role)
- All stage output, cost gate, and error scenarios use correct roles per ux-spec §CLI.color-roles

US-075
Title: Tutorial reader uses A1 Paper + Inter + darkness hierarchy
_Mapped to: FR-83, FR-85 | Sprint: S5 track A | Owner: frontend-developer + ui-designer_
Description: As a developer reading the generated tutorial, I want a visually comfortable, high-contrast interface.
Acceptance Criteria:
- All CSS custom-property values match ux-spec §Tutorial.tokens exactly (oklch, px, line-height)
- Topbar is the darkest surface; narration panel is the lightest (~20% closer to white)
- Inter WOFF2 fonts embedded (no CDN); JetBrains Mono for code blocks
- Playwright visual regression snapshot (1440×900 light + dark) passes golden comparison

US-076
Title: Tutorial splitter resizable 28–72% persisted in localStorage
_Mapped to: FR-84 | Sprint: S5 track C | Owner: frontend-developer + javascript-pro_
Description: As a developer using the tutorial, I want to resize narration vs code area to match my reading style.
Acceptance Criteria:
- Splitter drag range clamped to 28–72% (narration fraction of content area)
- `pointerdown/pointermove/pointerup` implementation; cursor `col-resize`
- Persisted in `localStorage` key `wiedunflow:tweak:narr-frac:v2`
- Disabled (hidden) on viewport <1024px
- Details per ux-spec §Tutorial.components.splitter

US-077
Title: Tutorial Tweaks panel (theme toggle only in production)
_Mapped to: FR-86 | Sprint: S5 track C | Owner: frontend-developer_
Description: As a developer reading the tutorial, I want a dark-mode option without leaving the file.
Acceptance Criteria:
- `⚙` icon in topbar opens slide-in tweaks panel (`width: 280px`, right side, shadow per ux-spec)
- Production panel: only light/dark theme toggle
- Prototype controls (palette/direction/font/confidence/degraded) NOT included
- Theme persisted in `localStorage` key `wiedunflow:tweak:theme:v2`
- `Escape` closes panel; click outside closes panel

US-078
Title: Skipped-lesson placeholder rendered inline when skipped
_Mapped to: FR-87 | Sprint: S5 track A | Owner: frontend-developer_
Description: As a developer reading a degraded tutorial, I want to clearly see which lessons failed grounding.
Acceptance Criteria:
- Placeholder shown inline in narration panel for `lesson.status == "skipped"`
- Visual: `border: 2px dashed var(--warn)`, diagonal hatching background, centered SKIPPED pill
- Text: "This lesson was skipped — N unresolved symbol references."
- Style matches ux-spec §Tutorial.components.skipped-placeholder

US-079
Title: Degraded banner rendered top of HTML when run_status=degraded
_Mapped to: FR-88 | Sprint: S5 track A | Owner: frontend-developer_
Description: As a developer opening a degraded tutorial, I want an immediate notice that some lessons are missing.
Acceptance Criteria:
- Banner rendered at top of tutorial when `TUTORIAL_META.run_status == "degraded"`
- Orange-tinted background (`oklch(0.94 0.10 40)`), `padding: 12px 24px`
- Text: `⚠ N of M lessons skipped — grounding failed`
- Style matches ux-spec §Tutorial.components.degraded-banner

US-080
Title: Confidence pill in narration meta row (HIGH/MEDIUM/LOW oklch)
_Mapped to: FR-39 (additional AC) | Sprint: S5 track A | Owner: frontend-developer_
Description: As a developer reading a lesson, I want a visual confidence indicator so I understand AI certainty about the narration.
Acceptance Criteria:
- Confidence pill shown in lesson meta row (below lesson title)
- HIGH: `oklch(88% 0.12 145)` bg / `oklch(30% 0.12 145)` text (green-tinted)
- MEDIUM: `oklch(93% 0.08 80)` bg / `oklch(35% 0.12 80)` text (amber-tinted)
- LOW: `oklch(93% 0.06 25)` bg / `oklch(35% 0.1 25)` text (red-tinted)
- Colors match ux-spec §Tutorial.tokens (confidence pills)

### Interactive picker for repository selection (v0.5.0, Sprint 9)

US-088
Title: Picker entry point — `wiedun-flow` without arguments launches repo picker in TTY
_Mapped to: .ai/ux-spec.md §4.0 | Sprint: S9 track A | Owner: python-pro_
Description: As a user running `wiedun-flow` with no arguments in a terminal, I want an interactive menu to select a repository instead of remembering CLI flags.
Acceptance Criteria:
- `wiedun-flow` (no args) in a TTY (`sys.stdin.isatty() and sys.stdout.isatty()`) launches `main_menu_loop` from `cli/menu.py`
- `wiedun-flow` with any subcommand (`wiedun-flow generate ...`, `wiedun-flow init`), or in non-TTY (pipes, CI), or when `WIEDUNFLOW_NO_MENU=1` is set → use existing Click group (no menu)
- Menu returns to top-level loop after each completed pipeline run
- Implementation: `cli/main.py:main()` guards with 3-line TTY check before dispatching to Click group

US-089
Title: Read recent runs from LRU cache file
_Mapped to: .ai/ux-spec.md §4.0 | Sprint: S9 track B | Owner: python-pro_
Description: As a user, I want to re-run the same repo without typing the path again.
Acceptance Criteria:
- Recent runs source reads `~/.cache/wiedunflow/recent-runs.json` (LRU list, max 10 entries)
- Each entry contains `repo_path` (absolute) and last-run timestamp
- File missing or malformed → graceful empty list (no crash)
- Entry with deleted `repo_path` → still displayed, validation happens after selection

US-090
Title: Discover git repositories in cwd depth=1 with .gitignore-aware filtering
_Mapped to: .ai/ux-spec.md §4.0 | Sprint: S9 track A | Owner: python-pro_
Description: As a user in a directory with multiple git projects, I want to quickly navigate to one without typing paths.
Acceptance Criteria:
- Walk `cwd` to max_depth=1 (only direct subdirectories, no recursion)
- Skip hardcoded ignored dirs: `node_modules`, `.venv`, `venv`, `__pycache__`, `dist`, `build`, `target`, `.tox`, `.idea`, `.vscode`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`
- Parse `cwd/.gitignore` (if exists) and filter results via `pathspec.PathSpec.from_lines("gitwildmatch", ...)`
- Return dirs containing `.git/` subdir; sort by mtime DESC (newest first)
- Format display: `[YYYY-MM-DD HH:MM] /path/to/repo` (ISO date+time)
- Cap UI results to 20; silently drop tail if >20 found
- Empty result → message "No git repositories found in current directory." → re-render source picker

US-091
Title: Manual path entry with git repo validation
_Mapped to: .ai/ux-spec.md §4.0 | Sprint: S9 track A | Owner: python-pro_
Description: As a user with a repo outside cwd, I want to type the path manually.
Acceptance Criteria:
- `io.path("Repo path:", only_directories=True)` prompt via `MenuIO.path()` (questionary under the hood)
- Validation: path must exist + contain `.git/` subdir
- On validation failure: print error message + retry prompt (max 3 attempts, then fall back to source picker)
- On success: path returned to picker caller
- Implementation: `MenuIO.path()` used for first time in real pipeline (previously draft in menu.py:155)

US-092
Title: Write recent runs to LRU cache on successful tutorial generation
_Mapped to: cli/menu.py (writeback after `_launch_pipeline` returns) | Sprint: S9 track B | Owner: python-pro_
Description: As a user, I want subsequent runs of the same repo to appear in "Recent runs" without manual curation.
Acceptance Criteria:
- After a successful tutorial generation, the repo path is written to `~/.cache/wiedunflow/recent-runs.json`
- File format: list of `{repo_path, last_run_timestamp}` (JSON array)
- LRU behavior: if path already exists in list, move it to top; drop oldest entries beyond 10
- File missing → create with single entry
- File corrupted → recover gracefully with single entry (no crash)

### Dynamic pricing catalog (v0.5.0, Sprint 9)

US-093
Title: PricingCatalog port — interface for per-model pricing lookups
_Mapped to: docs/adr/0014-dynamic-pricing-catalog.md | Sprint: S9 track B | Owner: python-pro_
Description: As a cost-gate feature, I need a pluggable interface to fetch live model pricing.
Acceptance Criteria:
- Protocol `PricingCatalog` in `src/wiedunflow/interfaces/pricing_catalog.py` with single method `blended_price_per_mtok(model_id: str) -> float | None`
- Returns blended USD/MTok (60% input + 40% output, empirical planning+narration split)
- Returns `None` for unknown models so chains can fallback
- Never raises — pricing lookup is non-critical

US-094
Title: StaticPricingCatalog — hardcoded fallback backed by MODEL_PRICES
_Mapped to: docs/adr/0014-dynamic-pricing-catalog.md | Sprint: S9 track B | Owner: python-pro_
Description: As a fallback, I need always-available pricing for common models without network calls.
Acceptance Criteria:
- `StaticPricingCatalog` in `src/wiedunflow/adapters/static_pricing_catalog.py`
- Backed by `cli/cost_estimator.MODEL_PRICES` (single source of maintenance)
- Used as leaf of every chain, ensuring cost gate never lacks a price

US-095
Title: LiteLLMPricingCatalog — fetch live pricing from LiteLLM GitHub JSON
_Mapped to: docs/adr/0014-dynamic-pricing-catalog.md | Sprint: S9 track B | Owner: python-pro_
Description: As the cost gate, I need current model prices that update independently of WiedunFlow releases.
Acceptance Criteria:
- `LiteLLMPricingCatalog` in `src/wiedunflow/adapters/litellm_pricing_catalog.py`
- Fetches https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json (3s timeout)
- Blends `0.6 * input_cost_per_token + 0.4 * output_cost_per_token`, converts USD/MTok
- Strips provider prefix (`openai/gpt-4.1` → `gpt-4.1`)
- **Network errors**: timeout, 5xx, 404 → all downgrade to empty dict per-query, no crash

US-096
Title: CachedPricingCatalog — 24h disk cache decorator
_Mapped to: docs/adr/0014-dynamic-pricing-catalog.md | Sprint: S9 track B | Owner: python-pro_
Description: As performance optimization, I need cached pricing that refreshes daily.
Acceptance Criteria:
- `CachedPricingCatalog` in `src/wiedunflow/adapters/cached_pricing_catalog.py`
- Wraps any `upstream` catalog; reads `export_dump()` and calls `hydrate(prices)` for state management
- Cache file: `~/.cache/wiedunflow/pricing-<provider>.json` (e.g., `pricing-litellm.json`)
- TTL 86400 seconds (24h); fresher on rehydrate if older
- Fallback chain: `ChainedPricingCatalog([CachedPricingCatalog(LiteLLM), StaticPricingCatalog()])`

US-097
Title: ChainedPricingCatalog — fallback chain where first non-None answer wins
_Mapped to: docs/adr/0014-dynamic-pricing-catalog.md | Sprint: S9 track B | Owner: python-pro_
Description: As orchestration, I need a clean fallback strategy for pricing lookups.
Acceptance Criteria:
- `ChainedPricingCatalog` in `src/wiedunflow/adapters/cached_pricing_catalog.py`
- Query each catalog in order; first non-`None` answer wins
- Factory `_build_pricing_chain()` in `cli/main.py` builds `[CachedPricingCatalog(LiteLLM), StaticPricingCatalog()]` unconditionally; `httpx` is a hard dependency declared in `[project.dependencies]`
- Network failures inside `LiteLLMPricingCatalog` downgrade to empty dict; chain falls through to `StaticPricingCatalog`

US-098
Title: httpx declared as explicit hard dependency in pyproject.toml
_Mapped to: docs/adr/0014-dynamic-pricing-catalog.md | Sprint: S9 track B | Owner: python-pro_
Description: As intent signaling, I want explicit declaration that WiedunFlow imports httpx directly (PEP-621 honesty), not relying on transitive availability via anthropic/openai SDKs.
Acceptance Criteria:
- `httpx>=0.27` in `[project.dependencies]` of `pyproject.toml`
- Plain `import httpx` at top of `litellm_pricing_catalog.py` (no try/except, no defensive `_HTTPX_AVAILABLE` flag — anthropic+openai already require httpx, so unavailability is impossible in any supported install)
- New test `tests/unit/cli/test_no_httpx_outside_litellm_pricing.py` (clone `test_no_questionary_outside_menu.py`) ensures httpx not imported elsewhere — three-sink rule extension

US-099
Title: UX-spec §4.0 Picker mode — formalizes repo selection UI
_Mapped to: .ai/ux-spec.md §4.0 | Sprint: S9 track C | Owner: technical-writer_
Description: As UX specification, I document the three-source picker (Recent / Discover / Manual) flow and acceptance criteria.
Acceptance Criteria:
- Section added to UX-spec with source selector, drill-down per source, Back semantics, validation, empty states
- Exact copy for empty states: "No recent runs found. Choose another source." etc.
- Discovery scope: max_depth=1, skip list, .gitignore-aware, mtime sort DESC, cap 20
- Cross-references to `cli/menu.py`, `cli/picker_sources.py`, `interfaces/pricing_catalog.py` as applicable

US-100
Title: PRD v0.1.3 bump — formalize v0.5.0 user stories (US-088..US-099)
_Mapped to: .ai/prd.md | Sprint: S9 track C | Owner: technical-writer_
Description: As documentation, I capture the complete v0.5.0 feature set in formalized user stories.
Acceptance Criteria:
- PRD version bumped 0.1.0 → 0.1.3-draft
- US-088 through US-099 added with title, description, acceptance criteria
- All FRs referenced (none new; US-088/090/091 are v0.5.0 realizations of v0.4.0+ pipeline)
- CHANGELOG.md updated with `[0.5.0]` section (Added/Changed/Fixed)
- README.md notes LiteLLM pricing auto-update + 24h cache fallback
- Implementation-plan.md Sprint 9 marked DONE
- CLAUDE.md ADR_INDEX includes ADR-0014

## 6. Success Metrics

### 6.1 Release gate (hard)

All of the following must be true before tagging `v0.1.0`:

- `pytest -m eval` passes on the full five-repo corpus (US-065).
- Zero crashes across the five pinned repos.
- Fewer than 5% hallucinated symbols per generated tutorial.
- MCP Python SDK tutorial coverage ≥70% of the concepts listed in `tests/eval/corpus/mcp_python_sdk.yaml` versus the Anthropic Skilljar "Building MCP Clients" reference.
- Rubric sign-off (US-066): average ≥3 across coverage, accuracy, and narrative flow.

### 6.2 Ongoing metrics

| Metric | MVP target | Hard fail | Measurement |
|---|---|---|---|
| Concept coverage vs Anthropic Skilljar "Building MCP Clients" | ≥70% | — | Manual checklist against `tests/eval/corpus/mcp_python_sdk.yaml` |
| Hallucinated symbols in output | 0 | any occurrence is a regression | AST-grounding validator (Stage 1 snapshot vs `code_refs[].symbol`) |
| Narrative quality (reduced form) | author + 2 friends average ≥3/5 on coverage, accuracy, narrative flow | — | Rubric eval on MCP Python SDK tutorial pre-release |
| First run (medium repo ≤500 `.py` files) | <30 min | — | Timed run on benchmark corpus |
| Incremental run (<20% files changed) | <5 min | — | Timed cache-hit run |
| Per-tutorial cost (medium repo) | <$8 USD | — | `cost` field in `run-report.json` |
| Output HTML size (medium repo) | <8 MB | warn at >20 MB | File size assertion in build stage |
| Robustness across 5 pinned OSS repos | 0 crashes; <5% hallucinated symbols each | any crash blocks release | `pytest -m eval` |
| Jedi resolution coverage (high tier) | >80% on benchmark repos | — | `resolution_coverage_pct` in `run-report.json` |
| Zero telemetry guarantee | verified | any network call outside configured LLM provider is a regression | Integration test with network namespace restricted; template-time linter |
| Dependency CVE scan | no HIGH+ findings | HIGH+ finding blocks release | pip-audit in release workflow (FR-78) |
| Design fidelity vs ux-spec.md | pixel-perfect alignment | any regression blocks release | manual review at release gate comparing rendered output against `.ai/ux-spec.md` token values |

### 6.3 Operational signals (post-release)

Not release-blocking, but tracked from v0.1.0 onward:

- Proportion of runs ending with `status = "ok"` versus `"degraded"` versus `"failed"`, aggregated locally by the author from self-use (no telemetry is emitted; this metric is computed only when the author copies run reports to a private analytics file manually).
- Cache hit rate distribution across runs — informs whether the 20% PageRank-diff threshold is tuned correctly.
- Distribution of `skipped_lessons_count / total_planned_lessons` — informs whether the 30% DEGRADED threshold is tuned correctly.

These signals guide v0.2 scope. They are never reported to any remote service.
