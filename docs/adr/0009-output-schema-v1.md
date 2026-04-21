# ADR-0009 — Output JSON schema v1.0.0 (tutorial.html envelope + future compat)

Status: Accepted
Date: 2026-04-21
Sprint: 5
Deciders: Michał Kamiński

## Context

Sprint 5 replaces the walking-skeleton `tutorial_minimal.html.j2` with the
pixel-perfect template mandated by `.ai/ux-spec.md` and ADR-0011. Because the
rendered HTML is a single file served from `file://`, every piece of data the
navigation JS consumes must live inside the document. This ADR pins the shape
of that data and the forward-compatibility strategy so Track A (Jinja2 +
renderer), Track C (vanilla JS), and future post-MVP consumers can evolve
without breaking older tutorials.

Three constraints drive the envelope:

1. **Vanilla JS only** (ADR-0005). The reader runs without a bundler, so the
   payload must be parse-friendly native JSON inside `<script type="application/json">` blocks.
2. **Offline-first** (US-040). No `fetch()` or external manifest; everything
   including the schema version must be inline.
3. **Parallel track ownership** (Sprint 5 plan decision #7). Track A owns the
   Python renderer; Track C owns the vanilla JS that consumes the payload.
   A single pinned schema version lets both tracks evolve independently.

## Decision

The rendered `tutorial.html` embeds exactly **three JSON payloads** identified
by stable DOM IDs. The namespace `window.CodeGuide.*` is reserved for the
reader runtime and documented below.

### DOM IDs (locked)

| ID | Purpose |
|---|---|
| `#tutorial-progress` | Progress bar rail (3 px, fixed top) |
| `#tutorial-topbar` | Sticky topbar (52 px) |
| `#tutorial-sidebar` | TOC container (280 px) |
| `#tutorial-content` | Three-column grid wrapper (narration + splitter + code) |
| `#tutorial-narration` | Narration scroll container |
| `#tutorial-narration-body` | Narration content root — tutorial.js renders into this |
| `#tutorial-splitter` | Resizable splitter (28–72 %) |
| `#tutorial-code` | Code panel (sticky) |
| `#tutorial-code-head` | Code panel header (file path, lang) |
| `#tutorial-code-body` | Code panel body — tutorial.js renders lines here |
| `#tutorial-footer` | Footer meta row (40 px) |
| `#tweaks-panel` | Settings panel (theme toggle) |
| `#tutorial-meta` | `<script type="application/json">` — meta payload |
| `#tutorial-clusters` | `<script type="application/json">` — clusters payload |
| `#tutorial-lessons` | `<script type="application/json">` — lessons payload |

### JSON payload: `#tutorial-meta`

```jsonc
{
  "schema_version": "1.0.0",
  "codeguide_version": "0.0.5",
  "repo": "modelcontextprotocol/python-sdk",
  "sha": "abc1234…",
  "branch": "main",
  "generated_at": "2026-04-21T14:30:00+00:00",
  "run_status": "ok" | "degraded",
  "total_lessons": 12,
  "skipped_count": 0
}
```

### JSON payload: `#tutorial-clusters`

```jsonc
[
  { "id": "default", "label": "Tutorial", "kicker": "All lessons",
    "description": "", "lesson_count": 12 }
]
```

Clusters are a grouping layer for the sidebar TOC. For the MVP, the renderer
emits a single `default` cluster covering every lesson; future sprints may
derive clusters from the graph community-detection output (Stage 2).

### JSON payload: `#tutorial-lessons`

```jsonc
[
  {
    "id": "lesson-001",
    "cluster_id": "default",
    "title": "The Orchestrator",
    "confidence": "HIGH" | "MEDIUM" | "LOW",
    "status": "generated" | "skipped",
    "narrative": "Plain-text fallback for readers that don't support segments.",
    "segments": [
      { "kind": "p",    "text": "<p>-safe HTML paragraph</p>" },
      { "kind": "p",    "text": "Paragraph with a code citation.",
        "code_ref": {
          "file": "src/client/models.py",
          "lang": "python",
          "lines": ["<span class=\"tok-kw\">def</span> ..."],
          "highlight": [1, 3]
        }
      },
      { "kind": "code", "text": "loose code excerpt (mobile inline)" }
    ],
    "code_refs": ["CodeSymbol names …"]
  }
]
```

Segments are **ordered**. Desktop renders `p` segments in the narration
column and the first segment that carries a `code_ref` in the sticky code
column. Mobile (<1024 px, see `initStackedMobile()`) displays every segment
inline in document order; `code_ref` lines become a `<pre class="mobile-inline-code">`
block immediately after the paragraph that cites them.

### JS namespace

```jsonc
window.CodeGuide = {
  init(): void,                 // bootstrap entry — called on DOMContentLoaded
  _errors: string[],            // populated when JSON parse or DOM lookup fails
  _meta, _clusters, _lessons,   // parsed payloads, available after init()
  _activeIndex, _activeId       // current navigation position
}
```

### localStorage keys (namespaced, locked)

| Key | Type | Default |
|---|---|---|
| `codeguide:<repo>:last-lesson` | lesson id string | first lesson id |
| `codeguide:tweak:theme:v2` | `"light"` \| `"dark"` | `"light"` |
| `codeguide:tweak:narr-frac:v2` | float in `[0.28, 0.72]` | `0.5` |

Other keys prefixed with `codeguide:*` are reserved for future use.

### Forward compatibility

- **schema_version** is SemVer **MAJOR.MINOR.PATCH**. A reader that sees an
  unknown version logs `console.warn("CodeGuide: unknown schema_version 'X', supported: 1.0.0")`
  and continues rendering on a best-effort basis (decision #5 of Sprint 5 plan: **fail-open**,
  never block the read).
- Additive fields in meta/clusters/lessons are **non-breaking**; readers MUST
  ignore unknown keys.
- Field removals or type changes are a breaking change and require a MAJOR
  bump plus a superseding ADR.

## Alternatives considered

1. **Single monolithic JSON** (`#tutorial-data`). Used in the Sprint 1 walking
   skeleton. Simpler to write but couples meta/clusters/lessons lifecycles —
   any addition requires a diff across the whole payload. Rejected in favour
   of independent payloads so the renderer can omit (e.g.) `clusters` in
   dry-run mode without rewriting the rest.
2. **Dedicated manifest file referenced by `<script src="…manifest.json">`**.
   Violates US-040 (external reference under `file://`).
3. **HTML data attributes** (`data-lessons="[…]"`). Forces string-escaping of
   the entire payload on every element and is noisy in DOM inspectors.

## Consequences

- **Renderer** (`adapters/jinja_renderer.py`) emits the three payloads via
  `json.dumps(ensure_ascii=False)` through Jinja2 `| safe`.
- **Reader** (`renderer/templates/tutorial.js`) parses each payload via
  `JSON.parse(el.textContent)`; on parse failure, the error is recorded in
  `window.CodeGuide._errors` so tests (`tests/integration/test_html_file_url.py`)
  can assert zero parse errors.
- **Tests** pin the shape: `tests/integration/test_walking_skeleton.py::test_tutorial_html_has_three_json_payloads`
  and `test_tutorial_html_has_schema_version` protect the envelope.
- **PRs** touching the envelope MUST update this ADR and bump `schema_version`
  if the change is not additive.

## Related

- ADR-0005 — Frozen vanilla JS output (no Preact/React/bundler)
- ADR-0011 — UX design system (A1 Paper / Inter / Direction A)
- Sprint 5 implementation plan (`C:/Users/micha/.claude/plans/…keen-noodle.md`)
- `.ai/ux-spec.md` §Tutorial (DOM layout, localStorage keys)
