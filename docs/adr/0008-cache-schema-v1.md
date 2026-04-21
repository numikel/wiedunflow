# ADR-0008 — Cache schema v1 (SQLite-backed durable cache)

Status: Accepted
Date: 2026-04-20
Sprint: 4
Deciders: Michał Kamiński

## Context

Sprint 4 requires a durable cache to support three product requirements:

1. **Incremental runs** (US-023): the second run on a repo with <20 % changed
   files must complete in <5 min.  Without persistence across runs, every
   lesson would be regenerated regardless of whether its source symbols changed.

2. **Resume** (US-017): if the pipeline is interrupted (crash, Ctrl+C, network
   error), the user should be able to re-enter at the first incomplete lesson
   rather than restarting from scratch.  Lesson generation is the most
   expensive stage ($0.10–$0.30 per lesson with Opus) so a full restart after a
   late-stage failure is a significant cost and UX regression.

3. **Plan invalidation** (US-018): when the user explicitly requests
   ``--regenerate-plan``, the cached manifest must be deleted together with all
   lesson checkpoints (because lesson IDs may differ after a re-plan).

The existing ``InMemoryCache`` (Sprint 1) has no persistence across process
exits and no typed structure.  It is retained for test injection but is not
sufficient for production use.

A cross-platform solution is required: the tool targets Linux, macOS, and
Windows (Python 3.11+ CI matrix).

## Decision

### Storage engine: SQLite with WAL mode

SQLite was chosen over alternatives (see §Alternatives) because:
- Zero daemon — the cache is a single file, ideal for a CLI tool.
- Bundled with every CPython build since 2.5.
- WAL journal mode enables concurrent readers while a write is in progress,
  which matters for the parallel leaf-description generation in Stage 6.
- The `threading.Lock` wrapper makes write serialisation explicit and safe for
  `ThreadPoolExecutor`-based parallel narration.

### Cache key design

Keys are SHA-256 hex digests of null-delimited fields:
- **Lesson checkpoint key**: ``sha256(repo_abs\x00commit\x00lesson_id)``
- **Plan key**: ``sha256(repo_abs\x00commit\x00__plan__)``
- **File key**: ``sha256(file_bytes)`` — content-addressed

**The model name is deliberately excluded from the key.**  A user who switches
from ``claude-opus-4-7`` to ``claude-sonnet-4-6`` must supply
``--regenerate-plan`` explicitly.  Silent reuse of Opus-generated lessons with
a Sonnet config would be confusing; explicit invalidation is safer and clearer.

### No JSON1 extension

SQLite's JSON1 extension is not reliably present on all Windows builds.
JSON fields are stored as ``TEXT`` and decoded in Python via ``json.loads``
inside the adapter.  The entities layer operates on decoded Python objects.

### Schema (DDL)

```sql
CREATE TABLE IF NOT EXISTS schema_version (
    version  INTEGER PRIMARY KEY
);
INSERT OR IGNORE INTO schema_version VALUES (1);

CREATE TABLE IF NOT EXISTS generic_kv (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS checkpoints (
    cache_key          TEXT PRIMARY KEY,
    repo_abs           TEXT NOT NULL,
    commit_hash        TEXT NOT NULL,
    lesson_id          TEXT NOT NULL,
    lesson_json        TEXT NOT NULL,
    concepts_snapshot  TEXT NOT NULL,
    model_used         TEXT NOT NULL,
    cost_cents         INTEGER NOT NULL,
    created_at         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_checkpoints_repo
    ON checkpoints(repo_abs, commit_hash);

CREATE TABLE IF NOT EXISTS plan_cache (
    cache_key               TEXT PRIMARY KEY,
    repo_abs                TEXT NOT NULL,
    commit_hash             TEXT NOT NULL,
    manifest_json           TEXT NOT NULL,
    pagerank_snapshot_json  TEXT NOT NULL,
    created_at              TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_plan_repo
    ON plan_cache(repo_abs, commit_hash);

CREATE TABLE IF NOT EXISTS file_cache (
    sha256          TEXT PRIMARY KEY,
    ast_json        TEXT,
    callgraph_json  TEXT,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pagerank_snapshots (
    repo_abs     TEXT NOT NULL,
    commit_hash  TEXT NOT NULL,
    ranks_json   TEXT NOT NULL,
    top_n        INTEGER NOT NULL DEFAULT 20,
    created_at   TEXT NOT NULL,
    PRIMARY KEY (repo_abs, commit_hash)
);
```

### Default cache location

Delegated to ``platformdirs.user_cache_path("codeguide", appauthor=False)``:
- **Linux**: ``~/.cache/codeguide/cache.db``
- **Windows**: ``%LOCALAPPDATA%\codeguide\Cache\cache.db``
- **macOS**: ``~/Library/Caches/codeguide/cache.db``

The ``--cache-path`` flag (US-020) overrides the default.

### PageRank diff threshold

If the symmetric difference between the top-20 PageRank symbols of the
previous run and the current run is ≥ 20 % (ratio ≥ 0.20), the manifest is
regenerated.  Below the threshold the cached manifest is reused and only
lessons touching changed files are re-generated.

The 20 % threshold is the same value used by `is_structural_change` in the
`RankedGraph`-based diff (previously in `graph_diff.py`), creating a
consistent cross-layer policy.

### Migration from InMemoryCache

No data migration is needed.  ``InMemoryCache`` is retained for test injection.
On first run with SQLite the database is created fresh.  Upgrading the schema
in a future sprint requires a version bump in ``schema_version`` and a
forward-compatible migration statement added to ``_init_schema``.

## Consequences

### Positive

- Durable cross-run caching enables <5 min incremental runs (US-023 AC1).
- Resume (US-017) survives crashes at any lesson boundary.
- WAL mode allows parallel readers — no lock contention during Stage 6.
- Zero extra infrastructure: single file, cross-platform, always available.
- Content-addressed file cache (SHA-256) means the same file in different repos
  never duplicates analysis work.

### Negative / trade-offs

- SQLite is a single-file lock: under heavy parallel *writes* (not typical for
  CodeGuide's pipeline) contention may appear.  The `threading.Lock` mitigates
  this but does not eliminate it.
- The cache file is local to the machine — no cross-machine cache sharing in
  MVP.  Team scenarios where multiple developers run CodeGuide on the same repo
  gain no benefit from each other's caches.
- JSON stored as TEXT loses type information at the SQL layer; queries on JSON
  fields require loading into Python first.

## Alternatives considered

- **Redis / Memcached**: daemon dependency, rejected for a CLI tool.
- **shelve / pickle**: not human-inspectable, version-fragile, rejected.
- **DuckDB**: good analytical SQL but overkill for key-value + row-by-key
  access patterns; heavier installation footprint.
- **sqlite-vec + embeddings** (ADR-0002 v2 plan): deferred to v2 — the BM25
  RAG in MVP does not require vector storage in the cache layer.

## Related

- ADR-0002 (RAG stack — sqlite-vec deferred to v2)
- ADR-0006 (AST snapshot schema — grounding contract)
- US-017 (resume), US-018 (regenerate-plan), US-020 (cache-path),
  US-023 (incremental <5 min), US-024 (PageRank diff), US-025 (platformdirs),
  US-026 (SHA-256 file granularity)
- Code: `src/codeguide/adapters/sqlite_cache.py`,
  `src/codeguide/entities/cache_entry.py`,
  `src/codeguide/entities/cache_key.py`,
  `src/codeguide/use_cases/resume_run.py`,
  `src/codeguide/use_cases/graph_diff.py`
