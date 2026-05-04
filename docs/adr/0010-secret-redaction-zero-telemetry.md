# ADR-0010 — Secret redaction policy + zero-telemetry contract

- **Status**: Accepted
- **Date**: 2026-04-22 (amended 2026-05-04)
- **Sprint**: 6 (Privacy + Config + Hardening)
- **Related US**: US-005, US-006, US-007, US-008, US-011, US-068, US-069
- **Supersedes**: —

## Context

WiedunFlow transmits source-code excerpts to third-party LLM APIs (Anthropic
by default, OpenAI / OpenAI-compatible endpoints by configuration). Before
v0.1.0 we need audytowalne guarantees:

1. A first-time cloud-provider user cannot accidentally ship their code to
   a remote LLM — we must block the pipeline on a consent banner.
2. Files that obviously hold secrets (`.env`, `*.pem`, `id_rsa`) must not
   reach ingestion, regardless of `.gitignore` or `--include` / `--exclude`.
3. API keys and bearer tokens that leak into log messages (for example,
   from an `httpx.HTTPStatusError` repr) must never be rendered at any log
   level.
4. The generated HTML tutorial must not trigger any outgoing network
   request when opened offline. The pipeline itself must not emit
   telemetry.

This ADR captures the seven binary decisions that Sprint 6 relies on.

## Decisions

### D1 — Secret redaction: pattern-only regex

Decision: redaction is implemented as a hardcoded list of regular
expressions in `wiedunflow.cli.secret_filter._PATTERNS`. No entropy-based
heuristic, no learned classifier.

Pattern list (authoritative — update requires amending this ADR):

| # | Pattern (verbatim) | Matches |
|--:|--------------------|---------|
| 1 | `sk-ant-[A-Za-z0-9_\-]{20,}` | Anthropic session / admin keys |
| 2 | `sk-proj-[A-Za-z0-9_\-]{20,}` | OpenAI project-scoped keys |
| 3 | `sk-[A-Za-z0-9]{20,}` | OpenAI classic keys & compatible deployments |
| 4 | `hf_[A-Za-z0-9]{20,}` | HuggingFace tokens |
| 5 | `(?i)bearer\s+[A-Za-z0-9._\-]{16,}` | Bearer tokens (OAuth, proxy) |
| 6 | `(?i)authorization:\s*\S+(?:\s+\S+)*` | Authorization HTTP headers |
| 7 | `\b[A-Fa-f0-9]{40,}\b` | Generic long hex (SHA/HMAC/session tokens) |

Replacement literal: `[REDACTED]`. Applied **before** the structlog
rendering processor (JSON or console).

**Rationale**: predictability over recall. Entropy heuristics surface
false positives on commit SHAs, Pygments spans and base64 test fixtures;
pattern-only matching is trivially verifiable via parametrized tests.

**Known gaps** (accepted): novel provider key shapes introduced after
2026-04-22 are **not** redacted until a new pattern is added.

### D2 — Redaction scope: structlog processor on both sinks

Decision: the redaction processor is installed on every structlog chain
(`cli/logging.py::configure`) and runs before both the `JSONRenderer` and
the `ConsoleRenderer`. It is enabled by default; `--no-log-redaction`
disables it but is **hidden from `--help`** (dev-only escape hatch, per
US-069 AC5).

`redact_path()` and `truncate_source()` are complementary helpers; they
are NOT invoked automatically by `redact()` — callers with repo context
opt in explicitly.

### D3 — Consent storage: separate `consent.yaml`

Decision: per-provider consent state lives in
`<platformdirs.user_config_dir("wiedunflow")>/consent.yaml` — a file
distinct from the user-level `config.yaml`.

```yaml
anthropic:
  granted: true
  granted_at: "2026-04-22T14:37:00+00:00"
openai: null
```

File permissions are set to `0o600` on POSIX after every write. Windows
relies on the default ACL of `%APPDATA%\wiedunflow\`.

**Rationale**: state and preferences have different lifecycles. A user
can `rm consent.yaml` to retract all zgods without touching their model
and API-key settings. Tests mock the store path trivially.

### D4 — Consent granularity: per-provider, persistent across repos

Decision: granting consent for `anthropic` once on a given machine
suppresses the banner for **every** subsequent WiedunFlow run that uses
that same provider (regardless of the repo). Switching to `openai`
re-triggers the banner.

**Rationale**: users accept the data-sharing relationship at the
provider level, not the repo level. Repo-level granularity would force a
banner on every new project — friction without a privacy benefit.

### D5 — Hard-refuse list: hardcoded 8 patterns + whitelist in config

Decision: the ingestion stage refuses to read files whose `path.name`
matches any of:

```
.env          .env.*         *.pem
*_rsa         *_rsa.pub      *_ed25519
credentials.* id_rsa         id_ed25519
```

(9 patterns — `.env` and `.env.*` together cover every dotenv variant.)

The refusal happens **before** `.gitignore` parsing, before `--include`
and before `--exclude`. The only escape hatch is a commit-level
whitelist in `tutorial.config.yaml`:

```yaml
security:
  allow_secret_files:
    - ".env.example"
```

**Rationale**: CLI flags would be ergonomically equivalent to
`--include`, which PRD AC3 forbids. Whitelisting in project config
leaves a `git log` audit trail and requires a PR reviewer's explicit
approval. Legitimate `.env.example` docs remain accessible with one
config line.

### D6 — Zero-telemetry test: dual-layer (netns + socket monkeypatch)

Decision:

- Linux CI runs `tests/integration/test_zero_telemetry.py` **including**
  the `@pytest.mark.netns` test, which invokes the CLI under
  `unshare --user --net --map-root-user` and asserts exit code 0 / 2
  (never a connection-related crash).
- macOS and Windows skip the netns test (`@pytest.mark.skipif`) but run
  the `pytest-socket` based test, which disables `socket.connect` for the
  duration of the CLI invocation.

**Rationale**: PRD AC1 specifies a network namespace; namespaces are
Linux-only. Socket monkeypatching provides equivalent protection at the
Python level on platforms without kernel namespaces. Running both on
Linux costs <2 s and catches issues that either layer alone would miss.

### D7 — Editor resolver: shlex.split + shutil.which + metacharacter deny-list

Decision: `cli/editor_resolver.py::_validate_editor_cmd` applies three
independent guards to every `$EDITOR` / `$VISUAL` value:

1. Reject strings containing any of `;  |  &&  ||  \`  $(  >&`.
2. Parse with `shlex.split` (raise `ValueError` → reject).
3. Require `shutil.which(parts[0])` to return non-`None`.

`subprocess.run` is invoked with `shell=False` unconditionally. The
`code` / `notepad.exe` / `/usr/bin/vi` absolute-path fallbacks are
guarded by the same PATH check where available and by `Path.exists`
otherwise.

**Rationale**: the `--review-plan` workflow launches an external editor
with user-supplied env vars. Malicious payloads in a CI runner's
environment must not translate into shell execution. All three guards
are cheap and independently auditable.

### D11 — Log redaction pattern catalog (amended 2026-05-04, v0.9.6)

**Decision**: Redaction patterns applied by `redact()` in `cli/secret_filter.py` are
versioned in this ADR. Adding a pattern requires an amendment commit;
removing a pattern requires a new ADR.

**Catalog** (12 patterns — 7 original + 5 added 2026-05-04 in v0.9.6):

| # | Pattern | Provider/use | Example | Source |
|---|---------|--------------|---------|--------|
| 1 | `sk-ant-[A-Za-z0-9_\-]{20,}` | Anthropic (covers v1, v2, v3 `sk-ant-api03-*`) | `sk-ant-api03-AbCd...` | Anthropic API docs |
| 2 | `sk-proj-[A-Za-z0-9_\-]{20,}` | OpenAI project keys | `sk-proj-...` | OpenAI API docs |
| 3 | `sk-[A-Za-z0-9]{20,}` | OpenAI classic + compatible | `sk-AbC...` | OpenAI API docs |
| 4 | `hf_[A-Za-z0-9]{20,}` | HuggingFace | `hf_AbC...` | HF docs |
| 5 | `(?i)bearer\s+[A-Za-z0-9._\-]{16,}` | Generic Bearer | `Bearer eyJhbGc...` | OAuth |
| 6 | `(?i)authorization:\s*\S+(?:\s+\S+)*` | Auth header | `authorization: Bearer ...` | RFC 7235 |
| 7 | `\b[A-Fa-f0-9]{40,}\b` | Generic 40+ hex (SHA-1+) | `a1b2c3...` (40 chars) | Heuristic |
| **8** | **`AKIA[A-Z0-9]{16}`** | **AWS Access Key ID** | `AKIAIOSFODNN7EXAMPLE` | AWS docs |
| **9** | **`(?i)aws.{0,20}[0-9a-zA-Z/+]{40}\b`** | **AWS Secret heuristic** | `aws_secret_access_key=wJal...` | AWS docs |
| **10** | **`gh[pousr]_[A-Za-z0-9]{36,255}`** | **GitHub classic PAT (ghp/ghu/gho/ghs/ghr)** | `ghp_AbC...` | GitHub docs |
| **11** | **`github_pat_[A-Za-z0-9_]{82}`** | **GitHub fine-grained PAT** | `github_pat_11AAA...` | GitHub docs |
| **12** | **`-----BEGIN (?:RSA \|OPENSSH \|DSA \|EC )?PRIVATE KEY-----`** | **PEM private key (any flavor)** | `-----BEGIN RSA PRIVATE KEY-----` | RFC 7468 |

Bold rows added 2026-05-04 (v0.9.6 redaction extension).

**Note on D5 vs D11**: D5 ("hard-refuse list") governs which *files* the ingestion
stage refuses to read (e.g. `.env`, `*.pem`, `id_rsa`). D11 governs which
*substrings* the structlog processor redacts from log messages at runtime.
Both layers are necessary; neither is sufficient alone — a `.pem` file that
slips past D5 via `allow_secret_files` will still have its key header
redacted by D11's PEM pattern.

## Consequences

**Positive**

- Every secret leak vector (logs, editor env, ingestion) has a single
  dedicated gate that can be unit-tested in isolation.
- `consent.yaml` is a user-visible, user-editable artifact — trust
  boundary is explicit.
- The zero-telemetry test suite runs on every CI job (socket MP) with the
  stronger netns layer as a Linux-only "belt-and-suspenders" check.

**Negative**

- Pattern-only redaction misses novel API-key shapes until the list is
  updated. Mitigation: quarterly review of Anthropic / OpenAI / HF key
  format announcements.
- The hard-refuse list is opinionated; project-specific secret file names
  (e.g. `deploy.key`) require an explicit whitelist entry.
- The netns test requires user-namespace support in the kernel;
  restricted CI environments that disable `user_namespaces` cannot run
  it (logged as skip, not fail).

**Escape hatches**

- `--no-log-redaction` — hidden CLI flag for developers reproducing an
  incident on a trusted machine. Not documented in `--help`.
- `security.allow_secret_files` — project config array.
- Consent revocation: `rm ~/.config/wiedunflow/consent.yaml`.

## Implementation references

- `src/wiedunflow/cli/secret_filter.py` — D1, D2
- `src/wiedunflow/cli/logging.py::_redact_secrets_processor` — D2
- `src/wiedunflow/adapters/yaml_consent_store.py` — D3
- `src/wiedunflow/cli/consent.py::ensure_consent_granted` — D4
- `src/wiedunflow/ingestion/secret_blocklist.py` — D5
- `tests/integration/test_zero_telemetry.py` — D6
- `src/wiedunflow/cli/editor_resolver.py::_validate_editor_cmd` — D7

## Links

- ADR-0005 — Frozen vanilla JS output (supporting file:// offline
  guarantee referenced in US-011 AC2)
- ADR-0011 — UX design system (consent banner exact copy lives in
  `.ai/ux-spec.md` §CLI)
- CLAUDE.md §PRIVACY_AND_SECURITY
