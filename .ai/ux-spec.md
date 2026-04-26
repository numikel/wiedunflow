---
version: 0.2.0
status: Accepted
last_updated: 2026-04-26
depends_on:
  - .ai/prd.md
  - .ai/tech-stack.md
  - docs/adr/0011-ux-design-system.md
  - docs/adr/0013-interactive-menu-driven-tui.md
  - docs/adr/0014-dynamic-pricing-catalog.md
skill_reference: .claude/skills/wiedunflow-ux-skill/
---

# WiedunFlow UX Specification

## §1. Przeznaczenie dokumentu

This document is the **single source of truth** for all user-facing surfaces in WiedunFlow: the CLI output (`wiedun-flow init` terminal experience) and the generated `wiedunflow-<repo>.html` offline reader.

**When to read this:**
- Implementing or modifying CLI output (stages, prompts, cost gate, error scenarios, run report)
- Implementing or modifying the tutorial reader template, styles, or interactions
- Reviewing UX design changes before opening a PR
- Debugging discrepancies between the skill prototype and production output

**When to update this:**
- Adding a new CLI stage or reordering existing stages
- Changing visual hierarchy, spacing, or color values in the tutorial
- Adding a new error scenario or modifying error-handling copy
- Changing localStorage keys, JSON data shape, or typography settings
- Adding or removing a tutorial component

**Relationship to skill and ADR:**
- The skill `wiedunflow-ux-skill` contains immutable hi-fi prototypes in HTML (`reference/tutorial/design/` and `reference/cli/design/`). Those prototypes are design references only — not production code.
- ADR-0011 documents seven binary design decisions that constrain the tutorial reader and core CLI (palette, fonts, CLI direction, surface hierarchy). All decisions are final for MVP; any reversal requires a new ADR.
- ADR-0013 documents twelve binary decisions for the interactive menu-driven TUI ("centrum dowodzenia") launched in v0.4.0, including hybrid CLI/menu, questionary framework, ModelCatalog port, and three-sink rule.
- ADR-0014 documents the dynamic pricing catalog launched in v0.5.0, including PricingCatalog port, four adapters (Static/LiteLLM/Cached/Chained), and httpx hard dependency.
- This spec is the **living specification** for implementers. When you build the tutorial renderer or CLI output, follow this document's pixel values, copy, color roles, and state-management contracts.

## §2. Binary design decisions (per ADR-0011)

These seven decisions are **closed** for MVP. Reversing any of them requires a new ADR superseding ADR-0011, user research justification, and simultaneous updates to `.ai/prd.md` and this spec.

| # | Decision | Status | Rationale |
|---|----------|--------|-----------|
| 1 | CLI: Modern direction only (Minimal and Retro ASCII dropped) | Accepted 2026-04-19 | Consistent with Claude Code / opencode / uv aesthetic. No heavy TUI; no retro ASCII. |
| 2 | Tutorial: A1 Paper palette only (A2, A3 dropped) | Accepted 2026-04-19 | Dove white + graphite hierarchy proven in design review. Reduces CSS maintenance and snapshot testing burden. |
| 3 | Tutorial: Direction A only ("clean technical"; Direction B "editorial reader" dropped) | Accepted 2026-04-19 | Avoids split design system. Direction A serves primary persona (developer exploring code for themselves, not reading narrative prose). |
| 4 | Body font: Inter only (serif / mono body variants dropped) | Accepted 2026-04-19 | Mono reserved for code + UI micro accents. Serif explored but reduced visual clarity against code blocks. |
| 5 | Surface hierarchy: topbar darkest, narration lightest (~20% closer to white) | Accepted 2026-04-19 | Non-negotiable constraint. Defines the visual reading priority in both light and dark modes. |
| 6 | Fonts self-hosted as WOFF2 (offline-first, no CDN) | Accepted 2026-04-19 | Satisfies FR-14 (offline-capable). Single HTTP request from CDN breaks the `file://` guarantee. |
| 7 | Syntax highlighting: Pygments pre-rendered during build (no runtime highlight.js / Prism) | Accepted 2026-04-19 | Avoids 15 KB+ JS bundle. Rendering happens in the Python pipeline (stage 7), HTML ships with tokenized spans. |

---

## §3. Tutorial reader — complete specification

### §3.1 Layout and viewport behaviour

#### Desktop (≥1024px)

Three-column layout, full viewport height:

```
┌────────────────────────────────────────────────────────────┐
│ progress bar (3px, fixed top)                              │
├────────────────────────────────────────────────────────────┤
│ topbar (52px, sticky top: 0)                               │
├────────────────────────────────────────────────────────────┤
│ [optional degraded banner, 44px, conditional]              │
├────────────┬─────────────────────┬──────────────────────────┤
│            │                     │                          │
│ sidebar    │  narration          │  code panel              │
│ (280px,    │  (resizable,        │  (resizable,             │
│ sticky)    │  default 50%)        │  default 50%)            │
│            │  ▲ splitter         │                          │
│            │  (28–72% range)     │                          │
│            │                     │                          │
├────────────┴─────────────────────┴──────────────────────────┤
│ footer (40px, sticky bottom)                                │
└────────────────────────────────────────────────────────────┘
```

- **Progress bar**: fixed top, z-index 50, `height: 3px`, `background: transparent` with inner span filled by `--accent` color, width scales as lesson index / total lessons. Smooth `width 220ms ease` transition.
- **Topbar**: sticky `top: 0`, `z-index: 40`, `height: 52px`, `background: var(--topbar)`, `border-bottom: 1px solid var(--border)`, `backdrop-filter: saturate(1.4) blur(8px)`. Contains brand, breadcrumb, and 3 icon buttons (direction, theme, tweaks).
- **Sidebar**: `width: 280px`, sticky `top: 52px`, `height: calc(100vh - 52px)`, scrollable, `border-right: 1px solid var(--border)`. Padding `28px 22px 40px`. Renders lesson clusters with nested lesson list.
- **Degraded banner**: conditional, renders only when `run_status == "degraded"`. Height 44px, orange-tinted background, warning copy + count pill.
- **Splitter**: `width: 10px`, positioned between narration and code, draggable, visual indicator `::::`, persistent drag range 28–72% of content width.
- **Narration panel**: takes 50% (default) or custom `--narr-frac` proportion of remaining width. `padding: 56px 48px`, `background: var(--bg)` (lightest surface), `border-right: 1px solid var(--border)`.
- **Code panel**: takes remaining width after narration + splitter. `position: sticky top: 52px`, `height: calc(100vh - 52px)`, `overflow-y: auto`, `background: var(--surface)`, Pygments pre-rendered HTML.
- **Footer**: `height: 40px`, sticky `bottom: 0`, `background: var(--surface)`, `border-top: 1px solid var(--border)`, grid layout showing meta (commit, branch, cost, elapsed, confidence).

#### Mobile (<1024px)

- Sidebar hides; replaced by hamburger drawer (implementation: beyond this spec, but assumed to use similar TOC markup).
- Splitter hides.
- Narration and code stack vertically (`flex-direction: column`).
- Topbar remains sticky at top, footer becomes non-sticky or collapses.

### §3.2 Components (10 core)

#### 1. Progress bar

- **Fixed**, `top: 0`, `left: 0`, `right: 0`, `z-index: 50`, `height: 3px`.
- **Background**: transparent (inherits page background).
- **Inner span** (the fill): `background: var(--accent)`, `width: (current_lesson_index / total_lessons) * 100%`.
- **Transition**: `width 220ms ease-out`.

#### 2. Topbar

- **Height**: 52px.
- **Background**: `var(--topbar)` (darkest surface per hierarchy rule).
- **Position**: sticky `top: 0`, z-index 40.
- **Border**: `border-bottom: 1px solid var(--border)`.
- **Backdrop**: `backdrop-filter: saturate(1.4) blur(8px)`.
- **Layout**: horizontal flex, `gap: 16px`, `padding: 0 24px`, items vertically centered.

**Contents:**
- **Brand square**: `22×22px`, `background: var(--ink)`, `color: var(--bg)`, `border-radius: 5px`, mono font, text "wf" (10px) stacked with "WiedunFlow" label (11px/600).
- **Breadcrumb**: flex 1, `font-size: 13px`, `color: var(--ink-dim)`, structure `owner/repo › cluster-label › lesson-num lesson-title`. Overflow ellipsis on narrow viewports.
- **3 icon buttons** (left-to-right): direction toggle (A|B, for prototype only; production omits), theme toggle (☾), tweaks panel toggle (⚙). Each: `32×32px`, `border: 1px solid var(--border)`, `border-radius: 7px`, 13px mono or icon.

#### 3. Sidebar (table of contents)

- **Width**: 280px, sticky `top: 52px`, `height: calc(100vh - 52px)`, scrollable overflow-y.
- **Padding**: `28px 22px 40px`.
- **Background**: `var(--panel)`.
- **Border**: `border-right: 1px solid var(--border)`.

**TOC structure:**
- **Repo header**: `font-size: 11px`, `font-weight: 600`, `letter-spacing: 0.12em`, `text-transform: uppercase`, `color: var(--ink-dim)`, `margin-bottom: 18px`.
- **Cluster** (repeated per cluster in manifest):
  - Cluster header: `kicker` (10.5px mono uppercase `var(--ink-dim)`) + label (13px/600 `var(--ink)`).
  - Description: 12px `var(--ink-dim)`, `line-height: 1.5`, `max-width: 220px`.
  - Lesson list: `gap: 2px`, nested flex column.
- **Lesson link**: grid layout `22px | 1fr | auto` with `gap: 10px`, `padding: 7px 8px`, `border-radius: 6px`.
  - `.num`: 11px mono, right-aligned, `var(--ink-dim)`, user-select none.
  - `.title`: 13px, `var(--ink-2)`, white-space nowrap, overflow ellipsis.
  - `.time`: 10.5px mono, `var(--ink-dim)` (e.g. "3m").
  - **States**:
    - default: `background: transparent`.
    - hover: `background: var(--panel)`, `color: var(--ink)`.
    - current (active lesson): `background: var(--panel)`, `color: var(--ink)`, `border: 1px solid var(--border)`.
    - done (past lesson): `color: var(--ink-dim)`, title `text-decoration: line-through 1px var(--border)`, `.num` replaced with `✓` icon (12px/600 `var(--accent)`).

#### 4. Narration column

- **Padding**: `56px 48px 80px`.
- **Background**: `var(--bg)` (lightest surface, ~20% closer to white than page background per hierarchy rule).
- **Border**: `border-right: 1px solid var(--border)`.
- **Max-width prose**: 62 characters (approximate).

**Lesson header:**
- **Kicker**: 12px uppercase, `letter-spacing: 0.08em`, `color: var(--ink-dim)`. Format: `Lesson NN / MM · cluster-label` (mono for numbers).
- **H1 (.lesson-title)**: `font-size: 38px`, `font-weight: 600`, `letter-spacing: -0.015em`, `color: var(--ink)`, `text-wrap: pretty`, `max-width: 22ch`.
- **Subtitle (.lesson-sub)**: 15px Inter, `color: var(--ink-dim)`, `max-width: 56ch`, `margin-bottom: 36px`.

**Meta row:**
- Layout: flex, `gap: 18px`, `font-size: 11px`, font mono, `color: var(--ink-dim)`.
- **Confidence pill**: 7px colored dot + text label. Colors per confidence tier (see Design tokens, §3.6).
- Content: confidence pill, estimated read time, word count, file path.
- Separator: `padding: 10px 0 24px`, `border-bottom: 1px solid var(--border)`, `margin-bottom: 32px`.

**Narration body (.narration-body):**
- `max-width: 62ch`, `font-size: 16.5px`, `line-height: 1.72`, `color: var(--ink-2)`, `text-wrap: pretty`.
- Paragraph spacing: `margin-bottom: 1.5em`.

**Inline code:**
- Font: JetBrains Mono, `font-size: 0.88em`, `background: var(--surface)`, `padding: 1px 6px`, `border-radius: 4px`, `border: 1px solid var(--border)`.

**Emphasis (.em):**
- `color: var(--ink)`, `font-style: italic`.

**Up-next card** (at end of lesson body):
- `margin-top: 42px`, `border: 1px solid var(--border)`, `border-radius: 10px`, `padding: 22px 24px`, `background: var(--panel)`, `max-width: 62ch`.
- Label: "Up next · cluster-label" (10.5px mono uppercase `var(--ink-dim)`).
- Title: 20px/600 `var(--ink)`.
- Subtitle: 13px `var(--ink-dim)`.
- Button: `background: var(--ink)`, `color: var(--bg)`, `font-size: 13px`, `font-weight: 500`, `padding: 9px 14px`, `border-radius: 7px`, copy `Continue → NN`.

**Prev/Next navigation** (at bottom of narration):
- Layout: grid `1fr / 1fr` (two equal columns), `gap: 14px`, `max-width: 62ch`.
- Card style: `padding: 14px 16px`, `border: 1px solid var(--border)`, `border-radius: 10px`, `background: var(--panel)`.
- Hover: `border-color: var(--ink-2)`, `color: var(--ink)`.
- Content: `.dir` (11px mono uppercase letter-spacing 0.06em `var(--ink-dim)`) + `.ttl` (14px/500 `var(--ink)`).
- Disabled state: `opacity: 0.35`, `pointer-events: none`.

#### 5. Splitter

- **Width**: 10px, positioned absolutely between narration and code.
- **Draggable**: Pointer Events API (`pointerdown/pointermove/pointerup`) — unified mouse and touch handling.
- **Visual state**:
  - Default: `background: var(--border)`, width 1px centered with invisible padding for easy target.
  - Hover: width 2px, `background: var(--accent)`.
  - Dragging: `body.classList.add('is-resizing')` (sets cursor + disables pointer events on children).
- **Drag range**: 28%–72% of content width, enforced via `clamp(0.28, custom_frac, 0.72)`.
- **Persistence**: current position written to `localStorage` key `wiedunflow:tweak:narr-frac:v2` as a float.
- **Touch**: same handlers as mouse, using `clientX` on both `TouchEvent` and `MouseEvent`.

#### 6. Code panel

- **Position**: sticky `top: 52px`, `height: calc(100vh - 52px)`, `flex-direction: column`, `background: var(--surface)`.
- **Overflow**: `overflow-y: auto`.

**Header (.codepanel-header):**
- `padding: 14px 22px`, `background: var(--surface)`, `border-bottom: 1px solid var(--border)`.
- **File icon**: 14×14px CSS-drawn (outlined rectangle with 3 horizontal lines), `color: var(--ink-dim)`.
- **File path**: `directory/` (mono, `var(--ink-dim)`) + `filename` (mono, `var(--ink)`/500).
- **Right-aligned**: "python · NN lines shown" (11px mono `var(--ink-dim)`).

**Body (.codepanel-body):**
- `flex: 1`, `overflow-y: auto`, `padding: 18px 0 40px`.
- Pre-rendered Pygments HTML with tokenized spans.

**Code rows (.code .row):**
- Grid layout: `54px | 1fr` (line number column | content column).
- `font-size: 13px`, `line-height: 1.7`, font-family `JetBrains Mono`.
- **Line number (.ln)**: right-aligned, `color: var(--ink-dim)`, `padding-right: 16px`, `opacity: 0.7`, `user-select: none`.
- **Content (.ct)**: `padding-right: 20px`, `white-space: pre-wrap`.
- **Highlighted row (.row.hl)**: `background: var(--hl)`, `box-shadow: inset 3px 0 0 0 var(--hl-line)` (left accent bar).

**Syntax token classes** (produced by Pygments during render):
| Class | Element | Light color | Dark color |
|-------|---------|-------------|-----------|
| `.tok-kw` | Keyword | `oklch(0.55 0.15 300)` | `oklch(0.78 0.14 310)` |
| `.tok-str` | String | `oklch(0.50 0.13 145)` | `oklch(0.78 0.14 140)` |
| `.tok-com` | Comment | `var(--ink-dim)` italic | `var(--ink-dim)` italic |
| `.tok-fn` | Function call | `oklch(0.55 0.15 240)` | `oklch(0.78 0.14 235)` |
| `.tok-cls` | Class/type | `oklch(0.55 0.16 40)` | `oklch(0.78 0.14 55)` |
| `.tok-num` | Number | `oklch(0.55 0.16 30)` | `oklch(0.78 0.14 40)` |

#### 7. Footer

- **Height**: 40px.
- **Position**: sticky `bottom: 0`, z-index 10.
- **Background**: `var(--surface)`.
- **Border**: `border-top: 1px solid var(--border)`.
- **Padding**: `12px 56px`.

**Layout:**
- Grid: `1fr auto`.
- Left column: flex row, `gap: 6px 18px`, `font-size: 12px` mono, `color: var(--ink-dim)`. Each meta pair: `<label>: value` (label + value in separate spans).
- Content: commit hash, branch, generated-at timestamp, confidence pill, cost (haiku + opus breakdown), elapsed (Xm Ys).
- Right column: "WiedunFlow vX.X.X · Apache 2.0 — offline" text (11px mono `var(--ink-dim)`).

#### 8. Degraded banner (conditional)

Renders when `run_status == "degraded"`.

- **Height**: 44px.
- **Background**: `oklch(0.94 0.10 40)` (light) / `oklch(0.30 0.10 35)` (dark).
- **Text color**: `oklch(0.35 0.16 35)` (light) / `oklch(0.82 0.14 45)` (dark).
- **Border**: `border-bottom: 1px solid oklch(0.82 0.14 40)` (light) / `oklch(0.40 0.12 35)` (dark).
- **Padding**: `12px 56px`.
- **Layout**: flex, `gap: 10px`, items centered.

**Copy:** "DEGRADED run — N of M lessons were skipped due to grounding failures. The tutorial is still usable; skipped sections are flagged inline."

**Count pill**: mono, tinted background matching banner, displays `N skipped`.

#### 9. Skipped-lesson placeholder (per-lesson)

Renders inline above `.narration-body` when `lesson.status == "skipped"`.

- **Border**: `1px dashed var(--border)`.
- **Border-radius**: 10px.
- **Padding**: `22px 24px`.
- **Background**: diagonal hatching `repeating-linear-gradient(45deg, transparent 0 10px, color-mix(in oklab, var(--border) 60%, transparent) 10px 11px)`.
- **Tag "SKIPPED"**: 10.5px mono uppercase, color tinted orange (light) / amber (dark).
- **Copy**: "This lesson was skipped — [N] unresolved symbol references could not be grounded against the codebase. See the source file for details: `<path>`."

#### 10. Tweaks panel

- **Position**: fixed bottom-right, `right: 20px`, `bottom: 20px`, z-index 60.
- **Dimensions**: 300px wide, auto height.
- **Background**: `var(--panel)`.
- **Border**: `1px solid var(--border)`.
- **Border-radius**: 12px.
- **Padding**: 16px 18px.
- **Shadow**: `0 20px 40px -20px rgba(0, 0, 0, 0.25)`.
- **Hidden by default**; toggled by `⚙` button (topbar) and by URL hash `?edit_mode=1` (prototype only).

**Controls** (each row = label + segmented control):
- **Label**: 11px uppercase, `letter-spacing: 0.06em`, `color: var(--ink-dim)`, `margin-bottom: 8px`.
- **Segmented control**: `display: inline-flex`, `width: 100%`, `border: 1px solid var(--border)`, `border-radius: 7px`, `padding: 2px`, `gap: 2px`, `background: var(--bg)`.
- **Buttons**: `flex: 1`, `padding: 6px 8px`, `border-radius: 5px`, 12px Inter, `color: var(--ink-2)`. Active (`.on`): `background: var(--ink)`, `color: var(--bg)`.

**Production controls** (shipped):
- **Theme**: light / dark

**Prototype-only controls** (removed before shipping):
- Direction, palette, body font, confidence tier, degraded toggle.

### §3.3 Navigation

- **Click TOC lesson**: jump to lesson, update `location.hash = "#lesson-<id>"`, `window.scrollTo({top: 0, behavior: 'smooth'})`.
- **Arrow keys** (when focus outside input): `ArrowLeft` → previous lesson, `ArrowRight` → next lesson.
- **Prev/Next buttons** in narration: same as arrow keys.
- **Up-next "Continue"**: same as ArrowRight.
- **Deep link**: on page load, parse `location.hash` with regex `#lesson-(.+)$`; if matching lesson exists, open it.
- **Persistence**: write current lesson id to `localStorage` key `wiedunflow:<repo>:last-lesson`. Read on page load; default to first lesson if not found.

### §3.4 Splitter interaction

- **Mousedown/touchstart** on splitter → `dragging = true`, `body.classList.add('is-resizing')`.
- **Mousemove/touchmove**: calculate `clientX` relative to content rect, compute `frac = clamp(0.28, x / width, 0.72)`, apply `document.documentElement.style.setProperty('--narr-frac', frac)`, position splitter at `frac * 100%`.
- **Mouseup/touchend**: `dragging = false`, `body.classList.remove('is-resizing')`.
- **On window resize**: re-read `--narr-frac` and reposition splitter.
- **Persistence**: write `frac` to `localStorage` key `wiedunflow:tweak:narr-frac:v2` on drag end.

### §3.5 State management (localStorage)

All keys prefixed `wiedunflow:` to avoid collision with other apps.

| Key | Value type | Default | When set | Notes |
|-----|------------|---------|----------|-------|
| `wiedunflow:<repo>:last-lesson` | string (lesson id) | first lesson | on lesson change | Persists across page reloads |
| `wiedunflow:tweak:theme:v2` | `"light"` \| `"dark"` | `"light"` | on theme toggle | Maps to `[data-theme=...]` on `<html>` |
| `wiedunflow:tweak:narr-frac:v2` | float in [0.28, 0.72] | 0.5 | on splitter drag end | Applied as CSS custom property `--narr-frac` |

**Not persisted in production** (prototype-only):
- Palette (`wiedunflow:tweak:palette:v2`) — fixed to A1 Paper.
- Direction (`wiedunflow:tweak:dir:v2`) — fixed to A.
- Body font (`wiedunflow:tweak:font:v2`) — fixed to Inter.
- Confidence (`wiedunflow:tweak:conf:v2`) — driven by manifest.
- Degraded (`wiedunflow:tweak:deg:v2`) — driven by manifest.

### §3.6 JSON data shape

Three `<script type="application/json">` blocks injected by Jinja2 at build time:

```javascript
TUTORIAL_META = {
  repo: string,                  // e.g. "modelcontextprotocol/python-sdk"
  sha: string,                   // commit hash
  branch: string,
  generated_at: ISO 8601 string,
  wiedunflow_version: string,     // e.g. "0.1.0"
  run_status: "ok" | "degraded", // "ok" or "degraded" (failures abort before render)
  total_lessons: number,
  skipped_count: number,         // 0 for "ok", ≥1 for "degraded"
  symbol_coverage: number,       // percent (0-100)
  cost_haiku_usd: number,
  cost_opus_usd: number,
  elapsed_seconds: number,
}

TUTORIAL_CLUSTERS = [
  {
    id: string,
    label: string,
    kicker: string,              // "Stage 1" style
    description: string,
    lesson_count: number,
  },
  ...
]

TUTORIAL_LESSONS = [
  {
    id: string,                  // unique within tutorial
    cluster_id: string,          // references TUTORIAL_CLUSTERS[].id
    title: string,
    subtitle: string,
    read_time_minutes: number,
    word_count: number,
    confidence: "HIGH" | "MEDIUM" | "LOW",
    status: "ok" | "skipped",

    narration: [
      { kind: "p", text: string },  // HTML-safe; <code> and <em> allowed inline
      // more paragraph objects...
    ],

    code: {
      file: string,              // e.g. "src/client/models.py"
      lang: string,              // "python" (for display)
      highlight: number[],       // 1-indexed line numbers to highlight
      lines: string[],           // plain-text source lines; will be tokenized by Pygments at render time
    },
  },
  ...
]
```

### §3.7 Design tokens

#### Spacing scale (px)

Informal, use consistently: `2, 4, 6, 7, 8, 10, 12, 14, 16, 18, 20, 22, 24, 28, 32, 36, 40, 42, 48, 56, 80`

#### Border radius (px)

- Pills, inline code: 4px
- Buttons, segmented controls: 6–7px
- Cards, navigation: 10px
- Tweaks panel: 12px

#### Typography

**Fonts (self-hosted WOFF2):**
- **Inter**: weights 400, 500, 600, 700. Used for body, headings, UI labels.
- **JetBrains Mono**: weights 400, 500, 600. Used for code, line numbers, metadata.
- **Fallbacks**: `ui-sans-serif, system-ui, -apple-system, Helvetica, Arial, sans-serif` (sans); `ui-monospace, SF Mono, Menlo, Consolas, monospace` (mono).

**Sizes and roles:**
| Size | Role | Weight | Line-height |
|------|------|--------|-------------|
| 38px | H1 (lesson title) | 600 | 1.1 |
| 24px | H2 (card title) | 600 | 1.25 |
| 18px | H3 (section) | 600 | 1.35 |
| 16.5px | Body prose | 400 | 1.72 |
| 15px | Lesson subtitle | 400 | 1.5 |
| 14px | UI medium | 500 | 1.4 |
| 13px | Sidebar lesson link | 400 | 1.4 |
| 13px | Code font | 400 | 1.6 |
| 12.5px | Breadcrumb | 400 | 1 |
| 12px | Meta row | 400 | 1.4 |
| 11px | UI small | 500 | 1.4 |
| 10.5px | UI micro (kicker, tag) | 600 | 1 |

#### A1 Paper light palette

CSS custom properties defined in `:root`:

```css
--bg:        oklch(0.97 0.004 100);     /* narration bg, lightest */
--panel:     oklch(0.93 0.006 100);     /* sidebar, tweaks, cards */
--surface:   oklch(0.89 0.008 100);     /* code bg, code panel */
--topbar:    oklch(0.22 0.01 250);      /* darkest surface, header */

--ink:       oklch(0.18 0.01 250);      /* body text */
--ink-2:     oklch(0.31 0.01 250);      /* secondary text */
--ink-dim:   oklch(0.50 0.01 250);      /* tertiary, metadata */

--accent:    oklch(0.55 0.18 250);      /* links, progress, active */
--border:    oklch(0.82 0.006 100);     /* dividers, light stroke */
--border-2:  oklch(0.77 0.008 100);     /* secondary border */

--code-bg:   oklch(0.91 0.008 100);     /* inline code background */
--hl:        oklch(0.87 0.006 100);     /* highlighted code row bg */
--hl-line:   oklch(0.35 0.01 250);      /* highlighted row left bar */
```

#### A1 Paper dark palette

Apply via `[data-theme=dark]`:

```css
--bg:        oklch(0.14 0.01 250);
--panel:     oklch(0.18 0.01 250);
--surface:   oklch(0.22 0.01 250);
--topbar:    oklch(0.08 0.01 250);

--ink:       oklch(0.92 0.01 250);
--ink-2:     oklch(0.77 0.01 250);
--ink-dim:   oklch(0.65 0.01 250);

--accent:    oklch(0.55 0.18 250);      /* same as light */
--border:    oklch(0.27 0.01 250);
--border-2:  oklch(0.19 0.01 250);

--code-bg:   oklch(0.11 0.01 250);
--hl:        oklch(0.20 0.01 250);
--hl-line:   oklch(0.70 0.01 250);
```

#### Semantic color tokens

**Confidence pills** (dot color + background):
| Tier | Light background | Dark background | Dot color |
|------|------------------|-----------------|-----------|
| HIGH | `oklch(0.93 0.08 145)` | `oklch(0.28 0.08 145)` | `oklch(0.65 0.16 145)` |
| MEDIUM | `oklch(0.93 0.09 80)` | `oklch(0.30 0.09 75)` | `oklch(0.75 0.15 75)` |
| LOW | `oklch(0.93 0.08 30)` | `oklch(0.30 0.09 30)` | `oklch(0.60 0.18 25)` |

#### Shadows

- Cards, buttons: `0 1px 3px rgba(0, 0, 0, 0.08), 0 1px 2px rgba(0, 0, 0, 0.04)`
- Tweaks panel: `0 20px 40px -20px rgba(0, 0, 0, 0.25)`
- Highlighted code row: `inset 3px 0 0 0 var(--hl-line)` (left accent bar, not a drop shadow)
- Topbar: `0 1px 0 var(--border)`

#### Hierarchy rule (non-negotiable)

1. **Topbar is the darkest surface** in both light and dark modes.
2. **Sidebar, page bg, code panel** are mid-tone.
3. **Narration** is the lightest — it must visibly lift off the page. In light mode, narration is ~20% closer to white than the page background.

Any palette change must pass this sanity check.

### §3.8 Assets

**Fonts:**
- Inter (OFL) — weights 400, 500, 600, 700, self-hosted as WOFF2 in `src/wiedunflow/renderer/fonts/`.
- JetBrains Mono (OFL) — weights 400, 500, 600, self-hosted as WOFF2 in same directory.
- Fallbacks to system stack if files are missing.

**Icons:**
- Brand "cg" square: CSS-drawn (pseudo-element `::before` with solid background + text).
- Code-panel file icon: CSS-drawn (pseudo-element with box-shadow grid).
- No SVG files, no icon fonts.

**Shipped in production:**
- A1 Paper palette only.
- Inter body font only.
- Light and dark themes.

---

## §4. CLI — complete specification

### §4.1 Output structure

Every `wiedun-flow init <repo>` run produces output in this order:

1. **Invocation line** — shell echoes the command (not printed by CLI).
2. **Version banner** — dim: `WiedunFlow 0.1.0 · claude-haiku-4-5 + claude-opus-4-7`.
3. **Preflight section** — five checks (git, python, API key, repo, file count).
4. **Cost gate** — boxed estimate + blocking prompt `Proceed? [y/N]`.
5. **Seven stages** — `[N/7] <Name>`, indented detail lines, stage completion summary.
6. **Run report** — framed card with status, lessons, files, cost, elapsed, final link.
7. **Fresh shell prompt** — blinking caret on new line.

### §4.2 Version banner

One line, dim tone (ANSI 8 / bright black):

```
WiedunFlow 0.1.0 · claude-haiku-4-5 + claude-opus-4-7
```

### §4.3 Preflight section

Five checks, each on its own line, indented 2 spaces, good tone (ANSI 2 / green):

```
  ✓ git available (git version 2.43.0)
  ✓ python 3.11.9
  ✓ ANTHROPIC_API_KEY present
  ✓ target is a public Python repo
  ✓ 47 python files · 87 KLOC · 412 top-level symbols
```

### §4.4 Cost gate

Boxed panel using `rich.panel.Panel(box=rich.box.HEAVY)`:

```
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ ESTIMATED COST                                           ┃
┃━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ ┃
┃ Model      Stage                        Est. tokens  Cost ┃
┃ haiku      stages 1-4 (analyse/cluster)     ~410 000  $0.41 ┃
┃ opus       stages 5-6 (narrate/ground)      ~280 000  $1.87 ┃
┃ ───────────────────────────────────────────────────────── ┃
┃ TOTAL                                       ~690 000  $2.28 ┃
┃                                                            ┃
┃ Runtime est. 18-26 min · 12 lessons across 4 clusters   ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

Proceed? [y/N]
```

**Logic:**
- `[y/N]` — default is No.
- Accept: `y`, `yes` (case-insensitive).
- Reject: anything else (including empty `<Enter>`, `n`, `no`, Ctrl+C).

**On yes:** continue to stage 1.

**On no:** print `aborted by user. no API calls were made.` + final cost line and exit 0.

### §4.5 Stages (7 ordered)

Each stage prints:
1. Header: `[N/7] <Name>` (accent tone, ANSI 4 / blue).
2. Detail lines indented 5 spaces (default tone).
3. Stage completion: `  ✓ done · <summary>` (good tone, ANSI 2 / green).

**Stage 1: Clone**
```
[1/7] Clone
     cloning modelcontextprotocol/python-sdk@abc1234…
     47 python files · 87 KLOC
     ✓ done · elapsed 1:23
```

**Stage 2: Static analyse (Jedi)**
```
[2/7] Static analyse (Jedi)
     [1/47] analysing src/client/models.py
     [2/47] analysing src/client/session.py
     …
     [47/47] analysing tests/integration_test.py
     symbol resolution 87% · 412 symbols, 352 references linked
     ✓ done · elapsed 4:11
```

**Stage 3: Concept clustering · claude-haiku-4-5**
```
[3/7] Concept clustering · claude-haiku-4-5
     tokens: 98 234 in · 2 856 out
     · Session management (4 lessons)
     · Request/response models (3 lessons)
     · Tool calling (3 lessons)
     · Resource lifecycle (2 lessons)
     cost: $0.15 · cumulative $0.15 · elapsed 2:45
     ✓ done · 4 clusters identified
```

**Stage 4: Lesson outlining · claude-haiku-4-5**
```
[4/7] Lesson outlining · claude-haiku-4-5
     tokens: 142 567 in · 4 234 out
     ✓ Session management (4 lessons)
     ✓ Request/response models (3 lessons)
     ✓ Tool calling (3 lessons)
     ✓ Resource lifecycle (2 lessons)
     cost: $0.18 · cumulative $0.33 · elapsed 3:21
     ✓ done · manifest ready (12 lessons)
```

**Stage 5: Narration · claude-opus-4-7**
```
[5/7] Narration · claude-opus-4-7
     tokens: 456 123 in · 67 890 out
     [1/12] narrating 'Session basics: initialization and context'
     [2/12] narrating 'Sessions: threading safety and scoping'
     [3/12] narrating 'Sessions: cleanup and context managers'
     …
     [12/12] narrating 'Resource lifecycle: weak references and finalization'
     cost: $1.56 · cumulative $1.89 · elapsed 8:45
     ✓ done · 12 lessons narrated
```

**Stage 6: Grounding against AST**
```
[6/7] Grounding against AST
     checking all symbol references against Jedi index …
     ✓ lesson 1 (high confidence, 100% refs grounded)
     ✓ lesson 2 (high confidence, 100% refs grounded)
     ✓ lesson 3 (medium confidence, 96% refs grounded)
     ✓ lesson 4 (high confidence, 100% refs grounded)
     …
     ⚠ lesson 7 (low confidence, 78% refs grounded) — 3 unresolved
     ⚠ lesson 9 (low confidence, 81% refs grounded) — 2 unresolved
     cost: $0.35 · cumulative $2.24 · elapsed 2:34
     ✓ done · 12 lessons grounded, 0 skipped
```

Or on degraded run:

```
[6/7] Grounding against AST
     checking all symbol references against Jedi index …
     ✓ lesson 1 (high confidence, 100% refs grounded)
     ✓ lesson 2 (high confidence, 100% refs grounded)
     ! lesson 5: 4 unresolved references in src/advanced/reflection.py
     ! lesson 7: 3 unresolved references in src/meta/descriptor_protocol.py
     ! lesson 9: 2 unresolved references in src/advanced/reflection.py
     ! lesson 11: 5 unresolved references in src/meta/dynamic_classes.py
     ⚠ degraded run: 4 of 12 lessons will be marked SKIPPED
     cost: $0.35 · cumulative $2.24 · elapsed 2:47
     ✓ done · 8 lessons grounded · 4 skipped
```

**Stage 7: Render + finalize**
```
[7/7] Render + finalize
     rendering tutorial.html with Jinja2 + Pygments…
     inlining CSS…
     inlining fonts (Inter, JetBrains Mono)…
     inlining JavaScript (interactions, state management)…
     inlining JSON manifest (lessons, clusters, metadata)…
     final size: 2.4 MB
     total cost: $2.28 (haiku $0.41 · opus $1.87) · elapsed 0:42
     ✓ done · tutorial ready
```

### §4.5.1 Animation strategy (Sprint 8 / v0.2.0)

The §4.5 stage copy is silent on **how** per-file (`[42/47] analysing src/foo.py`)
and per-lesson (`[1/12] narrating '…'`) lines should evolve over time. Sprint 8
binds two distinct animation modes to the two stage classes:

| Stage | Mode | Rationale |
|-------|------|-----------|
| Stage 2 (Analysis / Jedi) | **Replace-line** (`StageReporter.progress_line`) | Mass scan; no individual file is interesting on its own. One updating row keeps the transcript compact. The terminal shows a single `[N/M] analysing …` line that updates in place. |
| Stage 6 (Generation / narration) | **Scrolling event log** (`StageReporter.lesson_event`) | Each lesson costs measurable money and time. Keeping every `[N/12] narrating '<title>'` line in the transcript makes failures auditable post-hoc. New events append below. |
| Stages 1, 3, 4, 7 | **Static** (`StageReporter.detail`) | Short stages with no per-item progress. Header + ✓ done is enough. |
| Stages 3, 4, 5, 6 (LLM stages) | **Live counters footer** (`StageReporter.tick_counters`) | The §4.6 footer renders below the active body region; it pins running cost / tokens / elapsed and refreshes on every LLM event. |

Implementation lives in `src/wiedunflow/cli/stage_reporter.py` (orchestrator
side) and `src/wiedunflow/cli/output.py` (Rich Live region helpers). The Live
region is started lazily on the first `progress_line` / `lesson_event` /
`tick_counters` call and closed by `stage_done`. On non-TTY consoles `rich.live.Live`
falls back to per-update prints — CI and `--log-format=json` pipes still
capture every state, just without the animated overdraw.

Stages 1 and 2 names (`Ingestion`, `Analysis`) currently differ from the
§4.5 spec text (which says `Clone`, `Static analyse (Jedi)`). The spec text
describes a v0.5+ pipeline where ingestion will fetch URLs and where Stage 4
(`Lesson outlining`) will be split from `Concept clustering`. Reconciliation
is tracked for a later sprint; the current implementation matches CLAUDE.md
§PIPELINE verbatim.

### §4.6 Live counters (during LLM stages)

While stages 3, 4, 5, 6 are running (calling an LLM), display a footer or periodic update showing:

```
elapsed 2:45 · cost $0.15 · tokens: 98 234 in · 2 856 out
```

Update per chunk or per response. Implementation: `rich.live.Live` footer or plain periodic redraw.

### §4.7 Color roles

Use these 8 roles consistently. Map to ANSI/terminal colors:

| Role | Used for | ANSI | Hex (Modern light) |
|------|----------|------|-------------------|
| default | regular text | default FG | inherit |
| dim | per-file progress, cost summaries, metadata | 8 (bright black) | `#868a93` |
| good | `✓` ticks, success messages | 2 (green) | `#2d9f61` |
| warn | `⚠` grounding warnings, backoff notices | 3 (yellow) | `#d89f13` |
| err | `✗` failures, network errors | 1 (red) | `#c23d1b` |
| accent | stage headers `[N/7]`, section titles | 4 (blue) | `#3d5ee7` |
| link | final tutorial path | 6 (cyan), underlined | `#00aaaa` |
| prompt | shell `$` | default FG, `$` green | — |

**Do not invent new roles. Bold only for links.**

### §4.8 Error scenarios

#### Happy path

12 lessons narrated, 0 grounding failures, all API calls succeed.

```
[6/7] Grounding against AST
     …
     ✓ done · 12 lessons grounded, 0 skipped

[7/7] Render + finalize
     …
     ✓ done · tutorial ready

┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ ✓ success                                             ┃
┣━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┫
┃ lessons    12 of 12 narrated                          ┃
┃ files      47 python files · 87% symbol coverage      ┃
┃ elapsed    18:43                                      ┃
┃ cost       $2.28 (haiku $0.41 · opus $1.87)           ┃
┃ tokens     558 860 in · 114 222 out                    ┃
┃ open       file:///Users/.../tutorial.html            ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
```

Report status: **success**, left border color: green.

#### Degraded run

Grounding (stage 6) has unresolved symbol references in N lessons. Pipeline does **not abort** — it continues to stage 7 and sets `run_status: "degraded"` in the manifest.

```
[6/7] Grounding against AST
     …
     ! lesson 5: 4 unresolved references in src/advanced/reflection.py
     ! lesson 7: 3 unresolved references in src/meta/descriptor_protocol.py
     ! lesson 9: 2 unresolved references in src/advanced/reflection.py
     ! lesson 11: 5 unresolved references in src/meta/dynamic_classes.py
     ⚠ degraded run: 4 of 12 lessons will be marked SKIPPED
     ✓ done · 8 lessons grounded · 4 skipped

[7/7] Render + finalize
     …
     ✓ done · tutorial ready

┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ ⚠ degraded                                            ┃
┣━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┫
┃ lessons    8 of 12 narrated · 4 skipped               ┃
┃ files      47 python files · 87% symbol coverage      ┃
┃ elapsed    19:12                                      ┃
┃ cost       $2.28 (haiku $0.41 · opus $1.87)           ┃
┃ tokens     558 860 in · 114 222 out                    ┃
┃ skipped    lesson-5, lesson-7, lesson-9, lesson-11    ┃
┃ open       file:///Users/.../tutorial.html            ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
```

Report status: **degraded**, left border color: amber. Tutorial renders with degraded banner + per-lesson skip placeholders.

#### Rate limited (429)

Anthropic returns `RateLimitError`. Absorb with exponential backoff (2s, 4s, 8s, …, max 5 attempts):

```
[5/7] Narration · claude-opus-4-7
     tokens: 456 123 in · 67 890 out
     [1/12] narrating 'Session basics: initialization and context'
     [2/12] narrating 'Sessions: threading safety and scoping'
     [3/12] narrating 'Sessions: cleanup and context managers'
     ⚠ HTTP 429 rate_limit_error (tokens-per-minute)
     ⟳ backoff 2s (attempt 1/5)
     [4/12] narrating 'Cleanup: finally blocks and context exit'
     ✓ resumed · rate-limit window cleared
     [5/12] narrating 'Context variables and local storage'
     …
     cost: $1.56 · cumulative $1.89 · elapsed 10:15
     ✓ done · 12 lessons narrated (1 rate-limit retry, 2s total backoff)
```

Note in report: `note: "1 rate-limit retry absorbed (2s total backoff)"`.

#### Failed (unrecoverable)

Network stays down or non-retryable error after retries exhausted. Abort cleanly:

```
[5/7] Narration · claude-opus-4-7
     tokens: 456 123 in · 67 890 out
     [1/12] narrating 'Session basics: initialization and context'
     [2/12] narrating 'Sessions: threading safety and scoping'
     [3/12] narrating 'Sessions: cleanup and context managers'
     ✗ network error: ConnectionError (api.anthropic.com)
     ⟳ retry 1/3 in 2s
     ✗ network error: ConnectionError (api.anthropic.com)
     ⟳ retry 2/3 in 4s
     ✗ network error: ConnectionError (api.anthropic.com)
     ⚠ exhausted retries. aborting pipeline.

┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ ✗ failed                                              ┃
┣━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┫
┃ failed at  stage 5 (narration)                        ┃
┃ reason     network error: ConnectionError              ┃
┃ cost       $0.33 (haiku $0.41 · opus partial)          ┃
┃ elapsed    5:42                                       ┃
┃ cleanup    partial artefacts in ./wiedunflow-output/   ┃
┃ resume     wiedun-flow init --resume <run-id>           ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
```

Report status: **failed**, left border color: red. Retain partial artefacts in `./wiedunflow-output/.cache/` for `--resume`. Exit code 1.

#### Cost-gate abort

User types `n` or presses `<Enter>` at cost-gate prompt:

```
Proceed? [y/N]

aborted by user. no API calls were made.
total cost: $0.00 · elapsed 0:08
```

Exit code 0. No cached files, no `.wiedunflow-output` directory.

#### Ctrl+C mid-stage

User presses Ctrl+C while an LLM call is running:

```
[5/7] Narration · claude-opus-4-7
     [1/12] narrating 'Session basics: initialization and context'
     ✗ interrupted by user

┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ ✗ failed                                              ┃
┣━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┫
┃ failed at  stage 5 (narration)                        ┃
┃ reason     keyboard interrupt                         ┃
┃ cost       $0.12 (haiku $0.41 · opus partial)          ┃
┃ elapsed    2:15                                       ┃
┃ cleanup    partial artefacts in ./wiedunflow-output/   ┃
┃ resume     wiedun-flow init --resume <run-id>           ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
```

Report status: **failed**, reason: `keyboard interrupt`. Exit code 130.

### §4.9 Run report card

A framed card printed at the end of every run. Border color encodes status:
- **Green** for `success`
- **Amber** for `degraded`
- **Red** for `failed`

**Exact layout** (label : value rows):

| Field | Example | Always shown |
|-------|---------|---|
| (status emoji) | `✓`, `⚠`, `✗` | Yes |
| lessons | `12 of 12 narrated` or `8 of 12 narrated · 4 skipped` | Yes |
| files | `47 python files · 87% symbol coverage` | Yes (except on failed) |
| elapsed | `18:43` | Yes |
| cost | `$2.28 (haiku $0.41 · opus $1.87)` | Yes |
| tokens | `558 860 in · 114 222 out` | Yes (except on failed) |
| skipped | (list of lesson ids) | Only if degraded |
| failed at | (stage name) | Only if failed |
| reason | (error reason) | Only if failed |
| cleanup | `partial artefacts in ./wiedunflow-output/` | Only if failed |
| resume | `wiedun-flow init --resume <run-id>` | Only if failed |
| open | `file:///Users/.../tutorial.html` | Only if success or degraded |

### §4.10 Clickable tutorial link

After successful or degraded run, the tutorial path is printed as:

```
file:///Users/user/project/tutorial.html
```

On terminals that support hyperlinks (iTerm, modern VSCode terminal, Windows Terminal), this becomes a clickable link. Otherwise it is plain text — the user can copy-paste.

---

## §5. Menu mode (v0.4.0+)

**Triggered when**: user runs `wiedun-flow` without arguments in a TTY environment (`sys.stdin.isatty() and sys.stdout.isatty()`) and enters `main_menu_loop()` from `cli/menu.py`. Bypass mechanisms: running any subcommand (e.g., `wiedun-flow generate <repo>`, `wiedun-flow init`), non-TTY context (CI/pipes), or `WIEDUNFLOW_NO_MENU=1` env var.

### §5.1 Top-level menu

Seven-item menu displayed with arrow navigation (`↑↓ Enter Esc`):

```
WIEDUNFLOW v0.4.0+

┌─────────────────────────────────────┐
│ 1. Initialize config                │
│ 2. Generate tutorial                │
│ 3. Show config                      │
│ 4. Estimate cost                    │
│ 5. Resume last run                  │
│ 6. Help                             │
│ 7. Exit                             │
└─────────────────────────────────────┘
```

**Item 1: Initialize config** — equivalent to `wiedun-flow init <repo>`. Launches inline repo picker (3-source, patrz §5.2).

**Item 2: Generate tutorial** — opens 5-section sub-wizard (patrz §5.3).

**Item 3: Show config** — renders current `tutorial.config.yaml` as rich panel with syntax highlighting.

**Item 4: Estimate cost** — displays cost-gate panel (copy from §4.4) based on current config + repo file count.

**Item 5: Resume last run** — enabled only when `SQLiteCache.has_checkpoint(repo_abs)` returns true. Disabled (dimmed) otherwise. On selection, continues from last checkpoint (Stage N).

**Item 6: Help** — displays help text covering menu navigation and command overview.

**Item 7: Exit** — closes menu, returns to shell prompt.

### §5.2 Generate sub-wizard (5 sections)

Entered when user selects "Generate tutorial" from top-level menu.

**§5.2.1 Section 1: Repo + Output**

Three-source picker for repository path:
1. **Recent runs** — list of last 10 repo paths sorted by `.git/HEAD` mtime DESC, formatted as `[YYYY-MM-DD HH:MM] /path/to/repo`. Empty state: `"No recent runs found. Choose another source."`
2. **Discover in cwd** — auto-discover `.git/` repositories in current directory (max depth 1, no nesting). Skip hardcoded dirs (`node_modules`, `.venv`, `venv`, `__pycache__`, `dist`, `build`, `target`, `.tox`, `.idea`, `.vscode`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`). Respect `.gitignore` if present. Sort by mtime DESC, cap 20 results. Empty states: `"No git repositories found in current directory."` or `"All discovered repositories are ignored by .gitignore."`
3. **Type path manually** — prompt user for directory path, validate it contains `.git/` subdir. On failure, show error + re-prompt.

Back semantics: selecting "Back" returns to top-level menu.

**§5.2.2 Section 2: Provider + Models**

Dropdown to select LLM provider (Anthropic or OpenAI), then model picker.

**ModelCatalog port** (ADR-0013 D#11):
- Interface: `interfaces/model_catalog.py` Protocol with `list_models() -> list[str]` method.
- Adapters: `AnthropicModelCatalog` (via `anthropic.Anthropic().models.list()`) and `OpenAIModelCatalog` (via `openai.OpenAI().models.list()`).
- **OpenAI filter**: strips `ft:*` (fine-tuned models) and non-chat models (audio, realtime, image, tts, whisper, embedding, moderation, transcribe, dall-e, sora, codex, search, deep-research).
- **24h disk cache**: `~/.cache/wiedunflow/models-<provider>.json` (e.g., `models-anthropic.json`, `models-openai.json`).
- **Hardcoded fallback list**: activates only when API call fails (offline, missing key, rate limit, 5xx).
- **Express path**: if user has saved config, auto-fill provider + model and skip sections §3–§4, jumping directly to §5 (Summary + Launch).
- **OpenAI default models**: `gpt-5.4` (planning + narration) + `gpt-5.4-mini` (per-symbol describe). Per ADR-0015 (v0.7.0+, rate-limit relief + cost parity). Earlier versions: `gpt-4.1` (v0.4.0+) → `gpt-4o` (pre-v0.4.0).

**§5.2.3 Section 3: File Filters (optional)**

Dynamic add/edit/remove list manager for `exclude` and `include` patterns. Allows user to customize which files are analyzed. Skipped on express path.

**§5.2.4 Section 4: Limits + Audience (optional)**

Configurable settings:
- **max_lessons**: cap on total lessons (default from config, e.g., 30).
- **max_cost_usd**: hard limit on API spend (default from config, e.g., 10.0).
- **target_audience**: 5-level enum (`noob`, `junior`, `mid`, `senior`, `expert`), default `mid`. Narration adapts language and pacing to audience.

Skipped on express path.

**§5.2.5 Section 5: Summary + Launch**

Displays:
- **File count** from discovered repo.
- **Estimated lesson count** (heuristic from file count + symbol coverage).
- **Estimated cost** (blended from PricingCatalog, patrz §6).
- **Two buttons**: `Cancel` (returns to top-level menu) or `Launch` (begins 7-stage pipeline).

After Launch, the existing `rich.Live` 7-stage pipeline takes over terminal. On completion, menu loop redraws (returns to top-level menu).

### §5.3 Three-sink rule (ADR-0013 + ADR-0014 extension)

Architectural constraint for dependency isolation:

- **`import rich` ONLY in `cli/output.py`**: Stage reporter, panel rendering, live region management.
  - Test: `test_no_rich_outside_output.py` (parametrized Grep over all `.py` files).
- **`import questionary` ONLY in `cli/menu.py`**: Menu prompts, list navigation, input validation.
  - Test: `test_no_questionary_outside_menu.py`.
  - Exception: `cost_gate.py` receives `confirm_fn: Callable | None` parameter (dependency injection) instead of importing questionary directly.
- **`import httpx` ONLY in `adapters/litellm_pricing_catalog.py`**: HTTP fetch for live pricing.
  - Test: `test_no_httpx_outside_litellm_pricing.py`.
- **Plain `print()` in `cli/menu_banner.py`** and everywhere else for diagnostics/debugging (not user-facing UI prompts).

---

## §6. Pricing display (v0.5.0+)

**Objective**: Cost gate and pipeline use LIVE pricing from LiteLLM instead of hardcoded `MODEL_PRICES` dict. New models (e.g., `gpt-5.4-mini`, `claude-opus-4-8`) are automatically priced after LiteLLM publishes them—no WiedunFlow release required.

### §6.1 Architecture (ADR-0014)

**PricingCatalog Protocol** (`interfaces/pricing_catalog.py`):
```python
class PricingCatalog(Protocol):
    def blended_price_per_mtok(self, model_id: str) -> float | None:
        """
        Returns blended price in USD per million tokens.
        Blending formula: 0.6 * input_cost_per_token + 0.4 * output_cost_per_token
        Empirical split based on typical planning (input-heavy) + narration (output-heavy) split.
        Returns None if model not found (allows caller to chain fallbacks).
        Never raises exceptions on network failure or unknown models.
        """
```

### §6.2 Four adapters

**1. StaticPricingCatalog** (`adapters/static_pricing_catalog.py`)
- Backed by existing `cli/cost_estimator.MODEL_PRICES` dict.
- Leaf adapter: guarantees cost gate never returns `None` (no crash on unknown model).
- Hard-maintains ~50 popular models across Anthropic, OpenAI, and OSS endpoints.

**2. LiteLLMPricingCatalog** (`adapters/litellm_pricing_catalog.py`)
- Fetches from `https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json` (~3500 models).
- HTTP timeout: 3 seconds.
- Blending: `0.6 * input_cost_per_token + 0.4 * output_cost_per_token`, converted to USD/MTok.
- **Provider-prefix stripping**: Maps `openai/gpt-4.1` and `gpt-4.1` to same price (removes `anthropic/`, `openai/` prefix).
- Network failures (timeout, 5xx, 404) downgrades to empty dict per-query; caller chains fallback (no crash).

**3. CachedPricingCatalog** (`adapters/cached_pricing_catalog.py`)
- Decorator wrapping any upstream adapter (LiteLLM, Static, or Chained).
- **Cache location**: `~/.cache/wiedunflow/pricing-<provider>.json` (e.g., `pricing-litellm.json`).
- **TTL**: 24 hours (86400 seconds).
- On cache miss or expiry, fetches from upstream, stores result.

**4. ChainedPricingCatalog** (`adapters/cached_pricing_catalog.py`)
- Fallback chain: `[CachedPricingCatalog(LiteLLMPricingCatalog), StaticPricingCatalog]`.
- First non-`None` result wins.
- Guarantees availability: if LiteLLM fetch fails, StaticPricingCatalog always returns a price for known models.

### §6.3 Integration in cost gate

During `§4.4 Cost gate` render, the cost estimator calls `pricing_catalog.blended_price_per_mtok(model_id)` for each model. If live pricing is available (LiteLLM not rate-limited, not offline), uses it. If unavailable, falls back to static list. Cost gate renders successfully in both cases—no user-facing "offline" message.

---

## §7. Brand identity (v0.6.0+)

**Hard-cut rebrand on 2026-04-26**: CodeGuide → **WiedunFlow**. Zero aliases, zero migration shim. Reinstall required.

### §7.1 Etymology and messaging

- **"Wiedun"** — Old Polish for sage/wise one. Reflects the tool's role: it knows your code (via AST + call-graph analysis) and guides readers through it.
- **Brand promise**: "Turn code into a guided tour, instantly."

### §7.2 Nomenclature

All strings updated post-rebrand v0.6.0:

| Asset | Old (CodeGuide) | New (WiedunFlow) |
|-------|---|---|
| Package | `codeguide` | `wiedunflow` |
| CLI command | `codeguide` | `wiedun-flow` |
| ENV prefix | `CODEGUIDE_*` | `WIEDUNFLOW_*` |
| Cache dir | `~/.cache/codeguide/` | `~/.cache/wiedunflow/` |
| localStorage namespace | `codeguide:*` | `wiedunflow:*` (reserved; do not use for new keys) |
| Default output filename | `tutorial.html` | `wiedunflow-<repo>.html` |
| Per-repo state dir | `.codeguide/` | `.wiedunflow/` |
| GitHub org/repo | `codeguide-ai/codeguide` | `numikel/wiedunflow` |
| ASCII banner | (none) | `WIEDUNFLOW` (capital, displayed in TTY menu) |
| Brand color (accent) | (unchanged) | `oklch(0.55 0.18 250)` — accent blue, same as A1 Paper palette |

### §7.3 Footer in generated HTML

Generated `wiedunflow-<repo>.html` files now display in footer:
```
WiedunFlow vX.Y.Z · Apache 2.0 — offline
```

Previous: `CodeGuide vX.Y.Z · Apache 2.0 — offline`.

### §7.4 Documentation and messaging

- GitHub README: updated all references (package, command, paths, brand name).
- PyPI package: renamed to `wiedunflow`.
- All CLI help text, error messages, and banners use `WiedunFlow` (capital W, capital F).
- No legacy aliases in code or configuration — clean migration required.

---

## §8. Mapping to PRD functional requirements

This table links new FR-81..FR-90 (added in design review 2026-04-19) to ux-spec sections.

**Section shorthand convention** used throughout PRD and this document:
- `§CLI.*` → corresponds to section `§4` of this document (e.g., `§CLI.cost-gate` = `§4.4 Cost gate`)
- `§Tutorial.*` → corresponds to section `§3` of this document (e.g., `§Tutorial.tokens` = `§3.7 Design tokens`)
- `§Tutorial.components.*` → corresponds to named component entries in `§3.2 Components`

| FR | US | Section | Description |
|----|----|----|---|
| FR-81 | US-012, US-070 | §CLI.cost-gate | Cost gate boxed panel, blocking prompt, default No |
| FR-82 | US-071 | §CLI.stages | 7-stage exact copy, live counters, stage completion summaries |
| FR-83 | US-075 | §Tutorial.tokens | A1 Paper palette, dark theme, surface hierarchy |
| FR-84 | US-041, US-076 | §Tutorial.splitter | Resizable splitter 28–72% range, localStorage persistence |
| FR-85 | US-075 | §Tutorial.assets | Inter + JetBrains Mono WOFF2 self-hosted |
| FR-86 | US-077 | §Tutorial.tweaks-panel | Tweaks panel theme toggle (production), remove palette/direction/font controls |
| FR-87 | US-031, US-078 | §Tutorial.skipped-placeholder | Skipped lesson visual (diagonal hatching, orange tag, copy) |
| FR-88 | US-032, US-079 | §Tutorial.degraded-banner | Degraded banner (top of page, orange tint, N of M copy) |
| FR-89 | US-055, US-072 | §CLI.run-report | Run report framed card, status-colored border, all fields per scenario |
| FR-90 | US-054, US-073 | §CLI.error-scenarios.rate-limited | 429 backoff copy, retries, exponential backoff feedback |

---

## §9. Non-goals

The following are explicitly **out of scope** for MVP and require a new ADR if revisited:

- **Minimal CLI direction** — prototype exploration only, not shipped. Return to this in v2+ if user research justifies it.
- **Retro ASCII CLI direction** — prototype exploration only, not shipped.
- **A2 and A3 palettes** — prototype explorations only, not shipped. Warm/Editorial palettes require palette expansion decision.
- **Direction B ("editorial reader")** — prototype exploration only, not shipped. Narrative layout for text-first reading.
- **postMessage edit-mode integration** — prototype feature (Tweaks panel triggered externally). Not part of shipping product.
- **Scenario picker in CLI** — prototype scaffolding (used by `design/WiedunFlow CLI.html` to show different error paths). Not shipped.
- **i18n / multi-language output** — CLI and narration English-only in MVP. Localization deferred to v2+.

---

## §10. Changelog

```
2026-04-26 v0.2.0
  - Backfill §5 Menu mode (ADR-0013) — interactive TUI, 7-item top-level menu, 5-section Generate sub-wizard, ModelCatalog port, 24h model list cache.
  - Backfill §6 Pricing display (ADR-0014) — PricingCatalog Protocol, four adapters (Static/LiteLLM/Cached/Chained), httpx hard dep, 24h pricing cache, graceful network-failure fallback.
  - Backfill §7 Brand identity (v0.6.0+) — hard-cut rebrand CodeGuide → WiedunFlow, zero aliases, updated nomenclature (package, CLI, ENV, cache, localStorage, output filename, per-repo state).
  - Renumber old §5/§6/§7 → §8/§9/§10 (PRD mapping, Non-goals, Changelog).
  - Update header cross-references to ADR-0013 and ADR-0014.

2026-04-19 v0.1.0-draft
  - Initial version ported from wiedunflow-ux-skill reference READMEs.
  - Integrated ADR-0011 seven binary decisions.
  - Complete tutorial reader spec (layout, components, interactions, tokens).
  - Complete CLI spec (stages, cost gate, error scenarios, run report).
  - Mapping to PRD functional requirements (FR-81..FR-90).
```
