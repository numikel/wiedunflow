# Changelog

All notable changes to CodeGuide are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
