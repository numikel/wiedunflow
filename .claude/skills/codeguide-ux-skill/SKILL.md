---
name: codeguide-ux
description: Implement CodeGuide's user-facing surfaces — the `codeguide init` terminal experience and the generated `tutorial.html` reader. Use when building either the CLI output (preflight, cost gate, 7-stage pipeline, run report, errors) or the offline HTML tutorial (split-view reader with clustered TOC, resizable splitter, syntax-highlighted code panel). Both ship with the CodeGuide Python CLI and must match the bundled design references pixel-for-pixel.
---

# CodeGuide UX — implementation skill

CodeGuide has two user-facing surfaces. This skill describes both:

1. **The CLI** — what `codeguide init <repo>` prints to the user's terminal while a tutorial is being generated (preflight → cost gate → 7 stages → run report).
2. **The generated tutorial** — the single-file `tutorial.html` that CodeGuide writes to disk when the pipeline finishes successfully or degrades.

Both are spec'd here. The `reference/` folder contains hi-fi HTML prototypes of each — they are design references, not production code to paste in.

## ⚠️ Read this before you start

The prototypes in `reference/` are **browser-based mockups**. They exist solely to show what the finished surfaces should look and feel like — nothing more.

- **The CLI prototype (`reference/cli/design/`)** is HTML/CSS/JS that fakes a PowerShell terminal inside a browser tab. **The real CLI is a Python program that prints to stdout.** Do NOT build a web app. Do NOT port `cli-app.js` or `cli-styles.css` to anything. The only file from the CLI prototype you will reuse is `cli-session-data.js`, and only as a **copywriting reference** — the exact strings it prints are the exact strings the Python CLI should print.
- **The tutorial prototype (`reference/tutorial/design/`)** is a hi-fi version of the file that CodeGuide generates. That one IS shipped as a real HTML file on disk — but it is rendered by the Python pipeline (Jinja2 + Pygments), not served as a web app. You still do NOT ship the prototype JS/CSS directly; you recreate the design inside the Python renderer's templates.

TL;DR: **prototypes are for looking at, not for pasting.** Both deliverables are produced by the CodeGuide Python CLI — one prints to a terminal, the other writes an offline HTML file to disk.

## Approved design decisions

Do not re-explore these; they are settled.

### Tutorial reader (`tutorial.html`)
- **Palette:** A1 Paper only (dove white + graphite). No A2/A3.
- **Body font:** Inter (sans) only. No serif/mono body variants.
- **Direction A** only. No editorial (direction B) variant.
- **Hierarchy rule:** topbar is the **darkest** surface; narration is the **lightest** (~20% closer to white than the page bg) in both light and dark.

### CLI (`codeguide init`)
- **Direction: Modern.** Boxed sections for the cost gate, light color accents on status (✓ good, ⚠ warn, ✗ error, muted dim), unicode box-drawing for emphasis but not for everything. Reference: Claude Code, `opencode`, `uv`-era polish — not heavy TUI, not retro ASCII.
- **Chrome:** PowerShell (not macOS traffic lights) — menu bar + tab bar + window min/max/close + status bar. This sets the user's expectation that the tool runs natively on Windows/Mac/Linux.
- **Theme:** Dark default; light is supported (Tokyo-night-ish → Solarized-light-ish).
- **Interaction:** the cost gate is a real stdin prompt (`Proceed? [y/N]`) — not an auto-advance.
- The CLI prototype also ships "Minimal" and "Retro ASCII" directions as Tweaks; **both are design explorations and are NOT part of the shipped CLI.** Drop them.

## How to use this skill

### If you are implementing the tutorial reader
1. Read `reference/tutorial/README.md` — the complete spec: layout, per-component dimensions, state management, localStorage keys, expected JSON shape from the pipeline, and the implementation checklist.
2. Open the prototype: `reference/tutorial/design/Tutorial Reader.html`. Click lessons, drag the splitter, toggle theme, scroll code.
3. Read the prototype source: `reference/tutorial/design/tutorial-styles.css` (tokens), `tutorial-app.js` (interactions), `tutorial-data.js` (data shape).
4. Follow the implementation checklist at the bottom of `reference/tutorial/README.md`.

### If you are implementing the CLI

The CLI is a **Python program** (likely `click` + `rich`) that runs in the user's real terminal (PowerShell on Windows, iTerm/Terminal on macOS, any xterm on Linux). It has no GUI, no web view, no Electron shell. The PowerShell-style chrome in the prototype is just there to set the visual context of the mockup — the shipping CLI runs in whatever terminal the user already has open.

1. Read `reference/cli/README.md` — scenarios, stages, output format, cost-gate contract, error handling.
2. Open the prototype: `reference/cli/design/CodeGuide CLI.html` to **see** what the output looks like. Use the scenario picker (Happy / Degraded / Rate-limited / Failed / Cost-gate abort) and keep the Modern direction — that is the shipping look. **Do not copy the HTML/CSS/JS.**
3. Read `reference/cli/design/cli-session-data.js` — every line the CLI should print, in order, with exact copy, is encoded there as event scripts per scenario. **This is the only prototype file you reuse, and only for the strings.**
4. Port those strings into Python `rich` output — exact copy, exact spacing, exact prefixes (`✓ ⚠ ✗ ⟳ ·`), exact color roles. The prototype uses JS because it runs in a browser; the output format (what the user sees in their terminal) is what's shared.

## Constraints (both surfaces)

- **Offline.** Tutorial must work over `file://` with zero network requests. Self-host fonts as WOFF2.
- **No SPA framework** in the tutorial. Vanilla JS only, inlined.
- **Python renderer** uses Jinja2 + pre-rendered Pygments HTML for the tutorial; `rich` (or equivalent) for the CLI. No JS syntax highlighting.
- **Persist user state** in `localStorage` under `codeguide:*` keys (tutorial only).
- **Match pixel values** from the prototype CSS exactly. Hierarchy rules are non-negotiable.

## Constraints (CLI specifically)

- **Exact copy matters.** The line "4 clusters identified", the stage names `[N/7] <Name>`, the cumulative-cost summaries, the prompt text "Proceed? [y/N]" — copy all of these verbatim from the prototype's session scripts.
- **Cost is printed after every stage that calls an LLM** as `cost: $X.XX · cumulative $Y.YY · elapsed MM:SS`. File-progress is printed as `[N/total] <verb> <path>`.
- **Retries on 429 / network errors** use exponential backoff (2s, 4s, 8s, …). Print `⟳ backoff Ns (attempt K/5)` each time.
- **On degraded runs** (grounding failures), continue to stage 7 and emit the tutorial with a degraded banner — don't abort.
- **On failed runs** (network exhausted, unrecoverable error), emit a `run failed` report with a resume hint (`codeguide init --resume <run-id>`) and retain partial artefacts in `./codeguide-output/.cache`.
- **Cost-gate abort** (`n` at the prompt) must not make any API calls and must exit 0 with a clean "no money spent" message.

## What this skill does NOT cover

- The CodeGuide pipeline internals (Jedi analyser, clustering prompts, grounding loop, etc.) — see the project's own PRD and tech-stack docs.
- The CLI's Minimal and Retro ASCII directions — prototype-only.
- The tutorial's A2/A3 palettes or direction B — prototype-only.
- Any surface other than `codeguide init` output and `tutorial.html`.
