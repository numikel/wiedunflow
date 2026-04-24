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
  --provider [anthropic|openai|openai_compatible|custom]
                               LLM provider (default: anthropic; `custom` for Ollama / LM Studio / vLLM).
  --model-plan MODEL           Override the planning-stage model (default: claude-sonnet-4-6).
  --model-narrate MODEL        Override the narration-stage model (default: claude-opus-4-7).
  --base-url URL               OpenAI-compatible endpoint (e.g. http://localhost:11434/v1 for Ollama).
  --resume / --no-resume       Resume from the last checkpoint (US-017); --no-resume forces clean run.
  --regenerate-plan            Discard the cached lesson manifest and re-run Stage 4 (US-018).
  --cache-path FILE            Override the cache database location (US-020).
  --max-cost USD               Abort if the projected LLM cost exceeds this value (US-019).
  --dry-run                    Run Stages 0..4 and emit a preview HTML without paying for narration (US-015).
  --review-plan                Pause after Stage 4 and open the lesson manifest in $EDITOR (US-016).
  --log-format [text|json]     Structured log output on stderr (US-022). Default: text.
  -V, --version                Show the version and exit.
  -h, --help                   Show this message and exit.
```

### Output HTML reader (Sprint 5 / v0.0.5)

The generated `tutorial.html` is a single self-contained file — open it with `file://` in any
modern browser. No server, no CDN, no runtime network calls (US-040). Fonts (Inter + JetBrains
Mono) are inlined as `data:` URIs, Pygments syntax classes are pre-rendered, and the three JSON
payloads (`#tutorial-meta`, `#tutorial-clusters`, `#tutorial-lessons`) live inside `<script
type="application/json">` blocks — contract locked in ADR-0009.

Keyboard navigation: **←/→** switches lessons, **click in the TOC** jumps to any lesson, and
`tutorial.html#/lesson/<id>` deep-links straight into a specific one. The splitter between the
narration and code panels is resizable between 28 % and 72 %; your choice, along with the
light/dark theme, persists in `localStorage`. On screens narrower than 1024 px the reader stacks
narration and code inline.

A **degraded** run (> 30 % of lessons skipped) is marked with an amber banner at the top of the
page, and each skipped lesson is replaced by a dashed placeholder listing the unresolved symbols
so you can see exactly what was dropped and why.

### Exit codes (Sprint 5 / v0.0.5)

- `0` — tutorial written, `run-report.status == "ok"`.
- `1` — fatal error (config, planning, unhandled exception).  `run-report.status == "failed"`, `stack_trace` recorded.
- `2` — tutorial written **but degraded** (> 30 % of planned lessons skipped).  `run-report.status == "degraded"`.
- `130` — interrupted by Ctrl+C.  `run-report.status == "interrupted"`; rerun with `--resume` to continue.

Every run writes `.codeguide/run-report.json` (US-029 / US-056) with structured status, skipped-lesson count, cache hit rate, and (on failure) the full traceback.

### Ctrl+C semantics (US-027, US-028)

The CLI installs a two-phase SIGINT handler.  The first Ctrl+C flushes an explanatory banner to stderr, lets the **current lesson finish** (cap: 90 s), and checkpoints state so the next run can `--resume` from where it left off.  A second Ctrl+C within 2 seconds calls `os._exit(130)` for an immediate abort.

### BYOK — OpenAI, Ollama, LM Studio, vLLM (US-052, US-053)

The same `OpenAIProvider` adapter covers the hosted OpenAI API and any OpenAI-compatible endpoint via `--base-url`.  Anthropic stays the default.

```bash
# OpenAI (hosted)
export OPENAI_API_KEY=sk-...
codeguide ./my-repo --provider openai --model-plan gpt-4o --model-narrate gpt-4o

# Ollama — local inference, no API key, consent banner skipped
codeguide ./my-repo \
  --provider custom \
  --base-url http://localhost:11434/v1 \
  --model-plan llama3.1:70b \
  --model-narrate llama3.1:70b

# LM Studio / vLLM — same pattern, swap base-url to the server port
codeguide ./my-repo --provider custom --base-url http://localhost:8000/v1
```

Ollama and other OSS endpoints ignore `api_key`; pass anything (the SDK requires a non-empty string).  Consent is **not** prompted when `--base-url` is set because nothing leaves the machine.

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

For sensitive codebases use the **local-inference path** shipped in Sprint 4 / v0.0.4:
`--provider custom --base-url http://localhost:11434/v1` (Ollama) or any OpenAI-compatible
endpoint (LM Studio, vLLM).  Consent is **not** prompted when `--base-url` is set — no code
leaves your machine.  See the *BYOK* section above for ready-to-paste examples.

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
