# ADR-0003: Clean architecture layering — ports and adapters

- Status: Accepted
- Date: 2026-04-20
- Deciders: Michał Kamiński
- Related PRD: v0.1.2-draft
- Supersedes: none

## Context

CodeGuide's 7-stage pipeline integrates with external dependencies across the full stack: LLM providers (Anthropic, OpenAI, OSS), source code parsers (tree-sitter for Python; TypeScript/JavaScript planned for v2), cache storage (SQLite), and render engine (Jinja2).

Without architectural discipline on dependency flow, the codebase will gradually couple entities and use-cases to concrete implementations:
- `entities.LessonPlan` imports `anthropic.Client` (blocks BYOK).
- `use_cases.RankGraph` imports `sqlite3` pragmas (blocks cache swaps).
- `generate_tutorial.py` instantiates `TreeSitterParser` directly (blocks parser upgrades to LSP or Pyright).

This coupling violates the project's core commitment: **BYOK (Bring Your Own Key)** — users supply their own LLM API keys and choose their provider. Similarly, users should be able to upgrade their Python toolchain or swap storage without forking CodeGuide's core logic.

The intended scope of v2 includes adding a TypeScript/JavaScript parser as an alternative to tree-sitter — and this upgrade should be a single adapter change, not a cascading refactor through use-cases and entities.

## Decision

Adopt Robert C. Martin's **Clean Architecture** with five strict layers in `src/codeguide/`:

### Layer 1: Entities (`src/codeguide/entities/`)

Domain-level invariants, decoupled from frameworks and SDKs:
- `LessonPlan`, `LessonManifest` (Pydantic v2 models defining lesson structure)
- `CodeSymbol` (represents a function, class, module with AST metadata)
- `CallGraph` (domain aggregate of CodeSymbol relationships)
- `ConceptSet` (what topics have been taught to avoid re-teaching)

**Rule**: Entities can only import from `entities/` and the standard library. Zero imports from `use_cases`, `adapters`, `interfaces`, `anthropic`, `openai`, `sqlite3`, or `jinja2`.

### Layer 2: Use Cases (`src/codeguide/use_cases/`)

Orchestrators for the 7-stage pipeline:
- `GenerateTutorial` — top-level coordinator
- `IngestionUseCase` — file discovery, cache lookup
- `AnalysisUseCase` — AST parsing, Jedi call-graph resolution
- `GraphUseCase` — PageRank ranking, community detection
- `PlanningUseCase` — call LLM to produce lesson manifest
- `GenerationUseCase` — parallel/sequential LLM calls for descriptions and narration

**Rule**: Use-cases import from `entities` and `interfaces` (ports) **only**. No imports from `adapters`, SDK libraries, or frameworks. Use-cases define *what* should happen; they do not know *how* it is implemented (that is the adapter's job).

### Layer 3: Interfaces (`src/codeguide/interfaces/`)

Ports (Protocol, ABC) defining contracts without implementations:

```python
# src/codeguide/interfaces/__init__.py
from typing import Protocol

class LLMProvider(Protocol):
    def complete(self, messages: list, model: str, max_tokens: int) -> str: ...
    def count_tokens(self, text: str) -> int: ...

class Parser(Protocol):
    def parse(self, path: Path) -> CodeSymbol: ...

class VectorStore(Protocol):
    def index(self, documents: list[str]) -> None: ...
    def query(self, text: str, k: int) -> list[str]: ...

class Cache(Protocol):
    def get(self, key: str) -> Any: ...
    def set(self, key: str, value: Any) -> None: ...

class Editor(Protocol):
    def write_html(self, path: Path, html: str) -> None: ...
```

**Rule**: Interfaces declare contracts, never implementations. Ports are agnostic about provider, SDK, or storage backend.

### Layer 4: Adapters (`src/codeguide/adapters/`)

Concrete implementations of ports. Each port has ≥1 adapter:

```
src/codeguide/adapters/
  ├── llm/
  │   ├── __init__.py
  │   ├── anthropic_provider.py      # AnthropicProvider(LLMProvider)
  │   ├── openai_provider.py         # OpenAIProvider(LLMProvider)
  │   └── openai_compatible.py       # OpenAICompatibleProvider(...Ollama, vLLM)
  ├── parser/
  │   ├── __init__.py
  │   └── tree_sitter_parser.py      # TreeSitterParser(Parser)
  ├── vector_store/
  │   ├── __init__.py
  │   └── bm25_vector_store.py       # Bm25VectorStore(VectorStore)
  ├── cache/
  │   ├── __init__.py
  │   └── sqlite_cache.py            # SqliteCache(Cache)
  └── editor/
      ├── __init__.py
      └── html_editor.py             # HtmlEditor(Editor)
```

**Rule**: Adapters are the **only** layer that imports SDKs (`anthropic`, `openai`, `sqlite3`, `jinja2`, `tree_sitter`). They translate between the port contract and the external library API.

Example adapter:

```python
# src/codeguide/adapters/llm/anthropic_provider.py
from codeguide.interfaces import LLMProvider
import anthropic

class AnthropicProvider(LLMProvider):
    def __init__(self, api_key: str):
        self.client = anthropic.Anthropic(api_key=api_key)
    
    def complete(self, messages: list, model: str, max_tokens: int) -> str:
        response = self.client.messages.create(
            messages=messages, model=model, max_tokens=max_tokens
        )
        return response.content[0].text
```

### Layer 5: Delivery (`src/codeguide/cli/`, `src/codeguide/renderer/`)

Frameworks and I/O adapters that assemble the stack:

```python
# src/codeguide/cli/__init__.py — click entrypoint
from codeguide.adapters.llm import AnthropicProvider
from codeguide.adapters.parser import TreeSitterParser
from codeguide.adapters.vector_store import Bm25VectorStore
from codeguide.adapters.cache import SqliteCache
from codeguide.use_cases import GenerateTutorial

@click.command()
def main(repo_path: Path, api_key: str):
    llm = AnthropicProvider(api_key)
    parser = TreeSitterParser()
    vector_store = Bm25VectorStore()
    cache = SqliteCache()
    
    use_case = GenerateTutorial(llm, parser, vector_store, cache)
    use_case.execute(repo_path)
```

## Consequences

### Positive

- **BYOK Guarantee** — to swap providers (Anthropic → OpenAI, sqlite-vec → local Ollama embeddings), change the adapter factory in `cli/__init__.py`. Zero changes to entities, use-cases, or business logic.
- **Testability** — a single `FakeLLMProvider` implementing the `LLMProvider` protocol replaces mocking across the Anthropic SDK. Write one e2e test with real code, real AST, fake LLM; it is legible and maintainable.
- **Parser upgrade path** — in v2, when we add TypeScript/JavaScript, we create a new `LspParser(Parser)` adapter that calls the TypeScript LSP. The orchestrator (`GenerateTutorial`) is unchanged.
- **Dependency injection** — the delivery layer wires adapters to use-cases. Testing and production both use the same dependency-injection pattern: no test-specific branches in use-cases.
- **Type safety** — `mypy --strict` enforcement at the `entities` and `use_cases` layer ensures that we cannot accidentally leak SDK imports into core logic. CI will catch it.
- **Reasoning and documentation** — layers explicitly encode the architecture: entities encode domain rules, use-cases encode business processes, adapters encode vendor specifics.

### Negative

- **Scaffolding overhead** — five layers + protocols add ~50–100 lines of boilerplate per new external dependency (port + adapter). Simple scripts can be built faster without this abstraction.
- **Indirection** — code reviewers and new contributors must trace through layers to understand the full call stack. Mitigated by clear naming and documentation.

### Neutral

- **Existing monolith projects** — if a future v2 adds a monolithic feature (e.g., a plugin API), it would *not* go through the entities/use-cases/adapters model; plugins have their own enclosure. This is acceptable — the core CodeGuide pipeline stays clean.

## Alternatives Considered

1. **Hexagonal Architecture (Ports & Adapters only)** — rejected because the 7-stage pipeline deserves a dedicated `use_cases` layer for orchestration logic. Without it, all business logic leaks into the delivery layer.
2. **Three-layer (Domain/Application/Infrastructure)** — rejected because the term "Application" conflates both orchestration (our use-cases) and I/O adapters (our delivery layer), making it ambiguous which layer owns dependency injection.
3. **Monolith without abstraction** — rejected because we commit to BYOK and v2 parser upgrade. Those features require an inversion of control at the port level from day 1.
4. **Async throughout** — rejected. We use async only for concurrent LLM calls in `GenerationUseCase`. Everywhere else (file I/O, AST parsing, cache lookup) is synchronous by default. Complicates testing and adds overhead without benefit.

## Migration Criteria (reconsidering layer count in v2+)

Revisit this decision if **any** of the following becomes true:

- We add a plugin API (deserves its own enclosure, not the five-layer stack).
- The entity layer grows beyond 2000 LOC with frequent cross-cutting concerns (suggests a domain event bus is needed).
- We add conversational state or memory (use-cases would need a fourth layer for domain events).

Until then, five layers remain the standard.

## Implementation Notes

- Enforce at CI-time via `mypy --strict` on `src/codeguide/{entities,use_cases}/**` — any import from outside those layers will fail.
- Document each new port with a README: `src/codeguide/interfaces/README.md` listing all ports and their intended adapters.
- Golden rule for code review: "Which layer does this belong in?" — if unclear, the architecture is unclear.

## References

- ADR-0001 (direct SDK, not LangChain) — implies need for adapter layer to wire SDKs
- PRD v0.1.2-draft, §1 (BYOK, extensibility for v2)
- Robert C. Martin, *Clean Architecture* (2017), Ch. 1–4
- "Layered vs Hexagonal vs Onion Architecture", Sam Newman, monolith patterns
