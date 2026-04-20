# CodeGuide — generate interactive HTML tutorials from local Git repos

![CI](https://github.com/Mkaminsky-dev/codeguide/actions/workflows/ci.yml/badge.svg)

## What is CodeGuide

CodeGuide is a Python CLI that turns a local Git repository into a single, self-contained HTML
file — an interactive, tutorial-style guided tour of the code. Open the output directly in your
browser via `file://`, with no server and no runtime dependencies required. It combines AST
analysis, graph ranking, BM25 retrieval, and direct LLM orchestration to generate coherent,
pedagogically sound code walkthroughs.

## Install

> Available on PyPI from v0.1.0. Until then, install from source (see Development Setup in
> [CONTRIBUTING.md](CONTRIBUTING.md)).

```bash
uvx codeguide
```

## Quickstart

```bash
# Generate a tutorial for the current repository
codeguide .

# Specify a target directory
codeguide /path/to/repo

# Use a custom config
codeguide . --config tutorial.config.yaml
```

## CLI Reference

```
$ codeguide --help
Usage: codeguide [OPTIONS] REPO_PATH

  Generate an interactive HTML tutorial from a local Git repository.

Options:
  --exclude PATTERN   Additional .gitignore-style pattern to exclude (may repeat).
  --include PATTERN   Pattern to re-include despite .gitignore (may repeat).
  --root PATH         Override detected repo root (monorepo subtree).
  -V, --version       Show the version and exit.
  -h, --help          Show this message and exit.
```

### File discovery

`.gitignore` is respected by default.  User `--exclude` patterns are ADDITIVE (layered on top of
`.gitignore`), and `--include` patterns can re-enable files that would otherwise be excluded.
`__pycache__` and dotted directories (`.venv`, `.git`) are always skipped.  For monorepos,
CodeGuide auto-detects the Python subtree (first `pyproject.toml` or `setup.py` below the repo
root) — pass `--root` to override.

### Supported Python parsing (Sprint 2 / v0.0.2)

- AST extraction: `tree-sitter` + `tree-sitter-python` (functions, classes, methods, async).
- Call graph resolution: `jedi` with 3-tier coverage reporting (resolved / uncertain / unresolved).
- Graph ranking: `networkx` PageRank, Louvain communities (seed=42), SCC-condensed topological sort.
- Planning / generation still uses `FakeLLMProvider` — real LLM adapters land in Sprint 3.

## Privacy & LLM Disclosure

CodeGuide transmits parts of your source code to the configured LLM provider (Anthropic by
default). For sensitive code, see BYOK configuration with Ollama / LM Studio / vLLM for local
inference. Zero telemetry, zero usage analytics.

## BYOK Configuration

CodeGuide supports multiple LLM backends via BYOK (Bring Your Own Key). Configure in
`tutorial.config.yaml`:

```yaml
llm:
  provider: anthropic   # anthropic | openai | ollama | lmstudio | vllm
  model: claude-opus-4-7
  concurrency: 10
```

For local inference (Ollama / LM Studio / vLLM), set `base_url` to your local endpoint. No
source code leaves your machine.

Full configuration reference and environment variables: see [docs/config-reference.md](docs/config-reference.md)
(available from Sprint 1).

## License

Apache 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).

## Roadmap

Implementation plan (Sprint 0-7): [`.ai/implementation-plan.md`](.ai/implementation-plan.md)
