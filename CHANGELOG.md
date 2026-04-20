# Changelog

All notable changes to CodeGuide are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
