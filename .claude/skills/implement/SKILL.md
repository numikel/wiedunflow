---
name: implement
user-invocable: true
description: Plan then auto-implement — runs planning-header first, then automatically starts implementation after plan approval (no extra prompt needed). Use for any coding task. Examples: /implement US-023, /implement "Sprint 0 Foundation", /implement "add BM25 index".
---

# Implement Skill — Plan → Approve → Implement

Automatyczny pipeline: planowanie (planning-header rules) → zatwierdzenie planu przez użytkownika → natychmiastowa implementacja.

## Trigger
`/implement <task-description>`

Przykłady:
- `/implement US-023`
- `/implement "Sprint 0 Foundation"`
- `/implement "Track A Sprint 2: tree-sitter parser"`
- `/implement T-001.5`

## PHASE 1 — PLANNING

Invoke the `planning-header` skill with the user's task passed as `args`. This activates all mandatory planning rules:

1. Use subagents per their competencies for research and design.
2. Use Context7 MCP for up-to-date library/framework documentation.
3. Define parallel steps where possible (agent teams for independent tracks).
4. Apply Socratic method — ask ≥5 questions before committing to decisions.
5. End planning with documentation updates (README, CHANGELOG, CLAUDE.md if needed).
6. Ask about version bump level (major/minor/patch) and recommend based on scope.
7. Include test expansion as the final implementation step.

Write the final plan to the plan file and call ExitPlanMode to present it to the user.

## PHASE 2 — AUTOMATIC IMPLEMENTATION

**CRITICAL: Once the user approves the plan (ExitPlanMode returns with approval), do NOT wait for an additional user message. Begin implementing the approved plan immediately.**

### Implementation rules

- Read the approved plan file before writing a single line of code.
- Execute tasks in the order defined in the plan (respecting dependencies).
- For parallel tracks: spawn agent teams in a **single message** (multiple Agent tool calls simultaneously).
- After all parallel tracks complete: verify no cross-track conflicts before proceeding.
- Apply Clean Architecture layer separation per CLAUDE.md (entities → use_cases → interfaces → adapters → cli).
- Per-task DoD: code + tests (pytest, all AC as separate test cases) + docs update + conventional commit + DCO `Signed-off-by:`.
- Lint after every task: `ruff check && ruff format --check && mypy --strict src/...`.

### Verification (after all tasks)

Run the full local verification suite:
```
uv sync && ruff check && ruff format --check && mypy --strict src/codeguide/** && pytest
```

If CI config exists: confirm CI matrix would pass (GitHub Actions equivalent steps).

### Final report

After successful verification, report:
- Tasks completed (list)
- Tests added / updated
- Files modified
- Version bump applied (if any)
- Next recommended action (e.g., next sprint task, pending US)

## Behavior flow

```
User: /implement <task>
  ↓
PHASE 1: planning-header rules active
  ↓ Explore agents (codebase recon)
  ↓ Plan agent (design)
  ↓ Socratic Q&A with user (≥5 questions)
  ↓ Write plan file → ExitPlanMode
  ↓ User sees plan → approves
  ↓ [AUTOMATIC — no extra prompt]
PHASE 2: implementation
  ↓ Agent teams (parallel tracks if plan defines them)
  ↓ Per-task: code + tests + docs + commit
  ↓ Verification suite
  ↓ Final report
```
