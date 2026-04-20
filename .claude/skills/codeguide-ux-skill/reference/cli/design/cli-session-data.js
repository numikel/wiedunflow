/* CodeGuide CLI — session scripts.
   Each script is an array of "events" with a time offset (seconds from start)
   and either a line to append or a control directive.
   Event kinds:
     "line"      { t, text, tone? }                — print one line (tone: default|dim|good|warn|err|accent|link)
     "stream"    { t, lines: [{delay, text, tone}] } — stream multiple lines over time
     "spinner"   { t, label, duration }            — inline spinner that resolves to ✓
     "prompt"    { t, label, await: "gate" }       — interactive prompt
     "rule"      { t, style? }                     — horizontal rule
     "blank"     { t }                             — empty line
     "box"       { t, title, lines }               — boxed section
     "stage"     { t, num, name, duration, details } — rendered stage block
     "report"    { t, ... }
     "end"       { t }
*/

// Happy-path demo compressed to ~45s.
window.CLI_STATES = {
  happy: {
    label: "Happy path",
    desc: "Successful run · high confidence · 12 lessons · $2.29",
    total: 45,
    events: happyPath(),
  },
  degraded: {
    label: "Degraded",
    desc: "Grounding failures · 4 lessons skipped · tutorial still usable",
    total: 48,
    events: degradedPath(),
  },
  ratelimit: {
    label: "Rate limited",
    desc: "Anthropic 429 · exponential backoff · eventual success",
    total: 52,
    events: rateLimitedPath(),
  },
  failed: {
    label: "Failed",
    desc: "Network lost mid-run · stage 4 fails · clean rollback",
    total: 28,
    events: failedPath(),
  },
  abort: {
    label: "Cost-gate abort",
    desc: "User types 'no' at the confirmation gate · no money spent",
    total: 12,
    events: abortPath(),
  },
};

// ---------- helpers ----------
function intro() {
  return [
    { t: 0.0, kind: "line", text: "$ codeguide init https://github.com/kennethreitz/requests", tone: "prompt" },
    { t: 0.4, kind: "blank" },
    { t: 0.5, kind: "line", text: "CodeGuide 0.1.0 · claude-haiku-4-5 + claude-opus-4-5", tone: "dim" },
    { t: 0.9, kind: "blank" },
    { t: 1.0, kind: "line", text: "Preflight", tone: "accent" },
    { t: 1.1, kind: "line", text: "  ✓ git available (2.43.0)", tone: "good" },
    { t: 1.3, kind: "line", text: "  ✓ python 3.11.7", tone: "good" },
    { t: 1.5, kind: "line", text: "  ✓ ANTHROPIC_API_KEY present", tone: "good" },
    { t: 1.7, kind: "line", text: "  ✓ target is a public Python repo", tone: "good" },
    { t: 1.9, kind: "line", text: "  ✓ 47 .py files · est. 4 800 LOC · 18 top-level symbols", tone: "good" },
    { t: 2.1, kind: "blank" },
  ];
}

function costGate(tStart) {
  return [
    { t: tStart + 0.0, kind: "box", title: "Estimated cost", lines: [
      "Model      Stage                        Est. tokens       Est. cost",
      "haiku      stages 1-4 (analyse/cluster)     ~410 000          $0.41",
      "opus       stages 5-6 (narrate/ground)      ~280 000          $1.87",
      "─────────────────────────────────────────────────────────────────",
      "TOTAL                                       ~690 000          $2.28",
      "",
      "Runtime est. 18-26 min · 12 lessons across 4 concept clusters",
    ] },
    { t: tStart + 1.4, kind: "blank" },
    { t: tStart + 1.5, kind: "prompt", label: "Proceed? [y/N] ", await: "gate" },
  ];
}

function stage(tStart, num, name, duration, details) {
  const ev = [];
  ev.push({ t: tStart, kind: "line", text: `[${String(num).padStart(1,"0")}/7] ${name}`, tone: "accent" });
  details.forEach((d) => {
    ev.push({ t: tStart + d.dt, kind: "line", text: "     " + d.text, tone: d.tone || "default" });
  });
  ev.push({ t: tStart + duration - 0.1, kind: "line", text: `     ✓ done · ${details.summary || ""}`, tone: "good" });
  ev.push({ t: tStart + duration, kind: "blank" });
  return ev;
}

function happyPath() {
  const ev = intro();
  ev.push(...costGate(2.2));
  // After user answers y (at t≈5.5 in demo timing), pipeline starts
  const p = 6.0;
  // Stage 1 — Clone
  ev.push(...stageBlock(p + 0.0, 1, "Clone", 3.0, [
    { dt: 0.2, text: "cloning kennethreitz/requests@a1b2c3d ..." },
    { dt: 1.8, text: "cloned · 47 files · 4 812 LOC" },
    { dt: 2.2, text: "cost: $0.00 · elapsed 00:03" , tone: "dim" },
  ], "repo ready"));
  // Stage 2 — Static analyse
  ev.push(...stageBlock(p + 3.2, 2, "Static analyse (Jedi)", 5.0, [
    { dt: 0.3, text: "[  5/47] analysing requests/api.py", tone: "dim" },
    { dt: 1.1, text: "[ 12/47] analysing requests/sessions.py", tone: "dim" },
    { dt: 2.0, text: "[ 23/47] analysing requests/models.py", tone: "dim" },
    { dt: 3.0, text: "[ 36/47] analysing requests/adapters.py", tone: "dim" },
    { dt: 4.0, text: "[ 47/47] analysing requests/utils.py", tone: "dim" },
    { dt: 4.5, text: "symbol resolution 87% · 143/164 references linked" },
    { dt: 4.7, text: "cost: $0.00 · elapsed 00:08" , tone: "dim" },
  ], "87% symbol resolution"));
  // Stage 3 — Concept clustering (haiku)
  ev.push(...stageBlock(p + 8.4, 3, "Concept clustering · claude-haiku-4-5", 5.0, [
    { dt: 0.3, text: "tokens in 48 210 · out 3 812" },
    { dt: 2.0, text: "4 clusters identified:" },
    { dt: 2.2, text: "  · Foundations          (3 lessons)", tone: "dim" },
    { dt: 2.4, text: "  · Request lifecycle    (3 lessons)", tone: "dim" },
    { dt: 2.6, text: "  · Internals & utilities (4 lessons)", tone: "dim" },
    { dt: 2.8, text: "  · Closing               (2 lessons)", tone: "dim" },
    { dt: 4.5, text: "cost: $0.12 · cumulative $0.12 · elapsed 00:13", tone: "dim" },
  ], "4 clusters · 12 lessons"));
  // Stage 4 — Lesson outlining (haiku)
  ev.push(...stageBlock(p + 13.6, 4, "Lesson outlining · claude-haiku-4-5", 4.5, [
    { dt: 0.3, text: "tokens in 312 440 · out 28 990" },
    { dt: 1.5, text: "  ✓ overview / api-surface / sessions", tone: "good" },
    { dt: 2.3, text: "  ✓ prepared-request / adapters / response", tone: "good" },
    { dt: 3.2, text: "  ✓ models / auth / cookies / utils", tone: "good" },
    { dt: 3.9, text: "  ✓ exceptions / next", tone: "good" },
    { dt: 4.2, text: "cost: $0.29 · cumulative $0.41 · elapsed 00:18", tone: "dim" },
  ], "12 outlines approved"));
  // Stage 5 — Narration (opus)
  ev.push(...stageBlock(p + 18.3, 5, "Narration · claude-opus-4-5", 9.0, [
    { dt: 0.3, text: "tokens in 198 210 · out 81 420" },
    { dt: 1.0, text: "[ 1/12] narrating 'A library that hides HTTP's sharp edges'", tone: "dim" },
    { dt: 2.2, text: "[ 3/12] narrating 'Session — the real entry point'", tone: "dim" },
    { dt: 3.6, text: "[ 5/12] narrating 'HTTPAdapter — the connection pool'", tone: "dim" },
    { dt: 5.0, text: "[ 7/12] narrating 'Models — Request, PreparedRequest, Response'", tone: "dim" },
    { dt: 6.4, text: "[ 9/12] narrating 'Cookies — a jar and a dict'", tone: "dim" },
    { dt: 7.6, text: "[12/12] narrating 'Where to go next'", tone: "dim" },
    { dt: 8.4, text: "cost: $1.46 · cumulative $1.87 · elapsed 00:32", tone: "dim" },
  ], "12 lessons narrated"));
  // Stage 6 — Grounding (opus)
  ev.push(...stageBlock(p + 27.6, 6, "Grounding against AST", 5.0, [
    { dt: 0.3, text: "checking all symbol references against Jedi index ..." },
    { dt: 2.0, text: "  ✓ 164/164 code references verified", tone: "good" },
    { dt: 3.0, text: "  ✓ 47/47 file paths verified", tone: "good" },
    { dt: 4.0, text: "  ✓ confidence: HIGH (0 retries needed)", tone: "good" },
    { dt: 4.5, text: "cost: $0.41 · cumulative $2.28 · elapsed 00:41", tone: "dim" },
  ], "0 grounding failures"));
  // Stage 7 — Render + finalize
  ev.push(...stageBlock(p + 32.8, 7, "Render + finalize", 3.0, [
    { dt: 0.3, text: "rendering tutorial.html with Jinja2 + Pygments" },
    { dt: 1.0, text: "  ✓ inlining CSS (54 KB)", tone: "good" },
    { dt: 1.5, text: "  ✓ inlining JS (22 KB)", tone: "good" },
    { dt: 2.0, text: "  ✓ self-hosted fonts (118 KB)", tone: "good" },
    { dt: 2.5, text: "cost: $0.01 · total $2.29 · elapsed 00:45", tone: "dim" },
  ], "tutorial.html 412 KB"));
  // Report
  const r = p + 36.3;
  ev.push({ t: r, kind: "blank" });
  ev.push({ t: r + 0.1, kind: "report", status: "success", data: {
    lessons: 12, files: 47, coverage: 87,
    cost: 2.29, haiku: 0.41, opus: 1.87,
    elapsed: "00:45", tokens_in: 558860, tokens_out: 114222,
    link: "./codeguide-output/tutorial.html",
  } });
  ev.push({ t: r + 2.6, kind: "line", text: "$ ▌", tone: "prompt" });
  ev.push({ t: r + 3.0, kind: "end" });
  return ev;
}

function stageBlock(tStart, num, name, duration, details, summary) {
  const ev = [];
  ev.push({ t: tStart, kind: "line", text: `[${num}/7] ${name}`, tone: "accent" });
  details.forEach((d) => {
    ev.push({ t: tStart + d.dt, kind: "line", text: "     " + d.text, tone: d.tone || "default" });
  });
  ev.push({ t: tStart + duration - 0.1, kind: "line", text: `     ✓ done · ${summary}`, tone: "good" });
  ev.push({ t: tStart + duration, kind: "blank" });
  return ev;
}

// Degraded — same spine but stage 6 reports 4 failures + retry + final degraded report.
function degradedPath() {
  const ev = happyPath();
  // Find and truncate at stage 6; rebuild tail
  const cutAt = ev.findIndex(e => e.kind === "line" && e.text && e.text.startsWith("[6/7]"));
  const pipelineStart = 6.0;
  const base = ev.slice(0, cutAt);
  const p = pipelineStart;
  // Replace stage 6 with grounding failures
  base.push(...stageBlock(p + 27.6, 6, "Grounding against AST", 6.0, [
    { dt: 0.3, text: "checking all symbol references against Jedi index ..." },
    { dt: 1.5, text: "  ! lesson 'cookies': 3 unresolved references in requests/cookies.py", tone: "warn" },
    { dt: 2.4, text: "  ! lesson 'utils':   2 unresolved references in requests/utils.py", tone: "warn" },
    { dt: 3.0, text: "  ⟳ retry with pyright fallback (v2+) — not enabled", tone: "dim" },
    { dt: 4.0, text: "  ✓ 146/164 code references verified (4 lessons flagged)", tone: "good" },
    { dt: 4.8, text: "  ⚠ degraded run: 4 of 12 lessons will be marked SKIPPED", tone: "warn" },
    { dt: 5.5, text: "cost: $0.52 · cumulative $2.39 · elapsed 00:43", tone: "dim" },
  ], "8 lessons grounded · 4 skipped"));
  base.push(...stageBlock(p + 33.8, 7, "Render + finalize", 3.0, [
    { dt: 0.3, text: "rendering tutorial.html with degraded banner" },
    { dt: 1.0, text: "  ✓ inlining 8 narrated + 4 skipped placeholders", tone: "good" },
    { dt: 2.0, text: "  ✓ run_status = \"degraded\"", tone: "good" },
    { dt: 2.5, text: "cost: $0.01 · total $2.40 · elapsed 00:47", tone: "dim" },
  ], "tutorial.html 398 KB · degraded"));
  const r = p + 37.3;
  base.push({ t: r, kind: "blank" });
  base.push({ t: r + 0.1, kind: "report", status: "degraded", data: {
    lessons: 12, lessons_skipped: 4, files: 47, coverage: 64,
    cost: 2.40, haiku: 0.41, opus: 1.98,
    elapsed: "00:47", tokens_in: 576410, tokens_out: 119840,
    link: "./codeguide-output/tutorial.html",
    skipped: ["cookies", "utils", "auth", "exceptions"],
  }});
  base.push({ t: r + 3.0, kind: "line", text: "$ ▌", tone: "prompt" });
  base.push({ t: r + 3.4, kind: "end" });
  return base;
}

// Rate-limited — stage 5 hits 429s and backs off, eventual success.
function rateLimitedPath() {
  const ev = happyPath();
  const cutAt = ev.findIndex(e => e.kind === "line" && e.text && e.text.startsWith("[5/7]"));
  const base = ev.slice(0, cutAt);
  const p = 6.0;
  base.push(...stageBlock(p + 18.3, 5, "Narration · claude-opus-4-5", 15.0, [
    { dt: 0.3, text: "tokens in 198 210 · out 81 420" },
    { dt: 1.0, text: "[ 1/12] narrating 'A library that hides HTTP's sharp edges'", tone: "dim" },
    { dt: 2.5, text: "[ 3/12] narrating 'Session — the real entry point'", tone: "dim" },
    { dt: 3.8, text: "  ⚠ HTTP 429 rate_limit_error (tokens-per-minute)", tone: "warn" },
    { dt: 4.0, text: "  ⟳ backoff 2s (attempt 1/5)", tone: "dim" },
    { dt: 6.2, text: "  ⚠ HTTP 429 rate_limit_error", tone: "warn" },
    { dt: 6.4, text: "  ⟳ backoff 4s (attempt 2/5)", tone: "dim" },
    { dt: 10.6, text: "  ✓ resumed · rate-limit window cleared", tone: "good" },
    { dt: 11.5, text: "[ 7/12] narrating 'Models — Request, PreparedRequest, Response'", tone: "dim" },
    { dt: 13.0, text: "[12/12] narrating 'Where to go next'", tone: "dim" },
    { dt: 14.4, text: "cost: $1.46 · cumulative $1.87 · elapsed 00:38 (6s in backoff)", tone: "dim" },
  ], "12 lessons narrated (2 retries)"));
  base.push(...stageBlock(p + 33.6, 6, "Grounding against AST", 5.0, [
    { dt: 0.3, text: "checking all symbol references against Jedi index ..." },
    { dt: 3.0, text: "  ✓ 164/164 code references verified", tone: "good" },
    { dt: 4.0, text: "  ✓ confidence: HIGH", tone: "good" },
    { dt: 4.5, text: "cost: $0.41 · cumulative $2.28 · elapsed 00:48", tone: "dim" },
  ], "0 grounding failures"));
  base.push(...stageBlock(p + 38.8, 7, "Render + finalize", 3.0, [
    { dt: 0.3, text: "rendering tutorial.html" },
    { dt: 2.5, text: "cost: $0.01 · total $2.29 · elapsed 00:52", tone: "dim" },
  ], "tutorial.html 412 KB"));
  const r = p + 42.3;
  base.push({ t: r, kind: "blank" });
  base.push({ t: r + 0.1, kind: "report", status: "success", data: {
    lessons: 12, files: 47, coverage: 87,
    cost: 2.29, haiku: 0.41, opus: 1.87,
    elapsed: "00:52", tokens_in: 558860, tokens_out: 114222,
    link: "./codeguide-output/tutorial.html",
    note: "2 rate-limit retries absorbed (6.0s total backoff)",
  }});
  base.push({ t: r + 3.0, kind: "line", text: "$ ▌", tone: "prompt" });
  base.push({ t: r + 3.4, kind: "end" });
  return base;
}

// Failed — network dies mid stage 4.
function failedPath() {
  const ev = intro();
  ev.push(...costGate(2.2));
  const p = 6.0;
  ev.push(...stageBlock(p + 0.0, 1, "Clone", 3.0, [
    { dt: 0.2, text: "cloning kennethreitz/requests@a1b2c3d ..." },
    { dt: 1.8, text: "cloned · 47 files · 4 812 LOC" },
  ], "repo ready"));
  ev.push(...stageBlock(p + 3.2, 2, "Static analyse (Jedi)", 5.0, [
    { dt: 2.0, text: "[ 23/47] analysing requests/models.py", tone: "dim" },
    { dt: 4.5, text: "symbol resolution 87% · 143/164 references linked" },
  ], "87% symbol resolution"));
  ev.push(...stageBlock(p + 8.4, 3, "Concept clustering · claude-haiku-4-5", 5.0, [
    { dt: 2.0, text: "4 clusters identified · 12 lessons" },
    { dt: 4.0, text: "cost: $0.12 · cumulative $0.12", tone: "dim" },
  ], "4 clusters"));
  // Stage 4 fails
  ev.push({ t: p + 13.6, kind: "line", text: "[4/7] Lesson outlining · claude-haiku-4-5", tone: "accent" });
  ev.push({ t: p + 14.3, kind: "line", text: "     [ 3/12] outlining 'sessions'", tone: "dim" });
  ev.push({ t: p + 15.6, kind: "line", text: "     [ 5/12] outlining 'prepared-request'", tone: "dim" });
  ev.push({ t: p + 16.8, kind: "line", text: "     ✗ network error: ConnectionResetError (api.anthropic.com)", tone: "err" });
  ev.push({ t: p + 17.2, kind: "line", text: "     ⟳ retry 1/3 in 2s", tone: "dim" });
  ev.push({ t: p + 19.4, kind: "line", text: "     ✗ network error: ConnectionResetError", tone: "err" });
  ev.push({ t: p + 19.8, kind: "line", text: "     ⟳ retry 2/3 in 4s", tone: "dim" });
  ev.push({ t: p + 23.9, kind: "line", text: "     ✗ network error: ConnectionResetError", tone: "err" });
  ev.push({ t: p + 24.3, kind: "line", text: "     ⚠ exhausted retries. aborting pipeline.", tone: "err" });
  ev.push({ t: p + 24.5, kind: "blank" });
  const r = p + 25.0;
  ev.push({ t: r, kind: "report", status: "failed", data: {
    failed_at: "stage 4 (lesson outlining)",
    reason: "network unavailable after 3 retries",
    cost: 0.17, haiku: 0.17, opus: 0.00,
    elapsed: "00:36",
    cleanup: "partial artefacts in ./codeguide-output/.cache retained for resume",
    resume_hint: "codeguide init --resume <run-id>",
  }});
  ev.push({ t: r + 3.0, kind: "line", text: "$ ▌", tone: "prompt" });
  ev.push({ t: r + 3.4, kind: "end" });
  return ev;
}

// Abort — user declines cost gate.
function abortPath() {
  const ev = intro();
  ev.push(...costGate(2.2));
  // Prompt completes at 3.7, user types 'no'
  // app.js sees "await: gate" and waits; on resume with answer=no we push abort events
  const r = 4.0;
  ev.push({ t: r + 0.0, kind: "blank" });
  ev.push({ t: r + 0.1, kind: "line", text: "aborted by user. no API calls were made.", tone: "dim" });
  ev.push({ t: r + 0.5, kind: "line", text: "total cost: $0.00 · elapsed 00:04", tone: "dim" });
  ev.push({ t: r + 1.0, kind: "blank" });
  ev.push({ t: r + 1.5, kind: "line", text: "$ ▌", tone: "prompt" });
  ev.push({ t: r + 2.0, kind: "end" });
  return ev;
}
