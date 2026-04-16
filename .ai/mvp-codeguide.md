# MVP: Codebase Tutorial Generator

*High-level description dla sesji planistycznej → PRD*

---

## 1. Problem statement

Dzisiaj onboarding nowego developera do średniego/dużego repozytorium zajmuje
dni lub tygodnie. Istniejące narzędzia (Sourcegraph, Cursor, Aider) pomagają
*pisać* kod, ale nie *uczą* istniejącego kodu w formacie kursu. Narzędzia typu
Swimm, CodeTour wymagają ręcznego autorstwa lekcji — senior pisze je przez
dni, a potem dokumentacja rozjeżdża się z kodem.

**Luka rynkowa**: brakuje narzędzia, które automatycznie generuje
interaktywny, tutorial-style przewodnik po dowolnym repozytorium — w stylu
platform edukacyjnych jak Anthropic Skilljar — bez ręcznej pracy autora.

## 2. Produkt w jednym zdaniu

Narzędzie CLI w Pythonie, które na podstawie lokalnego repozytorium generuje
pojedynczy plik HTML działający jako interaktywny tutorial guided tour po
kodzie — otwierany bezpośrednio w przeglądarce z `file://`, bez serwera, bez
instalacji dodatkowych zależności po stronie odbiorcy.

## 3. User journey (happy path)

1. Developer instaluje narzędzie (`pip install <nazwa>`)
2. Ustawia API key w env vars (`ANTHROPIC_API_KEY`)
3. Odpala `<nazwa> ./moje-repo`
4. Widzi progress bar: analiza statyczna → graf relacji → RAG indexing →
   generacja lekcji
5. Po 10-30 minutach dostaje plik `tutorial.html` (~3-8 MB)
6. Otwiera w Chrome (`file://...`), dostaje guided tour z nawigacją
   Previous/Next, podświetlonymi fragmentami kodu i narracją "co to robi i
   dlaczego"
7. Może wysłać plik koledze w Slacku — działa u odbiorcy bez żadnej
   instalacji

## 4. Zakres MVP

### IN SCOPE

- **Input**: lokalna ścieżka do repozytorium **Git** (GitHub/GitLab/
  bitbucket nieistotne — liczy się że jest to folder z `.git/`).
  Użytkownik sam klonuje repo, narzędzie operuje na lokalnym folderze.
  Support dla bezpośredniego `github.com/user/repo` URL to v2.
- **Język kodu**: Python only (ale architektura modularna, parser/LSP
  jako plugin — gotowa na TS/JS w v2)
- **Język narracji**: angielski tylko. Wersje językowe (np. polski) to
  v2+, jak produkt się przyjmie.
- **Tryb przeglądania**: guided tour (Previous/Next) z podświetlaniem
  fragmentów kodu i narracją
- **Output format**: pojedynczy self-contained HTML file, otwierany
  przez `file://` w Chrome/Firefox/Edge — żadnego serwera, żadnego
  `npm install` po stronie usera
- **Tutorial versioning**: output HTML zawiera w metadata commit hash
  i branch repo, żeby user wiedział "to jest tutorial dla wersji X".
  Wyświetlane w stopce tutoriala.
- **LLM**: LangChain/LangGraph z BYOK — user dostarcza własny API key
  przez env var. Wsparcie dla:
  - **Anthropic** (default, Haiku 4.5 + Sonnet 4.5) przez
    `langchain-anthropic`
  - **OpenAI** (GPT-4o-mini + GPT-4o) przez `langchain-openai`
  - **OSS modele** (Ollama, LM Studio, vLLM) przez `ChatOpenAI` z
    `base_url` override — udokumentowane w README z przykładem konfigu
  - UWAGA: dla providerów z niestandardowymi polami (OpenRouter,
    DeepSeek, reasoning models) wymagany dedykowany `langchain-*`
    pakiet — w MVP nieobsługiwane, v2
- **Konfiguracja projektu**: opcjonalny plik `tutorial.config.yaml` w
  root repo albo `--config` flaga w CLI. Pozwala na:
  - `exclude`: glob patterns do pominięcia (np. `tests/**`, `migrations/**`)
  - `include`: whitelista (opcjonalna, domyślnie wszystko)
  - `focus_modules`: lista ścieżek do specjalnego potraktowania
  - `llm`: provider, model, koncurrentność
  - Domyślnie narzędzie **respektuje `.gitignore`** bez dodatkowej
    konfiguracji
- **Cache**: SQLite-based, file-level hash invalidation — jeśli plik
  się nie zmienił, nie regenerujemy jego analizy ani opisów LLM
- **Edge cases**:
  - Cykle w call graph: detekcja + opis jako "współzależne moduły"
    (MUST — inaczej nieskończona pętla)
  - Polimorfizm, dynamic imports, reflection: **wykrywanie i oznaczanie
    jako "uncertain"** (NIE próbujemy poprawnie rozwiązywać — osobny
    research problem)
- **Edukacyjny kontekst**: RAG nad docstringami, `README.md`, `docs/`,
  `CONTRIBUTING.md`, commit messages dla narracji "dlaczego"
- **Licencja**: **Apache 2.0**. Open source od początku, komercyjne
  usługi (hosted SaaS, premium features) ewentualnie v2+. Uzasadnienie
  wyboru i operacyjne implikacje — patrz sekcja 12.

### OUT OF SCOPE (v2+)

- Mind map / wizualny graf relacji (nice-to-have, nie blocker MVP)
- TypeScript/JavaScript parsing (architektura gotowa, implementacja
  później)
- Proper resolve polimorfizmu / type inference (wymaga abstract
  interpretation)
- Web app / SaaS deployment — MVP to CLI tool
- VS Code extension
- Automatic GitHub Pages deployment / sharing infrastructure
- Framework-specific understanding (Django, FastAPI, Flask patterns)
- Auto-update tutoriala przy zmianach w repo (CI/CD integration)
- Multi-user collaboration / comments na lekcjach
- Bezpośredni input GitHub URL (`github.com/user/repo`) — w MVP user
  sam klonuje repo, narzędzie operuje na lokalnym folderze
- Wersje językowe narracji inne niż angielski
- Provider-specific features (OpenRouter reasoning, DeepSeek
  reasoning_content) — wymaga dedykowanych pakietów LangChain
- Hosted SaaS / komercyjne usługi
- Telemetry / usage analytics (nawet opt-in) — MVP jest w 100%
  offline, żadnych calls do autora narzędzia

## 5. Architektura wysokopoziomowa

### Generator pipeline (Python CLI)

```
[CLICK: user odpala CLI na ścieżce repo]
         │
         ▼
┌─────────────────────────────────────────┐
│ Stage 0: Ingestion (~sekundy)           │
│ - detect languages (pyproject.toml)     │
│ - find docs/, README, CONTRIBUTING      │
│ - hash files → cache lookup (SQLite)    │
└────────────────┬────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────┐
│ Stage 1: Static analysis (~10-30s)      │
│ - tree-sitter-python → AST              │
│ - Jedi → resolved call graph            │
│ - extract docstrings, type hints        │
│ - detect entry points (main, __init__,  │
│   CLI scripts, API endpoints)           │
│ - detect cycles → mark clusters         │
│ - detect dynamic imports → mark         │
│   "uncertain"                           │
└────────────────┬────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────┐
│ Stage 2: Graph ranking (~sekundy)       │
│ - PageRank na call graph                │
│ - community detection (feature          │
│   clusters)                             │
│ - topological sort od leaves do roots   │
│ → "story outline" jako input dla LLM    │
└────────────────┬────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────┐
│ Stage 3: RAG indexing (~30-60s)         │
│ sqlite-vec embeddings nad:              │
│ - docstrings                            │
│ - README / docs/*.md                    │
│ - CONTRIBUTING.md                       │
│ - commit messages                       │
│ - inline comments (z wagą niższą)       │
└────────────────┬────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────┐
│ Stage 4: Lesson planning (1 LLM call)   │
│ Sonnet 4.5 dostaje:                     │
│ - ranked graph summary                  │
│ - entry points                          │
│ - feature clusters                      │
│ - project type (library/app/CLI)        │
│ → zwraca lesson_manifest (JSON):        │
│   {lessons: [{id, title, teaches,       │
│    prerequisites, code_refs,            │
│    external_context_needed}]}           │
└────────────────┬────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────┐
│ Stage 5: Content generation (~10-20min) │
│ LangGraph orchestrator ze state:        │
│   {explored_symbols,                    │
│    lessons_generated,                   │
│    concepts_introduced}                 │
│                                         │
│ Per lekcja:                             │
│ - Haiku 4.5: opisy funkcji liściowych   │
│   (parallel, do 20 na raz)              │
│ - Sonnet 4.5: narracja lekcji           │
│   (sequential, z pełnym kontekstem      │
│   wcześniejszych lekcji)                │
│ - RAG lookup gdy agent pyta o spec      │
│ - Checkpoint po każdej lekcji           │
│   (resume po przerwaniu)                │
└────────────────┬────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────┐
│ Stage 6: Artifact build (~sekundy)      │
│ - Pygments: pre-render syntax           │
│   highlighting → HTML spans             │
│ - Jinja2 template: jeden index.html     │
│ - Inline: CSS, vanilla JS (albo         │
│   Preact 3KB), dane lekcji jako         │
│   <script type="application/json">      │
│ - Zero external deps, działa z file://  │
└─────────────────────────────────────────┘
```

### Output structure

```html
<!DOCTYPE html>
<html>
<head>
  <style>/* ~50KB inline CSS */</style>
</head>
<body>
  <div id="app"></div>

  <script type="application/json" id="tutorial-data">
    {
      "metadata": {"project_name": "...", "generated_at": "..."},
      "lessons": [...],
      "code_snippets": [...],  // pre-rendered HTML z highlighting
      "graph": {...}           // dla v2 mind map, już w danych
    }
  </script>

  <script>
    // Vanilla JS / Preact, bez bundlera
    // Nawigacja Previous/Next, rendering lekcji, code panel
    // ~100-200KB logiki
  </script>
</body>
</html>
```

## 6. Kluczowe decyzje techniczne

| Decyzja | Wybór | Uzasadnienie |
|---|---|---|
| Parser Python | tree-sitter-python + Jedi | tree-sitter = fakty AST, Jedi = call graph resolve. LSP (pyright) zbyt ciężki na MVP |
| Orkiestracja LLM | LangGraph + BYOK multi-provider router | znajomy stack, gotowe abstrakcje ReAct, state persistence, wsparcie Anthropic/OpenAI/Ollama przez ChatOpenAI base_url override |
| RAG storage | sqlite-vec | lokalny, zero infra, działa wewnątrz artefaktu cache |
| Cache | SQLite + file-level hash | 80% zysku za 20% pracy, graph-level invalidation to v2 |
| Frontend output | Vanilla JS lub Preact 3KB + Jinja2 template | żadnego Reacta/Astro/bundlera — constraint file:// zabrania fetch() |
| Syntax highlighting | Pygments (Python) | nie wymaga Node.js subprocess, jakościowo wystarczy |
| Model routing | Haiku 4.5 (opisy liściowe) + Sonnet 4.5 (narracja) | ~$0.50-$2.00 per tutorial dla średniego repo |

## 6.5. Przykład konfiguracji użytkownika

**`tutorial.config.yaml`** (opcjonalny, w root repo):

```yaml
# Provider LLM - domyślnie anthropic
llm:
  provider: anthropic         # anthropic | openai | ollama | custom
  model_narrative: claude-sonnet-4-5-20250929
  model_descriptions: claude-haiku-4-5-20251001
  concurrency: 10             # max równoległych wywołań LLM
  # Dla custom/Ollama:
  # base_url: http://localhost:11434/v1
  # api_key_env: CUSTOM_API_KEY

# Filtrowanie plików
files:
  # .gitignore jest respektowane domyślnie
  exclude:
    - "tests/**"
    - "migrations/**"
    - "**/__pycache__/**"
    - "docs/legacy/**"
  include: []                 # puste = wszystko co nie jest w exclude
  focus_modules:              # moduły z podwyższoną wagą w tutorialu
    - "src/core/"
    - "src/api/"

# Generacja
tutorial:
  max_lessons: 30             # hard limit
  target_audience: "mid-level Python developer"
  output_path: "./tutorial.html"
```

Przy braku configu: sensowne defaulty + respektowanie `.gitignore`.

## 7. Krytyczne constraints (must-have dla MVP)

- **file:// compatibility**: output musi działać otwarty bezpośrednio w
  Chrome z dysku. To wyklucza `fetch()`, ES modules z relative imports,
  bundle splitting. Wszystko inline w jednym HTML.
- **Zero runtime deps po stronie odbiorcy**: user dostaje plik, otwiera,
  działa. Żadnego Node.js, Pythona, serwera.
- **BYOK**: user płaci za własne zużycie LLM. Brak billingu po stronie
  narzędzia.
- **Incremental**: drugi run na tym samym repo musi być <5 min jeśli
  zmienione jest <20% plików. Inaczej narzędzie staje się bezużyteczne
  w iteracji.
- **Narrative coherence**: lekcja N nie może powtarzać tego, co było w
  lekcjach 1..N-1. Wymaga structured state w LangGraph, nie można tego
  zostawić "na sprycie LLM".

## 8. Sukces MVP — jak zmierzymy

Weź oficjalny Python MCP SDK (https://github.com/modelcontextprotocol/python-sdk)
i wygeneruj dla niego tutorial. Porównaj z Anthropic Skilljar "Building MCP
Clients" course (który jest napisany ręcznie przez seniorów Anthropic).

Kryteria sukcesu MVP:

- **Pokrycie**: tutorial wymienia co najmniej 70% kluczowych konceptów,
  które wymienia Skilljar
- **Jakość narracji**: w blind test, 3/5 developerów oceniłoby
  wygenerowany tutorial jako "useful for onboarding" (skala 1-5, >=3)
- **Poprawność techniczna**: 0 halucynowanych funkcji/klas (grounding
  działa), <5% mylnych opisów zachowania (oceniane przez autora repo)
- **Performance**: pierwszy run <30 min, kolejny (po zmianie 1 pliku)
  <5 min, koszt <$3 per full generation
- **Robustness**: narzędzie nie crashuje na 5 losowo wybranych OSS
  Python repo z GitHuba (obsługuje cykle, dynamic imports jako
  "uncertain")

## 9. Ryzyka i mitigacje

| Ryzyko | Prawdopodobieństwo | Impact | Mitigacja |
|---|---|---|---|
| LLM halucynuje funkcje/klasy | Średnie | Wysoki | Hybrid grounding: każdy symbol w opisie musi być w AST. Walidacja post-hoc. |
| Narrative coherence słabnie przy >20 lekcjach | Wysokie | Wysoki | Structured state w LangGraph, explicit "concepts_introduced" w promptach |
| HTML output za duży (>20MB) | Średnie | Średni | Limit na rozmiar repo w MVP (np. <500 plików), lazy rendering lekcji |
| Rate limits Anthropic API | Średnie | Średni | Exponential backoff, konfigurowalny concurrency (default 10) |
| Konkurencja (Cursor/Sourcegraph dodaje tę funkcję) | Niskie | Wysoki | Niche na onboarding/OSS docs, szybki time-to-MVP |
| Dynamic imports/reflection → bezużyteczny graf | Średnie | Średni | Oznaczenie "uncertain", nie próba rozwiązania w MVP |

## 10. Roadmap (sugerowany, 4-6 tygodni part-time)

- **Tydzień 1**: szkielet CLI + tree-sitter parsing + statyczny HTML
  template z hardcoded danymi. Smoke test całego pipeline.
- **Tydzień 2**: Jedi call graph + sqlite-vec RAG + PageRank. Bez LLM
  jeszcze, tylko "structured data out".
- **Tydzień 3**: LangGraph orchestration + LLM content generation +
  SQLite cache + checkpointing.
- **Tydzień 4**: Pygments syntax highlighting + Jinja2 template polish
  + mobile-responsive CSS (jak Skilljar na komórce).
- **Tydzień 5**: eval na MCP Python SDK + 5 innych OSS repo. Fix edge
  cases (cykle, dynamic imports).
- **Tydzień 6**: dokumentacja, `pyproject.toml`, release na PyPI, blog
  post / demo video.

## 11. Rozstrzygnięte decyzje i pozostałe otwarte pytania

### Rozstrzygnięte w trakcie dyskusji

| Pytanie | Decyzja |
|---|---|
| Źródło repo | Lokalny folder z `.git/`. Bezpośredni GitHub URL input w v2. |
| Telemetry | Brak w MVP. Narzędzie 100% offline (poza LLM API). |
| LLM providers | Anthropic default, OpenAI + OSS (Ollama/LM Studio) przez podmianę endpointu w LangChain. Udokumentowane w README z przykładami configu. |
| Tutorial versioning | Tak — commit hash + branch w metadata HTML output. |
| Customization | Przez `tutorial.config.yaml` w repo albo `--config` flag. Exclude/include patterns, focus modules. Respektowanie `.gitignore` domyślnie. |
| Język narracji | Tylko angielski w MVP. Wersje językowe w v2+. |
| Licencja | Apache 2.0 (patent grant ważny dla AI/ML, preferowana w enterprise). Operacyjne koszty patrz sekcja 12. |

### Otwarte pytania do sesji PRD

- **Distribution**: PyPI only, czy też Docker image dla tych co nie
  chcą instalować Pythona lokalnie?
- **CLI UX detale**: jak wygląda dokładnie flow pierwszego użycia?
  Interactive setup wizard (pyta o API key, domyślny provider) czy
  tylko flagi i env vars?
- **Rozmiar repo — hard limit?**: czy narzędzie powinno odmówić dla
  repo >N plików (np. >1000), czy próbować i pokazać ostrzeżenie o
  czasie/koszcie?
- **Resume checkpoint**: po crashu/Ctrl+C, czy narzędzie automatycznie
  wznawia od ostatniego checkpointu, czy wymaga flagi `--resume`?
- **Artefakt output name**: default `tutorial.html` czy `<repo-name>-
  tutorial-<commit-hash>.html`? To druga opcja lepsze dla dzielenia,
  pierwsza prostsza.
- **Private repo / sensitive code**: czy w MVP dokumentujemy
  ostrzeżenie "twój kod jest wysyłany do providera LLM"? (Ollama jako
  rozwiązanie dla sensitive code).

## 12. Licencja Apache 2.0 — uzasadnienie i implikacje operacyjne

### Dlaczego Apache 2.0 (a nie MIT)

Obie licencje są OSS-friendly i akceptowane w enterprise. Wybór Apache 2.0
dla tego projektu motywowany jest trzema czynnikami:

1. **Patent grant (sekcja 3 licencji)** — contributorzy udzielają
   użytkownikom explicit licencji na swoje patenty związane z kodem. MIT
   tego nie ma. W obszarze AI/ML, gdzie patenty są coraz bardziej aktywne
   (OpenAI, Microsoft, Google składają setki patentów rocznie), ta
   ochrona jest istotna dla użytkowników i kontrybutorów.

2. **Patent retaliation clause** — jeśli ktoś pozwie projekt lub jego
   użytkowników za patent w związku z kodem, traci licencję na
   korzystanie z projektu. To defensywna ochrona dla ecosystemu.

3. **Preferowana przez enterprise** — korporacyjne legal reviews często
   łatwiej zatwierdzają Apache 2.0 właśnie ze względu na explicit patent
   clauses. Dla projektu, który celuje w enterprise onboarding use case
   (Siemens, Dell, inne korporacje), to konkretna zaleta adopcyjna.

### Operacyjne wymagania (koszty)

**One-time setup (~30 min na początku projektu):**

- **`LICENSE` file** — standardowa treść Apache 2.0, pobrana z
  https://www.apache.org/licenses/LICENSE-2.0.txt i umieszczona w root
  repozytorium.
- **`NOTICE` file** — plik w root zawierający copyright attribution
  projektu oraz wymagane `NOTICE` content z Apache-licensed zależności
  (jeśli istnieją). Na start: podstawowy copyright dla projektu.
- **Header w plikach źródłowych** (opcjonalne, rekomendowane):
  ```python
  # Copyright 2026 [Autor]
  # Licensed under the Apache License, Version 2.0 (the "License");
  # you may not use this file except in compliance with the License.
  # You may obtain a copy of the License at
  #
  #     http://www.apache.org/licenses/LICENSE-2.0
  ```
  Automatyzacja przez pre-commit hook (np. `addheader` albo
  `insert-license` pre-commit plugin) — koszt ~5 min konfiguracji,
  potem transparentne.
- **`pyproject.toml`** — pole `license = "Apache-2.0"` i classifier
  `"License :: OSI Approved :: Apache Software License"`.

**Ongoing operational costs:**

- **Dependency tracking** (~5 min per nowa Apache-licensed zależność):
  jeśli dodajesz dependency na Apache 2.0 które ma własny `NOTICE`
  file, jego treść musi zostać zachowana w twojej dystrybucji. W
  praktyce dla większości Python packages (LangChain, LangGraph,
  tree-sitter bindings) — zależności zarządzają tym same przy
  instalacji przez pip.
- **Modification notices (sekcja 4b licencji)**: jeśli forkujesz kod
  innego Apache 2.0 projektu i go modyfikujesz w swoim repo, musisz
  zaznaczyć które pliki zostały zmodyfikowane i kiedy. W praktyce:
  większość projektów nie trzyma tego perfekcyjnie; komentarz
  `# Modified from [source] on [date]` na początku modyfikowanych
  plików wystarczy.
- **Trademark disclaimer (sekcja 6)**: licencja explicite nie daje
  praw do znaków towarowych. Jeśli projekt zyska brand recognition
  (nazwa, logo), trzeba osobno zadbać o trademark policy. W MVP:
  niemijalne.

**Decyzje do podjęcia w trakcie PRD:**

- **Contributor License Agreement (CLA)?** Apache Foundation projekty
  używają ICLA/CCLA. Dla małego projektu: overhead większy niż
  benefit. Alternatywa: **Developer Certificate of Origin (DCO)** —
  sign-off w commit message (`Signed-off-by: Name <email>`),
  wymuszane przez GitHub Actions. Prostsze, lightweight, dobrze
  rozumiane w OSS community. **Rekomendacja: DCO od v1, CLA jeśli
  projekt urośnie.**
- **Copyright holder** — osoba fizyczna (ty) czy entity (firma, jeśli
  założysz)? W MVP: osoba fizyczna. Można to później przekazać do
  entity przez Copyright Assignment Agreement, ale to osobny proces.
- **Attribution w output HTML** — czy wygenerowane tutoriale mają
  zawierać footer "Generated by [nazwa] (Apache 2.0)"? Nie jest to
  wymaganie licencji (output nie jest "derivative work" w sensie
  kodu), ale dobra praktyka dla brand awareness.

### Tooling do compliance

Istnieją narzędzia które automatyzują większość powyższych wymagań:

- **`reuse`** (https://reuse.software/) — tool i standard FSFE do
  zarządzania licencjami w repozytorium, weryfikuje headers, generuje
  SPDX manifest. Dobrze integruje się z CI.
- **`licensecheck`** — Python package do skanowania licencji
  zależności.
- **pre-commit hooks** (`insert-license`, `reuse lint`) —
  automatyczne wstawianie headerów i walidacja.

**Rekomendacja dla MVP**: wystarczy ręcznie utworzyć `LICENSE` +
`NOTICE` + jeden pre-commit hook dla headerów. `reuse` i pełne SPDX
compliance to v2 jeśli projekt się rozwija.

### Podsumowanie kosztów

| Koszt | Czas | Kiedy |
|---|---|---|
| LICENSE + NOTICE files | 10 min | Jednorazowo na start |
| Header template + pre-commit | 20 min | Jednorazowo na start |
| Per nowa Apache dependency | ~5 min | Okazjonalnie |
| DCO setup (GitHub Action) | 15 min | Jednorazowo na start |
| Audit zależności przed releasem | ~30 min | Przed każdym major release |

**Total one-time cost: ~1 godzina setup + ~30 min per release cycle.**

Koszt realny, ale niski. Benefit (patent protection, enterprise
friendliness) uzasadnia ten overhead dla projektu celującego w AI/ML
i enterprise adoption.
