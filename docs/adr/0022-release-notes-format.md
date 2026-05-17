# ADR-0022: Release-notes format and process

- **Status**: Accepted
- **Date**: 2026-05-17
- **Deciders**: Michał Kamiński (product owner)
- **Related ADRs**: ADR-0004 (UV-exclusive toolchain), ADR-0019 (brand unification)
- **Relates to**: v0.11.1+ (format stabilised from this release forward)

## Context

WiedunFlow shipped 17 GitHub Releases between ``v0.1.0-rc.1`` (2026-04-24) and ``v0.11.0`` (2026-05-17). A spot audit captured in the project-local research scratchpad (``release-notes-best-practices/``, gitignored) found two systemic problems:

1. **Title divergence.** Only five of seventeen titles followed the ``vX.Y.Z — <theme>`` shape (``v0.10.1``, ``v0.9.6``, ``v0.7.0``, ``v0.6.0``, ``v0.5.0``); the remaining twelve were bare tag names, including ``v0.9.0`` (the multi-agent narration ship) and all of the ``v0.9.x`` patches. A reader scanning the Releases index could not tell from the title alone which release introduced what.
2. **Body divergence.** The two hand-curated releases (``v0.10.1`` and ``v0.9.6``) ran nine independent conventions against each other: hero shape, breaking-changes position (top vs bottom), separator usage (``---`` vs none), stats-block name (``By the numbers`` vs ``Quality gates (all green)``), stats-block content (cost-accuracy row vs lint/typecheck rows), references-block name, link-form (relative ``CHANGELOG.md`` vs absolute ``/blob/v0.9.6/...``), emoji policy (four section-header emoji in ``v0.10.1``, five in ``v0.9.6``), and alert mechanism (none vs blockquote). The other fifteen releases relied on the minimal ``.github/release-notes-template.md`` (31 lines, envsubst-rendered Install + Usage + ``What's new`` auto-generation marker) and produced bodies that were structurally consistent but editorially empty.

A cross-project synthesis over twenty-seven Tier-1+2 reference projects (anthropic-sdk-python, openai-sdk-python, uv, ruff, poetry, pydantic, click, FastAPI, Django, axum, Rust, React, Next.js, Astro, Vite, Tailwind CSS, Kubernetes, Node.js, TypeScript, Vue, Svelte, Deno, Bun, Prisma, Black, OpenAI Codex CLI, Linear) produced strong convergences: zero emoji in 25 of 27 projects, the Anthropic-style ``**Full Changelog**: <compare URL>`` footer adopted whenever a footer exists, top-of-body breaking-changes placement in 9 of the 13 projects that flag breaking changes at all, the ``vX.Y.Z — <theme>`` title shape in every hand-curated Tier-1 CLI/library, and a single canonical name for the stats block per project. The synthesis explicitly rejected three otherwise-tempting paths for our scale: Stainless-generated bare-tag titles (designed for SDK weekly automation, loses the editorial layer), Common Changelog inline ``**breaking:**`` prefixes (axum's model, illegible against our ADR-anchored breaking changes that carry migration prose), and ``release-please`` / ``changesets`` automation (heavy machinery that does not pay off below ~5 maintainers).

The maintainer is a single person. Backfilling history through ``gh release edit`` against the twelve bare-tag releases was considered and rejected: the editorial cost of inventing themes for releases six weeks after the fact outweighs the consistency benefit, and the ``CHANGELOG.md`` entries (Keep-a-Changelog format, well-formed) already provide an authoritative cross-release record.

This ADR records the twelve binary decisions that close the format and process gaps. The format takes effect from ``v0.11.1`` forward.

## Decisions

### D1 — Title shape

Every GitHub Release MUST carry a title of the form ``vX.Y.Z — <one-line theme>``. Bare-tag titles are rejected for every release type, including chore patches (``v0.11.2 — Chore: dependency bumps``) and security patches (``v0.11.3 — Security: mistune CVE-2026-XXXX``). Prereleases may carry a bare tag in exceptional cases but the themed form is preferred. The theme fits inside the GitHub Releases index card width — roughly forty characters past the tag separator.

### D2 — Hero / TL;DR

MINOR (``v0.X.0``) and MAJOR (``vX.0.0``) releases MUST open with a hero block: two or three bullets, or a single paragraph of at most three sentences. The hero leads with user-visible impact and never restates the implementation path. PATCH releases MAY include a hero but are not required to; a chore-only patch typically omits it.

### D3 — Section ordering

The body sections appear in this fixed order: title → Install → Usage → Breaking changes → Features → Bug fixes → Performance → Documentation → Quality gates → References → Affected versions (security patches only) → Contributors (major releases only) → ``What's new`` (the softprops auto-generation marker) → Full Changelog footer. Sections that have no content for a given release are omitted entirely per D6, except for the title, Install, Usage, ``What's new`` marker, and Full Changelog footer which are always present.

### D4 — Quality-gate stats block

The stats block has a single canonical name, ``### Quality gates``, and a single canonical content shape — a four-row table matching the release-pipeline gates: Formatting (``uv run ruff format --check .``), Lint (``uv run ruff check .``), Type-check (``uv run mypy src/wiedunflow``), Unit + integ (``uv run pytest``). The block is optional for chore patches whose run output carries no information beyond "as expected". The earlier names ``By the numbers`` (v0.10.1) and ``Quality gates (all green)`` (v0.9.6) are superseded.

### D5 — Breaking-changes alert style

Breaking changes are introduced by a GitHub Flavored Markdown alert block at the top of the body, immediately after the Install and Usage sections. The alert is ``> [!WARNING]`` for ordinary breaking changes and ``> [!CAUTION]`` for security-relevant breaking changes (e.g. a vulnerable code path is removed and the surface shape changes in the same patch). Inline ``**breaking:**`` prefixes — the Common Changelog convention used by axum — are rejected because at our cadence breaking changes carry an ADR link plus migration prose, which the inline form makes illegible.

### D6 — Breaking-changes omission rule

On a release with zero breaking changes the entire ``### Breaking changes`` section is omitted, alert and all. Printing a "No breaking changes in this release" placeholder is rejected — it adds noise without information and trains readers to skim past the section even when it matters.

### D7 — Zero-emoji rule

No emoji anywhere in the release body, title, alert blocks, table contents, or commit-tag annotation. Visual hierarchy comes from GFM alert blocks, headers, and tables only. This matches twenty-five of the twenty-seven reference projects and aligns with the existing ``.ai/ux-spec.md`` no-emoji convention for the CLI surface.

### D8 — Link form

Every link to a file or directory inside this repository in the release body MUST be an absolute URL pinned to the release tag: ``https://github.com/numikel/wiedunflow/blob/${RELEASE_TAG}/<path>``. Relative paths (``./docs/...``, ``CHANGELOG.md``), branch-pinned paths (``/blob/main/...``), and commit-hash-pinned paths are all rejected. A reader landing on a release page six months after it shipped should see the repository state that shipped with that release, not whatever main moved on to.

### D9 — Compare-URL footer

The last non-empty line of every release body is ``**Full Changelog**: https://github.com/numikel/wiedunflow/compare/vPREV...vNEXT``. The ``vPREV`` value comes from ``git describe --tags --abbrev=0`` taken before the release commit. The softprops ``### What's new`` auto-generated block (rendered from merged PR titles) is preserved above this footer when the workflow's ``generate_release_notes`` flag fires, but the manual compare-URL footer stays as the LAST line.

### D10 — Forbidden ID classes

Release bodies, titles, and tag annotations MUST NOT reference ``F-XXX`` review-finding IDs. The ``.ai/reviews/`` directory is gitignored, the IDs do not survive outside the local checkout, and a reader chasing one of those references lands nowhere. ``ADR-XXXX`` (binding), ``US-XXX`` (user-story tracking), and ``CVE-YYYY-NNNNN`` (vulnerability disclosure) are encouraged.

### D11 — Backfill policy

The format takes effect from ``v0.11.1`` forward only. Releases ``v0.1.0-rc.1`` through ``v0.11.0`` are preserved as historical record and are not retroactively rewritten through ``gh release edit``. The first release on the new format carries no marker — the format simply is what it is from ``v0.11.1`` onward, and a reader diffing the boundary sees the change in shape itself.

### D12 — Tooling layer

The format is governed by four artefacts arranged across three load contexts and one operational layer:

- This ADR — binding spec, on-demand load, owned by the maintainer.
- ``CLAUDE.md`` ``## RELEASE_NOTES`` section — always-loaded summary in the project-root agent prompt, short enough to scan but operational enough to apply without loading the playbook.
- ``docs/release-notes-playbook.md`` — on-demand load for detail: per-release-type checklists, template walkthrough, worked example, troubleshooting.
- ``.claude/skills/release/SKILL.md`` — user-invocable Claude Code skill (``/release``), end-to-end eight-step flow that walks the maintainer from ``pyproject.toml`` bump through ``gh release create``.

The existing ``.github/workflows/release.yml`` envsubst plus ``softprops/action-gh-release@v3`` pipeline is unchanged. The skill pre-renders the body to ``.github/release-notes-rendered.md`` which the workflow consumes via ``body_path`` exactly as it does today; nothing in the workflow needs to know that a skill exists upstream.

## Consequences

### Positive

- The ``v0.10.1`` / ``v0.9.6`` editorial divergence ends. From ``v0.11.1`` forward every release follows one shape, one name per stats block, one position per alert, one link form.
- Hard rules (zero emoji, tagged URLs, compare-URL footer as the last line, no ``F-XXX`` references) are mechanically checkable from the rendered body — a future ``ruff``-style linter for release bodies has unambiguous targets.
- A new maintainer or contributor discovers the format in under five minutes: the ``CLAUDE.md`` summary catches them in any agent session, the ADR explains why, the playbook shows how, the skill executes the flow.
- The skill removes the manual envsubst step (currently invisible in the workflow file unless the maintainer reads ``release.yml`` carefully) from the day-to-day cutting flow without breaking the unattended tag-triggered path.

### Negative

- The maintainer pays roughly ten minutes of editorial work per MINOR release for the hero draft and the per-section curation. PATCH releases stay close to today's effort because the reduced-scope template lets most sections drop out.
- Releases ``v0.1.0-rc.1`` through ``v0.11.0`` stay non-conforming. Anyone diffing the Releases index across the ``v0.11.0`` → ``v0.11.1`` boundary sees the format change cold; no in-page banner explains it.
- A new contributor joining without Claude Code in their workflow needs to learn the format from the playbook and ADR alone — the skill's stop-points and pre-flight checks are unavailable to them.

### Neutral

- The ``release.yml`` workflow stays exactly as-is. ``pip-audit``, ``notice-check``, ``build-artifacts``, and ``create-release`` jobs are unchanged. Envsubst still fires at the same step against the same placeholder set.
- PyPI publishing remains deferred; this ADR makes no assumption about a PyPI presence and the ``Install`` block continues to reference ``uv pip install git+...@${RELEASE_TAG}`` plus the per-release ``.whl`` asset.
- ``CHANGELOG.md`` format (Keep-a-Changelog) is unchanged. The skill promotes the ``[Unreleased]`` block to a tagged section as part of its eight-step flow but does not touch the file structure.

## Alternatives Rejected

### ``release-please`` (Google's release-automation GitHub Action)

Conventional-commit-driven bumps, automatic ``CHANGELOG`` promotion, a long-lived release PR that the bot keeps in sync as commits land on ``main``. Used by anthropic-sdk-python and openai-sdk-python (Stainless template). Rejected because the automation surface (release-PR pattern, manifest file, opinionated commit-message parsing, mandatory ``release-type`` configuration) does not pay off below five active maintainers and would tie WiedunFlow to a release shape designed for SDK weekly automation rather than narrative CLI releases. Reconsider when a second active committer joins.

### ``changesets`` (npm-ecosystem incremental-changelog tool)

Per-PR ``.changeset/*.md`` files that the bot consumes at release time to produce a categorised CHANGELOG entry. Used by Astro and Svelte. Rejected because the tool was invented for monorepos with independent per-package versions; WiedunFlow ships one Python package and the ``CHANGELOG.md`` plus Conventional Commits flow already covers the unit-of-change concern without the changeset-authoring overhead.

### Common Changelog inline-prefix taxonomy (axum)

``**added:**`` / ``**breaking:**`` / ``**changed:**`` / ``**fixed:**`` / ``**deprecated:**`` / ``**security:**`` bold prefixes on flat bullet lists, no section headers. Rejected because the format is optimised for dense changelogs where every entry is one bullet; our breaking changes carry an ADR link plus migration prose, which the inline form crushes into an illegible bullet.

### Stainless-generated SDK template (bare-tag titles, auto-generated body)

The shape used by anthropic-sdk-python and openai-sdk-python: ``X.Y.Z (YYYY-MM-DD)`` titles, Features/Bug Fixes/Performance/Reverts/Chores/Documentation auto-categorised from conventional-commit footers, ``Full Changelog`` footer. Rejected because the bare-tag title is appropriate for SDK release cadence (weekly, automated, where the body carries the editorial weight) but loses the editorial layer that makes a CLI release legible to a human reader scanning the index.

## References

- Research scratchpad: ``release-notes-best-practices/`` (gitignored, single-maintainer scratch space — twenty-seven per-project JSON profiles plus ``report.md`` synthesis and ``current-state-analysis.md`` baseline). The conclusions are folded into this ADR and ``docs/release-notes-playbook.md``; no external link survives.
- Current state at the time of writing: ``.github/release-notes-template.md`` (the 31-line envsubst template this ADR supersedes), ``.github/workflows/release.yml`` (the unchanged release-gate workflow), ``CHANGELOG.md`` (Keep-a-Changelog, latest entry ``[0.11.0]``).
- Playbook: ``docs/release-notes-playbook.md`` (per-release-type checklists, walkthrough, worked example, troubleshooting).
- Always-loaded summary: ``CLAUDE.md`` ``## RELEASE_NOTES`` section.
- Operational layer: ``.claude/skills/release/SKILL.md`` (user-invocable ``/release`` skill).
