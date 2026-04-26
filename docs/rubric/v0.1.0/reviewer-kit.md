# Release Quality Review — Reviewer Kit

Welcome! You are reviewing CodeGuide v0.1.0 for the MCP Python SDK. This kit walks you through setup, generation, scoring, and submission in 60–90 minutes.

## Setup (One-time, ~10 minutes)

### Step 1: Clone the repository with submodules

```bash
git clone https://github.com/numikel/code-guide.git
cd codeguide
git submodule update --init
```

### Step 2: Install dependencies

```bash
uv sync
```

### Step 3: Set up API access

CodeGuide requires an Anthropic API key. If you don't have one:
- Visit [console.anthropic.com](https://console.anthropic.com)
- Create an account or sign in
- Generate an API key
- Export it to your environment:

```bash
# macOS / Linux
export ANTHROPIC_API_KEY=sk-ant-...

# Windows PowerShell
$env:ANTHROPIC_API_KEY = "sk-ant-..."
```

Verify it's set:
```bash
echo $ANTHROPIC_API_KEY
```

## Generation (~30 minutes)

### Step 4: Generate the tutorial

The MCP Python SDK is already pinned as a Git submodule. Generate the tutorial:

```bash
uv run codeguide tests/eval/corpus/repos/python-sdk-mcp \
  --yes \
  --config tests/eval/configs/python-sdk-mcp.yaml
```

This will:
1. Run the full 7-stage pipeline
2. Estimate cost before proceeding (should be ~$5–8)
3. Generate `tutorial.html` in the current directory
4. Print a completion summary with elapsed time and cost

The first run typically takes 15–25 minutes depending on API latency and your machine.

### Troubleshooting

**Error: `ANTHROPIC_API_KEY not found`**
- Ensure you ran `export ANTHROPIC_API_KEY=...` in the same terminal session.
- Or: edit `~/.config/codeguide/config.yaml` and set `api_key: sk-ant-...` in the `anthropic` section.

**Error: `tests/eval/corpus/repos/python-sdk-mcp: no such file`**
- Run `git submodule update --init` to clone the reference repos.

**Cost estimate is much higher than $8**
- The config file `tests/eval/configs/python-sdk-mcp.yaml` may override the model. Check it and use:
  ```bash
  --model-plan claude-sonnet-4-6 --model-narrate claude-opus-4-7
  ```

**Generation stops at Stage N with a timeout**
- Network latency to Anthropic. Re-run with `--resume` to continue from that lesson.

## Scoring (~40–50 minutes)

### Step 5: Read the reference material

Open `tutorial.html` in your browser (any modern browser, no server required).

**Key points to evaluate:**
1. **Does the tutorial teach MCP client fundamentals?** (coverage)
   - Protocol structure and message flow
   - Client initialization and configuration
   - Request/response lifecycle
   - Error handling and edge cases

2. **Are code examples correct and runnable?** (accuracy)
   - Every `function_name` or `ClassName` reference should exist in the actual SDK
   - Type signatures should match the source
   - Examples should not hallucinate non-existent methods or classes

3. **Do lessons follow a logical progression?** (narrative flow)
   - Earlier lessons introduce foundational concepts
   - Later lessons build on prior knowledge
   - No critical concepts skipped or taught twice unexpectedly

**Compare against the reference** (Michał will provide the Anthropic Skilljar "Building MCP Clients" link privately, or email him):
- Does the CodeGuide tutorial cover the same material?
- Is the depth appropriate for a developer learning MCP?
- Are there obvious gaps?

### Step 6: Fill out the sign-off YAML

1. Copy `docs/rubric/v0.1.0/template.yaml` to a new file:
   ```bash
   cp docs/rubric/v0.1.0/template.yaml docs/rubric/v0.1.0/signoff-your-name.yaml
   ```

2. Replace the placeholder values:
   - `reviewer: "Your Full Name"`
   - `reviewer_role: "trusted_friend"` (or "author" if you are Michał)
   - `reviewed_at: "2026-04-24"` (today's date)
   - `tutorial_hash: "sha256:..."` (run `sha256sum tutorial.html` on Linux/macOS, or use PowerShell `Get-FileHash tutorial.html -Algorithm SHA256`)
   - `scores.coverage`, `scores.accuracy`, `scores.narrative_flow` (1–5 each)
   - `rationale.*` (2–5 sentences each, honest and specific)
   - `comments` (optional, free-form feedback)

3. Be honest. A score of 3 ("usable with caveats") is not a failure — it's realistic for an AI-generated tutorial. Only rate 5 if it rivals the hand-written reference.

### Step 7: Submit your sign-off

Choose one:

**Option A: Direct commit to the release branch**
```bash
git add docs/rubric/v0.1.0/signoff-your-name.yaml
git commit -m "chore(release): sign-off from <your-name> on v0.1.0 rubric (US-066)"
git push origin feat/sprint-7-release-gate
```

**Option B: Email to Michał**
Attach `signoff-your-name.yaml` and email to michał (Michał will add it to the repo).

## Timebox

**Total time: 60–90 minutes**
- Setup: ~10 min
- Generation: ~25 min
- Reference review: ~15 min
- Scoring: ~20 min
- Submission: ~2 min

If you cannot complete within the timebox, **tell Michał ASAP** (michał@...) so he can plan for delays.

## FAQ

**Q: Can I review on a different repository (not MCP SDK)?**  
A: No. v0.1.0 is gated on the MCP Python SDK specifically (PRD §3.15, FR-76). The reference tutorials and Skilljar comparison are for MCP only.

**Q: What if I find a hallucinated symbol?**  
A: Note it in your rationale or comments. Lower the accuracy score accordingly. This is data we need.

**Q: What if the tutorial generation crashes?**  
A: Email Michał with the error message and stack trace. Do not attempt to fix it yourself; let him know you cannot complete the review due to pipeline failure.

**Q: Can I change the score after submitting?**  
A: Yes. Edit the YAML file, update `reviewed_at` to today's date, and re-commit (or re-email).

**Q: Who else is reviewing?**  
A: Michał (author) + 2 trusted developer friends (names TBD). You can compare notes, but scores must be independent.

---

**Thank you for reviewing CodeGuide.** Your feedback directly shapes the quality bar for the release.

For questions, reach out to Michał Kamiński (michał@...).
