# Release Quality Rubric — WiedunFlow v0.1.0

## Purpose

This rubric codifies the human-judgment criteria for signing off on the v0.1.0 release (FR-76, US-066). It serves as the authoritative voice of developer experience quality beyond automated test coverage. A panel of three reviewers (author + two trusted developer friends) scores the generated tutorial for the MCP Python SDK reference corpus using three independent dimensions. The gate passes when the average score across all reviewers and dimensions meets or exceeds 3.0.

## Scale

Responses use a 5-point anchored scale:

| Score | Definition | Use case |
|-------|-----------|----------|
| **5** | Matches or exceeds hand-written reference quality | Tutorial is polished, complete, pedagogically sound |
| **4** | Close to hand-written quality; minor roughness | 1–2 narrative gaps or concept ordering issues; would not need rewrite |
| **3** | Usable with caveats | Tutorial teaches the material; reader may need external docs; some lessons feel rushed or thin |
| **2** | Requires significant rewriting to be useful | >3 broken narratives; concept dependencies out of order; hallucinated symbols; or major coverage gaps |
| **1** | Unusable; would not publish | Crashes during generation, completely incoherent output, or >30% of lessons skipped |

## Dimensions

### Coverage
**Definition**: Does the tutorial teach at least 70% of the reference concept list documented in the Anthropic Skilljar "Building MCP Clients" reference?

Scoring guidance:
- **5**: ≥90% of reference concepts are taught with clear examples.
- **4**: 75–90% coverage; 1–2 major concepts deferred to external docs.
- **3**: 70–75% coverage; reader must supplement with README or external guides.
- **2**: 50–70% coverage; large gaps in foundational concepts.
- **1**: <50% coverage or tutorial aborts before lesson 10.

### Accuracy
**Definition**: Are all code references grounded in the actual codebase (0 hallucinated symbols) and technically correct?

Scoring guidance:
- **5**: Every symbol reference exists; all code examples execute correctly; no conceptual errors.
- **4**: One minor hallucination or typo caught before publication; otherwise accurate.
- **3**: 1–2 ungrounded references or misleading statements; reader can still learn the core material.
- **2**: >2 hallucinations; factually incorrect explanations of async dispatch or type system.
- **1**: Widespread hallucinations (>10% of symbols); cascading errors in explanation.

### Narrative Flow
**Definition**: Does each lesson build logically on prior lessons without re-teaching material or jumping between concepts?

Scoring guidance:
- **5**: Progression feels natural; concepts introduced in dependency order; no redundancy.
- **4**: 1 instance of re-taught material or minor ordering quirk; generally coherent.
- **3**: 2–3 lessons feel slightly out of order; some concepts taught twice; reader must connect dots.
- **2**: Lessons jump between unrelated topics; poor pacing; reader gets lost.
- **1**: No discernible order; lessons feel random or contradict each other.

## Reviewers

- **Author**: Michał Kamiński (1 required, covers all 3 dimensions)
- **Trusted Developer Friends** (2 required, same rubric):
  1. [name / email] — [relationship or credentials]
  2. [name / email] — [relationship or credentials]

All three reviewers evaluate the same tutorial.html and provide independent scores.

## Gate Formula

```
gate_passes = (
  (avg_score_coverage >= 3.0) AND
  (avg_score_accuracy >= 3.0) AND
  (avg_score_narrative_flow >= 3.0) AND
  (avg(all_reviewers × all_dimensions) >= 3.0)
)
```

Where:
- `avg_score_coverage` = mean of all three reviewers' coverage scores
- `avg_score_accuracy` = mean of all three reviewers' accuracy scores
- `avg_score_narrative_flow` = mean of all three reviewers' narrative flow scores
- `avg(all_reviewers × all_dimensions)` = grand mean across all 9 scores

**Release decision**: Gate must pass before v0.1.0 can ship. Failure triggers ADR-0012 (3-strike policy, 3-day timebox).

## Archive and Aggregation

### Sign-off files
Each reviewer commits a signed-off YAML to the release branch at:
```
docs/rubric/v0.1.0/signoff-<reviewer_slug>.yaml
```

Example filenames:
- `signoff-michał-kamiński.yaml` (author)
- `signoff-alice-trusted-dev.yaml`
- `signoff-bob-trusted-dev.yaml`

### Aggregator output
After all three sign-offs are collected, run:
```bash
uv run python scripts/aggregate_rubric.py --dir docs/rubric/v0.1.0
```

This generates:
```
docs/rubric/v0.1.0/signoff-mcp-sdk.yaml
```

The aggregator emits an exit code:
- `0` = gate passed (avg ≥3.0 AND ≥3 reviewers with correct role mix)
- `1` = gate failed (insufficient reviewers or avg <3.0)

### GitHub Actions integration
The release workflow runs the aggregator as a blocking step before uploading assets to the GitHub Release. Failure blocks the release.

---

## Next: Reviewer Instructions

See [`docs/rubric/v0.1.0/reviewer-kit.md`](v0.1.0/reviewer-kit.md) for step-by-step setup and scoring instructions.
