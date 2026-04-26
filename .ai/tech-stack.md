# Tech Stack - WiedunFlow

Wersja dokumentu: v0.2.0
Ostatnia aktualizacja: 2026-04-26
Właściciel: Michał Kamiński
Wydanie docelowe: WiedunFlow v0.6.0+ (post-MVP polish)

> **Tech-stack po post-MVP polish (v0.6.0)**: aktualne wybory zwalidowane w 4 sprintach (v0.2.0 animacje → v0.3.0 quality enforcement → v0.4.0 TUI menu → v0.5.0 dynamic pricing → v0.6.0 rebrand). sqlite-vec + multi-language parser deferred do roadmap (patrz `.ai/implementation-plan.md`).

Dokument opisuje proponowany stos technologiczny dla WiedunFlow v0.1.0 zgodnie z wymaganiami `.ai/prd.md`. Każdy wybór jest zakotwiczony w konkretnym wymaganiu funkcjonalnym (FR-XX) lub ograniczeniu produktu.

## 1. Podsumowanie

WiedunFlow to jednoprocesowe CLI w Pythonie 3.11+, którego jedynym zewnętrznym zależnym ruchem sieciowym jest wywołanie LLM skonfigurowanego przez użytkownika (BYOK). Cały pipeline (7 etapów) działa lokalnie, artefakt wyjściowy to pojedynczy samodzielny plik HTML działający przez `file://` bez runtime'owych zależności po stronie odbiorcy (FR-14, FR-51).

Kluczowe decyzje:

- **UV‑exclusive toolchain** — jedyny wspierany menedżer środowisk i dystrybucji (FR-02). `pip`, `pipx`, `poetry`, `hatch` są wykluczone w całym projekcie.
- **Brak PyPI w MVP** — dystrybucja wyłącznie przez `uvx --from git+https://...` (FR-01, FR-03).
- **Brak telemetrii** — żadnych wywołań sieciowych poza skonfigurowanym dostawcą LLM; weryfikowane testem integracyjnym i linterem szablonu (FR-13, FR-14).
- **Apache 2.0 + DCO** — brak CLA; sign‑off wymuszany GitHub Action, nie pre‑commitem (FR-70, FR-72).
- **Cross‑platform first** — Linux, Windows, macOS × Python 3.11/3.12/3.13 (FR-04).
- **Budżet <$8/tutorial** — bump z <$3 odzwierciedla wybór Opus 4.7 jako default narration (FR-64, §6.2 PRD).

## 2. Runtime i język

| Komponent | Wybór | Uzasadnienie |
|---|---|---|
| Język | Python 3.11+ | Pattern matching, `tomllib`, `ExceptionGroup`, ulepszony `TypedDict` — wszystko używane w pipeline. FR-04 wymaga macierzy 3.11/3.12/3.13. |
| Typowanie | `from __future__ import annotations` + `mypy --strict` | Obowiązkowe adnotacje na publicznych API warstw `entities`/`use cases`/`interfaces`. Pre-commit blokuje regresje (FR-69). |
| Styl kodu | `ruff check` + `ruff format` | Jedno źródło prawdy dla lint + format; w pre-commicie (FR-69). Eliminuje konflikty `black` vs `isort` vs `flake8`. |
| Struktura pakietu | Layout `src/wiedunflow/` | Zapobiega importom z CWD w testach, standardowy dla UV. |

## 3. Packaging, dystrybucja i toolchain

| Komponent | Wybór | Uzasadnienie |
|---|---|---|
| Manager zależności i środowisk | **UV** (Astral) | FR-02: UV‑exclusive. `pyproject.toml` zawiera `[tool.uv]`; `uv sync` to jedyna udokumentowana ścieżka dev. |
| Dystrybucja MVP | Bare Git repo + `uvx --from git+https://github.com/<org>/wiedunflow wiedunflow` | FR-01, FR-03. Brak PyPI do v2. |
| Definicja projektu | `pyproject.toml` (PEP 621) + `[project.scripts]` | `wiedunflow = "wiedunflow.cli:main"`. |
| Nagłówki licencji | `insert-license` (pre-commit) | FR-69: wstrzykuje nagłówek Apache 2.0 do nowych plików `.py`. |
| Conventional commits | `commitlint` via `cz-cli` (pre-commit) | FR-69. Scope'y: `ingestion`, `analysis`, `graph`, `rag`, `planning`, `generation`, `build`, `cli`, `cache`, `config`. |
| Zasygnalizowanie DCO | GitHub Action, nie lokalny hook | FR-70. Weryfikacja `Signed-off-by:` przy każdym PR. |
| Agregacja NOTICE | Skrypt release'owy skanujący Apache-licensed zależności | FR-72. Nagłówek: „Copyright 2026 Michał Kamiński". |

## 4. Parsowanie i analiza statyczna (Etap 1–2)

| Komponent | Wybór | Uzasadnienie |
|---|---|---|
| AST | `tree-sitter-python` | Inkrementalny parser odporny na błędy składni — niezbędny przy ingestii dowolnych repozytoriów. Brak CPython‑specific edge cases. |
| Rozwiązywanie nazw i call graph | `Jedi` | Wystarczające pokrycie dla celu >80% (zielony poziom) bez instalacji zależności docelowego repo. **`pyright` adapter status (v2+)**: ADR-0006 (AST snapshot schema) bazuje na Jedi resolver — pyright wymaga zmiany kontraktu w `interfaces/parser.py` (Protocol). Decyzja zostanie podjęta w osobnym sprincie po pomiarze accuracy Jedi vs pyright na tym samym corpusie eval (post-v0.7.0). Trigger: FR-47. |
| Hashowanie plików | `hashlib.sha256` (stdlib) | Granularność inwalidacji cache na poziomie pliku (FR-29). |
| Filtrowanie plików | `pathspec` (kompatybilny z `.gitignore`) + hard‑refuse list | FR-09, FR-12: `.env*`, `*.pem`, `*_rsa`, `credentials.*` itd. wykluczane przed jakimkolwiek exclude/include użytkownika. |
| Uncertainty markers | Własna warstwa metadanych w `entities` | Oznaczanie dynamic import / reflection / unresolved Jedi jako `uncertain`; narracja o tym mówi wprost. |

## 5. Graf i ranking (Etap 3)

| Komponent | Wybór | Uzasadnienie |
|---|---|---|
| Struktura grafu | `networkx` | PageRank, wykrywanie cykli (`simple_cycles`), sort topologiczny, community detection (Louvain / Girvan‑Newman). Jedna biblioteka, zero infrastruktury. |
| Community detection | `python-louvain` lub `networkx.community` | Grupowanie modułów w „klastry tematyczne" dla planera lekcji. |
| Heurystyka „leaves‑to‑roots" | Własny algorytm nad `networkx` | Tworzy „story outline" karmiący wywołanie planistyczne (Etap 4). |
| PageRank diff (inkrementalne runy) | Własna implementacja nad snapshotami | FR-27: próg 20% zmienionych top‑ranked symboli → regeneracja manifestu. |

## 6. RAG i embeddingi (Etap 4)

| Komponent | Wybór | Uzasadnienie |
|---|---|---|
| Index store | `rank_bm25` (BM25Okapi) | Zero infrastruktury, zero binarnych rozszerzeń SQLite, deterministyczny ranking — idealny dla testów eval. Wystarczający dla korpusu jednego repo (README + docs + docstrings + commit messages). sqlite-vec + embeddingi zaplanowane do v2 po pomiarze jakości. **Status walidacji** (post-v0.6.0): BM25 zwalidowany w v0.7.0 release gate na 5 pinned repos (`tests/eval/corpus/repos.yaml`: click, requests, starlette, python-sdk-mcp, dateutil). Decyzja o sqlite-vec + embeddings (ADR-0015 TBD) wymaga porównania jakości retrieval BM25 vs hybrid na tym samym corpusie — eval baseline z v0.7.0 jest pre-req. ADR-0002 zostaje w mocy do decyzji ADR-0015. |
| Źródła indeksowane | Docstringi, `README.md`, `docs/**/*.md`, `CONTRIBUTING.md`, commit messages, inline comments (niższa waga) | Zgodnie z PRD sekcja 1. |
| Normalizacja i tokenizacja | Własny tokenizer (lowercase, snake/camelCase split, stopwords) | Niezależność od modelu embedding; deterministyczność. |
| Migracja do embeddings (v2) | Port `VectorStore` w `interfaces/` — wymiana adaptera BM25 → sqlite-vec bez zmian w `use_cases/` | Trigger w ADR-0002. |

## 7. Orkiestracja LLM (Etap 5–6)

| Komponent | Wybór | Uzasadnienie |
|---|---|---|
| Framework orkiestracji | Własny orchestrator w `use_cases/generate_tutorial.py` | Liniowy pipeline (plan → generate → validate → checkpoint per lekcja). Bez langgraph/langchain — decyzja w ADR-0001. |
| Abstrakcja LLM | Port `LLMProvider` w `interfaces/` | Minimalny kontrakt: `complete(messages, model, max_tokens)`, `count_tokens(...)`. BYOK przez wymianę adaptera. |
| Provider #1 (default) | `anthropic` SDK → `claude-haiku-4-5` (opisy, parallel) + `claude-opus-4-7` (narracja, sequential) | FR-64. Opus 4.7 dla jakości narracji; haiku 4.5 dla taniej pracy równoległej. |
| Provider #2 | `openai` SDK | FR-65. Bezpośrednio, bez langchain-openai. |
| Provider #3 (OSS local) | `httpx` + OpenAI-compatible endpoint (Ollama / LM Studio / vLLM) | FR-66. Brak banera zgody dla lokalnych endpointów (US-053). |
| Concurrency | `asyncio.Semaphore` (default 10, cap 20) | FR-67. Konfigurowalne przez `llm.concurrency`. |
| Backoff | `tenacity` (exponential + jitter, cap 60 s) | FR-68: retry na HTTP 429. |
| Walidacja output LLM | `pydantic.BaseModel` + tryb `json_schema` providera (gdzie dostępny) | FR-08/36/43. |
| Grounding validator | Warstwa `entities/`, bez zewnętrznych zależności | FR-36–38: pojedynczy retry, potem placeholder. |
| Długość lekcji | Własny walidator słów (150–1200) | FR-32, US-034. |
| State i checkpoint | SQLite row per completed lesson (state = JSON blob) | FR-21, FR-50. `--resume` czyta ostatnią row. |

## 8. Konfiguracja i CLI

| Komponent | Wybór | Uzasadnienie |
|---|---|---|
| Parser argumentów | `click` | Dojrzały, stabilny. Bez typer — redukcja zależności i ryzyka breaking changes. |
| Walidacja configu | `pydantic.BaseModel` | FR-08: walidacja `tutorial.config.yaml` z komunikatami wskazującymi ścieżkę błędu. |
| Format configu | YAML (`PyYAML`) | Człowieko‑czytelny, konwencjonalny dla narzędzi CLI. |
| Ścieżki user‑level | `platformdirs` | FR-30: `~/.config/`, `%APPDATA%`, `~/Library/...` bez POSIX‑only założeń. |
| Precedencja konfigu | Warstwowy loader (CLI > env > `--config` > `./tutorial.config.yaml` > user‑level > defaults) | FR-06; test integracyjny dla każdej granicy. |
| Interaktywny wizard `init` | `rich.prompt` + `questionary` | FR-05. Opcjonalny; CI pomija flagami (FR-07). |
| Edytor dla `--review-plan` | Resolver: `$EDITOR` → `$VISUAL` → `code --wait` → `notepad`/`vi` | FR-20. |
| Obsługa sygnałów | `signal` stdlib, dwustanowy handler SIGINT | FR-48, FR-49: pierwsze Ctrl+C = graceful (90 s cap), drugie = hard abort. |

## 9. Logowanie i raporty

| Komponent | Wybór | Uzasadnienie |
|---|---|---|
| Logger | `structlog` (preferowany) lub stdlib `logging` z JSON formatter | Zakaz `print()` w pipeline (CLAUDE.md). FR-26: `--log-format=json` → JSON per line do stderr. |
| SecretFilter | `logging.Filter` subclass w `interfaces/ports.py` | FR-80, US-069: redakcja API keys, external paths, verbatim source >INFO. Zastosowany do obu handlerów (human + JSON). |
| Terminal UI | `rich` | Progress bar (7 etapów), liczniki LLM, kolorowanie; OSC 8 hyperlinks dla końcowego `file://` URL (US-055). **Terminal UI**: `rich.panel.Panel` for cost-gate box (HEAVY border), `rich.live.Live` for real-time stage counters (elapsed / cumulative cost / tokens in/out), `rich.box.HEAVY` for framed run-report card. Color roles (`good / warn / err / accent / link / dim / default / prompt`) mapped to `rich.style.Style` constants — exact role→ANSI mapping and usage per `.ai/ux-spec.md` §CLI.color-roles. |
| Run report | Własny zapis `.wiedunflow/run-report.json` | FR-61, US-056. Schemat walidowany testem. |
| Historia runów | Rotacja 10 plików w `.wiedunflow/history/` | FR-63. |
| Auto‑gitignore | Idempotentny append `.wiedunflow/` | FR-62. |

## 10. Cache i persystencja

| Komponent | Wybór | Uzasadnienie |
|---|---|---|
| Silnik | SQLite (stdlib `sqlite3`) | Zero infrastruktury, cross‑platform, atomowe writes. Brak binarnych rozszerzeń — BM25 index serializowany do blob-a (ADR-0002). |
| Klucz cache | `<repo_absolute_path>+<commit_hash>` | FR-28. |
| Inwalidacja | SHA‑256 per plik | FR-29. |
| Lokalizacja | `platformdirs` per‑user, `--cache-path` override | FR-30, FR-24. |
| Migracje schematu | ADR `/docs/adr/*.md` + forward migration | CLAUDE.md: każda zmiana schematu cache wymaga ADR. |
| Checkpointing orchestratora | Jeden wiersz SQLite per ukończona lekcja (state = JSON blob) | FR-21: `--resume` po crash/Ctrl+C. Bez LangGraph checkpointera — ADR-0001. |

## 11. Renderowanie i artefakt wyjściowy (Etap 7)

| Komponent | Wybór | Uzasadnienie |
|---|---|---|
| Szablony | `Jinja2` | Standard de‑facto dla generacji HTML w Pythonie. |
| Podświetlanie składni | `Pygments` (pre‑render at build time) | FR-58: brak podświetlania w browserze. HTML spans wbudowane w dane lekcji. |
| Frontend JS | Vanilla JS (binarnie, bez opcji Preact) | `file://` forbid + zero bundler + zero framework. Decyzja zamknięta — nie przywracamy Preact bez ADR. |
| Inlining | Własny builder | FR-51: całość (CSS, JS, lesson JSON, Pygments HTML) w jednym pliku. |
| Offline linter | Template‑time AST/regex check na output | FR-14: fail build na `fetch(`, `Image(`, `<link rel="prefetch">`, `<link rel="preconnect">`, `http(s)://` poza whitelistą attribution. |
| Layout | CSS breakpoint 1024 px | FR-53: ≥1024 split‑view z scroll‑sync; <1024 stacked. Jedno źródło danych (embedded JSON). |
| Persystencja UI | `localStorage` pod kluczem `wiedunflow:<tutorial-id>:last-lesson` | FR-55, US-046. |
| Schema version | `metadata.schema_version = "1.0.0"` | FR-56. Template JS branchuje na unknown version (console warning). |
| Rozmiar outputu | Budżet <8 MB / warn >20 MB | FR-59; assertion w CI dla MCP Python SDK. |
| Fonty | Inter 400/500/600/700 + JetBrains Mono 400/500/600, self-hosted as WOFF2 (OFL license; license notice appended to `NOTICE` file) | System fallbacks: `ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif` / `ui-monospace, "SF Mono", Menlo, Consolas, "Courier New", monospace`. Rationale: FR-85, ADR-0011 §6, `.ai/ux-spec.md` §Tutorial.assets. |
| Paleta | A1 Paper only (dove white + graphite) using CSS custom properties: `--bg / --panel / --surface / --topbar / --ink / --ink-dim / --ink-micro / --accent / --warn / --border`. Dark palette via `[data-theme=dark]` attribute override. A2/A3 palettes and Direction B dropped (ADR-0011). | Rationale: ADR-0011, `.ai/ux-spec.md` §Tutorial.tokens. |
| Pygments → tok-\* classes | Pygments `TokenType` mapped to custom CSS classes via a `HtmlFormatter` subclass: `tok-kw` (Keyword), `tok-str` (String), `tok-com` (Comment), `tok-fn` (Name.Function), `tok-cls` (Name.Class), `tok-num` (Number). Colors in oklch color space. | Details per `.ai/ux-spec.md` §Tutorial.tokens. |
| CSS strategy | Single CSS source: `src/wiedunflow/renderer/templates/tokens.css` (design tokens / CSS custom properties) + `tutorial.css` (layout + component styles), included via Jinja2 `{% include %}` and inlined into the final HTML at build time. No PostCSS, no Tailwind, no build step. Vanilla CSS only. | Inline-everything constraint (FR-51, `file://` guarantee). |

## 12. Pricing & Cost Estimation (v0.5.0+)

**Architecture**: `PricingCatalog` Protocol + 4 adaptery (ADR-0014, 2026-04-26).

| Komponent | Wybór | Uzasadnienie |
|---|---|---|
| Port abstrakcji | `interfaces/pricing_catalog.py`: `blended_price_per_mtok(model_id: str) -> float \| None` | Blending formula: 60% input + 40% output, USD/MTok. Empiryczne proporcje dla planning (Stage 4) + narration (Stage 6). |
| StaticPricingCatalog | Hardcoded `MODEL_PRICES` dict z `cli/cost_estimator.py` | Fallback leaf adapter; gwarancja działania bez network. |
| LiteLLMPricingCatalog | HTTP fetch via `httpx` z BerriAI/litellm GitHub JSON (~3500 modeli) | Timeout 3s. Dostaje ~3500 modeli; auto-update po LiteLLM publish (bez WiedunFlow release). |
| CachedPricingCatalog | 24h disk cache decorator (`~/.cache/wiedunflow/pricing-<provider>.json`) | TTL 86400s. Per-provider cache file. |
| ChainedPricingCatalog | Fallback chain: `[CachedPricingCatalog(LiteLLM), StaticPricingCatalog()]` | Live → static; first non-None wins. Default chain w `cli/main.py:_build_pricing_chain()`. |
| Network failure handling | Graceful timeout/5xx/404 → empty dict, no crash, fallback to static | Nigdy nie blocka generacji. Partial failure = use best-effort. |
| Three-sink extension | `import httpx` ONLY w `adapters/litellm_pricing_catalog.py` | Test: `test_no_httpx_outside_litellm_pricing.py`. Lint enforce. |
| Prefix stripping | `gpt-4.1` i `openai/gpt-4.1` mapują na tę samą cenę | Provider-agnostic pricing lookup. |

**Effect**: nowe modele (`gpt-5.4-mini`, `claude-opus-4-8`) wycenione automatycznie po LiteLLM publish, bez WiedunFlow release.

## 13. CLI / UI Frameworks (v0.4.0+)

| Komponent | Wybór | Uzasadnienie |
|---|---|---|
| `rich>=13.7` | CLI panels (cost gate, run-report card, info panels) | Użyto ONLY w: `cli/output.py` ONLY. Lint test: `test_no_rich_outside_output.py`. |
| `questionary>=2.1.1,<3.0` | TUI menu, sub-wizard prompts, picker | Decyzja: ADR-0013 (Sprint 10/v0.4.0). Used in: `cli/menu.py` ONLY. Lint test: `test_no_questionary_outside_menu.py`. Transitive: `prompt_toolkit` ~600KB. |
| `click>=8.1.7` | CLI argument parsing (groups, commands, options) | Używane across `cli/`. |
| Plain `print()` | Diagnostic output, ASCII banner (`cli/menu_banner.py`) | Dla testów i debugowania. |

**Three-sink rule** (ADR-0011 D#8 + ADR-0013 D#9 + ADR-0014 §Alt #2): każdy z 4 wymienionych ma **dokładnie jeden** sink moduł. Żaden inny `src/wiedunflow/**` nie może ich importować — enforced przez lint testy (`test_no_rich_outside_output.py`, `test_no_questionary_outside_menu.py`, `test_no_httpx_outside_litellm_pricing.py`).

## 14. Testowanie

| Komponent | Wybór | Uzasadnienie |
|---|---|---|
| Framework | `pytest` | Fixtures, parametrize, markery. CI‑only (nie w pre‑commicie) — FR-69. |
| Mockowanie | `monkeypatch` + własny `FakeLLMProvider` implementujący port | CLAUDE.md: nigdy nie mockujemy LLM w E2E — deterministyczne odpowiedzi przez fake adapter. |
| Golden files | Snapshoty HTML | Każda zmiana szablonu musi być intencjonalna. |
| Browser E2E | `playwright` (headless Chromium) | US-040, US-041, US-042, US-045: `file://` + network disabled, viewport 1440×900 oraz 375×812. |
| Marker eval | `@pytest.mark.eval` — osobny run z prawdziwym API key | FR-77. Release gate, nie default CI. |
| Eval corpus | Git submodules, pinned commits w `tests/eval/corpus/repos.yaml` | FR-74: requests, click, starlette, mcp python‑sdk, dateutil. |
| Rubryka jakości | 5‑punktowa na coverage/accuracy/narrative flow, avg ≥3 na MCP Python SDK | FR-76. Autor + 2 zaufanych dev. |

## 15. CI/CD

| Komponent | Wybór | Uzasadnienie |
|---|---|---|
| Platforma | GitHub Actions | FR-04, FR-70. |
| Matryca | Python 3.11/3.12/3.13 × Ubuntu/Windows/macOS | FR-04, FR-61. |
| Setup UV | `astral-sh/setup-uv` | FR-04. |
| Kroki CI | `uv sync` → `ruff check` → `ruff format --check` → `mypy --strict src/wiedunflow/**` → `pytest` (bez `-m eval`) | CLAUDE.md + FR-69. |
| Branch protection | Required checks na `main`: pytest, ruff, mypy, DCO | CLAUDE.md. |
| DCO check | GitHub Action | FR-70. |
| Issue templates | `.github/ISSUE_TEMPLATE/{bug_report,feature_request,eval_regression}.yml` | FR-71, US-063. |
| Release workflow (v2+, przygotowane) | Trigger na tag `v*.*.*`, OIDC trusted publishing do PyPI | CLAUDE.md. W MVP wyłączone — FR-03. |
| Eval workflow | Oddzielny, ręczny trigger z sekretnym API key | FR-77, US-064. |
| Skan CVE | `pip-audit` (lub `uv audit` gdy dojrzeje) w release workflow | FR-78, US-067. HIGH+ blokuje release. Nie w default matrix. |

## 14. Production Dependencies (v0.1.0+v0.6.0)

**Core pipeline & analysis**:
- `tree-sitter>=0.25.0`, `tree-sitter-python>=0.25.0` — AST parsing (Etap 1)
- `jedi>=0.19.2` — call graph resolver (Etap 2)
- `networkx>=3.3` — graph ranking + PageRank (Etap 3)
- `rank-bm25>=0.2.2` — BM25Okapi RAG (Etap 4)

**Orchestration & LLM**:
- `anthropic>=0.40.0` — Anthropic SDK (default provider)
- `openai>=1.50.0` — OpenAI SDK (alt provider)
- `tenacity>=9.0.0` — exponential backoff retry (FR-68)

**Config & validation**:
- `pydantic>=2.7` + `pydantic-settings>=2.6.0` — config validation
- `pyyaml>=6.0` — YAML parsing
- `pathspec>=0.12.1` — `.gitignore` compatibility

**Rendering & output**:
- `jinja2>=3.1` + `markupsafe>=2.1` — HTML templating
- `pygments>=2.17` — syntax highlighting pre-rendering
- `mistune>=3.2.0` — markdown rendering w tutorials

**CLI & TUI (v0.4.0+)**:
- `click>=8.1.7` — CLI framework
- `rich>=13.7` — cost-gate panels, run-report card, progress bar (sink: `cli/output.py` ONLY)
- `questionary>=2.1.1,<3.0` — TUI menu, picker, sub-wizard (sink: `cli/menu.py` ONLY; ADR-0013)

**Pricing & cost estimation (v0.5.0+)**:
- `httpx>=0.27` — **EXPLICIT hard dep** (PricingCatalog adapter, ADR-0014; previously transitive via anthropic/openai). Sink: `adapters/litellm_pricing_catalog.py` ONLY.

**Infrastructure & logging**:
- `structlog>=24.1` — structured logging (JSON mode, SecretFilter)
- `platformdirs>=4.3.0` — cross-platform cache + config paths
- `numpy>=1.24` — linear algebra utilities

**Three-sink rule**: `rich` → `cli/output.py`, `questionary` → `cli/menu.py`, `httpx` → `adapters/litellm_pricing_catalog.py`. Lint-enforced przez `test_no_rich_outside_output.py`, `test_no_questionary_outside_menu.py`, `test_no_httpx_outside_litellm_pricing.py`.

## 16. Bezpieczeństwo i prywatność

| Obszar | Mechanizm | FR |
|---|---|---|
| Hard‑refuse secret list | `.env*`, `*.pem`, `*_rsa`, `*_rsa.pub`, `*_ed25519`, `credentials.*`, `id_rsa`, `id_ed25519` — enforce przed wszystkim innym | FR-09, US-008 |
| Consent banner per provider | Persistowany w user‑level config (`consent.<provider>: accepted`) | FR-10, FR-11, US-005, US-007 |
| Bypass dla CI | `--no-consent-prompt` (nie wyłącza hard‑refuse) | FR-12, US-006 |
| Zero telemetry | Test integracyjny z ograniczonym network namespace + template linter | FR-13, FR-14, US-011 |
| Storage sekretów | Tylko env vars i `tutorial.config.yaml` | CLAUDE.md (privacy section) |
| Budget cap | `--max-cost=<USD>` z checkpoint + exit | FR-23, US-019 |
| Skan CVE zależności | `pip-audit` w release workflow | FR-78, US-067 |
| Hardening subprocess | `shlex.split` + `shell=False` + walidacja binarki (rozwiązanie dla FR-20) | FR-79, US-068 |
| SecretFilter w logach | `logging.Filter`: API keys, external paths, verbatim source >INFO | FR-80, US-069, FR-26 |
| LangChain CVE expozycja | N/A — LangChain wycięty z MVP | ADR-0001 |

## 17. Dokumentacja

| Komponent | Wybór | Uzasadnienie |
|---|---|---|
| README | Sekcje wymagane: install przez `uvx`, quickstart 3‑krokowy, przykład `tutorial.config.yaml`, troubleshooting, licencja, link do CONTRIBUTING, disclosure transmisji kodu do LLM | FR-73 |
| ADR | `/docs/adr/{name}.md` dla zmian zależności, wzorców, integracji, schematu cache | CLAUDE.md |
| Changelog | `CHANGELOG.md`, Keep a Changelog | CLAUDE.md |
| Schema `tutorial.config.yaml` | JSON Schema w `/docs` + Pydantic model + przykład w README (spójne w jednym PR) | CLAUDE.md |

## 18. Architektura (Clean Architecture, warstwy)

Warstwy i zależności kierują się do wewnątrz (CLAUDE.md → Clean Architecture):

- **`entities/`** — `LessonPlan`, `CodeSymbol`, `CallGraph`, invarianty grounding i kolejności lekcji. Brak zależności od LangChain/SQLite.
- **`use_cases/`** — `GenerateTutorial`, `RankGraph`, `IndexRepo`, `PlanLessons`, `RenderHTML`. Operuje tylko na portach.
- **`interfaces/` (porty)** — `LLMProvider`, `Parser`, `VectorStore`, `Cache`, `Editor`, `Clock`.
- **`adapters/` (frameworki)** — `AnthropicProvider`, `OpenAIProvider`, `OllamaProvider`, `TreeSitterParser`, `JediResolver`, `SQLiteVecStore`, `SQLiteCache`, `JinjaRenderer`, `PygmentsHighlighter`.
- **`cli/`** — `click` entrypoint, wizard, signal handlers, progress UI.

Ta struktura bezpośrednio umożliwia BYOK (wymiana adaptera LLM) oraz plugin‑ready parser dla TS/JS w v2 (wymiana `Parser`).

## 19. Ryzyka i decyzje do rozstrzygnięcia

| Ryzyko / otwarta kwestia | Mitigation |
|---|---|
| `Jedi` coverage <50% na repach z heavy metaprogramming | FR-47: trzy‑stopniowy tiering + rekomendacja `pyright` adaptera w v2. Brak abortu. |
| Rozmiar embedded JSON przy >30 lekcjach dużych repo | Hard cap 30 lekcji (FR-39); lazy render gdy zbliżamy się do 20 MB (CLAUDE.md edge cases). |
| Cross‑platform ścieżki Windows (backslashes, długie ścieżki, `%LOCALAPPDATA%`) | `pathlib.Path` wszędzie, `platformdirs`, testy matrycowe (FR-30, US-025). |
| UV dostępność na Windows developerów | Dokumentowany błąd z czytelnym komunikatem „UV not on PATH — install from astral.sh/uv" (US-001). |
| Koszt Stage 4 planowania w `--dry-run` (~$0.05) | Udokumentowany wprost w outpucie preview HTML (FR-19, US-015). |
| Opus 4.7 koszt narracji przy >25 lekcjach zbliża się do $8 cap | FR-16/FR-23: `--max-cost` + formuła estymacji ostrzega przed uruchomieniem; user może w configu przełączyć na `claude-sonnet-4-6` jako tańszy fallback. |
| BM25 jakość retrieval na repach z ubogą dokumentacją | FR-46/US-038: warning o niskim pokryciu docstrings; migracja do sqlite-vec w v2 jeśli pomiar wykaże regresję w rubryce jakości (trigger w ADR-0002). |
| UX pixel-drift during template iteration (Medium) | Playwright visual regression tests (golden snapshots per viewport 1440×900 + 375×812, per theme light + dark) + manual review release gate comparing rendered HTML against `.ai/ux-spec.md` values. |

## 20. Co jest explicite POZA stackiem MVP

Zgodnie z sekcją 4.2 PRD i CLAUDE.md:

- **LangChain / LangGraph** (orkiestracja i providery) — zastąpione bezpośrednimi SDK; migracja opisana w ADR-0001.
- **sqlite-vec i embeddingi** — RAG w MVP oparty o BM25; ADR-0002 opisuje kryteria powrotu.
- **Preact** lub jakikolwiek framework frontendowy — vanilla JS binarnie.
- **typer, ruamel.yaml** — ujednolicone na `click` i `PyYAML`.
- PyPI, Docker, VS Code extension, GitHub Pages, hosted SaaS.
- Parsery inne niż Python (TS/JS), `pyright` adapter.
- Frameworki frontendowe (React, Astro, bundlery), runtime syntax highlighting.
- Telemetria / analytics / crash reporting (nawet opt‑in).
- Non‑English narration, polymorphism/dynamic dispatch resolution, framework‑specific understanding (Django/FastAPI/Flask).
- Provider‑specific fields (OpenRouter, DeepSeek reasoning).
- Shared / committed cache, full‑text search w HTML, mind‑map wizualizacja.
- **A2/A3 color palettes** — evaluated in design review, dropped in ADR-0011. Reversal requires new ADR.
- **Direction B** ("editorial reader" narrative layout) — evaluated, dropped in ADR-0011. Reversal requires new ADR.
- **Minimal CLI** (compact output direction) — prototype only, dropped in ADR-0011.
- **Retro ASCII CLI** (retro terminal output direction) — prototype only, dropped in ADR-0011.
- **Runtime syntax highlighting** (highlight.js / Prism.js) — Pygments pre-renders at build time (ADR-0011 §7).
- **External font CDN** — fonts self-hosted WOFF2 (ADR-0011 §6, offline-first guarantee).

Każde przesunięcie tej granicy wymaga osobnego ADR i zmiany boundary w PRD.

## Appendix: Cross-References (v0.6.0+)

| ADR | Decyzja | Sprint | Sekcje powiązane | Status |
|-----|---------|--------|------------------|--------|
| **ADR-0001** | LLM stack — direct SDK over LangChain/LangGraph | 3 | Orkiestracja LLM (§7) | Accepted 2026-04-16 |
| **ADR-0002** | RAG in MVP — BM25 over sqlite-vec + embeddings | 3 | RAG & embeddingi (§6) | Accepted 2026-04-16 |
| **ADR-0013** | Interactive menu-driven TUI ("centrum dowodzenia") | 10 | CLI/UI Frameworks (§13) | Accepted 2026-04-25 |
| **ADR-0014** | Dynamic pricing catalog — LiteLLM-backed | 11 | Pricing & Cost Estimation (§12) | Accepted 2026-04-26 |
| **ADR-0015** | sqlite-vec + embeddings evaluation & decision | TBD | RAG & embeddingi (§6) | Pending post-v0.7.0 eval baseline |

**Ścieżka walidacji tech-stack**: eval baseline (v0.7.0 na 5 repos) → BM25 vs hybrid porównanie (pre-req dla ADR-0015) → decyzja sqlite-vec → v0.8.0+ implementacja.
