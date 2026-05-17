# Release-notes playbook

On-demand detail for cutting a WiedunFlow GitHub Release. The binding spec is [ADR-0022](adr/0022-release-notes-format.md). The always-loaded summary lives in [`CLAUDE.md` `## RELEASE_NOTES`](../CLAUDE.md). The operational layer is the user-invocable [`/release` skill](../.claude/skills/release/SKILL.md).

This file is **not** loaded into every agent session — it loads when the agent needs the full per-release-type checklist, the section-by-section walkthrough, the worked example, or the troubleshooting steps.

## 1. Purpose and scope

### 1.1 What this playbook covers

- Per-release-type checklists for MAJOR / MINOR / PATCH / PRERELEASE / SECURITY-PATCH, with concrete commands.
- A section-by-section walkthrough of `.github/release-notes-template.md` explaining the rationale of every part.
- A fully worked example: a hypothetical `v0.11.1` patch release covering "BM25 cache miss on Windows case-sensitive paths".
- Workflow integration: how the `release.yml` four-job pipeline consumes the rendered body, when envsubst fires, when the skill is in/out of the loop.
- Troubleshooting: pip-audit allowlisting, notice-check regeneration, manual fallback when GitHub Actions is unreachable, tag-recovery procedures.
- Conventions reference: Conventional Commits scopes, SemVer boundaries for this project, PEP 440 wheel form vs git tag form.

### 1.2 Relationship to the other anchors

| Artefact | Load context | Role |
|---|---|---|
| `docs/adr/0022-release-notes-format.md` | On-demand | Binding spec. Twelve numbered decisions (D1-D12). Read once to understand WHY. |
| `CLAUDE.md` `## RELEASE_NOTES` | Always-loaded | Operational summary — triggers, core rules, anti-patterns. Read every session. |
| `docs/release-notes-playbook.md` (this file) | On-demand | Detail layer — checklists, walkthrough, examples, troubleshooting. Read when applying. |
| `.claude/skills/release/SKILL.md` | User-invocable (`/release`) | The 8-step flow that walks the maintainer from `pyproject.toml` bump to `gh release create`. |

If the summary in `CLAUDE.md` and the binding text in ADR-0022 disagree (they should not), ADR-0022 wins. If this playbook and ADR-0022 disagree, ADR-0022 wins — and the discrepancy is a documentation bug to fix.

## 2. Anatomy of a WiedunFlow release

### 2.1 The eight artefacts touched on every release

A release cuts cleanly across eight artefacts. The skill walks through them in order; a maintainer running by hand follows the same sequence.

1. `pyproject.toml` — `[project].version` bumped per SemVer rules from D1-derived release type.
2. `CHANGELOG.md` — `[Unreleased]` block promoted to `[X.Y.Z] - YYYY-MM-DD — <theme>`; a fresh empty `[Unreleased]` inserted above.
3. `.github/release-notes-rendered.md` — the body the GitHub Release will display, written by the maintainer (or the skill) using the template as scaffold and the appropriate per-type checklist as completeness guide.
4. Commit on `main` — `chore(release): vX.Y.Z — <theme>` (or `fix(security): vX.Y.Z — <one-line>` for security patches), DCO-signed with `git commit -s`.
5. Tag — `vX.Y.Z` annotated and GPG-signed via `git tag -s` (fall back to `-a` if no signing key is configured).
6. `git push origin main` followed by `git push origin vX.Y.Z` — main first so the tag lands on a published commit.
7. `uv build` — local sanity build producing `dist/wiedunflow-X.Y.Z-py3-none-any.whl` and `dist/wiedunflow-X.Y.Z.tar.gz`. CI builds in parallel; this is the paranoid cross-check.
8. GitHub Release — created by the `release.yml` workflow on tag push (default path) or by `gh release create` directly (manual fallback path).

### 2.2 How `release.yml` consumes the artefacts

The workflow has four jobs, gated as follows:

| Job | Trigger | Purpose | Reads | Writes |
|---|---|---|---|---|
| `pip-audit` | Every tag push + workflow_dispatch | OSV vulnerability scan against the resolved dep graph; allowlist embedded in `release.yml` itself with per-entry justification. | `pyproject.toml`, `uv.lock` | — |
| `notice-check` | Every tag push + workflow_dispatch | Verifies `NOTICE` is in sync with runtime Apache-2.0 deps via `scripts/aggregate_notice.py --check`. | `NOTICE`, runtime dep metadata | — |
| `build-artifacts` | Needs `pip-audit` + `notice-check` | Runs `uv build`, uploads `dist/*` as a workflow artifact named `release-dist`. | `pyproject.toml`, source tree | `dist/*` artifact |
| `create-release` | Needs `build-artifacts`; `if: github.ref_type == 'tag'` | Downloads `release-dist`, renders the body via envsubst, calls `softprops/action-gh-release@v3` to create the GitHub Release with `body_path: .github/release-notes-rendered.md`. | `release-dist`, `.github/release-notes-template.md` | GitHub Release (with `dist/*` attached) |

### 2.3 Where envsubst fires vs. where the maintainer fills in

The envsubst step inside `create-release` (`release.yml:199-213`) substitutes exactly two placeholders: `${RELEASE_TAG}` (from `github.ref_name`) and `${RELEASE_VERSION}` (derived as `${RELEASE_TAG#v}`). Every other piece of the body — the title-theme, hero, breaking-changes bullets, ADR references, compare-URL footer — is the maintainer's job.

The skill streamlines this by pre-rendering `.github/release-notes-rendered.md` locally during step 3, with the same envsubst substitutions plus the editorial sections filled in. When the workflow later runs envsubst against the committed `release-notes-rendered.md`, the placeholders are already gone — the substitution is idempotent on a fully-rendered file.

## 3. Per-release-type checklists

The five flows differ in template-section scope (which sections of `.github/release-notes-template.md` are kept vs. omitted), in editorial obligations (Hero/TL;DR mandatory or optional, Contributors yes or no, Migration guide yes or no), and in the alert variant used for breaking changes (`> [!WARNING]` vs. `> [!CAUTION]`).

### 3.1 MAJOR (`vX.0.0`)

1. Confirm that breaking changes are documented under `CHANGELOG.md` `[Unreleased] > ### BREAKING`. If they are not, stop and write them — a MAJOR with no breaking changes is misclassified.
2. Edit `pyproject.toml`: bump `[project].version` to `X.0.0`.
3. Edit `CHANGELOG.md`: rename `## [Unreleased]` to `## [X.0.0] - YYYY-MM-DD — <Theme>` (today's date). Insert a fresh empty `## [Unreleased]` block above.
4. Draft `.github/release-notes-rendered.md` from `.github/release-notes-template.md`. Keep ALL template sections; add a **Migration guide** block under Breaking changes (a paragraph of prose before the per-Protocol bullets); keep the **Contributors** block; keep the **Quality gates** block.
5. Replace every `vPREV` placeholder in the body with the previous tag from `git describe --tags --abbrev=0`.
6. Run the hard-rules check by eye: every in-repo link is `/blob/vX.0.0/...`; zero emoji anywhere; the compare-URL footer is the LAST non-empty line; no `F-XXX` references.
7. Stage the three files and commit with DCO sign-off:
   ```bash
   git add pyproject.toml CHANGELOG.md .github/release-notes-rendered.md
   git commit -s -m "chore(release): vX.0.0 — <theme>"
   ```
8. Sign the tag:
   ```bash
   git tag -s vX.0.0 -m "vX.0.0 — <theme>"
   ```
9. Push main first, then the tag:
   ```bash
   git push origin main
   git push origin vX.0.0
   ```
   The tag push triggers `release.yml`.
10. Run `uv build` locally as a paranoid cross-check while GitHub Actions builds in parallel.
11. After the `create-release` job uploads, set the release title (the workflow defaults to the tag name; the title-theme MUST be set explicitly):
    ```bash
    gh release edit vX.0.0 --title "vX.0.0 — <theme>"
    ```
12. Open `gh release view vX.0.0 --web` and verify: title shape, alert rendering, asset list, compare-URL link resolves, no broken `/blob/` links.
13. Announce on the dual channel (blog / release-channel / wherever the project's announcement surface lives). Paste the Hero/TL;DR block as-is — consistency across surfaces is the point.

### 3.2 MINOR (`v0.X.0`)

1. Confirm new features and any internal-Protocol breaking changes are recorded in `CHANGELOG.md` `[Unreleased]`.
2. Edit `pyproject.toml`: bump `[project].version` to `0.X.0`.
3. Promote `CHANGELOG.md` `[Unreleased]` to `[0.X.0] - YYYY-MM-DD — <Theme>`; insert fresh empty `[Unreleased]`.
4. Draft `.github/release-notes-rendered.md`: Hero/TL;DR (mandatory, 2-3 bullets OR ≤3-sentence paragraph), Breaking changes (if any, with `> [!WARNING]` alert), Features, Bug fixes, Performance (if measured), Documentation (if user-visible), Quality gates, References.
5. Run hard-rules check: tagged URLs, zero emoji, compare-URL footer LAST.
6. Commit:
   ```bash
   git add pyproject.toml CHANGELOG.md .github/release-notes-rendered.md
   git commit -s -m "chore(release): v0.X.0 — <theme>"
   ```
7. Sign tag and push:
   ```bash
   git tag -s v0.X.0 -m "v0.X.0 — <theme>"
   git push origin main
   git push origin v0.X.0
   ```
8. Cross-check with `uv build`.
9. After the workflow finishes:
   ```bash
   gh release edit v0.X.0 --title "v0.X.0 — <theme>"
   ```
10. Verify with `gh release view v0.X.0 --web`.

### 3.3 PATCH (`v0.X.Y`)

1. Confirm fixes are in `CHANGELOG.md` `[Unreleased]` under one or more of `### Fixed` / `### Changed` / `### Security` / `### Internal`.
2. Edit `pyproject.toml`: bump `[project].version` to `0.X.Y`.
3. Promote `CHANGELOG.md` `[Unreleased]` to `[0.X.Y] - YYYY-MM-DD — <Theme>`; insert fresh empty `[Unreleased]`.
4. Draft `.github/release-notes-rendered.md`. Title-theme MANDATORY (no bare-tag patches). Hero/TL;DR OPTIONAL. Apply the omit-if-empty rule per ADR-0022 §D6: if no breaking changes, the entire Breaking changes section is omitted (alert and all); if no measured performance work, omit Performance; etc. A chore-only patch (deps bump, doc typo) can legitimately be five sections long: title, Install, Usage, References (CHANGELOG link), Full Changelog footer.
5. Hard-rules check.
6. Commit:
   ```bash
   git add pyproject.toml CHANGELOG.md .github/release-notes-rendered.md
   git commit -s -m "chore(release): v0.X.Y — <theme>"
   ```
   (For security patches see §3.5 — the commit subject changes to `fix(security)`.)
7. Sign tag and push:
   ```bash
   git tag -s v0.X.Y -m "v0.X.Y — <theme>"
   git push origin main
   git push origin v0.X.Y
   ```
8. Cross-check with `uv build`.
9. After the workflow finishes:
   ```bash
   gh release edit v0.X.Y --title "v0.X.Y — <theme>"
   ```
10. Verify.

### 3.4 PRERELEASE (`vX.Y.Z-rc.N`, `-alpha.N`, `-beta.N`)

1. Confirm the `CHANGELOG.md` `[Unreleased]` block has the changes ready. **Do NOT promote** the block yet — prereleases do not seal the changelog; the corresponding stable release does.
2. Edit `pyproject.toml`: bump `[project].version` to the PEP 440 wheel form. The tag uses the dash-and-dot form (`v0.12.0-rc.1`); the wheel uses the squashed form (`0.12.0rc1`).
3. Draft `.github/release-notes-rendered.md`. Keep the title themed (`v0.12.0-rc.1 — <theme>` preferred over bare-tag). Skip Hero/TL;DR. Skip Contributors. Skip Quality gates unless the maintainer wants to surface them. Add this warning text to the Install section verbatim:
   ```markdown
   > [!WARNING]
   > This is a release candidate, not a stable release. Do not use in production.
   > Pin to a specific rc tag if you must test.
   ```
4. Sign the tag (no version-bump commit — `[Unreleased]` stays open):
   ```bash
   git tag -s v0.12.0-rc.1 -m "v0.12.0-rc.1 — <theme>"
   ```
5. Push the tag only (do NOT push main — the rc lives on the existing main HEAD):
   ```bash
   git push origin v0.12.0-rc.1
   ```
6. The `release.yml` workflow auto-detects `-rc` in the tag name (line 220: `prerelease: ${{ contains(github.ref_name, '-rc') }}`) and flags the release accordingly. For `-alpha.N` or `-beta.N`, the auto-detect does NOT fire — set the flag manually with `gh release edit --prerelease` after the workflow runs, or edit `release.yml` to match.
7. After the workflow finishes:
   ```bash
   gh release edit v0.12.0-rc.1 --title "v0.12.0-rc.1 — <theme>" --prerelease
   ```
8. Verify the GitHub Release page shows the "Pre-release" badge.

### 3.5 SECURITY-PATCH (`v0.X.Y`)

1. Confirm a security advisory exists (a private GitHub Security Advisory or a public CVE allocation). Gather: affected versions, fixed versions, and the CVE ID if one has been assigned.
2. Edit `pyproject.toml`: bump `[project].version` to `0.X.Y`.
3. Promote `CHANGELOG.md` `[Unreleased]` to `[0.X.Y] - YYYY-MM-DD — Security: <one-line>`. Insert fresh empty `[Unreleased]`.
4. Draft `.github/release-notes-rendered.md`. Title: `v0.X.Y — Security: <one-line summary>`.
5. Replace the `> [!WARNING]` alert in the Breaking changes section with `> [!CAUTION]`. (Even if the security fix does not technically break any Protocol shape, the CAUTION alert signals "act now" rather than "review on upgrade".)
6. Uncomment the **Affected versions** table in the template and populate it: vulnerable range, fixed version (this release), and the CVE row.
7. Add a one-line **Action required** sentence in the Hero/TL;DR — even a security patch deserves the hero. Example: "Upgrade to `v0.11.3` if you used the `narrate_lessons` flag against untrusted repo paths between v0.10.0 and v0.11.2."
8. Hard-rules check.
9. Commit with the `fix(security)` conventional-commit type (not `chore(release)`):
   ```bash
   git add pyproject.toml CHANGELOG.md .github/release-notes-rendered.md
   git commit -s -m "fix(security): v0.X.Y — <one-line CVE summary>"
   ```
10. Sign tag and push:
    ```bash
    git tag -s v0.X.Y -m "v0.X.Y — Security: <one-line>"
    git push origin main
    git push origin v0.X.Y
    ```
11. Cross-check with `uv build`.
12. After the workflow finishes:
    ```bash
    gh release edit v0.X.Y --title "v0.X.Y — Security: <one-line>"
    ```
13. Cross-post: publish the GitHub Security Advisory (request a CVE if not assigned), update the README banner if the project carries one, notify any downstream consumer channel.

## 4. Template walkthrough

### 4.1 Title — `vX.Y.Z — <theme>`

The GitHub Release title field is independent of the body H2. The body opens with `## WiedunFlow ${RELEASE_TAG}`; the title field is set separately via `gh release edit --title`. Both must match the `vX.Y.Z — <theme>` shape (ADR-0022 §D1).

The theme fits in about forty characters past the tag separator. Examples that work: `v0.11.0 — Cache, History, and Timeout Polish`, `v0.10.1 — Multi-Agent Cost Model + ADR-0016 Cleanup`, `v0.11.2 — Chore: dependency bumps`. Examples that are too long for the Releases index card: `v0.11.0 — Anthropic prompt caching wiring, BM25 index persistence, sliding-window compression, and HTTP read-timeout config field for local-endpoint BYOK` — collapse to a thematic phrase.

### 4.2 Install / Usage — envsubst placeholders

The template uses `${RELEASE_TAG}` and `${RELEASE_VERSION}` placeholders in the Install code blocks. The envsubst step in `release.yml:199-213` substitutes both. `${RELEASE_TAG}` is the git tag name verbatim (`v0.11.1`). `${RELEASE_VERSION}` is the version with the leading `v` stripped (`0.11.1`) — used for the wheel filename (`wiedunflow-0.11.1-py3-none-any.whl`).

If the skill pre-renders the body locally (the recommended flow), it substitutes the same two placeholders. The workflow's envsubst step on a fully-rendered file is idempotent — no remaining placeholders, no error.

### 4.3 Breaking changes — alert variants, omit-if-empty

The Breaking changes section opens with a GFM alert block. Two variants are recognised:

- `> [!WARNING]` for ordinary breaking changes (Protocol shape change, config field renamed, default behaviour reversed).
- `> [!CAUTION]` for security-relevant breaking changes (a vulnerable code path is removed and the surface shape changes in the same patch).

The omit-if-empty rule (ADR-0022 §D6) is the load-bearing one: a release with zero breaking changes omits the entire section, alert and all. There is no "No breaking changes in this release" placeholder. The reader who scans the Releases page for a section header named "Breaking changes" trusts the signal: if they see one, there is one; if they don't, there isn't.

### 4.4 Features / Bug fixes / Performance / Documentation

Four content sections, each independent and omit-if-empty.

- **Features**: new user-visible capabilities only. Internal refactors do not belong here. Group by area when four or more items.
- **Bug fixes**: user-observable defects fixed. Internal cleanup that the user could not have noticed goes under "Internal" in `CHANGELOG.md` but does NOT come up to the release body.
- **Performance**: measurable wins only. Cite the benchmark (or include before/after numbers). Drop the section if no measurement was done — "various performance improvements" is noise.
- **Documentation**: only when the docs change is user-visible (a new guide, a README restructure, a new ADR worth surfacing). Routine typo fixes do not belong here.

Every bullet that references an in-repo file uses an absolute tagged URL (ADR-0022 §D8) — `https://github.com/numikel/wiedunflow/blob/${RELEASE_TAG}/<path>`.

### 4.5 Quality gates — the single canonical block

The block has a single canonical name, `### Quality gates`, and a single canonical content shape — a four-row table:

| Gate | Command | Status |
|---|---|---|
| Formatting | `uv run ruff format --check .` | pass |
| Lint | `uv run ruff check .` | pass |
| Type-check | `uv run mypy src/wiedunflow` | pass |
| Unit + integ | `uv run pytest` | pass |

The Status column is always either `pass` or — in the unusual case where the maintainer is shipping a release knowing one gate is red and accepting the trade-off — `pass with exceptions` plus a one-line note in the row. Never `fail`; a red gate is a release blocker, not a footnote.

The block is optional for chore patches whose run output is uninteresting (e.g. a pure-deps bump that did not touch any code path). For everything else it is mandatory.

### 4.6 References — ADRs, USs, CVEs (never `F-XXX`)

The References section links to: ADRs by number (`ADR-0022`), user stories by number (`US-088`), changelog (`CHANGELOG.md#${RELEASE_VERSION}`), CVEs by full identifier (`CVE-2026-XXXX`).

`F-XXX` review-finding IDs are forbidden (ADR-0022 §D10). The `.ai/reviews/` directory is gitignored; readers chasing one of those references land nowhere. Memory `feedback_no_findings_refs_in_code.md` is the upstream reason — review tracking IDs are internal scratch space, not public artefacts.

### 4.7 Affected versions — security-patch only

The Affected versions table is uncommented and populated for security patches; it stays HTML-commented (and therefore invisible in the rendered body) for everything else. Shape:

| Range | Status | Action |
|---|---|---|
| `<= v0.X.Y` | Vulnerable | Upgrade to `${RELEASE_TAG}` |
| `${RELEASE_TAG}` | Fixed | — |

A single CVE identifier follows the table on its own line: `CVE: CVE-YYYY-NNNNN`.

### 4.8 Contributors — major-only

The Contributors section is uncommented and populated for MAJOR releases only. Format: a single sentence per contributor or grouped sentence — `Thanks to @handle for <contribution>.` Stay terse; this is acknowledgement, not a deep biography.

For MINOR, PATCH, and pre-release flows the Contributors block stays commented-out and invisible. A single-maintainer project on a MINOR cadence does not benefit from a one-line "Thanks to @numikel for everything in this release" entry.

### 4.9 What's new — auto-generation marker

The `### What's new` H3 with the trailing HTML comment is the marker `softprops/action-gh-release@v3` uses (with `generate_release_notes: true` set in `release.yml:221`) to append an auto-generated "What's Changed" list of merged PR titles below it.

The maintainer never edits this section by hand. If `generate_release_notes` is later disabled in the workflow, the marker stays but the auto-generated content does not appear — at that point the section can be dropped from the template entirely.

### 4.10 Full Changelog — compare URL as LAST line

The very last non-empty line of the body is `**Full Changelog**: https://github.com/numikel/wiedunflow/compare/vPREV...${RELEASE_TAG}`. The `vPREV` value comes from `git describe --tags --abbrev=0` taken before the release commit. The skill computes this automatically; a maintainer running by hand pastes the value.

The footer must be the LAST line (ADR-0022 §D9). Anything below it — even a "thanks for reading" sentence — pushes the load-bearing compare link out of the natural eye-stopping position on a GitHub Release page.

## 5. Worked example — hypothetical `v0.11.1`

### 5.1 Scenario

A user on Windows reports that the BM25 cache from ADR-0021 misses on the second run when the repository path is passed with different case-folding (`D:\code\foo` first run, `D:/code/Foo` second run). Root cause: the cache key `(repo_abs, commit_hash, corpus_config_fingerprint)` uses `Path.absolute()`-as-string which preserves the original case on Windows even though Windows treats the paths as the same filesystem location.

Fix: normalise `repo_abs` to lowercase on Windows before keying. One-line change in `src/wiedunflow/cache/bm25_index.py` plus a test in `tests/unit/cache/test_bm25_index.py`.

No breaking changes (the cache key shape is unchanged from the consumer's perspective — only the normalisation rule changes, and any old entries keyed by the original-case path are invalidated as cache misses on first hit). No new features. One bug fix. No performance measurement. No new ADR.

Release type: PATCH. Title-theme: `v0.11.1 — Fix: BM25 cache miss on Windows path-case`.

### 5.2 Full rendered body

```markdown
## WiedunFlow v0.11.1

Self-contained HTML tutorials from local Git repositories. Offline-first, BYOK
(Anthropic / OpenAI / Ollama), no telemetry.

### Install

Install directly from this release tag:

```bash
uv pip install git+https://github.com/numikel/wiedunflow@v0.11.1
```

Or download the `.whl` from the assets below and install offline:

```bash
uv pip install wiedunflow-0.11.1-py3-none-any.whl
```

### Usage

```bash
wiedunflow /path/to/your/repo
```

This generates a `wiedunflow-<repo>.html` next to the source repo. Open it in
any browser — no server required.

### Bug fixes

- `cache/bm25_index`: cache miss on the second run when the same repository path
  was passed with different case-folding on Windows (e.g. `D:\code\foo` then
  `D:/code/Foo`). Fixed by normalising `repo_abs` to lowercase on Windows before
  computing the cache key
  ([`src/wiedunflow/cache/bm25_index.py`](https://github.com/numikel/wiedunflow/blob/v0.11.1/src/wiedunflow/cache/bm25_index.py)).

### Quality gates

| Gate            | Command                              | Status |
| --------------- | ------------------------------------ | ------ |
| Formatting      | `uv run ruff format --check .`       | pass   |
| Lint            | `uv run ruff check .`                | pass   |
| Type-check      | `uv run mypy src/wiedunflow`         | pass   |
| Unit + integ    | `uv run pytest`                      | pass   |

### References

- Changelog (this release): [`CHANGELOG.md#0.11.1`](https://github.com/numikel/wiedunflow/blob/v0.11.1/CHANGELOG.md)
- Related ADR: [ADR-0021 — Cache, history, and timeout policy](https://github.com/numikel/wiedunflow/blob/v0.11.1/docs/adr/0021-cache-history-and-timeout-policy.md)

### What's new

<!-- GitHub auto-generates release notes from merged PR titles below this marker. -->
<!-- See CHANGELOG.md for the curated changelog. -->

---

**Full Changelog**: https://github.com/numikel/wiedunflow/compare/v0.11.0...v0.11.1
```

### 5.3 What the maintainer typed vs. what envsubst filled

What the maintainer typed (or what the skill drafted from `CHANGELOG.md` and `git log`):

- Title-theme: `Fix: BM25 cache miss on Windows path-case`.
- Bug-fix bullet with the file path and the cause description.
- ADR-0021 reference (the patch is in the cache layer ADR-0021 touched).
- Compare-URL footer with `vPREV=v0.11.0`.

What envsubst filled in the workflow run (the same that the skill pre-rendered locally):

- `${RELEASE_TAG}` → `v0.11.1` in the title, Install commands, every `/blob/` link, and the compare-URL footer.
- `${RELEASE_VERSION}` → `0.11.1` in the wheel-filename Install command.

What was omitted per the reduced-template rule (ADR-0022 §D6):

- Breaking changes section (no breaking changes).
- Features section (no new features).
- Performance section (no measurement done).
- Documentation section (no user-visible docs change).
- Affected versions table (not a security patch).
- Contributors section (not a MAJOR release).
- Hero/TL;DR (PATCH may have it; this one chose not to).

Net body: roughly 35 lines. Compare against the minimum-shape patch (chore-only deps bump): roughly 25 lines. Compare against a full MINOR with hero + breaking + features + fixes: roughly 100 lines. The shape scales with content, which is the point.

## 6. Workflow integration

### 6.1 The four jobs in `release.yml`

Recap from §2.2 with the timing dimension: on a tag push, `pip-audit` and `notice-check` run in parallel as the first wave, both gating the second wave; `build-artifacts` waits for both green; `create-release` waits for `build-artifacts` AND for the trigger to be a tag (not a workflow_dispatch).

The wall-clock on a clean tag push is roughly six to ten minutes — `pip-audit` carries most of the time (resolving the OSV database against the full dep graph). `notice-check` is fast (under a minute). `build-artifacts` is fast (`uv build` against a clean checkout, under two minutes). `create-release` is fast (envsubst + an API call to GitHub Releases, under thirty seconds).

### 6.2 When envsubst fires, when softprops triggers

Envsubst fires in the `create-release` job at the "Render release notes template" step (`release.yml:199-213`). It reads `.github/release-notes-template.md` and writes `.github/release-notes-rendered.md`, substituting `${RELEASE_TAG}` and `${RELEASE_VERSION}`. If the skill has already pre-rendered and committed `.github/release-notes-rendered.md`, the envsubst step writes the same content (idempotent) — the workflow does not know whether the file was pre-rendered or not.

`softprops/action-gh-release@v3` fires immediately after, at the "Create GitHub Release" step (`release.yml:215-222`). It creates the GitHub Release with `files: dist/*` (the wheel and the sdist), `draft: false`, `prerelease: <auto-detected from -rc>`, `generate_release_notes: true` (appends merged PR titles below the `### What's new` marker), and `body_path: .github/release-notes-rendered.md` (the content the maintainer or skill produced).

### 6.3 When the skill is in the loop and when it is not

The skill (`/release`) is in the loop for the maintainer-driven cutting flow: it walks `pyproject.toml` bump → CHANGELOG promote → body draft → commit → tag → push → uv build → either wait-for-workflow or run `gh release create` manually. The skill stops twice for review: after the body draft (STOP-point 1) and after the local build (STOP-point 2).

The skill is NOT in the loop for the workflow's unattended path. Once the maintainer pushes the tag, `release.yml` runs without any skill involvement — envsubst against the committed (already-rendered) body, then softprops, then done. A maintainer cutting a release without Claude Code in their environment can do every step by hand following §3; the workflow neither knows nor cares.

### 6.4 Tag-only path vs. manual `gh release create` path

The default path is workflow-driven: push the tag, wait for `release.yml` to finish, run one `gh release edit --title` to set the title-theme. This is the path the skill defaults to (STOP-point 2 question: "wait for the workflow, or override now?").

The manual path is the fallback when GitHub Actions is unavailable, the workflow is misconfigured, or the maintainer needs to ship before the workflow's wall-clock would allow. Per memory `project_release_manual_fallback.md` (manual GitHub Release fallback when `release.yml` fails), the commands are:

```bash
gh release create vX.Y.Z \
  --title "vX.Y.Z — <theme>" \
  --notes-file .github/release-notes-rendered.md \
  dist/wiedunflow-X.Y.Z-py3-none-any.whl \
  dist/wiedunflow-X.Y.Z.tar.gz
```

Add `--prerelease` for `-rc.N` / `-alpha.N` / `-beta.N` tags. Add `--target main` if the tag is not on `main` for some reason. The maintainer must run `pip-audit` and `scripts/aggregate_notice.py --check` locally before the manual `gh release create` — the workflow gates exist for a reason and the manual path skips them.

## 7. Troubleshooting

### 7.1 `release.yml` pip-audit gate fails

`pip-audit` reports a vulnerability against a dep in `uv.lock`. Two recovery paths:

1. **Upgrade away.** Find the fixed version (the OSV report gives it), bump the dep in `pyproject.toml`, run `uv lock`, re-commit, force-push the tag onto the new commit:
   ```bash
   git tag -d vX.Y.Z
   git tag -s vX.Y.Z -m "vX.Y.Z — <theme>"
   git push origin vX.Y.Z --force-with-lease
   ```
   `--force-with-lease` is safer than `--force` (it refuses if anyone else has updated the tag on the remote). Note: force-pushing a tag changes its meaning; if anyone has already pulled the previous tag, they will not auto-receive the new one.
2. **Allowlist with justification.** If the vulnerability does not apply to WiedunFlow's usage of the dep (e.g. a server-side feature we do not invoke), add an entry to the `pip-audit` allowlist embedded in `release.yml` itself. Every allowlist entry MUST carry a one-line justification (the workflow rejects entries without one). Re-trigger the workflow:
   ```bash
   gh workflow run release.yml --ref vX.Y.Z
   ```

### 7.2 `release.yml` notice-check fails

`scripts/aggregate_notice.py --check` reports that `NOTICE` is out of sync with the runtime Apache-2.0 deps. Recovery:

```bash
uv run python scripts/aggregate_notice.py --write
git add NOTICE
git commit -s -m "chore(release): regenerate NOTICE for vX.Y.Z"
```

Force-push the tag onto the new commit per the procedure in §7.1.

### 7.3 Manual fallback when GitHub Actions is down

Per memory `project_release_manual_fallback.md`: run `pip-audit` and `scripts/aggregate_notice.py --check` locally, run `uv build`, then `gh release create` with the manual flags. The commands are in §6.4. The flow takes about ten minutes of maintainer attention; the workflow flow takes about six minutes of wall-clock with two minutes of maintainer attention.

### 7.4 Tag created but push failed

The local tag exists, the remote tag does not. Two scenarios:

1. **Network glitch.** Retry the push:
   ```bash
   git push origin vX.Y.Z
   ```
   Safe — nothing on the remote has changed.
2. **The tag is wrong (e.g. the body in the commit had a typo).** Recover:
   ```bash
   git tag -d vX.Y.Z          # delete local tag
   git reset --soft HEAD~1    # un-commit the release commit, keep the working tree changes
   # fix the typo, re-stage, restart from Step 4 of the skill (or §3 of this playbook)
   ```
   Do NOT `git push --force` the tag if the previous version has already been pushed to a consumer-visible remote. The right move is to delete the broken tag on the remote (`git push origin :vX.Y.Z`), then push the corrected one — this is what the `--force-with-lease` flag does in one step.

### 7.5 Signed-tag rejected (no GPG key)

If `git tag -s` fails with "gpg failed to sign the data", the maintainer has no GPG key configured. Fall back to an annotated unsigned tag:

```bash
git tag -a vX.Y.Z -m "vX.Y.Z — <theme>"
```

Signing is recommended but not required by the workflow — neither `release.yml` nor GitHub Releases verify the signature. The skill warns when no key is configured and proceeds with the annotated form.

## 8. Conventions reference

### 8.1 Conventional Commits — types and scopes

Per `.pre-commit-config.yaml` line 66-77, the `conventional-pre-commit` hook enforces:

- **Types**: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`, `perf`, `build`, `ci`, `revert`.
- **Scopes** (enforced via `--force-scope`): `ingestion`, `analysis`, `graph`, `rag`, `planning`, `generation`, `build`, `cli`, `cache`, `config`, `deps`, `release`.

Release commits use `chore(release): vX.Y.Z — <theme>` for non-security flows and `fix(security): vX.Y.Z — <one-line>` for security patches.

### 8.2 SemVer rules — MAJOR / MINOR / PATCH

WiedunFlow follows SemVer 2.0.0 with the pre-PyPI clarification (per CLAUDE.md `## ADR_INDEX` entries for ADR-0016, ADR-0019, ADR-0020, ADR-0021): until PyPI publishing happens, "BREAKING" applies to internal Protocol surfaces and config field shapes. External users of the CLI do not have a stable API to depend on yet — the only stable surface is the CLI command name (`wiedunflow`), config file path (`tutorial.config.yaml`), and output filename pattern (`wiedunflow-<repo>.html`).

- **MAJOR (`vX.0.0`)** when X transitions: any breaking change visible to a CLI user (config field renamed without deprecation shim, command argument renamed, output format change), or any reserved-for-major architectural shift.
- **MINOR (`v0.X.0`)**: new features, internal Protocol changes (even breaking), new ADRs, large refactors. Most ADR-anchored changes are MINOR because the BREAKING is internal-only.
- **PATCH (`v0.X.Y`)**: bug fixes, security patches, dependency bumps, doc improvements, internal cleanup that does not change any contract.

### 8.3 PEP 440 wheel version vs. git tag

Stable releases: the wheel version equals the tag stripped of the leading `v`. Tag `v0.11.1` → wheel version `0.11.1`. The Install command in the rendered body uses both forms: `git+...@v0.11.1` (the tag) and `wiedunflow-0.11.1-...whl` (the wheel filename).

Prereleases: the tag form uses dash-and-dot (`v0.12.0-rc.1`, `v0.12.0-alpha.2`), the wheel form squashes the suffix per PEP 440 (`0.12.0rc1`, `0.12.0a2`). Set `[project].version` in `pyproject.toml` to the wheel form (e.g. `0.12.0rc1`); use the tag form only on the git tag itself. The envsubst step in `release.yml:208` derives `${RELEASE_VERSION}` as `${RELEASE_TAG#v}` — for a prerelease that yields `0.12.0-rc.1`, which is NOT the wheel form. For prereleases the maintainer must either edit the Install block by hand or accept that the rendered Install command will show the dash-and-dot form (which `uv pip install` accepts via the git URL but rejects via the wheel filename).

## 9. Future work

### 9.1 PyPI publishing

Deferred per project state at the time of writing. When PyPI publishing happens:

- Add the `pypa/gh-action-pypi-publish` step to `release.yml` (OIDC trusted-publishing, no long-lived tokens — per CLAUDE.md `## DEVOPS > GITHUB_ACTIONS`).
- Add a PyPI link to the Install section of the release-notes template (the `uv pip install wiedunflow==X.Y.Z` form, alongside the git+tag and wheel-asset forms).
- Reconsider the title-theme rule for chore patches: once PyPI shows the version list publicly, a bare-tag chore patch sticks out less than a themed one. The current ADR-0022 §D1 rule applies until then.

### 9.2 Reconsider `release-please` when a second active committer joins

The maintainer-overhead argument against `release-please` (§Alternatives Rejected in ADR-0022) is sensitive to maintainer count. With one maintainer, the editorial layer is faster to write by hand than to configure. With three or more, the automated bumping plus auto-generated CHANGELOG promotion plus release-PR pattern starts to pay back. Re-open the question when the second active committer ships their fifth PR.

### 9.3 Common Changelog inline prefixes — revisit if release count exceeds 50/year

The argument against Common Changelog (§Alternatives Rejected in ADR-0022) is sensitive to release density. With six weeks per ~3-5 releases, the per-release editorial layer carries the weight. With weekly releases (50+/year), the inline-prefix flat-list form starts to pay back because the per-section header cost dominates the per-bullet content cost. Re-open the question when the project's release cadence crosses one per week sustained.
