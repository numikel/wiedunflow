# PRD Planning Summary — WiedunFlow MVP

> **Uwaga historyczna (2026-04-16):** Ten dokument odzwierciedla pierwotne decyzje stackowe (LangGraph, sqlite-vec, sonnet-4-5, opcjonalny Preact). Aktualny stack został odchudzony w PRD 0.1.1-draft — patrz `.ai/prd.md` i `.ai/tech-stack.md`. ADR-0001 i ADR-0002 wyjaśniają różnice. Rebrand do WiedunFlow w v0.6.0+.

*Generated: 2026-04-16 — compiled from planning session against `.ai/mvp-wiedunflow.md`.*

<conversation_summary>

<decisions>

1. **Primary persona**: a developer who sits down to an unfamiliar repository (OSS or corporate) and wants to understand it for themselves. **Not** a maintainer authoring onboarding material. All UX trade-offs favor time-to-first-tutorial over sharing/collaboration features.

2. **First-run UX**: ship a `wiedun-flow init` wizard (provider, model, API key) that writes to a user-level config. CLI flags and environment variables always override the stored config. No mandatory interactive setup for CI / power users.

3. **Ex-ante cost & time estimation**: before Stage 4 (planning) show a summary ("X files, ~$Y cost, ~Z minutes") and require `y/N` confirmation. `--yes` flag bypasses for CI. Estimation is purely heuristic — **no pre-flight LLM calls**. Formula: `cost ≈ (symbols × 500 tokens × $haiku_price) + (lessons × 8000 tokens × $sonnet_price) × 1.3` (+30% variance buffer). Formula is documented in README so users can verify it.

4. **Tutorial navigation (in-HTML)**: MUST for MVP — (a) clickable TOC in sidebar, (b) deep-links via URL hash `#/lesson/5`, (c) keyboard shortcuts `←`/`→`. Full-text search is v2+.

5. **Layout of a single lesson**: split-view desktop / stacked mobile with breakpoint at **1024 px**. ≥1024 px = narration left / code right, 50/50, scroll-sync. <1024 px = stacked inline flow (narration paragraph → relevant code block → next paragraph → next code block). Both rendering paths are driven by the same JSON blob embedded in `<script type="application/json">`.

6. **Lesson length**: adaptive with hard limits — **min 150, max 1200 words** of narration per lesson. Prompt guidance: "3–8 paragraphs, 2–4 minutes reading time". Post-hoc validator rejects <150 words (too shallow, triggers regeneration) and truncates >1200 words (rambling). JSON metadata exposes `estimated_read_time_minutes`.

7. **Grounding retry policy**: 1 retry maximum per lesson. Retry prompt is **explicit**: "Your previous response referenced these non-existent symbols: [X, Y]. Rewrite the lesson using ONLY symbols from this AST slice: [allowed_symbols]." If the retry also fails → skip the lesson with an explicit placeholder block in the HTML ("This lesson was skipped due to grounding failures — see symbol X in the code"). The count is exposed as `skipped_lessons_count` in footer metadata and the run report.

8. **Failure handling mid-pipeline**: partial failures **never abort the full run**. Skipped lessons, reduced resolution coverage, and missing docs are all graceful degradations surfaced in the run report and HTML footer.

9. **Success metric (release gate)**: MVP-feasible form — author + 2 trusted developer friends fill a 5-point-scale rubric (coverage, accuracy, narrative flow) on the generated MCP Python SDK tutorial. Full blind test with 5 developers is pushed to v1.1.

10. **Secret protection — two-tier**: (a) hard-refuse list (`.env*`, `*.pem`, `*_rsa`, `credentials.*`) is **never** sent to the LLM, even if not in `.gitignore`; (b) on first run with a cloud provider (Anthropic/OpenAI), an explicit consent banner blocks startup: "Your source code will be sent to <provider>. Continue? [y/N]". Can be disabled via `--no-consent-prompt` or `consent: accepted` in config.

11. **Manifest review**: `--review-plan` flag opens the generated `lesson_manifest` in `$EDITOR` between Stage 4 and Stage 5. User may delete / reorder / edit lesson titles and descriptions before content generation begins.

12. **Incremental update strategy**: detect via diff of the PageRank graph structure. If >20% change in top-ranked symbols → regenerate the full manifest (CLI surfaces this). Otherwise reuse the manifest and only regenerate lessons touched by changed files. `--regenerate-plan` forces manifest regeneration. `--resume` skips already-cached lessons.

13. **Distribution**: **no PyPI release in MVP**. Bare Git repo + `uvx wiedun-flow` as the documented install path. PyPI package is v2+.

14. **Toolchain mandate — UV only**: `uv` / `uvx` is the **single toolchain** for WiedunFlow. No `pip` / `pipx` anywhere — install commands, docs, CI, examples must all use `uv`. `pyproject.toml` uses `[tool.uv]` configuration. `uv sync` for dev setup, `astral-sh/setup-uv` in GitHub Actions.

15. **CLI language**: English only. Aligns with narration language (EN). No i18n scaffolding in MVP.

16. **`--dry-run` mode**: executes Stages 0 through 4 inclusive (including the planning LLM call, ~$0.05), **skips** Stage 5 generation. Outputs `tutorial-preview.html` containing: proposed lesson titles, estimated cost, graph structure visualization. This is a trust-building feature — hard blocker in MVP.

17. **Cache**: per-user via `platformdirs` (`~/.cache/wiedunflow/` on Linux, `%LOCALAPPDATA%\wiedunflow\Cache` on Windows, `~/Library/Caches/wiedunflow` on macOS). Cross-platform is non-negotiable. Key = `<repo_absolute_path>+<commit_hash>`. `--cache-path` flag for power users. No shared / committed caches in MVP.

18. **Budget hard-stop**: `--max-cost=USD` flag. After every lesson, accumulated cost is compared to the cap. On overrun → checkpoint + graceful abort with message "Generated N/M lessons. Resume with --resume --max-cost=X". Eliminates runaway-bill scenarios for BYOK users.

19. **Zero-telemetry guarantee**:
    - `localStorage` for in-browser UX persistence (last-viewed lesson, session progress) is allowed — **zero network**, purely client-side persistence.
    - No `fetch()`, no `Image()`, no `<link rel="prefetch">`, no external CDN, no analytics beacon. Hard rule enforced by a template linter.
    - HTML footer includes the statement: "Generated by WiedunFlow vX.Y.Z (Apache 2.0) — this document is fully offline."

20. **Post-run report**: dual-format.
    - Human-readable to stdout: files generated, lessons generated / skipped, cost (Haiku + Sonnet breakdown), elapsed time, cache hit rate, `file://` URL.
    - Machine-readable: `.wiedunflow/run-report.json` (directory auto-added to `.gitignore`). Used by CI and eval tracking.

21. **Atypical repositories**:
    - Missing `README.md` → RAG skips it without crashing; narration explicitly flags "no README — descriptions derived from code only".
    - Monorepo with mixed languages → auto-detect the deepest Python subtree (heuristic: directory with the most `.py` files) and scope to it; CLI message "Detected Python subtree: backend/ (X files). Override with --root=.".
    - No docstrings / no docs at all → pipeline continues; Stage 4 adds a "low documentation coverage — tutorial quality may be degraded" warning that renders in the HTML footer.

22. **`code_refs` JSON schema** (per lesson): array of objects `{file_path, symbol, line_start, line_end, role}` where `role` ∈ {`primary`, `referenced`, `example`}. Every `symbol` must exist in the Stage 1 AST snapshot — this is the enforcement point for grounding validation. Line ranges are optional (v2 expands to arbitrary code ranges without symbol anchor).

23. **Jedi partial resolution — graceful**: pipeline always continues regardless of resolution rate. Thresholds reported:
    - >80% resolved → "high confidence" (green in report)
    - 50–80% → "medium" (amber warning in HTML footer)
    - <50% → "low" (red warning + recommendation: "consider pyright adapter — v2+")
    - `resolution_coverage_pct` exposed in run report JSON.

24. **Interrupt semantics**:
    - First Ctrl+C → "Finishing current lesson (N/M)... press Ctrl+C again to abort immediately." Finishes the active lesson (cap ~90 s), checkpoints, exit code 130.
    - Second Ctrl+C → hard abort, marks the active lesson as `interrupted`, checkpoints, exit 130.
    - Unhandled exception crash → persist "failed at lesson N" state plus stack trace into `.wiedunflow/run-report.json`. Resume picks up from the last completed lesson.

25. **Output HTML schema versioning**: `metadata.schema_version` (semver) embedded in the tutorial JSON. MVP hardcodes `"1.0.0"` and documents it. Template JS will branch on the version for v2 breaking changes. Also embed `metadata.wiedunflow_version` (package version) for debugging.

26. **Eval corpus — pinned 5 repos** in `tests/eval/corpus/repos.yaml`, each pinned to a specific commit via git submodule:
    1. `kennethreitz/requests` — stable, well-documented
    2. `pallets/click` — canonical CLI
    3. `encode/starlette` — async + strong type hints
    4. `modelcontextprotocol/python-sdk` — primary benchmark (vs Anthropic Skilljar reference)
    5. `dateutil/dateutil` — large utility-function surface
    Smoke test: no crash + <5% hallucinated symbols.

27. **"Where to go next" lesson**: the final lesson is generated by one additional Sonnet call at the end of Stage 5. Contents: (a) external doc links parsed from repo `README.md`, (b) top-5 highest-ranked files that were omitted from lessons ("explore next"), (c) `git log` hints about actively changing subdirectories.

28. **Pre-commit stack**:
    - `ruff check` + `ruff format` (lint + format)
    - `mypy --strict src/wiedunflow/**`
    - `insert-license` hook (Apache 2.0 headers)
    - `commitlint` via `cz-cli` (conventional commits)
    - NOT in pre-commit: pytest (CI only), bandit (v2), `reuse lint` (v2)
    - DCO sign-off enforced as a GitHub Action check on PRs, NOT as a pre-commit hook (not every contributor uses `git commit -s` locally).

29. **README.md — MVP required sections**: installation via `uvx`, 3-step quickstart, `tutorial.config.yaml` example, troubleshooting ("API key not found", "Jedi can't resolve"), license note, `CONTRIBUTING.md` link, provider data-transmission disclosure (source code is sent to the configured LLM provider unless Ollama is used).

30. **GitHub issue templates** (in `.github/ISSUE_TEMPLATE/`): `bug_report.yml`, `feature_request.yml`, `eval_regression.yml` (dedicated template for eval-corpus regressions to keep quality signal traceable).

</decisions>

<matched_recommendations>

1. Lock a single primary persona ("dev exploring an unfamiliar repo") and let it drive all UX trade-offs — especially favoring prostoty pierwszego uruchomienia over sharing features.
2. Implement `wiedun-flow init` wizard as the default path, with CLI flags / env vars always taking precedence — gives non-experts a frictionless start without penalizing CI.
3. Always display ex-ante cost + time estimate with `y/N` confirmation (even for small repos) — builds trust in a BYOK product. Heuristic-only, no pre-flight LLM call.
4. Ship clickable TOC + deep links + keyboard shortcuts as the MUST-HAVE navigation set; defer full-text search to v2.
5. Resolve split-view vs mobile conflict with a 1024 px breakpoint and two rendering paths from the same JSON.
6. Adaptive lesson length (150–1200 words) with a post-hoc validator, not a prompt-only hint — guards against both shallow and rambling LLM output.
7. 1 retry maximum with a grounding-focused prompt, then skip with a placeholder — bounded cost + predictable UX, and transparency for the reader.
8. Reduce the pre-release quality gate to "author + 2 friends" rubric to avoid blocking v1.0.0 on a full blind test.
9. Two-tier secret protection with explicit first-run consent banner — required for any realistic enterprise adoption.
10. `--review-plan` flag opening the manifest in `$EDITOR` — radically improves quality for users who know their repo, low implementation cost.
11. Incremental updates driven by a PageRank-graph diff (>20% rule) rather than naive file diff.
12. Skip PyPI in MVP — distribute via `uvx --from git+...` directly.
13. **Enforce UV-only toolchain**: all install commands, docs, CI, examples use `uv` / `uvx`; never `pip` / `pipx`.
14. CLI is English-only in MVP to avoid i18n scaffolding drift.
15. `--dry-run` mode (Stages 0–4) as a trust-building feature before the $3 commit.
16. Per-user platform-appropriate cache via `platformdirs` — cross-platform is mandatory (Windows / Linux / macOS).
17. `--max-cost=USD` hard cap with graceful abort + checkpoint for resumability.
18. Zero network in the output HTML (no fetch / prefetch / external CDN), but localStorage for UX is allowed. Footer statement reinforces the guarantee.
19. Dual run-report: human-readable stdout + `.wiedunflow/run-report.json` for CI and eval tracking.
20. Graceful handling for atypical repos: missing README / monorepos / zero-documentation repos do not abort the pipeline — they surface warnings.
21. Structured `code_refs` schema with `role` field and mandatory symbol-in-AST invariant as the single enforcement point for grounding.
22. Always-continue Jedi behavior with coverage tiers (high / medium / low) surfaced in HTML footer and JSON report.
23. Two-level Ctrl+C pattern (graceful → hard abort) matching familiar CLI conventions.
24. `metadata.schema_version` + `metadata.wiedunflow_version` in the embedded JSON from day 1 to enable safe v2 migrations.
25. Pinned 5-repo eval corpus with commit hashes — reproducible robustness testing.
26. Auto-generated "Where to go next" closing lesson for narrative completeness.
27. Pre-commit stack limited to fast checks (ruff / mypy / license header / commitlint); DCO enforced via GitHub Action.
28. README + GitHub issue templates (incl. `eval_regression.yml`) as hard scope of the v0.1.0 product surface.

</matched_recommendations>

<prd_planning_summary>

### a. Main functional requirements

**Product core**: Python 3.11+ CLI that transforms a local Git repository into a single, self-contained, offline-capable HTML file delivering an interactive, tutorial-style guided tour of the codebase. Pipeline: `tree-sitter` + Jedi → PageRank graph + community detection → `sqlite-vec` RAG → LangGraph-orchestrated LLM generation (Haiku 4.5 leaves / Sonnet 4.5 narration) → Jinja2 + Pygments → inlined HTML output.

**Functional requirements confirmed during planning**:

- **Distribution & toolchain**: UV-exclusive. Install via `uvx --from git+https://... wiedunflow` from the Git repo; no PyPI release in MVP. Dev setup, CI, docs — all use `uv` / `uvx`.
- **First-run wizard** (`wiedun-flow init`) for non-expert users; CLI flags + env vars always override.
- **Ex-ante estimation + confirmation**: heuristic cost/time estimate with `y/N` prompt before Stage 4; `--yes` bypass; published formula.
- **Modes**:
    - Default run — full pipeline.
    - `--dry-run` — Stages 0–4 only (includes ~$0.05 planning call), outputs `tutorial-preview.html` with proposed titles, cost, graph.
    - `--review-plan` — opens manifest in `$EDITOR` between Stages 4 and 5.
    - `--resume` — continues from last checkpoint.
    - `--regenerate-plan` — forces manifest regeneration.
    - `--max-cost=USD` — hard budget cap with graceful abort + checkpoint.
    - `--yes`, `--no-consent-prompt`, `--cache-path`, `--root` — additional overrides.
- **Safety & privacy**:
    - Hard-refuse file list (`.env*`, `*.pem`, `*_rsa`, `credentials.*`) — never sent to LLM.
    - First-cloud-run consent banner: "Your source code will be sent to <provider>. Continue? [y/N]".
    - Zero telemetry. Zero network calls outside the configured LLM provider.
- **BYOK providers**: Anthropic (default), OpenAI, OSS via `ChatOpenAI` + `base_url` (Ollama / LM Studio / vLLM). Provider-specific reasoning fields (OpenRouter, DeepSeek) are v2.
- **Output HTML**:
    - Single file, 100% inlined (CSS, JS, JSON data, pre-rendered Pygments HTML).
    - Split-view @ ≥1024 px (narration/code, scroll-sync) / stacked @ <1024 px.
    - Navigation: clickable TOC + `#/lesson/N` deep links + `←`/`→` keyboard shortcuts.
    - `localStorage` for last-viewed lesson / progress (no network).
    - Footer: repo commit hash, branch, `generated_at`, WiedunFlow version, offline-statement, Jedi resolution confidence tier.
    - Embedded JSON carries `metadata.schema_version: "1.0.0"` and `metadata.wiedunflow_version`.
    - "Where to go next" closing lesson generated automatically.
- **Graceful degradation**:
    - Missing README / docs → note in narration, no crash.
    - Monorepos → auto-scope to deepest Python subtree.
    - Low doc coverage → HTML footer warning.
    - Jedi resolution <50% / 50–80% / >80% → three tiers in footer + JSON.
    - Grounding failure after 1 retry → lesson skipped with in-HTML placeholder; `skipped_lessons_count` surfaced.
    - First Ctrl+C = finish current lesson + checkpoint; second Ctrl+C = hard abort; crash = stack trace captured in run report.
- **Cache**: platformdirs per-user, cross-platform, keyed by `<repo_abs_path>+<commit_hash>`, SHA-256 per-file invalidation; shared caches are not in MVP.
- **Post-run reporting**: stdout summary + `.wiedunflow/run-report.json` (auto-gitignored).
- **Lesson contract**:
    - Length 150–1200 words (adaptive; post-hoc validator).
    - `code_refs[]` with `{file_path, symbol, line_start, line_end, role∈{primary, referenced, example}}`.
    - Every `symbol` must exist in Stage 1 AST snapshot (grounding enforcement point).
    - Max 30 lessons per tutorial (configurable).

### b. Key user stories & usage paths

1. **First-time explorer (primary persona)**:
   `uvx --from git+https://... wiedunflow ./new-repo` → wizard pops up if no API key → consent banner (first cloud run) → cost/time estimate + `y/N` → user confirms → progress bar through 7 stages → `tutorial.html` opens in Chrome → learner uses TOC + arrow keys to navigate, reading lesson-by-lesson.

2. **Cost-anxious evaluator**:
   `uvx ... wiedunflow ./repo --dry-run` → gets `tutorial-preview.html` with proposed lesson titles + cost estimate for ~$0.05 → inspects the plan → either commits to the full run or adjusts `focus_modules` / `exclude`.

3. **Repo expert authoring the tutorial**:
   `wiedunflow ./repo --review-plan --max-cost=2.50` → manifest opens in `$EDITOR` → user edits titles, removes uninteresting lessons → saves → pipeline continues with bounded budget.

4. **Resuming after interruption**:
   Long run interrupted by Ctrl+C (graceful) or crash → next invocation detects checkpoint → prompts (or `--resume`) → picks up from last completed lesson → cache hit rate report confirms efficiency.

5. **Iterative update on an active project**:
   Same repo re-run after pulling new commits → PageRank diff ≤20% → manifest reused → only changed-file lessons regenerated → <5 min wall time, <$0.50.

6. **Sensitive-code user**:
   `wiedunflow ./proprietary-repo` → consent banner shown → user cancels → configures Ollama in `tutorial.config.yaml` → re-runs → 100% local inference, no source code leaves machine.

### c. Success criteria & measurement

| Metric | MVP target | Measurement |
|---|---|---|
| Concept coverage vs Anthropic Skilljar "Building MCP Clients" | ≥70% | Manual checklist against pinned reference list in `tests/eval/corpus/mcp_python_sdk.yaml` |
| Hallucinated symbols in output | 0 | AST-grounding validator; any occurrence is a regression |
| Narrative quality (reduced form) | author + 2 friends average ≥3/5 on coverage + accuracy + narrative flow | Rubric eval on MCP Python SDK tutorial pre-release |
| First run (medium repo ≤500 files) | <30 min | Timed run on benchmark corpus |
| Incremental run (<20% files changed) | <5 min | Timed cache-hit run |
| Per-tutorial cost (medium repo) | <$3 | Run report `cost` field |
| Output HTML size (medium repo) | <8 MB (warn at >20 MB) | File size assertion in build stage |
| Robustness across 5 pinned OSS repos | 0 crashes; <5% hallucinated symbols each | `pytest -m eval` pre-release gate |

**Pre-release release gate**: `pytest -m eval` on the full 5-repo corpus + rubric sign-off before tagging `v0.1.0`.

### d. Project scope & constraints

- **Language & rendering**: Python 3.11+, `ruff`, `mypy --strict`. Output is `file://`-compatible: no `fetch()`, no ES module imports, no external CDN.
- **License**: Apache 2.0; DCO (not CLA); `LICENSE` + `NOTICE` + Apache header on all `.py` files; `insert-license` pre-commit hook.
- **CI**: GitHub Actions matrix (Python 3.11 / 3.12 / 3.13 × Ubuntu / Windows / macOS). Setup via `astral-sh/setup-uv`. DCO check on PRs.
- **Release path**: tag-triggered, but no PyPI in MVP; `v0.1.0` is a Git tag + GitHub release.
- **Architecture**: Clean Architecture with layers `entities` (domain) / `use_cases` / `interfaces` (ports) / `frameworks` (adapters). `LLMProvider`, `Parser`, `VectorStore`, `Cache` are ports — enables BYOK and the future TS/JS parser in v2.
- **Out of MVP scope**: mind-map visualization, TypeScript/JavaScript parsing, pyright adapter, polymorphism resolution, SaaS / hosted deployment, VS Code extension, GitHub Pages auto-deploy, framework-specific understanding (Django/FastAPI), auto-update on push, multi-user collaboration, direct GitHub URL input, non-English narration, telemetry, PyPI release, Docker image, full-text search in HTML, shared caches.

</prd_planning_summary>

<unresolved_issues>

1. **Precise heuristic for "medium repo"**: performance budgets mention "medium repo ≤500 files", but we did not fix the exact symbol-count / LoC definition used for cost-estimation formula calibration. Needs empirical measurement during week 5 eval against the pinned 5-repo corpus.

2. **Auto-detected Python subtree — heuristic parameters**: we agreed on "deepest folder with the most `.py` files", but not on tie-breaking (equal counts at same depth) or the minimum `.py` count threshold to qualify as a Python subtree (vs a stray test script).

3. **`--review-plan` UX on Windows**: `$EDITOR` convention is Unix-first. Fallback on Windows (Notepad / VS Code via `code --wait` / env-var expansion) needs explicit specification to match the cross-platform commitment.

4. **Run-report retention / rotation policy**: `.wiedunflow/run-report.json` — do we keep only the latest, append to a history file, or rotate (last N)? Useful for eval tracking across iterations.

5. **Lesson-skip budget**: we defined skip semantics per lesson but not a global "too many skipped → abort" threshold. E.g. if 15/25 lessons skip due to grounding failures, should the whole run be marked "failed" rather than producing a near-empty tutorial?

6. **Consent persistence scope**: `consent: accepted` in config — is it per-repo, per-provider, or global? Impacts trust UX when users switch providers or run on multiple repos.

7. **Stage 4 failure handling**: the planning LLM call (Sonnet, single call) can itself return invalid JSON or reference out-of-graph symbols. Retry / fallback behavior for this specific failure mode was not discussed.

8. **Eval rubric rubric definition**: "5-point rubric on coverage / accuracy / narrative flow" needs concrete scoring anchors ("1 = unusable, 3 = usable with caveats, 5 = matches hand-written reference") before pre-release sign-off is reproducible.

9. **Default `tutorial.config.yaml` location when config present**: CLAUDE.md specifies "`./tutorial.config.yaml` → defaults", but not the interaction with `wiedun-flow init` user-level config (`~/.config/wiedunflow/config.yaml` assumed). The precedence chain {CLI flags > `--config <path>` > `./tutorial.config.yaml` > user config > defaults} should be explicitly codified in the PRD.

10. **Apache NOTICE content for first release**: copyright holder (individual vs entity), third-party NOTICE aggregation from dependencies — needs a one-off decision before `v0.1.0` tag.

</unresolved_issues>

</conversation_summary>
