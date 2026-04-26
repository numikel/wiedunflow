# Handoff: WiedunFlow Tutorial Reader

## Overview

This handoff bundles the design for **WiedunFlow's generated `tutorial.html`** — the reader-facing HTML artifact that every `wiedun-flow init` run produces. WiedunFlow is a CLI that analyses a Python repository and emits a self-contained, offline HTML tutorial; this document describes what that HTML should look like, behave like, and contain.

The goal of this handoff is to let a developer recreate the design **inside the WiedunFlow Python renderer** (Jinja2 templates + static CSS + a small amount of vanilla JS, per the tech stack). No SPA framework is required — the output is a single self-contained HTML file that must work when opened via `file://`.

## About the Design Files

The files bundled under `design_reference/` are **design references created in HTML**. They are a live prototype showing the intended look, hierarchy, and interactions. They are **not production code to copy directly**.

The task is to recreate these designs inside WiedunFlow's renderer, using its established patterns (Jinja2, pre-rendered Pygments HTML, inlined CSS, vanilla JS for interactions, `localStorage` for reader state). Where the prototype fakes generated content (syntax highlighting, lesson data), the real renderer will supply it from the pipeline's stage artefacts.

## Fidelity

**High-fidelity.** Colors, typography, spacing, hierarchy, and interaction states are all final. Recreate pixel-perfectly.

## Target environment

- **Renderer:** Jinja2 templates invoked from the WiedunFlow Python CLI.
- **Output:** a single `tutorial.html` with inlined `<style>` and `<script>` so it works offline via `file://`.
- **No external CDN calls at runtime.** Fonts must be either self-hosted or fall back cleanly to system fonts (see Typography).
- **No build step for the output.** The CLI writes the finished HTML; no bundler runs in the consumer's environment.

## Screens / Views

There is one screen — the tutorial reader — with several states.

### Layout (≥1024px)

Three-column grid, full viewport height:

```
┌────────────────────────────────────────────────────────────┐
│ progress bar (3px, fixed top)                              │
├────────────────────────────────────────────────────────────┤
│ topbar (52px, sticky)                                      │
│   [brand] [breadcrumb...................] [icon buttons]   │
├────────────┬───────────────────────────────────────────────┤
│ degraded banner (conditional, 44px)                        │
├────────────┼──────────────────────┬────────────────────────┤
│            │                      │                        │
│ sidebar    │ narration            │ code panel             │
│ (280px,    │ (resizable, default  │ (resizable, default    │
│ sticky)    │ 50%)                 │ 50%)                   │
│            │ ▲ splitter           │                        │
│            │ (draggable, 28–72%)  │                        │
│            │                      │                        │
├────────────┴──────────────────────┴────────────────────────┤
│ footer (meta row — commit/cost/confidence)                 │
└────────────────────────────────────────────────────────────┘
```

### Layout (<1024px)

- Sidebar hides (replaced by a hamburger-triggered drawer in the real implementation).
- Splitter hides.
- Narration and code stack vertically.

### Components

#### 1. Progress bar
- Fixed, top: 0; height: 3px; z-index 50
- Background transparent; inner `<span>` fills `width: %` of lesson progress
- Color: `--accent`
- Transition: `width 220ms ease`

#### 2. Topbar
- Sticky, height 52px, `background: var(--topbar-bg)`, `border-bottom: 1px solid var(--line-2)`
- `backdrop-filter: saturate(1.4) blur(8px)`
- Contents (horizontal flex, gap 16, px 20):
  - **Brand**: 22×22 square, `border-radius: 5px`, background `--ink`, color `--bg`, mono font, label "wf" + "WiedunFlow" in 13px/600 Inter
  - **Breadcrumb** (flex 1, 12.5px Inter, color `--muted`, `line-height: 1`):
    - `owner/repo` → `›` → `cluster.label` (color `--ink-2`) → `›` → `lesson-number` (11px mono, `--muted`, margin-right 8px) + `lesson.title` (`--ink`, 500)
    - Overflow ellipsis on small widths
  - **Icon buttons** (3 × 32×32, `border: 1px solid var(--line-2)`, radius 7px):
    - `A|B` direction toggle, `☾` theme toggle, `⚙` tweaks panel toggle

#### 3. Sidebar (TOC)
- 280px fixed width, sticky at top 52px, `height: calc(100vh - 52px)`, scrollable
- `border-right: 1px solid var(--line)`, padding 28px 22px 40px
- **TOC title**: `owner/repo`, 11px/600, letter-spacing 0.12em, uppercase, color `--muted`, margin-bottom 18px
- **Cluster** (repeated):
  - Header row: `kicker` (10.5px mono, uppercase, `--muted`) + `label` (13px/600, `--ink`)
  - `description` (12px, `--muted`, line-height 1.5, max-width ~220px)
  - Lesson list (gap 2px)
- **Lesson link** (grid: 22px | 1fr | auto; gap 10; padding 7px 8px; radius 6px):
  - `num` (11px mono, right-aligned, `--muted`)
  - `title` (13px, `--ink-2`, overflow ellipsis, nowrap)
  - `time` (10.5px mono, `--muted`, e.g. `3m`)
  - **States**:
    - default: transparent
    - hover: `background: var(--panel); color: var(--ink)`
    - current: `background: var(--panel); color: var(--ink); border: 1px solid var(--line-2)`
    - done: `color: var(--muted)`; title line-through 1px `--line-2`; num hidden, replaced with `✓` in `--accent`, 12px/600

#### 4. Narration column
- Padding: 56px 56px 80px; `background: var(--panel)`
- `border-right: 1px solid var(--line)`
- **Lesson kicker** (above H1): flex row, 12px/uppercase/letter-spacing 0.08em, color `--muted`. Contains `Lesson NN / NN` (mono) + 4px accent dot + cluster label.
- **H1 (.lesson-title)**: 38px/600/-0.015em, `--ink`, `text-wrap: pretty`, `max-width: 22ch`
- **Subtitle (.lesson-sub)**: 15px Inter, `--muted`, max-width 56ch, margin-bottom 36px
- **Meta row**: flex gap 18, 11px mono, `--muted`, `padding: 10px 0 24px`, `border-bottom: 1px solid var(--line)`, margin-bottom 32px
  - Confidence pill: 7px dot (high: `oklch(0.65 0.16 145)`, medium: `oklch(0.75 0.15 75)`, low: `oklch(0.60 0.18 25)`) + text
  - Read time + word count + file path
- **Narration body** (`.narration-body`):
  - `max-width: 62ch`, font-size 16.5px, line-height 1.72, `--ink-2`, `text-wrap: pretty`
  - Inline `<code>`: mono 0.88em, `background: --code-bg`, padding 1px 6px, radius 4px, 1px border `--line`
  - `<em>`: color `--ink`, italic
- **Up-next card** (appended to last paragraph area, not after nav):
  - Margin-top 42px; `border: 1px solid var(--line-2)`; radius 10px; padding 22px 24px; `background: var(--panel)`; max-width 62ch
  - Label: "Up next · cluster.label" (10.5px mono uppercase `--muted`)
  - Title: 20px/600 `--ink`
  - Subtitle: 13px `--muted`
  - Button: `background: --ink; color: --bg`; 13px/500 Inter; padding 9px 14px; radius 7px; copy `Continue → NN`
- **Prev/Next nav** (at bottom of narration, grid 1fr/1fr gap 14, max-width 62ch):
  - Each cell: padding 14px 16px; border 1px `--line-2`; radius 10px; `background: var(--panel)`
  - Hover: `border-color: --ink-2; color: --ink`
  - `.dir` (11px mono, `--muted`, uppercase, letter-spacing 0.06em)
  - `.ttl` (14px/500, `--ink`)
  - Disabled: opacity 0.35, `pointer-events: none`

#### 5. Splitter
- 10px wide, positioned absolutely, draggable column resize between narration and code
- Visual: 1px line (`--line`) with hover/drag turning it into a 2px `--accent` line plus a 4×36 grip pill
- Drag range: 28%–72% of content width
- Persisted in `localStorage` key `wiedunflow:tweak:narr-frac:v2`
- On touch devices: `touchstart/touchmove/touchend` handlers mirror mouse events
- While dragging: `body` gets `.is-resizing` (sets cursor and disables pointer events on children)

#### 6. Code panel
- `background: var(--panel)`; sticky at top 52px; height `calc(100vh - 52px)`; flex column
- **Header** (`.codepanel-header`): flex, padding 14px 22px, `background: var(--code-bg)`, `border-bottom: 1px solid var(--line)`, 12px mono:
  - File icon: 14×14 outlined rectangle with 3 horizontal lines (muted CSS-drawn, `::after` pseudo with box-shadows)
  - File path: `directory/` in `--muted` + `filename` in `--ink`/500
  - Right-aligned: `python · NN lines shown` (11px, `--muted`)
- **Body** (`.codepanel-body`): flex 1; overflow-y auto; `background: var(--code-bg)`; padding `18px 0 40px`
- **Code rows** (`.code .row`): grid `54px | 1fr`; 13px/1.7 mono
  - `.ln` (line number): right-aligned, `--muted`, padding-right 16px, opacity 0.7, user-select none
  - `.ct` (content): padding-right 20px, pre-wrapped
  - Highlighted row (`.row.hl`): `background: var(--hl)`; `box-shadow: inset 3px 0 0 0 var(--hl-line)` (left accent bar)
- **Syntax tokens** (used as markup produced by the Python renderer via Pygments):
  - `.tok-kw` keyword — light: `oklch(0.55 0.15 300)`, dark: `oklch(0.78 0.14 310)`
  - `.tok-str` string — light: `oklch(0.50 0.13 145)`, dark: `oklch(0.78 0.14 140)`
  - `.tok-com` comment — `--muted`, italic
  - `.tok-fn` function call — light: `oklch(0.55 0.15 240)`, dark: `oklch(0.78 0.14 235)`
  - `.tok-cls` class/type — light: `oklch(0.55 0.16 40)`, dark: `oklch(0.78 0.14 55)`
  - `.tok-num` number — light: `oklch(0.55 0.16 30)`, dark: `oklch(0.78 0.14 40)`

#### 7. Footer
- `border-top: 1px solid var(--line)`; `background: var(--panel)`; padding 28px 56px; 12px Inter, `--muted`
- Grid `1fr auto`; meta row is `display:flex; gap 6px 18px; font-family mono`; each `<span>` is `<label>key</label> value`
- Second meta row: resolution pill (conf-high/medium/low), cost `$X.XX (H $0.XX · O $0.YY)`, elapsed `Xm Ys`
- Offline line: "Generated by WiedunFlow vX.X.X (Apache 2.0) — this document is fully offline."
- Right column: 11px mono, `--muted` — schema version + lesson count

#### 8. Degraded banner (conditional, renders when `run_status == "degraded"`)
- Background: `oklch(0.94 0.10 40)` (light) / `oklch(0.30 0.10 35)` (dark)
- Text: `oklch(0.35 0.16 35)` / `oklch(0.82 0.14 45)`
- Padding: 12px 56px; 13px Inter; flex with 10px gap
- Border-bottom: 1px `oklch(0.82 0.14 40)` / `oklch(0.40 0.12 35)`
- Copy: `DEGRADED run — N of M lessons were skipped due to grounding failures. The tutorial is still usable; skipped sections are flagged inline.`
- Inline `.count` pill: mono, subtle tinted background

#### 9. Skipped-lesson placeholder (per-lesson when that specific lesson was skipped)
- Renders inline above the narration body when `lesson.status == "skipped"`
- `border: 1px dashed var(--line-2)`; radius 10px; padding 22px 24px
- Background: diagonal hatching — `repeating-linear-gradient(45deg, transparent 0 10px, color-mix(in oklab, var(--line) 60%, transparent) 10px 11px)`
- Top tag "SKIPPED" (10.5px mono uppercase, tinted orange on light / amber on dark)
- Copy explains the file path wasn't grounded and points to the source file

#### 10. Tweaks panel (reader-side settings)
- Fixed bottom-right, 20px from edges; 300px wide; `background: var(--panel)`; 1px `--line-2`; radius 12px; `box-shadow: 0 20px 40px -20px rgba(0,0,0,0.25)`; padding 16px 18px; z-index 60
- Hidden by default; toggled by `⚙` button and by host postMessage contract (see Interactions)
- Rows: label (11px uppercase letter-spacing 0.06em `--muted`) + segmented control
  - Segmented control: `display: inline-flex; width: 100%; border: 1px solid --line-2; radius 7px; padding 2px; gap 2px; background: --bg`
  - Button: `flex:1; padding 6px 8px; radius 5px; 12px Inter; --ink-2`; `.on` → `background: --ink; color: --bg`
- Controls (these are reader-side, not build-time): Light palette (A1/A2/A3), Direction (A/B — for the shipped product keep only A), Theme (light/dark), Body font (sans/serif/mono), Jedi confidence tier (high/medium/low — affects footer pill text), Degraded state toggle (demo-only — in production this is driven by the run manifest)

## Interactions & Behavior

### Navigation
- **Click a TOC lesson** → navigate to that lesson. Update `location.hash = "#/lesson/<id>"`. `window.scrollTo({top:0, behavior:'smooth'})`.
- **Arrow keys** (when focus is not in an input): `ArrowLeft` → previous lesson; `ArrowRight` → next lesson.
- **Prev/Next cards** at end of narration: same as arrow keys.
- **Up-next "Continue" button**: same as ArrowRight.
- **Deep link**: on page load, parse `location.hash` with regex `#\/lesson\/(.+)$`. If a matching lesson exists, open it.
- **Persistence**: write current lesson id to `localStorage` key `wiedunflow:<repo>:last-lesson`. Read on load.

### Splitter drag
- `mousedown/touchstart` on splitter → `dragging = true`, `body.classList.add('is-resizing')`
- `mousemove/touchmove` → clientX relative to content rect → frac = clamp(0.28, 0.72, x/width). Apply `content.style.setProperty('--narr-frac', frac)`; position splitter at `frac * 100%`. Persist to `wiedunflow:tweak:narr-frac:v2`.
- `mouseup/touchend` → `dragging = false`, remove `.is-resizing`.
- On resize: re-read `--narr-frac` and reposition splitter.

### Tweaks persistence
Each tweak is a simple segmented control → writes to localStorage and sets a `data-*` attribute on `<html>`:
- `data-palette` ∈ `a1` (default) | `a2` | `a3` → overrides the light palette variables
- `data-dir` ∈ `A` (default) | `B` — A is "clean technical", B is "editorial reader" (keep B optional)
- `data-theme` ∈ `light` (default) | `dark`
- `data-font` ∈ `sans` (default) | `serif` | `mono`

When an attribute changes, CSS vars cascade automatically (no re-render needed except for things that the footer injects via JS — re-render the footer).

### Edit-mode contract (used by the prototype host; safe to keep)
In the prototype, the Tweaks panel can also be toggled externally via `postMessage`:
- On load, post `{type: '__edit_mode_available'}` to `window.parent`.
- Listen for `{type: '__activate_edit_mode'}` / `{type: '__deactivate_edit_mode'}` to show/hide the Tweaks panel.

**In production this can be removed** — the Tweaks panel is simply toggled by the `⚙` button.

## State Management

### localStorage keys (all optional, sane defaults if absent)
- `wiedunflow:<repo>:last-lesson` — last open lesson id (string)
- `wiedunflow:tweak:palette:v2` — `a1`|`a2`|`a3`
- `wiedunflow:tweak:dir:v2` — `A`|`B`
- `wiedunflow:tweak:theme:v2` — `light`|`dark`
- `wiedunflow:tweak:font:v2` — `sans`|`serif`|`mono`
- `wiedunflow:tweak:conf:v2` — `high`|`medium`|`low` (prototype-only; real reader reads this from the manifest)
- `wiedunflow:tweak:deg:v2` — `off`|`on` (prototype-only; real reader reads `run_status` from the manifest)
- `wiedunflow:tweak:narr-frac:v2` — number in [0.28, 0.72]

### JSON data the renderer must embed

The prototype mocks this inline; the real renderer will embed the pipeline's stage-6 artefacts. Shape:

```ts
TUTORIAL_META = {
  project_name, owner, commit, branch, generated_at,
  wiedunflow_version, schema_version,
  file_count, total_lessons,
  resolution: number,           // percent
  cost_haiku, cost_opus,         // USD
  elapsed_seconds,
  doc_coverage: number,
}
TUTORIAL_CLUSTERS = Array<{
  id, label, kicker, description, lessons: lessonId[]
}>
TUTORIAL_LESSONS = Array<{
  id, cluster,
  title, subtitle,
  read_time: number, words: number,
  confidence: "high"|"medium"|"low",
  is_closer?: boolean,
  status?: "ok"|"skipped",
  narration: Array<
    | { kind: "p", text: string }       // HTML-safe; inline <code>/<em> allowed
    | { kind: "next-links", items: Array<{label, note}> }
  >,
  code: {
    file: string, lang: string,
    highlight: number[],                // 1-indexed
    lines: string[],                    // plain text; renderer must run Pygments and emit tok-* spans
  }
}>
```

## Design Tokens

### Spacing scale (informal — use these values consistently)
`2, 4, 6, 7, 8, 10, 12, 14, 16, 18, 20, 22, 24, 28, 32, 36, 40, 42, 48, 56, 80` (px)

### Radii
`4px` (pills, inline code), `5–7px` (buttons, segments), `10px` (cards, nav), `12px` (tweaks panel)

### Typography
- **UI font**: Inter — weights 400, 500, 600, 700
- **Body font**: Inter (sans)
- **Mono font**: JetBrains Mono — weights 400, 500, 600
- **Fallbacks**: `ui-sans-serif, system-ui, -apple-system, Helvetica, Arial, sans-serif` for sans; `ui-monospace, SF Mono, Menlo, Consolas, monospace` for mono
- **Self-host fonts** in production so the HTML stays offline-capable. Fall back to system stack if the font files are missing.

Key sizes: `10.5 / 11 / 12 / 12.5 / 13 / 14 / 15 / 16.5 / 20 / 38 px` plus `0.88em` for inline code.

### Light palette (A1 — Paper & ink, approved)
```
--a-bg:        #edeef0   /* page / sidebar */
--a-panel:     #fbfbfa   /* narration — 20% closer to white */
--a-ink:       #1a1d22
--a-ink-2:     #3d424a
--a-muted:     #6e737c
--a-line:      #dcdde0
--a-line-2:    #c4c6ca
--a-accent:    #3d424a
--a-accent-2:  #1a1d22
--a-code-bg:   #e6e7ea
--a-hl:        #dcdee2
--a-hl-line:   #5a616b
--a-topbar-bg: #dfe1e4   /* darker than page — header */
```

### Dark palette
```
--bg:        #0f1115   /* page / sidebar */
--panel:     #151821   /* narration */
--ink:       #eceef3
--ink-2:     #c4c7cf
--muted:     #868a93
--line:      #21242d
--line-2:    #2f333d
--accent:    #3d424a   (same as light — let it read as neutral)
--code-bg:   #0b0d12
--hl:        #1e222b
--hl-line:   #6a707c
--topbar-bg: #0a0c10   /* darkest — header */
```

### Semantic tokens
- **Confidence pills** (light / dark):
  - high — `oklch(0.93 0.08 145)` on `oklch(0.35 0.13 145)` / `oklch(0.28 0.08 145)` on `oklch(0.80 0.14 145)`
  - medium — `oklch(0.93 0.09 80)` on `oklch(0.40 0.14 70)` / `oklch(0.30 0.09 75)` on `oklch(0.82 0.14 80)`
  - low — `oklch(0.93 0.08 30)` on `oklch(0.42 0.16 30)` / `oklch(0.30 0.09 30)` on `oklch(0.80 0.14 30)`

### Shadows
- Tweaks panel: `0 20px 40px -20px rgba(0,0,0,0.25)`
- Splitter drag indicator: no shadow (uses width + color change)
- Highlighted code row: `inset 3px 0 0 0 var(--hl-line)` (left accent bar, not a drop shadow)

## Hierarchy rules (IMPORTANT — these were the main revision in this design)

1. **Topbar is the DARKEST surface** in both light and dark modes.
2. **Sidebar / page bg / code panel body** are the mid-tone.
3. **Narration** is the LIGHTEST surface — it must visibly lift off the page. In light mode this is ~20% closer to white than the page bg.

Sanity-check any palette changes against this three-step hierarchy.

## Assets

- **Fonts**: Inter, JetBrains Mono, optionally Source Serif 4 — self-host as WOFF2.
- **Icons**: two inline, CSS-drawn — the brand "cg" square and the code-panel file icon. No icon font, no SVG files.
- **Images**: none. The design is intentionally illustration-free; the codebase is the content.

Ship only the **A1 Paper** palette and the **Inter (sans)** body font. The A2/A3 palettes and serif/mono body-font options were prototype alternates and are not part of the handoff.

## Files in this bundle

Under `design_reference/`:
- `Tutorial Reader.html` — entry point, loads CSS and JS
- `tutorial-styles.css` — full stylesheet, all tokens as CSS custom properties
- `tutorial-app.js` — interactions (nav, splitter, tweaks, localStorage, postMessage)
- `tutorial-data.js` — mock content for the `kennethreitz/requests` demo (12 lessons, 4 clusters). The real renderer will replace this with Jinja-injected JSON.

Open `Tutorial Reader.html` in a browser to explore. Everything persists in `localStorage` across reloads.

## Implementation checklist for Claude Code

- [ ] Move the stylesheet into WiedunFlow's Jinja templates folder (`wiedunflow/renderer/templates/`), inline it into the final HTML via `{% include %}` or direct interpolation so there are no external CSS files at runtime.
- [ ] Port the vanilla JS into the same template, inlined at the bottom. Read `window.TUTORIAL_META/CLUSTERS/LESSONS` from a `<script type="application/json">` block that Jinja populates from the stage-6 artefact.
- [ ] Replace the prototype's hand-rolled Python highlighter with **pre-rendered Pygments output** (per the tech-stack doc — rendering happens at build time, no JS highlighting). Map Pygments classes to the `tok-*` classes used here.
- [ ] Wire the manifest fields into the footer: commit, branch, generated_at, resolution %, cost, elapsed, schema version.
- [ ] Honour `run_status == "degraded"` from the manifest to show the top banner; honour per-lesson `status == "skipped"` to render the skipped placeholder.
- [ ] Remove the A/B direction toggle and the degraded/confidence demo toggles from the shipped Tweaks panel — they were prototype conveniences. Keep theme only (light/dark). Body font and palette are fixed to Inter + A1 Paper.
- [ ] Ship the HTML as a single file (inline CSS, inline JS, inline JSON). Verify it opens over `file://` with no network requests.
- [ ] Self-host the three fonts as WOFF2 in the output; keep `@font-face` declarations so they're embedded and offline.
