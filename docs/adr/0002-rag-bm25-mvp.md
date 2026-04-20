# ADR-0002: RAG in MVP — BM25 over sqlite-vec + embeddings

- Status: Accepted
- Date: 2026-04-16
- Deciders: Michał Kamiński
- Related PRD: v0.1.1-draft
- Supersedes: none

## Context

PRD 0.1.0-draft specified `sqlite-vec` with provider embeddings (Anthropic Voyage or OpenAI `text-embedding-3-small`) for the RAG index over docstrings, README, docs/, CONTRIBUTING.md, commit messages, and inline comments.

Critical review surfaced four concerns:

1. **Cross-platform fragility** — `sqlite-vec` is a 0.x native SQLite extension. Loading it requires `enable_load_extension(True)` on the SQLite handle. On Windows, the default CPython SQLite build occasionally ships with extension loading disabled, and wheels for the extension itself are not always available for every CPython × OS combination in the CI matrix (FR-04: Python 3.11/3.12/3.13 × Ubuntu/Windows/macOS).
2. **Corpus size** — the text corpus per repository is small: one README, a handful of docs, docstrings (often sparse in the first place — see FR-46), a few thousand commit messages. BM25 handles this corpus size at least as well as vector similarity.
3. **Cost** — embeddings require either a network call to a paid API (Voyage / OpenAI) or a local model in Ollama. The first violates the "local-first MVP except for LLM narration" posture; the second adds a setup dependency for users who want to use the default Anthropic narration.
4. **Determinism** — BM25 is deterministic. Embedding models are stable but their updates (OpenAI routinely iterates `text-embedding-3-small`) silently shift retrieval rankings. Deterministic retrieval simplifies the eval corpus (FR-74, FR-75) and the grounding validator (FR-36).

## Decision

MVP RAG uses `rank_bm25.BM25Okapi` over a tokenized corpus:

- **Tokenizer**: custom — lowercase, snake/camelCase split, common English + code stopwords.
- **Storage**: in-memory index built per run; cached to SQLite as a serialized blob keyed by corpus hash.
- **Port**: `VectorStore` in `interfaces/ports.py` — `index(documents)`, `query(text, k) -> list[Document]`.
- **Adapter**: `Bm25VectorStore` in `adapters/`.

The port shape is designed so that swapping to `SqliteVecStore` in v2 is a single adapter change; use-cases and entities remain untouched.

## Consequences

**Positive**:

- Zero binary SQLite extension dependency — clean cross-platform story.
- Zero embeddings API cost; no setup burden for users on the default Anthropic + BM25 path.
- Deterministic retrieval — eval corpus (FR-74) produces reproducible results across runs.
- Faster first run — no embedding call latency.

**Negative**:

- No semantic similarity. BM25 matches tokens, not meaning. For repos with sparse docstrings and terse commit messages the retrieval will be weaker than a dense-embedding baseline would be.
- This weakness is correlated with FR-46 (low-documentation repos), which we already surface with a warning banner. Users with poorly documented repos were already getting a degraded experience — BM25 does not make that worse, but does not cure it either.

## Alternatives Considered

1. **`sqlite-vec` + OpenAI embeddings** (the original plan) — rejected on cross-platform fragility and cost, described in Context.
2. **`sqlite-vec` + local embeddings via `sentence-transformers`** — adds a heavyweight dependency (PyTorch) and a disk/RAM footprint that does not fit the "lightweight CLI" posture.
3. **Hybrid BM25 + embeddings (re-ranker)** — real win in theory, but doubles the complexity of the RAG stage and invalidates the "zero infra, deterministic" property. Deferred to v2+.
4. **Whoosh or Tantivy** — larger dependencies than `rank_bm25` for no meaningful retrieval-quality uplift at our corpus size.

## Migration Criteria (reconsidering sqlite-vec in v2+)

Revisit this decision when **any** of the following holds:

- The eval rubric (FR-76) averages below 3.0 on the `coverage` axis for 2 consecutive releases, with retrieval-quality identified (in post-mortems) as the root cause.
- We add semantic code search inside the output HTML (currently v2+ scope per §4.2 PRD).
- The upstream situation changes: `sqlite-vec` ships a stable 1.0, pre-built wheels for all MVP OS × Python combinations become routine, and CPython's SQLite build on Windows reliably supports `enable_load_extension`.

## References

- PRD v0.1.1-draft, §1 (Product Overview — Stage 4 Documentation indexing), FR-28, FR-46, FR-74, FR-76
- tech-stack.md §6 (RAG i embeddingi)
- CLAUDE.md sections STACK, PIPELINE Stage 4
