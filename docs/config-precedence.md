# Configuration precedence chain (US-004)

WiedunFlow merges configuration from up to six sources before passing a
validated `WiedunflowConfig` to the pipeline.  Sources are consulted in a
strict order; the first source that supplies a value wins and no lower-priority
source can override it.

## Priority table

| Priority | Source                                              | Override mechanism                           |
|---------:|-----------------------------------------------------|----------------------------------------------|
| 1 (top)  | CLI flags                                           | `--provider=openai`                          |
| 2        | Environment variables (`WIEDUNFLOW_*`, `*_API_KEY`)  | `ANTHROPIC_API_KEY=...`                      |
| 3        | `--config <path>` YAML                              | `--config ./custom.yaml`                     |
| 4        | Project config `./tutorial.config.yaml`             | commit to repo                               |
| 5        | User-level config (see path table below)            | run `wiedun-flow init`                         |
| 6 (bottom)| Built-in defaults                                  | code constant in `config.py`                 |

### User-level config path by OS

| OS           | Default path                                                    |
|--------------|-----------------------------------------------------------------|
| Linux / macOS| `~/.config/wiedunflow/config.yaml`                               |
| Windows      | `%APPDATA%\wiedunflow\config.yaml`                               |

Path is resolved via `platformdirs.user_config_dir("wiedunflow")`.

## Decision flow

```
┌─────────────────────────┐
│  1. CLI flags            │  --provider=openai?
└─────────────────────────┘
           │ not supplied
           ▼
┌─────────────────────────┐
│  2. Env variables        │  WIEDUNFLOW_LLM_PROVIDER set?
└─────────────────────────┘
           │ not set
           ▼
┌─────────────────────────┐
│  3. --config <path> YAML │  --config ./custom.yaml provided?
└─────────────────────────┘
           │ not provided / file absent
           ▼
┌─────────────────────────┐
│  4. ./tutorial.config.  │  file exists in cwd?
│     yaml (cwd)          │
└─────────────────────────┘
           │ absent
           ▼
┌─────────────────────────┐
│  5. User-level config    │  ~/.config/wiedunflow/config.yaml?
└─────────────────────────┘
           │ absent
           ▼
┌─────────────────────────┐
│  6. Built-in defaults    │  always applied as fallback
└─────────────────────────┘
```

Resolution happens **per field**, not per file.  A `./tutorial.config.yaml`
that sets only `max_lessons` will still pick up `llm_provider` from the
user-level config if no higher-priority source supplies it.

## YAML structure and field flattening

YAML configs use a nested `llm:` block.  `_load_yaml_flat` (internal helper)
flattens it before merging:

```yaml
# tutorial.config.yaml
llm:
  provider: openai          # → llm_provider
  model_plan: gpt-4o        # → llm_model_plan
  model_narrate: gpt-4o     # → llm_model_narrate
  concurrency: 5            # → llm_concurrency
  max_retries: 3            # → llm_max_retries
  max_wait_s: 30            # → llm_max_wait_s
  base_url: http://...      # → llm_base_url      (custom / Ollama)
  api_key_env: MY_KEY_VAR   # → llm_api_key_env   (custom / Ollama)

exclude_patterns:
  - "**/tests/**"
include_patterns: []

max_lessons: 20
target_audience: "senior Python developer"

security:
  allow_secret_files:
    - ".env.example"        # → security_allow_secret_files (frozenset)
```

## Environment variable reference

Pydantic BaseSettings reads `WIEDUNFLOW_*` env vars automatically
(`env_prefix = "WIEDUNFLOW_"`).  Most fields map 1-to-1:

| Env var                      | Config field          |
|------------------------------|-----------------------|
| `WIEDUNFLOW_LLM_PROVIDER`     | `llm_provider`        |
| `WIEDUNFLOW_LLM_MODEL_PLAN`   | `llm_model_plan`      |
| `WIEDUNFLOW_LLM_MODEL_NARRATE`| `llm_model_narrate`   |
| `WIEDUNFLOW_LLM_CONCURRENCY`  | `llm_concurrency`     |
| `WIEDUNFLOW_LLM_MAX_RETRIES`  | `llm_max_retries`     |
| `WIEDUNFLOW_LLM_MAX_WAIT_S`   | `llm_max_wait_s`      |
| `WIEDUNFLOW_LLM_API_KEY`      | `llm_api_key`         |
| `WIEDUNFLOW_LLM_BASE_URL`     | `llm_base_url`        |
| `ANTHROPIC_API_KEY`          | resolved by `resolve_api_key()` |
| `OPENAI_API_KEY`             | resolved by `resolve_api_key()` |

**Important**: env vars that conflict with a YAML value are stripped from the
merged YAML dict before `WiedunflowConfig` is constructed, ensuring env always
beats YAML without relying solely on Pydantic's init-kwarg precedence.

## Observability — DEBUG log lines

Run with `--log-format=json` and `DEBUG` level to see which source supplied
each key config field:

```
ts=... level=debug logger=wiedunflow.cli.config msg="config resolved: llm_provider=openai from cli"
ts=... level=debug logger=wiedunflow.cli.config msg="config resolved: llm_model_plan=gpt-4o from yaml"
ts=... level=debug logger=wiedunflow.cli.config msg="config resolved: llm_model_narrate=claude-opus-4-7 from default"
```

Source labels: `cli` | `env` | `yaml` | `default`.

## Implementation reference

Source: `src/wiedunflow/cli/config.py::load_config`

Key invariants:

- YAML keys are *flattened* by `_load_yaml_flat` (nested `llm:` block becomes
  `llm_provider`, `llm_model_plan`, …).
- Env vars are stripped from the merged YAML when the CLI does not also override
  the same field — this prevents YAML from shadowing env vars.
- `SecretStr` wraps `llm_api_key` so the key never appears in repr output
  (defensive privacy, ADR-0010 aligned).

Integration tests verifying every boundary: `tests/integration/test_config_precedence.py`
