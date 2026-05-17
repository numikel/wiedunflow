<!--
WiedunFlow release-notes body template.

Format stabilised from v0.11.1 onward (ADR-0022, 2026-05-17). Releases v0.11.0
and earlier are preserved as historical record and are NOT retroactively
rewritten — `gh release edit` on history is out of scope per ADR-0022 §D11.

Rendering: this file is processed by envsubst in .github/workflows/release.yml
(step "Render release notes template", release.yml:199-213) with ${RELEASE_TAG}
and ${RELEASE_VERSION} substituted. The rendered file lives at
.github/release-notes-rendered.md and is passed to softprops/action-gh-release
via body_path. The /release skill pre-renders the same path locally; the
workflow's envsubst step is idempotent on a fully-rendered file.

Per-release-type collapse rules — delete sections that apply:
  MAJOR  (vX.0.0)     : KEEP ALL sections + add Migration guide block under
                        Breaking changes. Keep Contributors. Keep Quality gates.
  MINOR  (v0.X.0)     : KEEP Hero/TL;DR, Breaking (if any), Features, Bug fixes,
                        Quality gates, References, Full Changelog footer.
                        Drop Contributors and Affected versions.
  PATCH  (v0.X.Y)     : Hero/TL;DR OPTIONAL. Breaking section OMITTED entirely
                        if empty (do NOT print "No breaking changes"). Quality
                        gates optional. Title-theme STILL REQUIRED.
  PRERELEASE          : prerelease=true auto-detected for -rc.N tags
                        (release.yml:220). Skip Hero/TL;DR and Contributors.
                        MUST add the "rc — not production" warning to Install.
  SECURITY-PATCH      : Replace > [!WARNING] with > [!CAUTION]. Affected
                        versions table REQUIRED. CVE refs MANDATORY if assigned.

Hard rules (ADR-0022 §D7-D10):
  - Zero emoji anywhere (title, headers, body, alerts, tables).
  - All in-repo links use absolute tagged URLs /blob/${RELEASE_TAG}/...
  - Compare-URL footer is the LAST non-empty line of the body.
  - Never reference F-XXX IDs (.ai/reviews/ is gitignored). ADR-XXXX, US-XXX,
    CVE-YYYY-NNNNN are fine and encouraged.

Detailed checklists: docs/release-notes-playbook.md §3.
Skill that drives this end-to-end: .claude/skills/release/SKILL.md (/release).
-->

## WiedunFlow ${RELEASE_TAG}

<!-- Hero / TL;DR — MANDATORY for MINOR+MAJOR (ADR-0022 §D2), MAY for PATCH.
     Either 2-3 bullets OR a single paragraph of <=3 sentences.
     Lead with user-visible impact, not the implementation path. -->

Self-contained HTML tutorials from local Git repositories. Offline-first, BYOK
(Anthropic / OpenAI / Ollama), no telemetry.

### Install

Install directly from this release tag:

```bash
uv pip install git+https://github.com/numikel/wiedunflow@${RELEASE_TAG}
```

Or download the `.whl` from the assets below and install offline:

```bash
uv pip install wiedunflow-${RELEASE_VERSION}-py3-none-any.whl
```

### Usage

```bash
wiedunflow /path/to/your/repo
```

This generates a `wiedunflow-<repo>.html` next to the source repo. Open it in
any browser — no server required.

<!-- BREAKING CHANGES — OMIT THIS ENTIRE SECTION if no breaking changes (ADR-0022
     §D6). Do NOT print a "No breaking changes" placeholder. Placement is TOP,
     immediately after Install/Usage (ADR-0022 §D5). For security patches,
     replace > [!WARNING] with > [!CAUTION]. -->

### Breaking changes

> [!WARNING]
> One or more public Protocols or config fields changed shape in this release.
> Review the migration notes below before upgrading.

- `<Protocol or surface>.<member>` — `<what changed>`. Migration: `<how to adapt>`.
  See [ADR-XXXX](https://github.com/numikel/wiedunflow/blob/${RELEASE_TAG}/docs/adr/XXXX-slug.md).

<!-- FEATURES — new user-visible capabilities only. Internal refactors do not
     belong here. Group by area when 4+ items. -->

### Features

- **<Feature name>** — `<one-line impact>`. Wired in
  [`src/wiedunflow/<path>.py`](https://github.com/numikel/wiedunflow/blob/${RELEASE_TAG}/src/wiedunflow/<path>.py).

<!-- BUG FIXES — user-observable defects fixed. Internal cleanup that the user
     could not have noticed goes in CHANGELOG.md under Internal but does NOT
     come up to this body. -->

### Bug fixes

- `<surface>`: `<symptom>` — fixed by `<short cause description>`
  ([`<path>`](https://github.com/numikel/wiedunflow/blob/${RELEASE_TAG}/<path>)).

<!-- PERFORMANCE — measurable wins only. Cite the benchmark or include
     before/after numbers. Drop the section if no measurement was done —
     "various performance improvements" is noise. -->

### Performance

- `<workload>`: `<before>` -> `<after>` (`<delta>`).

<!-- DOCUMENTATION — only when the docs change is user-visible (new guide,
     README restructure, new ADR worth surfacing). Routine typo fixes do NOT
     belong here. -->

### Documentation

- New: [ADR-XXXX — `<title>`](https://github.com/numikel/wiedunflow/blob/${RELEASE_TAG}/docs/adr/XXXX-slug.md).

<!-- QUALITY GATES — single canonical name (ADR-0022 §D4). 4-row table matching
     the release-pipeline gates. Optional for chore patches whose run output
     carries no information beyond "as expected"; mandatory otherwise. Status
     is `pass` for every gate — a red gate is a release blocker. -->

### Quality gates

| Gate            | Command                              | Status |
| --------------- | ------------------------------------ | ------ |
| Formatting      | `uv run ruff format --check .`       | pass   |
| Lint            | `uv run ruff check .`                | pass   |
| Type-check      | `uv run mypy src/wiedunflow`         | pass   |
| Unit + integ    | `uv run pytest`                      | pass   |

<!-- REFERENCES — ADRs, user stories, related issues / PRs.
     The CHANGELOG link uses the tagged URL so a reader on a stale tab gets
     the file as it shipped with this release. NEVER F-XXX (ADR-0022 §D10). -->

### References

- ADR: [ADR-XXXX](https://github.com/numikel/wiedunflow/blob/${RELEASE_TAG}/docs/adr/XXXX-slug.md)
- Changelog (this release): [`CHANGELOG.md#${RELEASE_VERSION}`](https://github.com/numikel/wiedunflow/blob/${RELEASE_TAG}/CHANGELOG.md)
- User stories: US-XXX, US-YYY

<!-- AFFECTED VERSIONS — SECURITY PATCH ONLY. Uncomment and populate for
     security releases; leave commented out (and therefore invisible in the
     rendered body) otherwise. -->

<!--
### Affected versions

| Range          | Status        | Action                    |
| -------------- | ------------- | ------------------------- |
| <= v0.X.Y      | Vulnerable    | Upgrade to ${RELEASE_TAG} |
| ${RELEASE_TAG} | Fixed         | -                         |

CVE: CVE-YYYY-NNNNN
-->

<!-- CONTRIBUTORS — MAJOR releases only. Drop for MINOR/PATCH/prerelease.
     Stay terse — this is acknowledgement, not a deep biography. -->

<!--
### Contributors

Thanks to @handle1, @handle2 for `<contribution>`.
-->

<!-- WHAT'S NEW — auto-generation marker for softprops/action-gh-release@v3
     with generate_release_notes=true (release.yml:221). The maintainer never
     edits this section by hand. Keep the marker comment unchanged. -->

### What's new

<!-- GitHub auto-generates release notes from merged PR titles below this marker. -->
<!-- See CHANGELOG.md for the curated changelog. -->

---

**Full Changelog**: https://github.com/numikel/wiedunflow/compare/vPREV...${RELEASE_TAG}
