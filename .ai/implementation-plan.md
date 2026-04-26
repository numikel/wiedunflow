# Plan implementacji CodeGuide v0.1.0 — sprint breakdown dla delegacji per-US

## Context

CodeGuide to greenfield Python CLI (3.11+) generujący pojedynczy self-contained HTML z tutorialem po lokalnym repo Git. Spec docelowy: `.ai/prd.md` (v0.1.2-draft, 90 FR / 80 US), tech stack: `.ai/tech-stack.md`, reguły projektu: `D:\CodeGuide\CLAUDE.md`, dwa ADR w `docs/adr/`.

**Stan startowy (potwierdzony rekonesansem)**: repo jest w 100% greenfield — istnieją tylko `CLAUDE.md`, `.gitignore` oraz `docs/adr/0001*` i `docs/adr/0002*`. Brak `pyproject.toml`, brak `src/`, brak `.github/`, brak `LICENSE`, brak `README.md`, brak `tests/`, brak pre-commit.

UX specification is maintained in `.ai/ux-spec.md` (single source of truth for design tokens, exact CLI copy, component dimensions, and state management contracts), anchored by ADR-0011 binary decisions. Pixel-perfect recreation of the UX is targeted for Sprint 5; the Sprint 1 walking skeleton uses minimal HTML without design tokens.

**Cel planu**: rozbić implementację 90 FR / 80 US z PRD na sprinty z twardymi granicami taskowymi (per User Story), tak by użytkownik mógł delegować pojedyncze US do agenta ("Zaimplementuj US-023") zamiast skomplikowanych wielo-story zadań. Plan definiuje także parallel tracks w ramach sprintu (2-3 agenty jednocześnie) i miejsca mini-eval.

## Founding decisions (z pytań Sokratesowych)

| Pytanie | Decyzja |
|---|---|
| Strategia dostarczania | **Walking skeleton first** — Sprint 1 = end-to-end pipeline z `FakeLLMProvider` i stubami per etap. Każdy kolejny sprint pogrubia jeden/dwa etapy. |
| Granularność taska | **Per User Story** — 1 task = 1 US z PRD + kod + testy + docs update. Acceptance criteria już napisane w PRD. |
| Parallelism agentów | **Agent team 2-3 parallel od S2+** — w S0/S1 liniowo (scaffolding + konwencje), od S2 identyfikujemy independent tracks (np. tree-sitter / Jedi / networkx). |
| Kiedy eval | **Mini-eval od S3** (click), rozszerzamy per sprint, pełny 5-repo gate w S7. |
| Tempo | 1 sprint ≈ 1 tydzień nominalnie, elastycznie (agent koduje na żądanie — nie blokuje timeline). |
| Wersjonowanie | **Inkrementalne v0.0.x** per sprint → **v0.1.0** po release gate (S7). Każdy sprint = tag `v0.0.N`. |
| Zakres | **100% PRD** — wszystkie 90 FR i 80 US non-negotiable dla v0.1.0. |
| Docs cadence | **Per PR/task** — DoD każdego taska: kod + testy + docs (README/CHANGELOG/ADR jeśli dotyczy). |

## Definition of Done — per task (US)

Każde PR zamykające jeden US musi zawierać:

1. **Kod** w odpowiedniej warstwie Clean Architecture (`entities/` | `use_cases/` | `interfaces/` | `adapters/` | `cli/`).
2. **Testy**: unit + ewentualnie integration (pytest markers: domyślny CI pomija `@pytest.mark.eval`).
3. **Type hints + mypy --strict** czyste na dotkniętych plikach.
4. **Acceptance criteria z PRD** — każde wymienione jako osobny test (1-1 mapping gdzie to możliwe).
5. **Docs update**: README (nowe flagi/config), CHANGELOG (Keep-a-Changelog), ADR jeśli decyzja architektoniczna, JSON schema `tutorial.config.yaml` jeśli dotknięte.
6. **Conventional commit** ze scope zgodnym z PIPELINE (`ingestion|analysis|graph|rag|planning|generation|build|cli|cache|config`) + DCO `Signed-off-by:`.
7. **Lint pass**: `ruff check` + `ruff format --check` + `mypy --strict src/codeguide/**`.

## Definition of Done — per sprint

1. Wszystkie US sprintu zamknięte (PR zmergowane do `main`).
2. CI matrix (3.11/3.12/3.13 × Ubuntu/Windows/macOS) zielony na `main`.
3. Tag `v0.0.N` z podpisem, CHANGELOG zaktualizowany sekcją release.
4. Sprint canary eval (od S3+) zalogowany w `tests/eval/results/<sprint>-<date>.json`.
5. Journal sesji w `D:\Obsidian Vault\Sesje\` (jeśli sprint był długi — ≥3 dni pracy).

## Sprint overview

| # | Sprint | Tag | Główne deliverable | Mini-eval | Parallel tracks |
|---|---|---|---|---|---|
| 0 | Foundation | v0.0.0 | Scaffold: pyproject, LICENSE, NOTICE, README, CONTRIBUTING, pre-commit, CI, issue templates, src/codeguide skeleton, eval corpus submodules | — | liniowo |
| 1 | Walking Skeleton | v0.0.1 | End-to-end pipeline na fixture repo z FakeLLMProvider. Output HTML otwiera się przez file:// | — | liniowo |
| 2 | Analysis + Graph real | v0.0.2 | Stage 1 (tree-sitter + Jedi) + Stage 2 (PageRank + community) na realnym kodzie | — | A: parser · B: Jedi · C: graph |
| 3 | RAG + Planning + Anthropic | v0.0.3 | Stage 3 (BM25) + Stage 4 (planning) + AnthropicProvider + atypical repos | canary: click | A: RAG · B: LLM port + Anthropic · C: planning |
| 4 | Generation + Cache + BYOK | v0.0.4 | Stage 5 (generation orchestrator) + cache + checkpoint + interrupt + OpenAI/OSS adapters + grounding retry | canary: click + requests | A: generation · B: cache · C: BYOK providers |
| 5 | Output HTML + Run modes + Reporting | v0.0.5 | Stage 6 (Jinja2 + Pygments + template linter) + CLI flags + navigation + run report + pixel-perfect UX recreation per ux-spec.md + CLI UX polish (rich.panel/rich.live/color roles) | smoke: click + requests + starlette | A: build · B: run modes · C: HTML frontend |
| 6 | Privacy + Config + Hardening | v0.0.6 | Consent banner, hard-refuse list, `codeguide init`, config precedence, SecretFilter, shell injection hardening, pip-audit | smoke: 4/5 repos | A: privacy + init · B: config chain · C: hardening + SecretFilter |
| 7 | Release Candidate + Release Gate | v0.1.0-rc.1 → v0.1.0 | Pełny 5-repo eval, rubric sign-off, cross-OS fixes, release workflow | **gate: 5/5 repos + rubric ≥3** | A: eval runner · B: rubric coordination · C: CI/release |
| 8 | CLI UX wiring + animations | v0.2.0 | Wiring `StageReporter`/`render_cost_gate`/`render_run_report` z v0.1.0 do orchestratora + nowe animacje (Stage 2 replace-line, Stage 5 scroll, live counters) + cost-gate prompt domyślnie ON dla TTY + banner | — | A: orchestrator hooks · B: CLI wiring · C: tests + docs |
| 9 | Interactive repo picker | v0.3.0 | `codeguide` bez argumentów (TTY) → questionary picker (recent / discover / manual path) | — | A: picker UI · B: sources + cache · C: ADR-0012 + tests |

## Sprint 0 — Foundation (v0.0.0)

**Cel**: scaffolding projektu zanim padnie pierwsza linia kodu pipeline. Bez funkcjonalności biznesowej.

**Tracks**: LINIOWO (jeden agent — `devops-engineer` + `backend-developer`).

### US + tematy tego sprintu

Nie są to US z PRD, to infrastruktura pre-dev (wymuszona przez FR-02, FR-04, FR-69..72, US-001, US-059..063):

- **T-000.1** `pyproject.toml` z `[tool.uv]`, `[project.scripts] codeguide = "codeguide.cli:main"`, classifiers, Apache-2.0, copyright Michał Kamiński. Python 3.11-3.13.
- **T-000.2** Layout `src/codeguide/{entities,use_cases,interfaces,adapters,cli}/` z `__init__.py` i minimalnym `cli/__init__.py` eksportującym `main()`.
- **T-000.3** `LICENSE` (Apache 2.0) + `NOTICE` (Copyright 2026 Michał Kamiński — szkielet, auto-fill w S7).
- **T-000.4** `README.md` (szkielet sekcji wymaganych przez FR-73), `CONTRIBUTING.md` (DCO), `CHANGELOG.md` (Keep-a-Changelog).
- **T-000.5** `.pre-commit-config.yaml`: `ruff check`, `ruff format`, `mypy --strict`, `insert-license` (Apache header), `commitlint` via `cz-cli` (scopes: ingestion/analysis/graph/rag/planning/generation/build/cli/cache/config).
- **T-000.6** `pyproject.toml` — sekcje `[tool.ruff]`, `[tool.mypy]` (strict, per-module dla `src/codeguide/**`), `[tool.pytest.ini_options]` z markerem `eval`.
- **T-000.7** `.github/workflows/ci.yml` — matrix 3.11/3.12/3.13 × ubuntu/windows/macos, `astral-sh/setup-uv`, steps: `uv sync` → `ruff check` → `ruff format --check` → `mypy --strict` → `pytest` (bez `-m eval`).
- **T-000.8** `.github/workflows/dco.yml` — DCO check.
- **T-000.9** `.github/ISSUE_TEMPLATE/{bug_report,feature_request,eval_regression}.yml` (US-063, FR-71).
- **T-000.10** `tests/eval/corpus/repos.yaml` + git submodules na pinned commitach dla: kennethreitz/requests, pallets/click, encode/starlette, modelcontextprotocol/python-sdk, dateutil/dateutil (US-065, FR-74).
- **T-000.11** `.gitignore` update: `.codeguide/`, `.venv/`, `__pycache__/`, `*.egg-info`, `dist/`, `build/`, `.mypy_cache/`, `.ruff_cache/`, `.pytest_cache/`.
- **T-000.12** ADR-0003 — Clean Architecture layering (entities/use_cases/interfaces/adapters/cli) — zrealizować w `docs/adr/`.
- **T-000.13** ADR-0004 — UV-exclusive toolchain i wykluczenie pip/pipx/poetry/hatch.
- **T-000.14** — Extract web fonts and design tokens stub
_Owner: python-pro_

  - Download Inter 400/500/600/700 + JetBrains Mono 400/500/600 WOFF2 files (OFL-licensed, from Google Fonts or fontsource)
  - Place in `src/codeguide/renderer/fonts/` with OFL license files; append license notice to `NOTICE` file (create if absent)
  - Create `src/codeguide/renderer/templates/tokens.css` with CSS custom properties for A1 Paper light + dark palette per `.ai/ux-spec.md` §Tutorial.tokens (all `--bg`, `--panel`, `--surface`, `--topbar`, `--ink`, `--ink-dim`, `--accent`, `--warn`, `--border` values; dark palette under `[data-theme=dark]`)
  - Create `src/codeguide/renderer/__init__.py` (empty, marks directory as Python package)
  - Test: `tests/unit/test_fonts_embedded.py` — assert WOFF2 magic bytes (`wOFF` / `wOF2`) for each font file; assert tokens.css contains all required custom properties

**DoD sprintu 0**:

- `uvx --from git+<local> codeguide --version` drukuje `0.0.0` (na fake stub `cli/main.py` zwracającym `print("codeguide 0.0.0")`).
- `uv sync && pytest` zielone (zero testów jeszcze).
- CI matrix przechodzi.
- `pre-commit install && pre-commit run --all-files` zielone.
- Tag `v0.0.0`, CHANGELOG sekcja `## [0.0.0] - <date> — Foundation`.

**Powiązane US z PRD (częściowo spełnione)**: US-001 (baseline install), US-059 (pre-commit), US-061 (CI matrix), US-063 (issue templates), US-062 (NOTICE szkielet), US-065 (eval corpus bez uruchomienia).

---

## Sprint 1 — Walking Skeleton (v0.0.1)

**Cel**: end-to-end pipeline 7 etapów działa na fixture repo z `FakeLLMProvider` zwracającym deterministyczny `lesson_manifest` i hardcoded narrację. Output HTML otwiera się przez `file://` w headless Chromium.

**Tracks**: LINIOWO (jeden agent — `python-pro` + `test-automator` przy testach e2e).

### US + tematy

- **T-001.1** Domain entities (`entities/`): `LessonPlan`, `Lesson`, `CodeSymbol`, `CallGraph`, `LessonManifest` — Pydantic v2 modele z invariants. Bez zależności zewnętrznych.
- **T-001.2** Ports (`interfaces/ports.py`): `LLMProvider`, `Parser`, `VectorStore`, `Cache`, `Editor`, `Clock`. Same ABC/Protocol.
- **T-001.3** `FakeLLMProvider` w `adapters/fake_llm_provider.py` — deterministyczne odpowiedzi per prompt hash; używane w testach e2e.
- **T-001.4** Stub adapters (wszystkie zwracają pre-scripted dane dla 1 fixture repo `tests/fixtures/tiny_repo/`): `StubTreeSitterParser`, `StubJediResolver`, `StubBm25Store`, `InMemoryCache`.
- **T-001.5** `use_cases/generate_tutorial.py` — orchestrator wywołujący 7 etapów po kolei, używający portów.
- **T-001.6** `adapters/jinja_renderer.py` + minimalny template HTML (hardcoded CSS + vanilla JS navigation Prev/Next + `<script type="application/json">` z lesson data).
- **T-001.7** `adapters/pygments_highlighter.py` — wrapping Pygments, pre-render code → HTML spans.
- **T-001.8** `cli/main.py` — click entrypoint `codeguide <repo>`, wywołuje use case, zapisuje `tutorial.html` do cwd.
- **T-001.9** Template-time offline linter (walidacja output HTML na `fetch(`, `Image(`, `<link rel="prefetch">`, `<link rel="preconnect">`, `http(s)://` poza whitelistą) — spełnia FR-14 częściowo.
- **T-001.10** Golden file test: uruchom pipeline na `tests/fixtures/tiny_repo/` → porównaj z `tests/fixtures/expected_tutorial.html` (snapshot).
- **T-001.11** Playwright test: otwórz `tutorial.html` w headless Chromium z wyłączonym network, sprawdź `console.error` == 0, kliknij Next → widać drugi lesson (US-040 baseline).

**Nowe ADR**: ADR-0005 — Frozen vanilla JS output (brak Preact/React/bundlera), binarna decyzja.

**DoD sprintu 1**: `codeguide tests/fixtures/tiny_repo/` produkuje `tutorial.html` < 500 KB, golden test zielony, Playwright zielony na `file://` bez sieci, tag `v0.0.1`.

**US z PRD (częściowo)**: US-014 (default mode na fake), US-040 (file:// + zero external) — baseline.

---

## Sprint 2 — Analysis + Graph real (v0.0.2)

**Cel**: zastąp stub parsera/resolvera/rankingu realnymi implementacjami. `codeguide` działa na ≥5 losowych OSS Python repo bez crashu (ale nadal z `FakeLLMProvider`).

**Parallel tracks** (3 agenty):

- **Track A — `python-pro`**: tree-sitter + pathspec + ingestion (Stage 0 + 1 parser).
- **Track B — `python-pro`**: Jedi resolver + cycle detection + dynamic-import flagging (Stage 1 resolver).
- **Track C — `python-pro`**: networkx PageRank + community detection + topological sort + leaves→roots outline (Stage 2).

### US z PRD przypisane

Track A:
- US-009 (respect `.gitignore`)
- US-010 (additive exclude/include patterns)
- **US-036** (no README handling)
- **US-037** (auto-detect Python subtree w monorepo)
- US-045 (`--root` override)

Track B:
- **US-039** (Jedi resolution 3-tier coverage reporting)
- US-038 (low documentation coverage warning)
- Cycle/dynamic-import detection jako metadata `uncertain` (CLAUDE.md GROUNDING_AND_COHERENCE)

Track C:
- PageRank ranking per symbol (przygotowanie do US-024 w S4)
- Graph community detection (feature clusters dla Stage 4 planning w S3)
- Snapshot top-N symboli (przygotowanie do US-024 diff w S4)

### Integracja end-of-sprint

- **T-002.INT**: uruchom `codeguide` (nadal z FakeLLMProvider) na 5 losowych OSS Python repo — asser zero crashów, loguj `resolution_coverage_pct`.
- Kontrakt cross-track: track A produkuje `IngestionResult`, B wzbogaca o `CallGraph`, C wzbogaca o `RankedGraph`.

**Nowe ADR**: ADR-0006 — AST snapshot schema (klucze, invariants grounding).

**DoD sprintu 2**: tag `v0.0.2`, cross-track integration test zielony na 5 losowych repos, golden snapshots zaktualizowane świadomie.

---

## Sprint 3 — RAG + Planning + Anthropic + canary eval (v0.0.3)

**Cel**: pierwszy realny LLM w pipeline. Anthropic działa, Stage 3 RAG indeksuje prawdziwe źródła, Stage 4 generuje realny `lesson_manifest`. Mini-eval na `pallets/click`.

**Parallel tracks** (3 agenty):

- **Track A — `python-pro` + `ai-engineer`**: Stage 3 BM25 index (rank_bm25) + tokenizer + PageRank graph diff (przygotowanie US-024).
- **Track B — `ai-engineer` + `llm-architect`**: `AnthropicProvider` adapter + retry/backoff + consent banner szkielet.
- **Track C — `ai-engineer` + `prompt-engineer`**: Stage 4 planning prompt + `lesson_manifest` Pydantic validation + retry (FR-43).

### US z PRD

Track A:
- BM25 indexer (FR, nie-US) — wymagane przez US-036/US-038 narrację
- US-024 (PageRank diff 20% threshold — infrastruktura, pełny test w S4)

Track B:
- **US-051** (Anthropic default)
- **US-054** (exponential backoff na 429)
- Baseline consent banner (pełny flow US-005/US-007 w S6)

Track C:
- **US-033** (fatal fail Stage 4 po retry)

Cross-cutting:
- **US-036** (no README narration flag) — domknięcie
- **US-038** (low doc coverage warning) — domknięcie
- **US-048** (schema version w output JSON) — zapis `schema_version: "1.0.0"`

### Mini-eval

- **T-003.EVAL**: uruchom `codeguide` z Anthropic na `pallets/click` (commit pinned), zapisz run-report, manualnie oceń spójność 3-5 pierwszych lekcji. Zapisz baseline do `tests/eval/results/s3-click-baseline.json`.

**Nowe ADR**: ADR-0007 — Planning prompt contract + retry strategy.

**DoD sprintu 3**: tag `v0.0.3`, click generuje sensowny `lesson_manifest` z Anthropic, baseline zapisany.

---

## Sprint 4 — Generation + Cache + BYOK + grounding (v0.0.4)

**Cel**: pełny Stage 5 generation z realnym Haiku (opisy parallel) + Opus (narracja sequential), cache SQLite z inkrementalnością, grounding validation + retry + degraded policy, interrupt handling, OpenAI + OSS adapters.

**Parallel tracks** (3 agenty):

- **Track A — `ai-engineer` + `python-pro`**: generation orchestrator + Haiku/Opus routing + `concepts_introduced` state + grounding validator + retry + skipped placeholder.
- **Track B — `postgres-pro`/`backend-developer`**: SQLite cache (file-level SHA-256 + platformdirs + checkpoint per lesson + `--cache-path` override) + PageRank diff integration.
- **Track C — `ai-engineer` + `backend-developer`**: `OpenAIProvider` adapter + `OpenAICompatibleProvider` (httpx base_url override) + concurrency semaphore.

### US z PRD

Track A:
- **US-030** (grounding retry)
- **US-031** (skipped lesson placeholder)
- **US-032** (DEGRADED marker ≥30% skipped)
- **US-034** (narracja 150-1200 words walidator)
- **US-035** (30-lesson cap)
- **US-049** ("Where to go next" closing lesson)

Track B:
- **US-023** (incremental <5 min)
- **US-024** (PageRank diff threshold — integracja)
- **US-025** (platformdirs cache location cross-OS)
- **US-026** (SHA-256 file granularity)
- **US-017** (`--resume`)
- **US-018** (`--regenerate-plan`)
- **US-020** (`--cache-path`)

Track C:
- **US-052** (OpenAI alt provider)
- **US-053** (Ollama/LM Studio/vLLM OSS endpoint)
- Concurrency hard-cap 20, default 10 (FR-67)

Cross-cutting (single owner, nie track):
- **US-027** (first Ctrl+C graceful, cap 90s, exit 130)
- **US-028** (second Ctrl+C hard abort)
- **US-029** (unhandled exception → run-report.json `failed` + stack trace + exit 1)

### Mini-eval

- **T-004.EVAL**: click + requests canary z Anthropic, dodaj asercje `skipped_lessons_count < 30%`, `hallucinated_symbols == 0`, incremental <5 min na small change.

**Nowe ADR**: ADR-0008 — Cache schema v1 (SQLite tables + SHA-256 keys + migration policy).

**DoD sprintu 4**: tag `v0.0.4`, incremental benchmark zielony, grounding 0-hallucinations na click + requests.

---

## Sprint 5 — Output HTML + Run modes + Reporting (v0.0.5)

**Cel**: produkcja-jakość Stage 6 (Jinja2 + Pygments + inline builder + linter), wszystkie CLI run modes, `run-report.json` + rotacja, navigation + mobile layout + localStorage.

**Parallel tracks** (3 agenty):

- **Track A — `frontend-developer` + `python-pro` + `ui-designer`**: Jinja2 template + Pygments pre-render + linter + **pixel-perfect recreation per ux-spec**.
- **Track B — `python-pro` + `ai-engineer`**: CLI flags + cost estimator + **CLI UX polish (rich.panel / rich.live / color roles / run-report card / error scenarios)**.
- **Track C — `frontend-developer` + `ui-designer`**: Vanilla JS navigation (TOC, arrow keys, hash routing, localStorage, stacked/split-view responsive).

### US z PRD

Track A:
- **US-040** (file:// + zero external deps — finalny)
- **US-047** (offline-guarantee footer)
- **US-050** (<8 MB medium repo)
- **US-058** (Pygments pre-render — implicit w FR-58)
- **US-075**: Tutorial reader uses A1 Paper + Inter + darkness hierarchy
- **US-078**: Skipped-lesson placeholder rendered inline when `lesson.status == "skipped"`
- **US-079**: Degraded banner rendered top of HTML when `run_status == "degraded"`
- **US-080**: Confidence pill in narration meta row (HIGH/MEDIUM/LOW oklch)

Playwright visual regression tests: golden screenshots per viewport (1440×900 + 375×812) per theme (light + dark). Snapshots stored in `tests/visual/snapshots/`. Any diff >0.1% blocks the sprint gate.

Track B:
- **US-015** (`--dry-run` — Stages 0..4 + preview HTML)
- **US-016** (`--review-plan` — edytor resolver $EDITOR/$VISUAL/code/vi/notepad)
- **US-019** (`--max-cost`)
- **US-012** (cost estimation prompt ex-ante)
- **US-013** (`--yes` bypass)
- **US-021** (`--root` override — domknięcie z S2)
- **US-022** (`--log-format=json`)
- **US-055** (stdout summary z OSC 8 hyperlink)
- **US-056** (run-report.json schema)
- **US-057** (`.codeguide/` do `.gitignore` auto-append)
- **US-058** (historia 10 reports rotacja)
- **US-070**: CLI prints boxed cost-gate estimate with `rich.panel`
- **US-071**: CLI emits 7-stage output with exact copy and live counters
- **US-072**: CLI run report rendered as framed status-colored card
- **US-073**: CLI 429 backoff displayed with attempt/5 counter
- **US-074**: CLI color roles follow ux-spec §CLI.color-roles

**T-005.UX-VALIDATE**: Manual review of CLI output vs `.ai/ux-spec.md` §CLI for all 5 scenarios: happy path, degraded, rate-limited (429), failed (unrecoverable), cost-gate abort. Each scenario must be reproducible via a unit test with `FakeLLMProvider`.

Track C:
- **US-041** (split-view ≥1024 px z scroll sync)
- **US-042** (stacked <1024 px)
- **US-043** (clickable TOC)
- **US-044** (deep-link `#/lesson/<id>`)
- **US-045** (arrow key nav)
- **US-046** (localStorage last-lesson)
- **US-048** (schema version w template JS branching — domknięcie)
- **US-076**: Tutorial splitter resizable 28–72% persisted in localStorage
- **US-077**: Tutorial Tweaks panel (theme toggle only in production)

Splitter drag range 28–72%; `pointerdown/pointermove/pointerup` events on the splitter element; `localStorage` key `codeguide:tweak:narr-frac:v2`. Disabled on <1024px.

### Mini-eval

- **T-005.EVAL**: click + requests + starlette smoke (3/5), dodaj asercje rozmiaru HTML.

**Nowe ADR**: ADR-0009 — Output JSON schema v1.0.0 + future compat strategy.

**DoD sprintu 5**: tag `v0.0.5`, 3 repa działają end-to-end, Playwright testy split/stacked zielone.

---

## Sprint 6 — Privacy + Config + Hardening (v0.0.6)

**Cel**: zabezpieczenia, pierwsze uruchomienie UX, config precedence, SecretFilter, hardening subprocess, pip-audit. Reszta US-001..013.

**Parallel tracks** (3 agenty):

- **Track A — `security-auditor` + `backend-developer`**: consent banner flow + hard-refuse list + `codeguide init` wizard + zero-telemetry integration test.
- **Track B — `python-pro`**: config precedence chain (CLI > env > `--config` > `./tutorial.config.yaml` > user-level > defaults) + Pydantic validator.
- **Track C — `security-auditor` + `devops-engineer`**: SecretFilter (FR-80) + shell injection hardening dla `--review-plan` (FR-79) + pip-audit release workflow.

### US z PRD

Track A:
- **US-002** (codeguide init wizard)
- **US-005** (consent banner blocking first cloud-provider run)
- **US-006** (`--no-consent-prompt`)
- **US-007** (consent persisted per-provider)
- **US-008** (hard-refuse secret list — enforce przed wszystkim)
- **US-011** (zero telemetry integration test z ograniczonym network namespace)

Track B:
- **US-003** (skip wizard with flags)
- **US-004** (config precedence chain)

Track C:
- **US-068** (shell injection hardening dla editor resolver)
- **US-069** (SecretFilter w logs)
- **US-067** (pip-audit release workflow)
- **US-060** (DCO GitHub Action — jeśli jeszcze nie finalne z S0)
- **US-062** (NOTICE auto-aggregation release script)

### Mini-eval

- **T-006.EVAL**: smoke 4/5 repos (bez MCP SDK, który zachowujemy na S7 release gate).

**Nowe ADR**: ADR-0010 — Secret redaction policy + zero-telemetry contract.

**DoD sprintu 6**: tag `v0.0.6`, consent flow działa, network-namespace test zielony, pip-audit przechodzi.

---

## Sprint 7 — Release Candidate + Release Gate (v0.1.0-rc.1 → v0.1.0)

**Cel**: full 5-repo eval (US-065) + rubric sign-off (US-066) + cross-OS bug fixes + release workflow. Tag `v0.1.0`.

**Parallel tracks** (3 agenty):

- **Track A — `test-automator` + `ai-engineer`**: eval runner na 5 pinned repos z Anthropic, hallucinated-symbol counter, concept coverage checklist vs Skilljar.
- **Track B — `product-manager` + `technical-writer`**: rubric coordination (autor + 2 trusted friends), scoring template, archiwum wyników razem z release.
- **Track C — `devops-engineer`**: release workflow (trigger on tag `v*.*.*` — ale bez PyPI publish w MVP zgodnie z FR-03), final cross-OS bug fixes, README finalny.

### US z PRD

Track A:
- **US-064** (release gate pytest -m eval)
- **US-065** (5-repo smoke pinned commits, zero crashes, <5% hallucinations)

Track B:
- **US-066** (rubric sign-off ≥3 avg)

Track C:
- **US-067** (pip-audit w release workflow — domknięcie z S6)
- **US-062** (NOTICE auto-aggregation — domknięcie)
- **US-059** (pre-commit — audit + domknięcie)
- **US-061** (CI matrix — final)

### Final eval

- **T-007.GATE**: `pytest -m eval` na wszystkich 5 repach MUSI być zielony, rubric avg ≥3 na MCP SDK tutorial, 0 crashów, <5% hallucinated symbols. Bez tego NIE tagujemy v0.1.0.

**DoD sprintu 7**: tag `v0.1.0`, CHANGELOG sekcja release, archiwum rubric w repo, README zawiera disclosure LLM transmission.

---

## Sprint 8 — CLI UX wiring + animations (v0.2.0)

**Cel**: wire'ować istniejący UX-spec do pipeline'a + dodać animacje per-stage.
Po sprintcie `codeguide ./repo` w TTY pokazuje banner, animowane stage'y,
cost-gate prompt domyślnie ON, run-report card. Plan szczegółowy:
`~/.claude/plans/ok-zastanawa-mnie-jednak-linear-wigderson.md` (zaakceptowany
2026-04-25).

**Parallel tracks** (3 agenty, ~5-7 dni):

- **Track A — `python-pro`**: orchestrator hooks + Stage 1-4 wiring w `use_cases/generate_tutorial.py`. Plik scope: `cli/stage_reporter.py`, `use_cases/generate_tutorial.py` (Stages 1-4 + cost-gate hook).
- **Track B — `python-pro` + `frontend-developer`**: CLI wiring + Stage 5-7. Plik scope: `cli/main.py`, `cli/output.py` (banner, preflight), `cli/cost_gate.py` (NEW), `use_cases/generate_tutorial.py` (Stages 5-7 progress callbacks).
- **Track C — `test-automator` + `technical-writer`**: testy + docs. Plik scope: `tests/unit/cli/test_*` (US-081 do US-086), `README.md`, `CHANGELOG.md`, `.ai/ux-spec.md §4.5.1`, ADR-0011 dopisek.

### US (Sprint 8 — nowe)

- **US-081** Animated Stage 2 (Jedi) — replace-line per file (Track A)
- **US-082** Scrolling Stage 5 (narration) — append-only event log (Track B)
- **US-083** Live counters footer (tokens / cost / elapsed) (Track A)
- **US-084** Cost-gate domyślnie ON dla TTY + bypass: `--yes` / `--no-cost-prompt` / non-TTY (Track B)
- **US-085** Run-report card dla success / degraded / failed / interrupted / cost-gate-abort (Track B)
- **US-086** Banner startowy `CodeGuide vX.Y.Z` (Track B)
- **US-087** Animation strategy doc (UX-spec §4.5.1) — Q3 decyzja zapisana (Track C)

### Founding decisions (Q1-Q6 z pytań Socratesowych, plan-mode 2026-04-25)

| # | Decyzja | Rationale |
|---|---|---|
| Q1 | Sprint 8 wire'owanie spec'a, Sprint 9 picker (osobno) | Wire'owanie ~80% jest już zbudowane (martwy kod) — tani sprint, nie blokuje v0.1.0 |
| Q2 | `codeguide` bez argumentów → picker tylko gdy `stdin.isatty()` | Non-TTY (CI, pipe) dalej wymaga argumentu — żaden release flow się nie zepsuje (Sprint 9) |
| Q3 | Stage 2 = replace-line, Stage 5 = scroll | Mass scan (no-history) vs event log (auditable) |
| Q4 | Cost gate domyślnie ON dla TTY, auto-bypass non-TTY, flaga `--no-cost-prompt` | Pierwszy run pyta o $$$; CI bez friction |
| Q5 | `rich.live` + `rich.spinner` (Sprint 8) | Zero nowych deps; questionary dopiero w Sprint 9 |
| Q6 | S8 → v0.2.0, S9 → v0.3.0 | SemVer pre-1.0; cost-gate-default jest perceptual-breaking |

**DoD sprintu 8**: tag `v0.2.0`, CHANGELOG sekcja, README "What you'll see", UX-spec §4.5.1, 28+ nowych testów, smoke test e2e na tiny_repo.

---

## Sprint 9 — Interactive repo picker + Dynamic pricing (v0.5.0)

**Status**: DONE (2026-04-26)

**Cel**: `codeguide` bez argumentów (TTY) → questionary picker z 3 sources (recent runs / discover git repos / manual path), potem flow Sprint 8. Równolegle: pricing catalog finalize (live LiteLLM + optional httpx).

**Parallel tracks** (3 agenty, ~5-7 dni):

- **Track A — `python-pro`**: picker UI (`cli/picker.py` NEW) + dispatch w `cli/main.py:_DefaultToGenerate`.
- **Track B — `python-pro`**: sources discovery (`cli/picker_sources.py` NEW) + recent runs cache (`cli/recent_runs_cache.py` NEW).
- **Track C — `test-automator` + `technical-writer`**: ADR-0012, UX-spec §4.0 Picker mode, FR-91, README, tests.

### US (Sprint 9 — nowe)

- **US-088** Picker entry — `codeguide` bez args + TTY → `run_repo_picker()`. Non-TTY zostaje bez zmian.
- **US-089** Recent runs source — czytanie `~/.cache/codeguide/recent.json`, fallback gdy plik nie istnieje
- **US-090** Git-repo discovery — rekurencyjny walk cwd do max_depth=2, znajdź `.git/`
- **US-091** Manual path source — `questionary.path()` z walidacją "is git repo"
- **US-092** Recent runs cache writeback — po success run zapisz wpis (LRU 10)

**Nowa dep**: `questionary>=2.0` (transitive `prompt_toolkit` ~600 KB).

**DoD sprintu 9**: tag `v0.3.0`, ADR-0012, UX-spec §4.0, FR-91, recent.json cross-platform.

## ADR queue

| ADR | Temat | Sprint | Status |
|---|---|---|---|
| 0001 | LLM stack direct SDK | — | Accepted (pre-plan) |
| 0002 | RAG BM25 MVP | — | Accepted (pre-plan) |
| 0011 | UX design system — palette, typography, CLI direction | S0 (pre-dev decision) | Accepted 2026-04-19 |
| 0003 | Clean Architecture layering | S0 | do napisania |
| 0004 | UV-exclusive toolchain | S0 | do napisania |
| 0005 | Frozen vanilla JS output | S1 | do napisania |
| 0006 | AST snapshot schema + grounding | S2 | do napisania |
| 0007 | Planning prompt contract + retry | S3 | do napisania |
| 0008 | Cache schema v1 | S4 | do napisania |
| 0009 | Output JSON schema v1.0.0 | S5 | do napisania |
| 0010 | Secret redaction + zero-telemetry | S6 | Accepted 2026-04-22 |

## Delegation playbook — jak rozmawiać z agentem

### Standardowy prompt dla agenta per US

```
Kontekst: projekt CodeGuide. Przeczytaj D:\CodeGuide\CLAUDE.md, sekcję <STAGE> z .ai/prd.md oraz odpowiednie ADR w docs/adr/.

Zadanie: zaimplementuj US-<NR> zgodnie z PRD §5 — wszystkie acceptance criteria jako osobne testy pytest.

Constraints:
- Clean Architecture — kod w warstwie: <entities|use_cases|interfaces|adapters|cli>
- Type hints + mypy --strict clean
- Conventional commit z scope: <ingestion|analysis|graph|rag|planning|generation|build|cli|cache|config>
- DCO sign-off w commicie
- Docs update: README (jeśli nowa flaga/config), CHANGELOG (Keep-a-Changelog), ADR jeśli decyzja architektoniczna

DoD: PR zielony na CI (ruff, mypy, pytest), wszystkie AC z US-<NR> mają osobne testy, docs zaktualizowane.

Sub-agent rekomendacja: <python-pro|ai-engineer|backend-developer|security-auditor|frontend-developer|test-automator>
```

### Delegation matrix — rekomendacja subagenta per typ US

| Obszar | Subagent primary | Uzupełniająco |
|---|---|---|
| Parser, call graph, ranking | `python-pro` | `performance-engineer` |
| LLM orchestration, prompts | `ai-engineer` | `prompt-engineer`, `llm-architect` |
| Adapters providerów | `ai-engineer` | `backend-developer` |
| Cache, persistence | `postgres-pro` | `backend-developer` |
| CLI, run modes | `python-pro` | `backend-developer` |
| Output HTML template | `frontend-developer` | `ui-designer` |
| Navigation JS | `frontend-developer` | `javascript-pro` |
| Security (consent, secrets, SecretFilter) | `security-auditor` | `compliance-auditor` |
| CI/CD, release | `devops-engineer` | — |
| Testy eval, rubric | `test-automator` | `product-manager` |
| Docs, README, CHANGELOG | `technical-writer` | — |

### Równoległość — jak uruchamiać agent teams (S2+)

W każdym sprincie S2-S7 identyfikuję 2-3 niezależne tracks (A/B/C). Delegacja tracków do agentów:

1. Główny Claude spawnuje 3 agenty w jednym message (parallel tool calls) z prefiksem `Agent:Track<A|B|C>`.
2. Każdy track ma wyraźnie określony scope (lista US) i kontrakt wyjściowy (typ danych → warstwa).
3. Po zakończeniu wszystkich tracków — główny Claude robi **integration test** na realnym repo (fixture lub 1 z 5 eval repos).
4. Merge konfliktów rozwiązuje główny Claude, nie subagent.

## Version bump recommendation

**Poziom zmian**: MINOR — wprowadzamy nowe FR-81..90, US-070..080 oraz AC additions bez łamania istniejących wymagań (brak breaking changes).

- `.ai/prd.md` — bump do `0.1.2-draft` (z `0.1.1-draft`; MINOR — new FR-81..90, US-070..080, AC additions — no breaking changes to existing requirements)
- `.ai/tech-stack.md` — bump do `0.1.2-draft` (PATCH — refinement of §9/§11/§17/§18, no new technology decisions)
- `implementation-plan.md` — no version bump; add CHANGELOG entry: `Unreleased — Integrated codeguide-ux-skill: T-000.14 fonts pre-work, S5 tracks A/B/C extended for pixel-perfect UX + CLI UX polish, ADR-0011 queued`

## Weryfikacja końcowa — po implementacji każdego sprintu

1. **Lokalnie**: `uv sync && ruff check && ruff format --check && mypy --strict src/codeguide/** && pytest` — zielone.
2. **CI**: matrix 3.11/3.12/3.13 × ubuntu/windows/macos zielony.
3. **Smoke**: `codeguide tests/fixtures/tiny_repo/ --yes` produkuje `tutorial.html` i otwiera się w Playwright bez console error.
4. **Canary eval (od S3)**: `pytest -m eval -k click` zielony (wymaga ANTHROPIC_API_KEY).
5. **Full eval (tylko S7)**: `pytest -m eval` zielony na wszystkich 5 pinned repos.
6. **Release gate (tylko S7)**: rubric avg ≥3 na MCP SDK podpisany przez autora + 2 trusted friends, 0 crashes, <5% hallucinations.

## Krytyczne pliki do modyfikacji (high-level)

- `.ai/ux-spec.md` — single source of truth for UX
- `docs/adr/0011-ux-design-system.md` — binary UX decisions
- `src/codeguide/renderer/fonts/*.woff2` — Inter + JetBrains Mono WOFF2 (S0 T-000.14)
- `src/codeguide/renderer/templates/tokens.css` — CSS custom properties (S0 T-000.14)
- `src/codeguide/renderer/templates/tutorial.css` — layout + component styles (S5 track A)
- `pyproject.toml` — pełna konfiguracja UV + ruff + mypy + pytest
- `src/codeguide/entities/*.py` — Pydantic modele
- `src/codeguide/interfaces/ports.py` — wszystkie porty (LLMProvider, Parser, VectorStore, Cache, Editor, Clock)
- `src/codeguide/use_cases/generate_tutorial.py` — orchestrator 7-stage
- `src/codeguide/adapters/{anthropic,openai,openai_compatible}_provider.py` — BYOK
- `src/codeguide/adapters/{tree_sitter_parser,jedi_resolver,bm25_store,sqlite_cache,jinja_renderer,pygments_highlighter}.py`
- `src/codeguide/renderer/templates/tutorial.html.j2` — Jinja2 template (S5 track A)
- `src/codeguide/cli/main.py` — click entry + run modes + signals + logger
- `src/codeguide/cli/config.py` — Pydantic config + precedence chain
- `src/codeguide/cli/logging.py` — structlog setup + SecretFilter
- `src/codeguide/cli/output.py` — rich.panel cost gate, run report card (S5 track B)
- `tests/eval/corpus/repos.yaml` + submodules
- `tests/fixtures/tiny_repo/` — fixture dla walking skeleton
- `docs/adr/0003..0011-*.md`
- `.github/workflows/{ci,dco,release,eval}.yml`
- `README.md`, `CHANGELOG.md`, `CONTRIBUTING.md`, `LICENSE`, `NOTICE`

## Ryzyka planu i mitigacje

| Ryzyko | Mitigacja |
|---|---|
| Walking skeleton w S1 za cienki → pogrubianie w S2-S6 odkrywa fundamentalne braki | S1 kończy się Playwright e2e + golden test — każda zmiana kontraktu entities wymusza świadomy update golden. |
| Parallel tracks S2+ generują merge conflicts | Każdy track ma wyraźny scope plików (różne moduły src/codeguide). Kontrakt cross-track = typ danych, nie wspólne pliki. |
| Rubric sign-off (US-066) blokuje release jeśli 2 friends niedostępni | Przygotować listę friends w S6 (nie S7), umówić slot review z timeboxem. |
| Eval cost eksploduje przy 5 repach × Anthropic (Opus drogi) | `--max-cost` na każdym eval run; logowanie kosztu per-repo; Opus z `claude-sonnet-4-6` fallback dla uboższych repos. |
| Cross-OS Windows test zielone lokalnie, czerwone w CI przez ścieżki | `pathlib.Path` wszędzie + `platformdirs`; CI ma jobs per OS od S0 — łapiemy wcześnie. |

## Session Journal

**Status**: extracted
**Session ref**: [[Sesje/2026-04-20-codeguide-sprint-0|Sprint 0 Foundation]]

### Co zrobione
- Sprint 0 plan zaakceptowany (2026-04-20) — 7 pytań Socratesowych, Context7 docs dla UV/ruff/pre-commit
- T-000.1..T-000.13 wdrożone przez devops-engineer (1 liniowy agent) + technical-writer (równolegle ADR)
- T-000.14 wdrożone przez python-pro (fonty WOFF2 z CDN, tokens.css, testy)
- 11/11 testów PASS, ruff clean, mypy strict clean, `codeguide --version` → `0.0.0`
- Worktree isolation uwaga: agenty pisały do GŁÓWNEGO repo mimo `isolation: worktree` (znany issue)

### Co poszło dobrze
- Parallel agents (devops + technical-writer) bez merge-konfliktów (rozdzielony scope plików)
- CDN fontsource działało (jsdelivr) — WOFF2 magic bytes `wOF2` OK
- GitHub Actions versions: `checkout@v6`, `setup-uv@v7` (skorygowane po Sprint 3 — `@v8` nie istnieje jako major tag, CI padło; autor astral-sh wypuścił tylko `v8.1.0`)
- mypy strict: 0 issues na 8 plikach od pierwszego uruchomienia

### Co poszło źle / blockers
- `isolation: worktree` nie odizolowało agentów — pisali do main repo. Worktree'e zostały locked bez commitów. Trzeba je usunąć ręcznie (`git worktree remove -f -f`).
- mypy nota: "unused section tests.*" — nieszkodliwa, zniknie gdy pojawią się testy z type hints

### Lessons learned
- `isolation: worktree` w Agent tool nie gwarantuje że agent BĘDZIE pisał do worktree — agent używa Write/Edit narzędzi które działają w current working directory. To `isolation: worktree` tylko zakłada repo copy, ale agent musi świadomie pisać do WORKTREE PATH.
- Dla prawdziwego isolation trzeba podać worktree path explicite w prompcie agenta.

### CLAUDE.md improvement candidates
- Dodać notę o `isolation: worktree` — agenty piszą do CWD (main repo), nie do worktree path. Jeśli chcemy izolacji, podaj worktree path explicite w prompcie.

### Auto-memory candidates
- `isolation: worktree` w Agent tool nie izoluje file writes — agents use Write/Edit na CWD

### Wnioski dla następnej sesji
- Sprint 1: Walking Skeleton — `python-pro` + `test-automator`. Trigger: "Zaimplementuj Sprint 1"
- Przed pushem v0.0.0 tag: `git worktree remove -f -f D:/CodeGuide/.claude/worktrees/agent-*`
- Commit flow: `git checkout -b chore/sprint-0-scaffold && git add ... && git commit -s -m "chore(config): ..."`
- Pre-commit autoupdate po pierwszym commit (pin najnowsze rev)
