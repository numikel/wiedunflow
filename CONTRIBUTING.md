# Contributing to CodeGuide

Thank you for your interest in contributing! This document covers the development workflow,
commit conventions, and expectations for pull requests.

## Developer Certificate of Origin (DCO)

All contributions are accepted under the [Developer Certificate of Origin
(DCO)](https://developercertificate.org/). By signing off on your commits
you certify that you have the right to submit the change under the
project's license (Apache-2.0).

Sign off every commit with the ``-s`` flag:

```bash
git commit -s -m "feat(rag): add hybrid retrieval fallback"
```

This appends a ``Signed-off-by: Your Name <you@example.com>`` line using
your configured git identity. The ``dco`` GitHub Action blocks any PR
that contains commits without the trailer.

## Development Setup

Prerequisites: [uv](https://docs.astral.sh/uv/) >= 0.4.0.

```bash
# Clone and install all dependencies (including dev group)
git clone https://github.com/Mkaminsky-dev/codeguide.git
cd codeguide
uv sync

# Install pre-commit hooks (runs ruff, mypy, license insertion, commitlint on every commit)
uv run pre-commit install
uv run pre-commit install --hook-type commit-msg
```

Run the test suite:

```bash
uv run pytest
```

Run linting and type checks manually:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src/codeguide
```

## Conventional Commits

All commits must follow [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/).

Format: `type(scope): description`

**Types**: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`

**Scopes** (pipeline stages, 1:1 with commit-lint config):

| Scope | Stage / area |
|---|---|
| `ingestion` | Stage 1: language detection, file hashing, cache lookup |
| `analysis` | Stage 2: tree-sitter AST, Jedi call graph, docstrings |
| `graph` | Stage 3: PageRank, community detection, topological sort |
| `rag` | Stage 4: BM25 index construction and retrieval |
| `planning` | Stage 5: LLM lesson manifest generation |
| `generation` | Stage 6: LLM lesson narration and orchestration |
| `build` | Stage 7: Pygments, Jinja2 template, HTML output |
| `cli` | Entry point, progress reporting, config resolution |
| `cache` | SQLite cache, checkpointing, incremental runs |
| `config` | `tutorial.config.yaml` schema, Pydantic models |
| `deps` | Dependency bumps (pyproject.toml, uv.lock) |
| `release` | Version bumps, CHANGELOG, PyPI publishing |

Breaking changes: append `!` after scope or add `BREAKING CHANGE:` footer.

Examples:
```
feat(cli): add --output flag to control HTML filename
fix(analysis): handle cyclic imports in Jedi call graph
feat(generation)!: change lesson_manifest JSON schema — updates config format
```

## Pull Request Checklist

Before opening a PR, verify:

- [ ] Tests pass: `uv run pytest`
- [ ] Docs updated — README if new CLI flag, CHANGELOG entry for every user-visible change
- [ ] Commit(s) follow Conventional Commits format with correct scope
- [ ] DCO sign-off present on every commit (`git commit -s`)
- [ ] ADR created in `docs/adr/` if the PR introduces an architectural decision
- [ ] CHANGELOG entry added under `[Unreleased]`
- [ ] Issue / US reference included (e.g. `Closes #42`, `Implements US-023`)
- [ ] `@pytest.mark.eval` tests pass if changing generation logic (requires `ANTHROPIC_API_KEY`)
