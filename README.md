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
# 1. First-run setup — interactive wizard writes ~/.config/codeguide/config.yaml
codeguide init

# 2. Generate a tutorial for the current repository (prompts for consent on first cloud run)
codeguide generate .
# Shorthand alias (preserved for backward compat): `codeguide .` still works

# 3. Non-interactive (CI, scripts) — skip both wizard and consent banner
ANTHROPIC_API_KEY=sk-ant-... codeguide generate /path/to/repo --yes --no-consent-prompt
```

## First-run setup (`codeguide init`)

Sprint 6 adds a subcommand that writes a nested-YAML user-level config without
touching the project:

```
$ codeguide init --help
Usage: codeguide init [OPTIONS]

  Interactive wizard — write a user-level config.yaml (US-002).

Options:
  --provider [anthropic|openai|openai_compatible|custom]
                            LLM provider (non-interactive: skip provider prompt).
  --model-plan MODEL        Model for the planning stage.
  --model-narrate MODEL     Model for the narration stage.
  --api-key KEY             API key for the provider (hidden input when prompting).
  --base-url URL            Base URL for openai_compatible / custom endpoints.
  --force                   Overwrite an existing user-level config.yaml.
```

Config locations (per `platformdirs`):

| OS      | Path                                                   |
|---------|--------------------------------------------------------|
| Linux   | `$XDG_CONFIG_HOME/codeguide/config.yaml` (≈ `~/.config/codeguide/config.yaml`) |
| macOS   | `~/Library/Application Support/codeguide/config.yaml`  |
| Windows | `%APPDATA%\codeguide\config.yaml`                      |

Permissions are set to `0o600` on POSIX so the API key is not world-readable.
Passing every flag (`--provider`, `--model-plan`, `--model-narrate`, `--api-key`)
produces a zero-prompt run (US-003).

## CLI Reference

`codeguide` is now a click group with two subcommands:

```
$ codeguide --help
Usage: codeguide [OPTIONS] COMMAND [ARGS]...

  CodeGuide — generate interactive HTML tutorials from local Git repositories.

Commands:
  generate  Generate an interactive HTML tutorial from a local Git repository.
  init      Interactive wizard — write a user-level config.yaml (US-002).
```

### `codeguide generate`

```
$ codeguide generate --help
Usage: codeguide generate [OPTIONS] REPO_PATH

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
  --no-cost-prompt             Skip the interactive cost-gate prompt (Sprint 8 / v0.2.0).
  --dry-run                    Run Stages 0..4 and emit a preview HTML without paying for narration (US-015).
  --review-plan                Pause after Stage 4 and open the lesson manifest in $EDITOR (US-016).
  --log-format [text|json]     Structured log output on stderr (US-022). Default: text.
  -V, --version                Show the version and exit.
  -h, --help                   Show this message and exit.
```

**Backward compatibility**: `codeguide <repo>` (without an explicit `generate`) still works — a custom
click group class rewrites an unknown first positional to `generate <positional>`.

### What you'll see (Sprint 8 / v0.2.0)

Running `codeguide ./my-repo` in a TTY produces:

```
CodeGuide v0.2.0
offline-friendly tutorial generator from local Git repos

[1/7] Ingestion
     ✓ done · 47 python files discovered
[2/7] Analysis
     parsing AST + resolving call graph for 47 files
     ✓ done · 412 symbols · 352 call edges
[3/7] Graph
     ✓ done · 412 symbols ranked · 0 cycle groups
[4/7] RAG
     ✓ done · BM25 index built · doc coverage 87%
[5/7] Planning
     generating lesson manifest…
     ✓ done · manifest ready (12 lessons)

┏━ ESTIMATED COST ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Model    Stage                            Est. tokens     Cost            ┃
┃ haiku    stages 1-4 (analyse/cluster)        ~410 000    $0.41            ┃
┃ opus     stages 5-6 (narrate/ground)         ~280 000    $1.87            ┃
┃ TOTAL                                        ~690 000    $2.28            ┃
┃ Runtime est. 18-26 min · 12 lessons across 1 clusters                     ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

Proceed? [y/N]: y

[6/7] Generation
     [1/12] narrating 'Session basics: initialization and context'
     [2/12] narrating 'Sessions: threading safety and scoping'
     …
     ✓ done · 12 lessons narrated
[7/7] Build
     ✓ done · tutorial.html written · 2387 KB

┏━ ✓ success ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃  lessons    12 of 12 narrated                                              ┃
┃  retries    0 grounding retries                                            ┃
┃  elapsed    18:43                                                          ┃
┃  output     ./tutorial.html                                                ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
open  tutorial.html
```

The cost-gate prompt **defaults to ON** for interactive terminals. Three bypass
options are available:

- `--yes` — auto-confirm both the consent banner and the cost prompt (existing
  v0.1.0 behaviour).
- `--no-cost-prompt` — skip only the cost prompt, keep the consent flow
  interactive.
- Non-TTY / piped / redirected stdin — the prompt is automatically bypassed
  so CI pipelines and `codeguide … > out.txt` keep working unchanged.

In `--log-format=json` mode the banner and animated progress are suppressed so
the stdout transcript stays parseable; structured stage events are still
emitted to stderr.

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
until you accept the consent banner on the first run for that provider on this machine.**

### Consent banner (Sprint 6 / v0.0.6)

The first time you run `codeguide generate` against Anthropic or OpenAI (hosted), the CLI
blocks and prints:

> Your source code will be sent to `<provider>`. Continue? [y/N]

Accepting writes `{granted: true, granted_at: <ISO>}` under that provider's key into
`<user_config_dir>/codeguide/consent.yaml` (file permissions `0o600` on POSIX).  **Subsequent
runs skip the banner** for any repo on the same machine.  Switching providers (e.g.
`--provider=openai`) triggers the banner again.  To revoke consent: delete `consent.yaml` (or
the relevant provider key).

- `--no-consent-prompt` — suppress the banner on CI / scripts (documented, visible in `--help`).
- `--yes` — auto-accept everything (stronger variant of `--no-consent-prompt`).
- `--base-url` with `--provider=openai_compatible` / `custom` skips the banner entirely
  — local inference means no code leaves the machine.

### Hard-refuse secret list

Files matching `.env`, `.env.*`, `*.pem`, `*_rsa`, `*_rsa.pub`, `*_ed25519`, `credentials.*`,
`id_rsa`, `id_ed25519` are **silently excluded from ingestion before `.gitignore` and before
`--include`/`--exclude` patterns**.  The only escape hatch is a project-level whitelist in
`tutorial.config.yaml` — commit to repo + review on PR:

```yaml
security:
  allow_secret_files:
    - ".env.example"
```

### Log redaction (SecretFilter)

API-key-shaped substrings (Anthropic `sk-ant-...`, OpenAI `sk-...` / `sk-proj-...`,
HuggingFace `hf_...`, generic `Bearer ...`, `Authorization: ...` headers, 40+ char hex blobs)
are replaced with `[REDACTED]` before structured logs reach stderr — on every log level, in
both `--log-format=text` and `--log-format=json`.  A hidden `--no-log-redaction` flag disables
redaction for local debugging only (not documented in `--help`).

### Zero telemetry

There is **zero telemetry** and **zero usage analytics** — the only outbound traffic is the
LLM API call.  An integration test (`tests/integration/test_zero_telemetry.py`) asserts this
on every CI run: `pytest-socket` disables outbound sockets during the CLI invocation
(cross-platform), and on Linux a `@pytest.mark.netns` test runs the full pipeline inside an
`unshare --user --net` namespace.

For sensitive codebases use the **local-inference path** shipped in Sprint 4 / v0.0.4:
`--provider custom --base-url http://localhost:11434/v1` (Ollama) or any OpenAI-compatible
endpoint (LM Studio, vLLM).  See the *BYOK* section above for ready-to-paste examples.

ADR-0010 captures the full secret-redaction + zero-telemetry contract
(`docs/adr/0010-secret-redaction-zero-telemetry.md`).

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

## Configuration precedence

CodeGuide resolves every configurable value through a strict chain:

| Priority | Source                                                                                                              | Override mechanism                          |
|---------:|---------------------------------------------------------------------------------------------------------------------|---------------------------------------------|
| 1 (top)  | CLI flags                                                                                                           | `--provider=openai`                         |
| 2        | Environment variables (`CODEGUIDE_*`, `*_API_KEY`)                                                                  | `ANTHROPIC_API_KEY=...`                     |
| 3        | `--config <path>` YAML                                                                                              | `--config ./custom.yaml`                    |
| 4        | Project config `./tutorial.config.yaml`                                                                             | commit to repo                              |
| 5        | User-level config (`~/.config/codeguide/config.yaml` on Linux/macOS, `%APPDATA%\codeguide\config.yaml` on Windows) | run `codeguide init`                        |
| 6 (bottom)| Built-in defaults                                                                                                  | code constant                               |

Run with `--log-format=json` and `DEBUG` level to see which source supplied each value:

```
ts=... level=debug msg="config resolved: llm_provider=openai from cli"
ts=... level=debug msg="config resolved: llm_model_plan=claude-sonnet-4-6 from default"
```

Full precedence specification: [docs/config-precedence.md](docs/config-precedence.md).

## Known limitations

The following limitations are acknowledged in v0.1.0 and prioritized for v0.2.0+:

- **Language support**: Python only. TypeScript, JavaScript, Go, and other languages are planned for v0.2.0+.
- **Narration language**: English only. Non-English language support and i18n infrastructure are deferred to v0.2.0+.
- **Dynamic constructs**: Dynamic imports, runtime polymorphism, reflection, and metaclass-based dispatch are detected and flagged as `uncertain` in the output HTML. Symbol resolution does not attempt to trace these patterns — see the code directly for runtime behavior.
- **Lesson capacity**: Hard cap at 30 regular lessons per tutorial (configurable via `tutorial.max_lessons`). Very large repositories are aggressively pruned to maintain narrative coherence. A synthetic "Where to go next" lesson is always appended as lesson 31.
- **Installation channel**: v0.1.0 ships as a Git-installable package only. PyPI release is explicitly deferred to v0.2.0+ per FR-03.

## License

Apache 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).

## Roadmap

Implementation plan (Sprint 0-7): [`.ai/implementation-plan.md`](.ai/implementation-plan.md)
