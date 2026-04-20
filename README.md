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

Set your Anthropic API key before the first run (BYOK — your key stays on your machine):

```bash
export ANTHROPIC_API_KEY=sk-ant-...   # bash / zsh
$env:ANTHROPIC_API_KEY = "sk-ant-..." # PowerShell
```

## Quickstart

```bash
# Generate a tutorial for the current repository (prompts for consent on first run)
codeguide .

# Non-interactive (CI, scripts) — skip the consent banner
codeguide /path/to/repo --yes

# Use a custom config
codeguide . --config tutorial.config.yaml
```

## CLI Reference

```
$ codeguide --help
Usage: codeguide [OPTIONS] REPO_PATH

  Generate an interactive HTML tutorial from a local Git repository.

Options:
  --exclude PATTERN            Additional .gitignore-style pattern to exclude (may repeat).
  --include PATTERN            Pattern to re-include despite .gitignore (may repeat).
  --root PATH                  Override detected repo root (monorepo subtree).
  --config PATH                Path to a YAML config file (default: ./tutorial.config.yaml).
  --no-consent-prompt          Skip the privacy consent banner (non-interactive).
  --yes                        Auto-confirm all prompts including the consent banner.
  --provider [anthropic|openai|openai_compatible]
                               LLM provider (default: anthropic; openai / openai_compatible in Sprint 4).
  --model-plan MODEL           Override the planning-stage model (default: claude-sonnet-4-6).
  --model-narrate MODEL        Override the narration-stage model (default: claude-opus-4-7).
  -V, --version                Show the version and exit.
  -h, --help                   Show this message and exit.
```

### File discovery

`.gitignore` is respected by default.  User `--exclude` patterns are ADDITIVE (layered on top of
`.gitignore`), and `--include` patterns can re-enable files that would otherwise be excluded.
`__pycache__` and dotted directories (`.venv`, `.git`) are always skipped.  For monorepos,
CodeGuide auto-detects the Python subtree (first `pyproject.toml` or `setup.py` below the repo
root) — pass `--root` to override.

### Parsing + RAG stack (Sprint 3 / v0.0.3)

- AST extraction: `tree-sitter` + `tree-sitter-python` (functions, classes, methods, async).
- Call graph resolution: `jedi` with 3-tier coverage reporting (resolved / uncertain / unresolved).
- Graph ranking: `networkx` PageRank, Louvain communities (seed=42), SCC-condensed topological sort.
- RAG: `rank_bm25.BM25Okapi` over docstrings, README, `docs/**/*.md`, CONTRIBUTING, and the last
  50 git-log messages.  Custom tokenizer splits `snake_case` and `camelCase` and strips a curated
  stopword list.
- Planning (Stage 5): `claude-sonnet-4-6`; narration (Stage 6): `claude-opus-4-7`.  Grounding is
  validated post-hoc against the AST snapshot — any hallucinated symbol fails the run fast
  (ADR-0007).

## Privacy & LLM Disclosure

CodeGuide transmits the source code it narrates (symbol bodies, docstrings, selected file
excerpts) to the configured LLM provider — Anthropic by default.  **No code leaves your machine
until you accept the consent banner on the first run of a session.**  `--yes` and
`--no-consent-prompt` bypass the prompt for CI / scripts; both flags are recorded in the run
logs.  There is **zero telemetry** and **zero usage analytics** — the only outbound traffic is
the LLM API call.

For sensitive codebases, Ollama / LM Studio / vLLM local-inference adapters arrive in Sprint 4
(`--provider openai_compatible` with a `base_url` override).

## Configuration

CodeGuide reads settings from the following sources, highest-precedence first:

1. CLI flags (`--provider`, `--model-plan`, `--model-narrate`, …)
2. Environment variables (`ANTHROPIC_API_KEY`, `CODEGUIDE_LLM_MODEL_PLAN`, …)
3. `--config <path>` (explicit YAML path)
4. `./tutorial.config.yaml` (in the current working directory)
5. `platformdirs` user-config file (`~/.config/codeguide/config.yaml` on Linux)
6. Built-in defaults

Example `tutorial.config.yaml` (see `tutorial.config.yaml.example` in the repo root):

```yaml
llm:
  provider: anthropic          # anthropic | openai | openai_compatible (S4+)
  model_plan: claude-sonnet-4-6
  model_narrate: claude-opus-4-7
  concurrency: 10              # cap 20; used from Sprint 4
  max_retries: 5
  max_wait_s: 60

exclude_patterns:
  - "**/tests/**"
  - "**/migrations/**"
include_patterns: []

max_lessons: 30
target_audience: "mid-level Python developer"
```

Full configuration reference and environment variables: see [docs/config-reference.md](docs/config-reference.md)
(available from Sprint 1).

## License

Apache 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).

## Roadmap

Implementation plan (Sprint 0-7): [`.ai/implementation-plan.md`](.ai/implementation-plan.md)
