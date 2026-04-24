# ADR-0005: Frozen vanilla JavaScript output — no frameworks in generated HTML

- Status: Accepted
- Date: 2026-04-20
- Deciders: Michał Kamiński
- Related PRD: v0.1.2-draft
- Supersedes: none

## Context

CodeGuide's output is a single, self-contained HTML file opened via `file://` protocol in a user's browser. This constraint — no server, no fetch(), no ES module imports, no external CDN — shapes the frontend architecture fundamentally.

Before adopting a framework (Preact, React, Alpine.js, htmx) for the tutorial reader UI, we must account for:

1. **`file://` protocol limitations** — `fetch()` fails with CORS error, relative ES module imports fail, external CDN resources cannot be loaded. Popular frameworks assume these capabilities exist. Workarounds (bundling, vendoring, inlining runtime) add size and complexity.

2. **Supply chain attack surface** — every framework added to the build pipeline is a transitive dependency chain. Preact pulls 15–20 packages, React pulls 50+. We commit to zero telemetry and auditable output; bundler-generated code is not easily auditable at runtime.

3. **Output size constraint** — target <8 MB for a medium repo (PRD v0.1.2, FR-70). Pre-rendered Pygments HTML + lesson JSON + vanilla JS typically fits in 3–5 MB. Adding Preact runtime (~3 KB minified) + JSX build step + tree-shaking overhead often exceeds 6 MB for large repositories.

4. **Long-term reproducibility** — a user should be able to open a tutorial HTML file generated in 2026 in a browser in 2036 without requiring npm, node_modules, or a build tool. Vanilla JS requires no runtime; it works in any browser.

5. **UX design system decision** (ADR-0011) — the tutorial reader uses a fixed, bespoke design system (A1 Paper palette, Inter font, Direction A layout). This is a pixel-perfect delivery contract, not a reusable component library. The design does not benefit from React's reusability, state management, or hooks ecosystem.

## Decision

**Zero frameworks in the generated HTML output.** The tutorial reader is written exclusively in vanilla JavaScript, with no Preact, React, Astro, Alpine.js, htmx, or any runtime that requires bundling, transpilation, or CDN fallbacks.

### Implementation

- **Frontend code** (`src/codeguide/renderer/templates/static/js/`): plain JavaScript, no JSX, no build step beyond minification (optional, via `terser` at build time).
- **Inline scripts** in the Jinja2 template: `<script>` tags with vanilla JS execute within the HTML document.
- **State management**: `window.localStorage` for persistent state (last viewed lesson, theme toggles); `document` API for DOM traversal and event binding.
- **DOM manipulation**: `document.querySelector`, `Element.addEventListener`, `textContent`, `classList.toggle`, `classList.add` — standard DOM APIs.
- **JSON data embedding**: lesson content, code references, and metadata are embedded as `<script type="application/json" id="...">` blocks parsed at runtime via `JSON.parse()`.
- **CSS**: inlined in the HTML via Jinja2 template; no external stylesheets, no CSS-in-JS runtime.
- **Syntax highlighting**: Pygments pre-renders HTML spans during the build stage (stage 7: build). No runtime Pygments, no highlight.js.

### API Surface

The frontend exposes the following module pattern (no ES modules, no imports):

```html
<script type="application/json" id="tutorial-data">
  {
    "lessons": [...],
    "metadata": {...}
  }
</script>

<script>
  // Global namespace: window.Tutorial
  window.Tutorial = {
    state: { currentLessonId: null, favorites: [] },
    init: function() { /* ... */ },
    goToLesson: function(id) { /* ... */ },
    markFavorite: function(id) { /* ... */ }
  };

  // Lifecycle
  document.addEventListener('DOMContentLoaded', () => {
    window.Tutorial.init();
  });
</script>
```

### Constraints

- ❌ No `import` statements, no `export`, no `require()`
- ❌ No external CDN (`unpkg.com`, `jsdelivr.net`, `cdnjs.com`)
- ❌ No build-time transpilation (TypeScript, JSX, ES6 module bundling)
- ❌ No npm packages in the generated HTML
- ❌ No async module loading or dynamic imports
- ❌ No lazy-loaded third-party scripts

## Consequences

### Positive

- **Zero dependencies** — the HTML file is entirely self-contained. No npm install, no node_modules, no bundler on the recipient's machine.
- **Zero attack surface in output** — no minifier vulnerabilities, no bundler exploits, no transitive CVEs embedded in the generated file.
- **Audit-friendly** — a developer can open DevTools, view the source, read the JS, and trace exactly what the UI does. No obfuscation from bundler overhead.
- **Maximum longevity** — vanilla JS written in 2026 runs unchanged in 2036. No framework version pinning, no "this version of React is incompatible with ES5" drift.
- **Faster cold start** — parsing and executing vanilla JS is faster than JIT-compiling a framework at page load.
- **`file://` compatibility** — the tutorial works in any browser with zero server setup.

### Negative

- **More verbose code** — managing state and DOM synchronization manually requires more lines than `React.useState()` or `@click="..."`. Estimated +30–50% LOC vs Preact + JSX.
- **No component library** — developers cannot reuse component patterns from the frontend framework ecosystem. Every interaction must be written fresh (but the surface is small: sidebar navigation, lesson viewer, favorites toggle, search highlight).
- **Harder for frontend specialists** — a developer comfortable with React, Vue, or Svelte may find vanilla DOM API work tedious. Mitigation: the tutorial reader is a single-page-application-like interface with a modest feature set (estimated <2000 LOC vanilla JS). Inline comments and a README (`src/codeguide/renderer/templates/README.md`) document patterns.
- **Testing vanilla JS** — without a framework test harness, DOM tests require setup boilerplate (e.g., `jsdom`). Mitigated by functional testing: the `tests/` suite includes golden-file HTML snapshots and Playwright e2e tests (stage 5: design review gates these before release).

### Neutral

- **Framework adoption in v2+** — if a future release adds a server-side tutorial reader or collaborative features, a framework becomes justified and a new ADR would supersede this one. For MVP's offline-first, single-user model, vanilla JS is optimal.

## Alternatives Considered

1. **Preact (3 KB minified)** — rejected.
   - Reasoning: Preact is lightweight, but still requires a build step (JSX → JS) and a bundler (or inline runtime). The `file://` constraint forbids `fetch()` for lazy-loading components. Inlining Preact runtime + transpiled JSX adds ~15–25 KB to the output, which is non-trivial for a 5 MB file. Signal-to-noise ratio is poor.
   - Reconsider if: interactivity needs exceed current scope (estimated 10+ interactive subsystems) OR we add a companion server-side reader.

2. **Alpine.js (15 KB minified)** — rejected.
   - Reasoning: Alpine simplifies DOM-driven UX (no build step, no transpilation). However, it is still a runtime dependency vendored in the output, and the `file://` constraint means we cannot load it from CDN. We would inline 15 KB of minified code for a modest interactive feature set (~sidebar, lesson nav, favorites). Vanilla JS is smaller and self-documenting.
   - Reconsider if: interactivity scope grows beyond current sidebar/nav/favorites model.

3. **htmx (15 KB minified)** — rejected.
   - Reasoning: htmx assumes server-side AJAX endpoints (`hx-get="/api/lesson/42"`). Our `file://` delivery model forbids fetch(). Htmx without a backend is not applicable; inlining it is pure overhead.
   - Reconsider if: we add a server-side option for collaborative tutorials (v2+).

4. **React (40 KB minified + JSX runtime)** — rejected.
   - Reasoning: React is a full application framework optimized for large interactive apps. CodeGuide's tutorial reader is a single-page app with modest state (current lesson, favorites, search highlight). React adds complexity and size for zero UX benefit. `file://` compatibility requires all React code be inlined and pre-compiled, negating React's promise of fast iteration.
   - Reconsider if: we pivot to a web application with collaborative editing, live preview, or multi-user cursors.

5. **Astro (zero JS by default, but with `client:` directives)** — rejected.
   - Reasoning: Astro is a build-time framework that ships zero JS by default and selectively hydrates components. For CodeGuide, this is a false promise: the tutorial reader *is* interactive (lesson navigation, favorites, search highlight, theme toggle). Opting into `client:load` or `client:visible` for every interactive element re-introduces a runtime (Preact, Vue, Svelte), which we already rejected. Astro's strength is mixing static and dynamic content; our entire output is dynamic navigation over lesson data.
   - Reconsider if: the majority of the tutorial becomes static content with sparse interactive regions (unlikely).

## Migration Criteria (reconsidering vanilla JS in v2+)

Revisit this decision if **any** of the following becomes true:

- CodeGuide adds a server-side option (cloud-hosted tutorials, collaborative editing, real-time features). A server enables Preact or React for the client, with a proper build pipeline and bundle optimization.
- The tutorial reader feature set grows to exceed 5000 LOC of vanilla JS, with complex state management that a framework would simplify.
- Users report performance issues or accessibility gaps that vanilla JS architecture cannot address without significant refactoring.
- The `file://` constraint is relaxed (e.g., we add optional HTTP server for local development or deployment).

Until any of these triggers, vanilla JavaScript remains exclusive.

## Implementation Notes

- **Naming convention**: entrypoint is `window.Tutorial` (avoid polluting global scope; use namespacing).
- **Comments**: document stateful operations and event bindings clearly. Assume readers are familiar with standard DOM APIs but not with CodeGuide's conventions.
- **Testing**: unit tests for state logic (e.g., `window.Tutorial.goToLesson`) use `jsdom` fixtures. DOM integration tests use Playwright snapshots.
- **Accessibility**: ensure all interactive elements have proper `aria-*` attributes. Test with WAVE or axe-core.
- **Progressive enhancement**: the HTML should be legible even if JS fails to load (graceful degradation). Display a fallback message with a link to the first lesson.

## References

- ADR-0011 (UX design system) — vanilla JS decision is a binary choice within the design-system ADR
- PRD v0.1.2-draft, §7.1 (output format: single HTML, no server)
- `file://` protocol limitations: MDN docs on CORS and cross-origin restrictions
- CLAUSE.md §OUTPUT_ARTIFACT (target size, vanilla JS requirement)
