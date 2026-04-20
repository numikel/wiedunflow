/* CodeGuide CLI player — play/pause, scrubber, speed, skip stage, restart,
   interactive cost-gate, state presets. */

(function () {
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => Array.from(el.querySelectorAll(s));

  const termEl = $("#term");
  const scrubberEl = $("#scrubber");
  const scrubberFill = $("#scrubber-fill");
  const timeRead = $("#time-read");
  const btnPlay = $("#btn-play");
  const btnRestart = $("#btn-restart");
  const btnSkip = $("#btn-skip");
  const speedGroup = $("#speed-group");
  const statePicker = $("#state-picker");
  const dirTabs = $("#dir-tabs");
  const statusbarTime = $("#sb-time");
  const statusbarCost = $("#sb-cost");
  const statusbarState = $("#sb-state");
  const statusbarTokens = $("#sb-tokens");
  const tweaksBtn = $("#tweaks-btn");
  const tweaksPanel = $("#tweaks");

  // ---------- Runtime state ----------
  const st = {
    stateKey: localStorage.getItem("cg-cli:state") || "happy",
    dir: localStorage.getItem("cg-cli:dir") || "modern",
    theme: localStorage.getItem("cg-cli:theme") || "dark",
    speed: parseFloat(localStorage.getItem("cg-cli:speed") || "1"),
    // Playback
    t0: 0,                      // performance.now() when play started
    clockOffset: 0,             // seconds already consumed
    playing: false,
    eventIdx: 0,
    awaiting: null,             // "gate" when waiting on interactive prompt
    gateAnswer: null,           // "y" | "n"
    currentSpinner: null,
    // Live counters
    cost: 0, tokens_in: 0, tokens_out: 0,
    elapsedLabel: "00:00",
  };

  // ---------- Apply root attributes ----------
  function applyRoot() {
    document.documentElement.dataset.dir = st.dir;
    document.documentElement.dataset.theme = st.theme;
    // Button ons
    $$("[data-state]", statePicker).forEach(b => b.classList.toggle("on", b.dataset.state === st.stateKey));
    $$("[data-dir]", dirTabs).forEach(b => b.classList.toggle("on", b.dataset.dir === st.dir));
    $$("[data-speed]", speedGroup).forEach(b => b.classList.toggle("on", parseFloat(b.dataset.speed) === st.speed));
    // Tweaks segs
    $$(".seg[data-key]").forEach(seg => {
      const key = seg.dataset.key;
      const val = st[key];
      $$("button", seg).forEach(b => b.classList.toggle("on", b.dataset.v === String(val)));
    });
    // Subtitle for state
    const cfg = window.CLI_STATES[st.stateKey];
    statusbarState.querySelector(".v").textContent = cfg ? cfg.label : st.stateKey;
    $("#scene-sub").textContent = cfg ? cfg.desc : "";
  }

  // ---------- Terminal rendering ----------
  function clearTerm() {
    termEl.innerHTML = "";
  }
  function renderCaret() {
    const c = document.createElement("span");
    c.className = "caret";
    c.setAttribute("data-caret", "1");
    return c;
  }
  function removeCaret() {
    const c = termEl.querySelector("[data-caret='1']");
    if (c) c.remove();
  }
  function scrollToEnd() {
    termEl.scrollTop = termEl.scrollHeight;
  }
  function addLine(text, tone = "default") {
    removeCaret();
    const d = document.createElement("div");
    d.className = "ln tone-" + tone;
    if (!text || !text.length) d.classList.add("blank");
    d.textContent = text || "";
    termEl.appendChild(d);
    // Caret trails on prompt lines that end with space + cursor slot
    scrollToEnd();
    return d;
  }
  function addBlank() {
    return addLine("", "default");
  }
  function addBox(title, lines) {
    removeCaret();
    const wrap = document.createElement("div");
    wrap.className = "box";
    const t = document.createElement("div");
    t.className = "title"; t.textContent = title;
    const pre = document.createElement("pre");
    pre.textContent = lines.join("\n");
    wrap.appendChild(t); wrap.appendChild(pre);
    termEl.appendChild(wrap);
    scrollToEnd();
  }
  function addPrompt(label, awaitKey) {
    removeCaret();
    const row = document.createElement("div");
    row.className = "ln prompt-row";
    const labEl = document.createElement("span");
    labEl.className = "label";
    labEl.textContent = label;
    const inp = document.createElement("input");
    inp.type = "text";
    inp.autocomplete = "off";
    inp.spellcheck = false;
    inp.placeholder = "y / n";
    inp.setAttribute("aria-label", label);
    row.appendChild(labEl);
    row.appendChild(inp);
    termEl.appendChild(row);
    scrollToEnd();

    st.awaiting = awaitKey;
    pausePlayback(); // halt the clock until resolved
    setTimeout(() => inp.focus(), 30);
    inp.addEventListener("keydown", (ev) => {
      if (ev.key !== "Enter") return;
      const raw = inp.value.trim().toLowerCase();
      const ans = raw === "y" || raw === "yes" ? "y" : "n";
      inp.disabled = true;
      inp.value = raw || (ans === "y" ? "y" : "no");
      // Render the typed response inline as text, then decide next
      st.gateAnswer = ans;
      st.awaiting = null;
      if (ans === "y") {
        // Continue happy/degraded/ratelimit/failed scripts — pipeline starts after this event
        // We just resume the clock.
        resumePlayback();
      } else {
        // Switch to abort tail
        switchToAbortTail();
      }
    });
  }
  function addReport(status, data) {
    removeCaret();
    const r = document.createElement("div");
    r.className = "report status-" + status;
    const hd = document.createElement("div"); hd.className = "hd";
    hd.textContent = status === "success" ? "✓ RUN COMPLETE"
      : status === "degraded" ? "⚠ RUN DEGRADED"
      : "✗ RUN FAILED";
    r.appendChild(hd);
    const rows = [];
    if (status === "failed") {
      rows.push(["failed at", data.failed_at]);
      rows.push(["reason", data.reason]);
      rows.push(["elapsed", data.elapsed]);
      rows.push(["cost", `$${data.cost.toFixed(2)} (haiku $${data.haiku.toFixed(2)} · opus $${data.opus.toFixed(2)})`]);
      rows.push(["cleanup", data.cleanup]);
      rows.push(["resume", data.resume_hint]);
    } else {
      rows.push(["lessons", status === "degraded"
        ? `${data.lessons - data.lessons_skipped} of ${data.lessons} narrated · ${data.lessons_skipped} skipped`
        : `${data.lessons} of ${data.lessons} narrated`]);
      rows.push(["files analysed", `${data.files} python files · ${data.coverage}% symbol coverage`]);
      rows.push(["elapsed", data.elapsed]);
      rows.push(["cost", `$${data.cost.toFixed(2)} (haiku $${data.haiku.toFixed(2)} · opus $${data.opus.toFixed(2)})`]);
      rows.push(["tokens", `${data.tokens_in.toLocaleString("en-US").replace(/,/g," ")} in · ${data.tokens_out.toLocaleString("en-US").replace(/,/g," ")} out`]);
      if (data.skipped) rows.push(["skipped", data.skipped.join(", ")]);
      if (data.note) rows.push(["note", data.note]);
    }
    rows.forEach(([k, v]) => {
      const row = document.createElement("div"); row.className = "row";
      const lab = document.createElement("label"); lab.textContent = k;
      const sp = document.createElement("span"); sp.textContent = v;
      row.appendChild(lab); row.appendChild(sp); r.appendChild(row);
    });
    if (data.link) {
      const row = document.createElement("div"); row.className = "row";
      const lab = document.createElement("label"); lab.textContent = "open";
      const a = document.createElement("a");
      a.className = "open-link"; a.textContent = data.link;
      a.addEventListener("click", (ev) => { ev.preventDefault(); openTutorial(); });
      row.appendChild(lab); row.appendChild(a); r.appendChild(row);
    }
    termEl.appendChild(r);
    scrollToEnd();
  }

  function openTutorial() {
    // Try to open the sibling Tutorial Reader.html if present (same project)
    const url = encodeURI("./Tutorial Reader.html");
    window.open(url, "_blank");
  }

  // ---------- Event dispatch ----------
  function applyEvent(ev) {
    switch (ev.kind) {
      case "line": {
        addLine(ev.text, ev.tone || "default");
        // Track cost from dim lines that report "cumulative $X.XX" or "total $X.XX"
        const m = ev.text && ev.text.match(/(?:cumulative|total)\s*\$([\d.]+)/);
        if (m) st.cost = parseFloat(m[1]);
        const tm = ev.text && ev.text.match(/tokens in\s*([\d\s]+)·\s*out\s*([\d\s]+)/);
        if (tm) { st.tokens_in = +tm[1].replace(/\s/g,""); st.tokens_out = +tm[2].replace(/\s/g,""); }
        break;
      }
      case "blank": addBlank(); break;
      case "box": addBox(ev.title, ev.lines); break;
      case "prompt": addPrompt(ev.label, ev.await); break;
      case "report": addReport(ev.status, ev.data); break;
      case "end": /* no-op */ break;
      default: break;
    }
  }

  // ---------- Clock ----------
  function currentEvents() {
    // Build a combined event list; for 'abort', inject only cost-gate + abort tail.
    const cfg = window.CLI_STATES[st.stateKey];
    return cfg ? cfg.events : [];
  }
  function totalDuration() {
    const cfg = window.CLI_STATES[st.stateKey];
    return cfg ? cfg.total : 45;
  }

  function play() {
    if (st.awaiting) return; // paused on interactive prompt
    if (st.eventIdx >= currentEvents().length) return;
    st.playing = true;
    btnPlay.textContent = "⏸  Pause";
    st.t0 = performance.now();
    if (!window.__cliRAF) tick();
  }
  function pausePlayback() {
    if (!st.playing) return;
    const now = performance.now();
    st.clockOffset += ((now - st.t0) / 1000) * st.speed;
    st.playing = false;
    btnPlay.textContent = "▶  Play";
  }
  function resumePlayback() {
    if (st.playing) return;
    st.t0 = performance.now();
    st.playing = true;
    btnPlay.textContent = "⏸  Pause";
  }
  function clockNow() {
    if (!st.playing) return st.clockOffset;
    const now = performance.now();
    return st.clockOffset + ((now - st.t0) / 1000) * st.speed;
  }

  function tick() {
    window.__cliRAF = requestAnimationFrame(tick);
    const t = clockNow();
    const events = currentEvents();
    // Dispatch events whose time has arrived
    while (st.eventIdx < events.length && events[st.eventIdx].t <= t) {
      const ev = events[st.eventIdx++];
      applyEvent(ev);
      if (st.awaiting) break;
    }
    // Update UI
    const total = totalDuration();
    const pct = Math.min(100, (t / total) * 100);
    scrubberFill.style.width = pct + "%";
    const mm = Math.floor(t / 60), ss = Math.floor(t % 60);
    const mT = Math.floor(total / 60), sT = Math.floor(total % 60);
    timeRead.textContent = `${pad(mm)}:${pad(ss)} / ${pad(mT)}:${pad(sT)}`;
    // Statusbar
    statusbarTime.querySelector(".v").textContent = `${pad(mm)}:${pad(ss)}`;
    statusbarCost.querySelector(".v").textContent = `$${st.cost.toFixed(2)}`;
    statusbarTokens.querySelector(".v").textContent =
      `${formatK(st.tokens_in)} / ${formatK(st.tokens_out)}`;
    // Caret on if waiting on prompt? handled elsewhere.
    if (t >= total && st.eventIdx >= events.length) {
      st.playing = false;
      btnPlay.textContent = "↻  Again";
    }
  }
  function pad(n) { return String(n).padStart(2, "0"); }
  function formatK(n) {
    if (!n) return "0";
    if (n >= 1000) return (Math.round(n / 100) / 10) + "K";
    return String(n);
  }

  function restart() {
    // Hard reset
    cancelAnimationFrame(window.__cliRAF); window.__cliRAF = null;
    st.playing = false;
    st.eventIdx = 0;
    st.clockOffset = 0;
    st.awaiting = null;
    st.gateAnswer = null;
    st.cost = 0; st.tokens_in = 0; st.tokens_out = 0;
    clearTerm();
    // Fresh caret placeholder so term isn't fully empty at t=0
    const c = document.createElement("div");
    c.className = "ln tone-dim";
    c.textContent = "Windows PowerShell · codeguide 0.1.0 · type 'codeguide --help' for commands";
    termEl.appendChild(c);
    scrubberFill.style.width = "0%";
    btnPlay.textContent = "▶  Play";
  }

  function skipStage() {
    const events = currentEvents();
    if (st.eventIdx >= events.length) return;
    // Fast-forward to the next event whose text starts with "[N/7]" beyond the current stage
    let cur = st.eventIdx;
    // find current stage number
    let curStage = 0;
    for (let i = cur - 1; i >= 0; i--) {
      const e = events[i];
      if (e.kind === "line" && /^\[(\d)\/7\]/.test(e.text || "")) {
        curStage = +RegExp.$1; break;
      }
    }
    // target: next "[S/7]" where S > curStage (or end)
    let target = events.length;
    for (let i = cur; i < events.length; i++) {
      const e = events[i];
      const m = e.kind === "line" && /^\[(\d)\/7\]/.exec(e.text || "");
      if (m && (+m[1]) > curStage) { target = i; break; }
    }
    // Apply all events up to target immediately (skipping prompts unless we already answered)
    for (let i = cur; i < target; i++) {
      const e = events[i];
      if (e.kind === "prompt") {
        // auto-answer with 'y' to progress
        st.gateAnswer = "y";
        continue;
      }
      applyEvent(e);
    }
    st.eventIdx = target;
    // Advance the clock to target event time so playback picks up smoothly
    const targetT = events[target] ? events[target].t : totalDuration();
    st.clockOffset = Math.max(st.clockOffset, targetT);
    if (st.playing) { st.t0 = performance.now(); }
  }

  function switchToAbortTail() {
    // Replace remaining events with the abort tail from CLI_STATES.abort.
    // The abort script begins right after cost-gate, but we're already past the gate
    // in the running script. We splice in the abort tail and continue.
    const now = clockNow();
    const abort = window.CLI_STATES.abort.events;
    // Find the first event in abort after its own prompt
    const tailStart = abort.findIndex(e => e.kind === "prompt") + 1;
    const tail = abort.slice(tailStart).map(e => ({ ...e, t: now + (e.t - abort[tailStart].t) }));
    // Replace remaining pipeline with the tail
    const cfg = window.CLI_STATES[st.stateKey];
    cfg._originalEvents = cfg._originalEvents || cfg.events;
    cfg.events = currentEvents().slice(0, st.eventIdx).concat(tail);
    cfg.total = (tail[tail.length - 1]?.t || now) + 1;
    resumePlayback();
  }

  // ---------- Wire controls ----------
  btnPlay.addEventListener("click", () => {
    if (!st.playing) {
      if (st.eventIdx >= currentEvents().length) restart();
      play();
    } else {
      pausePlayback();
    }
  });
  btnRestart.addEventListener("click", () => {
    restart();
  });
  btnSkip.addEventListener("click", () => {
    if (!st.playing) play();
    skipStage();
  });
  scrubberEl.addEventListener("click", (ev) => {
    const rect = scrubberEl.getBoundingClientRect();
    const frac = (ev.clientX - rect.left) / rect.width;
    const targetT = Math.max(0, Math.min(1, frac)) * totalDuration();
    // Reset and replay up to targetT instantly
    restart();
    const events = currentEvents();
    for (let i = 0; i < events.length; i++) {
      const e = events[i];
      if (e.t > targetT) { st.eventIdx = i; break; }
      if (e.kind === "prompt") { st.gateAnswer = "y"; continue; }
      applyEvent(e); st.eventIdx = i + 1;
    }
    st.clockOffset = targetT;
    scrubberFill.style.width = (targetT / totalDuration() * 100) + "%";
  });

  speedGroup.addEventListener("click", (ev) => {
    const b = ev.target.closest("button[data-speed]");
    if (!b) return;
    const wasPlaying = st.playing;
    if (wasPlaying) pausePlayback();
    st.speed = parseFloat(b.dataset.speed);
    localStorage.setItem("cg-cli:speed", String(st.speed));
    applyRoot();
    if (wasPlaying) resumePlayback();
  });

  statePicker.addEventListener("click", (ev) => {
    const b = ev.target.closest("button[data-state]");
    if (!b) return;
    st.stateKey = b.dataset.state;
    localStorage.setItem("cg-cli:state", st.stateKey);
    // Reset the events of each state in case abort polluted it
    for (const k of Object.keys(window.CLI_STATES)) {
      const c = window.CLI_STATES[k];
      if (c._originalEvents) { c.events = c._originalEvents; delete c._originalEvents; }
    }
    applyRoot();
    restart();
    play();
  });

  dirTabs.addEventListener("click", (ev) => {
    const b = ev.target.closest("button[data-dir]");
    if (!b) return;
    st.dir = b.dataset.dir;
    localStorage.setItem("cg-cli:dir", st.dir);
    applyRoot();
  });

  // Tweaks
  tweaksBtn.addEventListener("click", () => tweaksPanel.classList.toggle("open"));
  $$(".seg[data-key]").forEach(seg => {
    seg.addEventListener("click", (ev) => {
      const b = ev.target.closest("button[data-v]");
      if (!b) return;
      const key = seg.dataset.key;
      const v = b.dataset.v;
      if (key === "speed") st.speed = parseFloat(v);
      else st[key] = v;
      localStorage.setItem("cg-cli:" + key, String(st[key]));
      applyRoot();
    });
  });

  // Keyboard
  document.addEventListener("keydown", (ev) => {
    if (ev.target.tagName === "INPUT") return;
    if (ev.code === "Space") { ev.preventDefault(); btnPlay.click(); }
    else if (ev.key === "r" || ev.key === "R") btnRestart.click();
    else if (ev.key === "n" || ev.key === "N") btnSkip.click();
    else if (ev.key === "ArrowRight") { ev.preventDefault(); skipStage(); }
  });

  // Host edit-mode contract
  window.addEventListener("message", (e) => {
    if (!e.data || typeof e.data !== "object") return;
    if (e.data.type === "__activate_edit_mode") tweaksPanel.classList.add("open");
    else if (e.data.type === "__deactivate_edit_mode") tweaksPanel.classList.remove("open");
  });
  setTimeout(() => {
    try { window.parent.postMessage({ type: "__edit_mode_available" }, "*"); } catch (_) {}
  }, 30);

  // ---------- Boot ----------
  applyRoot();
  restart();
  // Autoplay after a beat
  setTimeout(() => play(), 450);
})();
