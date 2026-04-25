# ADR-0011: UX design system — palette, typography, CLI direction

- **Status**: Accepted
- **Date**: 2026-04-19
- **Deciders**: Michał Kamiński (product owner)
- **Related PRD**: v0.1.2-draft
- **Supersedes**: none

## Context

The CodeGuide UX design involves two user-facing surfaces: the CLI output (`codeguide init` terminal experience) and the generated `tutorial.html` offline reader. The skill `codeguide-ux-skill` contains high-fidelity prototypes exploring three CLI visual directions (Modern / Minimal / Retro ASCII) and three tutorial color palettes (A1 Paper / A2 / A3) with two narrative layouts (Direction A "clean technical" / Direction B "editorial reader").

Design review conducted 2026-04-19 evaluated all nine combinations (3 CLI × 3 palettes × 2 directions). The review resulted in a clear consensus: **one** canonical direction for each surface. Without this decision recorded as an ADR, future feature requests to "restore the warm palette" or "re-enable direction B" would have low cost of entry — despite all variants being deliberately evaluated and rejected. An ADR serves as a forcing function for any future reversal, requiring explicit user research justification and a superseding ADR.

## Decision

**Nine binary decisions are now final** (1-7 for MVP, 8-9 added in Sprint 8 /
v0.2.0):

1. **CLI direction**: Modern only. Minimal and Retro ASCII directions are dropped.
   - Rationale: Consistent with Claude Code, opencode, and uv aesthetic — modern Polish without heavy TUI or retro ASCII.

2. **Tutorial palette**: A1 Paper only (dove white + graphite in light mode; scaled dark mode). A2 and A3 are dropped.
   - Rationale: A1 Paper demonstrated highest contrast hierarchy and clarity in design review. A2 (warm beige) and A3 (high-saturation) reduce accessibility and increase CSS maintenance burden.

3. **Tutorial narrative direction**: Direction A ("clean technical") only. Direction B ("editorial reader") is dropped.
   - Rationale: Primary persona (developer exploring code for themselves, not reading narrative prose) favors task-oriented clean layout over editorial prose flow.

4. **Body font**: Inter sans-serif only. Serif and monospace body-font variants are dropped.
   - Rationale: Mono reserved exclusively for code blocks and UI micro accents; serif reduces clarity against code panels. Inter 16.5px at 1.72 line-height proved optimal in testing.

5. **Surface hierarchy**: Topbar is the darkest surface; narration panel is the lightest (~20% closer to white than page background). This constraint is non-negotiable.
   - Rationale: Establishes visual priority for reading flow: header < sidebar/code < narration prose. Validated across light and dark themes.

6. **Typography delivery**: Self-hosted fonts (Inter, JetBrains Mono) as WOFF2. No CDN, no external font requests.
   - Rationale: Satisfies FR-14 (offline-capable tutorial). Single HTTP request from a font CDN breaks the `file://` guarantee and introduces a network dependency in a tool designed for zero runtime coupling.

7. **Syntax highlighting**: Pre-rendered by Pygments during the Python build phase (stage 7). No runtime highlight.js or Prism.js in the browser.
   - Rationale: Avoids 15 KB+ syntax-highlighting JavaScript bundle. Tokenization happens in the renderer, HTML ships with pre-baked `tok-*` spans and `<style>` definitions. Zero runtime performance impact.

8. **CLI animation strategy** (added Sprint 8 / v0.2.0): Stage 2 (mass scan)
   uses a single replace-line live region; Stage 6 (narration) uses an
   append-only scrolling event log. Stages 3/4/5 (LLM stages) overlay a
   live counters footer (cost · tokens · elapsed) below the body. Stages
   1/7 are static (header + ✓ done only).
   - Rationale: Mass-scan progress (`[42/47] analysing src/foo.py`) is
     low-information per file — keeping a single updating row keeps the
     transcript compact. Narration events are paid LLM calls — keeping
     each `[N/12] narrating '<title>'` line in the transcript makes
     failures auditable post-hoc and matches the "$$$ accountability"
     mental model. Implementation: `rich.live.Live` (already in stack via
     `rich`) confined to `cli/output.py` per Sprint 5 #6 two-sink rule.
     No new dependency. Codified in `.ai/ux-spec.md §4.5.1`.

9. **Cost-gate prompt default** (added Sprint 8 / v0.2.0): The Stage-5
   cost-gate prompt is **on by default for TTY runs**. Bypass conditions
   are `--yes`, `--no-cost-prompt`, or non-TTY (`stdin.isatty() == False`).
   v0.1.0 only enforced `--max-cost` as a hard kill switch.
   - Rationale: Privacy and cost transparency are core product DNA
     (zero-telemetry, BYOK, Apache 2.0). A first-time `codeguide ./repo`
     run should pause and show "$2.28 OK?" rather than silently spending.
     Power users override with `--no-cost-prompt` once. Non-TTY auto-bypass
     keeps CI / pipes / `--log-format=json` flows unchanged.

## Consequences

### Positive

- **Single design system** reduces CSS maintenance and testing burden. Two color themes (light + dark) instead of 6–9 palette combinations.
- **Reproducible snapshots** — Playwright visual regression tests have 2 targets (light / dark) instead of 9. Pixel-perfect parity between skill prototype and product is verifiable.
- **Offline-first guarantee** — no external resources whatsoever. Fonts, styles, code, narration — all inlined in one HTML. Works over `file://` with no network calls.
- **Clearer product positioning** — "CodeGuide generates interactive tutorial.html" is sharper than "CodeGuide with customizable palettes and themes." MVP focuses on capability, not customization.

### Negative

- **No user-facing customization at ship** — users wanting a warm editorial reading experience (A2 palette + direction B) cannot opt in. Requires v2+ and business justification.
- **Locked design until next major revision** — returning to any dropped variant requires a new ADR, user research data, and stakeholder alignment.

### Neutral

- **Tweaks panel in production** contains only theme toggle (light/dark). Prototype controls (palette picker, direction toggle, font selector, confidence/degraded demo toggles) are removed. If a future v2 re-adds palette customization, the Tweaks panel structure remains, but new toggles must come with rationale.

## Reversal Process

To revisit any of the seven decisions above, the following steps are **mandatory:**

1. **Gather quantitative user research** — e.g., usability testing with 5+ external developers, feedback surveys from >50 CodeGuide users, or adoption metrics showing friction (e.g., "users frequently disable dark theme" or "requests for warm palette in top 3 feature requests").
2. **Write a new ADR** — title it "ADR-00XX: Reversal of ADR-0011 — adding support for [palette/direction/font]". Document the research, cost estimate (CSS growth, testing, documentation), and rollout plan.
3. **Update related documents** in the same PR:
   - `.ai/ux-spec.md` (add new palette/direction sections)
   - `.ai/prd.md` (FR changes if applicable)
   - CHANGELOG.md (note as a feature, not a patch)
4. **Stakeholder approval** — new ADR must be accepted by the same decision group as ADR-0011 (product owner + key reviewers).

Until this process is completed, all design decisions above are immutable for MVP.

## References

- `.ai/prd.md` v0.1.2-draft, §1 Product Overview
- `.ai/tech-stack.md` v0.1.2-draft, §11 Renderowanie i artefakt wyjściowy
- `.ai/ux-spec.md` v0.1.0-draft (living spec for all 7 decisions)
- `codeguide-ux-skill/SKILL.md` (approved decisions section)
- `codeguide-ux-skill/reference/tutorial/README.md` (design tokens)
- `codeguide-ux-skill/reference/cli/README.md` (CLI copy and color roles)
