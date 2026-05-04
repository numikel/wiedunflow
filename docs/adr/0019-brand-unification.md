# ADR-0019: Brand unification — single canonical `wiedunflow`, drop `wiedun-flow`

- **Status**: Accepted
- **Date**: 2026-05-02
- **Deciders**: Michał Kamiński (product owner)
- **Related**: v0.9.1 release
- **Supersedes (partial)**: ADR-0013 §1 (Hybrid mode wording — every reference to the CLI binary as `wiedun-flow`)

## Context

The v0.6.0 rebrand from CodeGuide to WiedunFlow (2026-04-26) introduced a deliberately mixed naming convention to satisfy two competing constraints:

| Form | Where used | Why |
|------|------------|-----|
| `wiedunflow` (no hyphen) | Python package, PyPI dist name, env prefix `WIEDUNFLOW_*`, localStorage `wiedunflow:*`, cache dir `.wiedunflow/`, output filename, GitHub repo, logger names | Python identifier rules (PEP-8 / PEP-423) — package names must not contain a hyphen |
| `wiedun-flow` (hyphenated) | CLI command in `[project.scripts]` and every place that referenced the binary | Unix kebab-case convention for user-facing CLI tools (matches `pre-commit`, `pip-compile`, `ruff-lsp`) |
| `WiedunFlow` (CamelCase) | Prose: README header, ADR text, banner ASCII art, HTML footer | Proper noun / brand display |

The split was technically defensible (it mirrors `pip` vs `pip-tools` vs `pip-compile` patterns in the broader Python ecosystem) and was documented in the rebranding session journal `2026-04-26-1729-ok-kontunnujmy.md` and memory entry `project_github_username.md` as a deliberate UX decision ("CLI komenda zachowała myślnik dla czytelności").

In practice, the split read as **inconsistency** to the product owner. Two forms of the same brand sitting side-by-side in `pyproject.toml`, README, and CLAUDE.md created a low-grade friction every time someone wrote `wiedun-flow` in the install instructions but `wiedunflow` in the env var. With the project still pre-PyPI (per `project_v0.9.0_ship_complete.md` memory), the cost of unification is essentially zero — there are no installed users whose binary path or shell aliases would break.

## Decision

**Drop `wiedun-flow` everywhere. The single canonical form is `wiedunflow` (lowercase, no hyphen). `WiedunFlow` (CamelCase) is preserved as the brand display form in prose only.**

Concrete changes (all in v0.9.1):

1. **`[project.scripts]`** — `wiedun-flow = "wiedunflow.cli.main:main"` becomes `wiedunflow = "wiedunflow.cli.main:main"`. After this release `wiedun-flow` is **not** registered as a console script.
2. **`prog_name`** in `@click.version_option` — `"wiedun-flow"` → `"wiedunflow"`.
3. **All docstrings, comments, README install/quickstart sections, ADR prose, CLI help text, banner taglines** — replace `wiedun-flow` with `wiedunflow`. Single mechanical search-and-replace; verified by `Grep "wiedun-flow"` returning zero matches across the repo (excluding historical CHANGELOG entry for v0.6.0 which is annotated with a forward-pointer to this ADR).
4. **All test-suite references** — including the `python -m wiedun-flow` calls in `tests/eval/test_s3_click_baseline.py` and `tests/integration/test_zero_telemetry.py`, which were silent bugs (`-m` cannot resolve a module with a hyphen) — replaced with `python -m wiedunflow`.
5. **Architectural lint test path drift fix (mimochodem)** — `tests/unit/cli/test_no_rich_outside_output.py`, `test_no_questionary_outside_menu.py`, `test_no_httpx_outside_litellm_pricing.py` had `_SRC_ROOT = .../src/wiedun-flow` (no such directory; the real path is `src/wiedunflow`). The lint tests were silently passing on empty `rglob()` iterations since v0.6.0. Fixed in this same PR — they now actually scan the source tree.
6. **No env var rename / no cache dir rename / no localStorage namespace change.** Those were already `wiedunflow*` (no hyphen) before v0.9.1; they are **not** affected by this decision.
7. **No `WiedunFlow` CamelCase change.** Brand display in README headers, ADR prose, banner ASCII, HTML footer, and CHANGELOG entries is preserved. The decision targets the hyphenated-vs-not-hyphenated lowercase split only.

### Alternatives considered and rejected

- **Status quo (mixed convention) + new `BRAND.md` documenting it.** Cheapest option; preserves the ergonomic kebab-case CLI. Rejected by product owner: explanation does not eliminate the friction, only formalizes it. Long-term cost of every new contributor needing to internalize the split exceeds the one-time cost of unification.
- **Push hyphenation everywhere (`wiedun-flow` as package name).** Technically impossible — Python package names cannot contain a hyphen (PEP-8, PEP-423). Would require either an underscore (`wiedun_flow`, ugly) or a different separator scheme entirely. Discarded immediately.
- **Defer to v1.0.0 and bundle with PyPI publish.** Rejected: v0.9.1 is the right time precisely because there are no PyPI users yet. Doing this at v1.0 means a MAJOR-bump-worthy change buried in a release that should focus on stabilization.

## Consequences

### Positive

- **One brand token to remember.** `wiedunflow` is now the answer to "what's it called" regardless of whether the question is about the package, the CLI, the env var, the cache, the localStorage namespace, or the GitHub repo. CamelCase form is reserved for prose.
- **Test-suite bugs fixed mimochodem.** The architectural lint tests now actually scan the source tree (they had been no-ops since v0.6.0). The `python -m wiedun-flow` invocations in eval tests now resolve correctly.
- **No user migration cost.** Pre-PyPI status (verified via `project_v0.9.0_ship_complete.md` memory) means zero installed binaries, zero shell aliases, zero CI scripts in the wild.

### Negative

- **Slightly less ergonomic CLI.** `wiedunflow init` reads as one mashed-together word; `wiedun-flow init` separated the brand visually. Rationalized by the product owner as worth the trade for unification.
- **Historical session journals (`2026-04-26-1729`) and memory entry `project_github_username.md` are now partially stale.** Both are updated in v0.9.1: `project_github_username.md` revokes the "myślnik dla czytelności" claim; a new `project_v0.9.1_brand_unification.md` records the current truth.
- **PATCH bump (v0.9.1) for what is technically a breaking change.** Defended by SemVer §4: in 0.x series anything may change at any time. Pre-PyPI status removes the user-impact concern that normally forces MAJOR semver-wise.

## Implementation note

Single PR `chore/brand-unification-wiedunflow` on branch off `main`. Single commit with conventional-commits header `chore!(cli): unify brand to "wiedunflow", drop "wiedun-flow"` and a `BREAKING CHANGE` footer in the body. DCO sign-off required (per project policy). Tag `v0.9.1` after merge.

Verification gate: `Grep "wiedun-flow"` over the whole repo (excluding `.git/`, `.venv/`, `dist/`) returns zero matches except one annotated CHANGELOG line for the v0.6.0 historical entry, which carries a `(further unified to wiedunflow in v0.9.1 — see ADR-0019)` pointer.
