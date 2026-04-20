# Changelog

All notable changes to CodeGuide are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
