/* WiedunFlow tutorial reader — interactive prototype */
(function () {
  const META = window.TUTORIAL_META;
  const CLUSTERS = window.TUTORIAL_CLUSTERS;
  const LESSONS = window.TUTORIAL_LESSONS;
  const byId = (id) => LESSONS.find(l => l.id === id);
  const clusterOf = (lessonId) => CLUSTERS.find(c => c.lessons.includes(lessonId));

  // --- Minimal Python syntax highlighter ---
  const KW = new Set(["def","class","return","from","import","with","as","if","elif","else","for","while","in","is","not","and","or","None","True","False","self","pass","raise","try","except","finally","lambda","yield","async","await"]);
  function highlight(line) {
    // Comments
    const commentIdx = line.indexOf("#");
    let head = line, tail = "";
    if (commentIdx >= 0) {
      // only treat as comment if outside strings (rough)
      const before = line.slice(0, commentIdx);
      const qCount = (before.match(/"/g)||[]).length + (before.match(/'/g)||[]).length;
      if (qCount % 2 === 0) {
        head = line.slice(0, commentIdx);
        tail = `<span class="tok-com">${escapeHtml(line.slice(commentIdx))}</span>`;
      }
    }
    // Strings
    head = head.replace(/("""[\s\S]*?"""|'''[\s\S]*?'''|"([^"\\]|\\.)*"|'([^'\\]|\\.)*')/g,
      (m) => `<span class="tok-str">${escapeHtml(m)}</span>`);
    // Tokens
    head = head.replace(/(?<!>)\b([A-Za-z_][A-Za-z0-9_]*)\b(?![^<]*>)/g, (m) => {
      if (KW.has(m)) return `<span class="tok-kw">${m}</span>`;
      if (/^[A-Z]/.test(m)) return `<span class="tok-cls">${m}</span>`;
      return m;
    });
    // Numbers
    head = head.replace(/\b(\d+)\b(?![^<]*>)/g, '<span class="tok-num">$1</span>');
    // Function call names (approx)
    head = head.replace(/([A-Za-z_][A-Za-z0-9_]*)(?=\()/g, (m, n) => {
      if (KW.has(n)) return m;
      return `<span class="tok-fn">${n}</span>`;
    });
    return head + tail;
  }
  function escapeHtml(s) { return s.replace(/[&<>]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[c])); }

  // --- State ---
  const STORAGE_KEY = "wiedunflow:requests:last-lesson";
  const DIR_KEY = "wiedunflow:tweak:dir:v2";
  const THEME_KEY = "wiedunflow:tweak:theme:v2";
  const FONT_KEY = "wiedunflow:tweak:font:v2";
  const CONF_KEY = "wiedunflow:tweak:conf:v2";
  const DEG_KEY = "wiedunflow:tweak:deg:v2";
  const PAL_KEY = "wiedunflow:tweak:palette:v2";
  // Clear old v1 keys once
  ["wiedunflow:tweak:dir","wiedunflow:tweak:theme","wiedunflow:tweak:font","wiedunflow:tweak:conf","wiedunflow:tweak:deg"].forEach(k => localStorage.removeItem(k));

  let current = localStorage.getItem(STORAGE_KEY) || LESSONS[0].id;
  if (!byId(current)) current = LESSONS[0].id;

  // Apply persisted tweak settings
  const html = document.documentElement;
  html.dataset.dir = localStorage.getItem(DIR_KEY) || "A";
  html.dataset.theme = localStorage.getItem(THEME_KEY) || "light";
  html.dataset.font = localStorage.getItem(FONT_KEY) || "sans";
  html.dataset.palette = localStorage.getItem(PAL_KEY) || "a1";

  // --- Rendering ---
  function renderSidebar() {
    const mount = document.getElementById("sidebar");
    const currentIdx = LESSONS.findIndex(l => l.id === current);
    let html = `<div class="toc-title">${META.owner}/${META.project_name}</div>`;
    CLUSTERS.forEach((cluster) => {
      html += `<div class="cluster">
        <div class="cluster-head">
          <span class="cluster-kicker">${cluster.kicker}</span>
          <span class="cluster-name">${cluster.label}</span>
        </div>
        <p class="cluster-desc">${cluster.description}</p>
        <ul class="lesson-list">`;
      cluster.lessons.forEach((lid) => {
        const lesson = byId(lid);
        const idx = LESSONS.findIndex(l => l.id === lid);
        const isCurrent = lid === current;
        const isDone = idx < currentIdx;
        const num = String(idx + 1).padStart(2, "0");
        html += `<li>
          <a class="lesson-link ${isCurrent ? "current" : ""} ${isDone ? "done" : ""}" data-id="${lid}">
            <span class="lesson-num">${num}</span>
            <span class="lesson-title-sm">${lesson.title}</span>
            <span class="lesson-time">${lesson.read_time}m</span>
          </a>
        </li>`;
      });
      html += `</ul></div>`;
    });
    mount.innerHTML = html;
    mount.querySelectorAll(".lesson-link").forEach(el => {
      el.addEventListener("click", () => goto(el.dataset.id));
    });
  }

  function renderBreadcrumb(lesson) {
    const cluster = clusterOf(lesson.id);
    const idx = LESSONS.findIndex(l => l.id === lesson.id);
    document.getElementById("breadcrumb").innerHTML = `
      <span>${META.owner}/${META.project_name}</span>
      <span class="sep">›</span>
      <span class="cluster">${cluster.label}</span>
      <span class="sep">›</span>
      <span class="lesson"><span class="lnum">${String(idx+1).padStart(2,"0")}</span>${lesson.title}</span>
    `;
  }

  function renderProgress() {
    const idx = LESSONS.findIndex(l => l.id === current);
    const pct = ((idx + 1) / LESSONS.length) * 100;
    document.getElementById("progress").style.width = pct + "%";
  }

  function renderNarration(lesson) {
    const idx = LESSONS.findIndex(l => l.id === lesson.id);
    const cluster = clusterOf(lesson.id);
    const kicker = `<div class="lesson-kicker">
      <span class="num">Lesson ${String(idx+1).padStart(2,"0")} / ${String(LESSONS.length).padStart(2,"0")}</span>
      <span class="dot"></span>
      <span>${cluster.label}</span>
    </div>`;
    const titleBlock = `<h1 class="lesson-title">${lesson.title}</h1>
      <p class="lesson-sub">${lesson.subtitle}</p>`;
    const meta = `<div class="lesson-meta">
      <span><span class="conf-${lesson.confidence}"><span class="conf-dot"></span>${lesson.confidence} confidence</span></span>
      <span>${lesson.read_time} min read</span>
      <span>${lesson.words} words</span>
      <span>${lesson.code.file}</span>
    </div>`;

    // Show a skipped-lesson placeholder if degraded mode is on and this lesson is flagged
    const degraded = localStorage.getItem(DEG_KEY) === "on";
    const skippedIds = new Set(["cookies", "utils"]); // arbitrary demo set
    let skippedHtml = "";
    if (degraded && skippedIds.has(lesson.id)) {
      skippedHtml = `<div class="skipped-block">
        <span class="tag">Skipped</span>
        <p><strong>This lesson was skipped due to grounding failures</strong> — the narration referenced <code>${lesson.code.file}</code> symbols that could not be verified against the AST after one retry. See the source file directly.</p>
      </div>`;
    }

    let body = "";
    lesson.narration.forEach((b) => {
      if (b.kind === "p") body += `<p>${b.text}</p>`;
      else if (b.kind === "next-links") {
        body += `<ul class="next-links">`;
        b.items.forEach(it => {
          body += `<li><span class="nl-code">${it.label}</span><span class="nl-note">${it.note}</span></li>`;
        });
        body += `</ul>`;
      }
    });

    // Up-next card (except last)
    let nextCard = "";
    if (idx < LESSONS.length - 1) {
      const next = LESSONS[idx + 1];
      const nextCluster = clusterOf(next.id);
      nextCard = `<div class="next-card">
        <div class="label">Up next · ${nextCluster.label}</div>
        <div class="title">${next.title}</div>
        <div class="sub">${next.subtitle} · ${next.read_time} min read</div>
        <button data-next="${next.id}">Continue → <span style="opacity:.7">${String(idx+2).padStart(2,"0")}</span></button>
      </div>`;
    }

    // Prev/Next nav
    const prev = idx > 0 ? LESSONS[idx - 1] : null;
    const next = idx < LESSONS.length - 1 ? LESSONS[idx + 1] : null;
    const nav = `<div class="lesson-nav">
      <a class="${prev ? "" : "disabled"}" ${prev ? `data-goto="${prev.id}"` : ""}>
        <div class="dir">← Previous</div>
        <div class="ttl">${prev ? prev.title : "Beginning"}</div>
      </a>
      <a class="end ${next ? "" : "disabled"}" ${next ? `data-goto="${next.id}"` : ""}>
        <div class="dir">Next →</div>
        <div class="ttl">${next ? next.title : "End of tutorial"}</div>
      </a>
    </div>`;

    document.getElementById("narration").innerHTML = `
      ${kicker}
      ${titleBlock}
      ${meta}
      <div class="narration-body">
        ${skippedHtml}
        ${body}
        ${nextCard}
      </div>
      ${nav}
    `;

    // Wire buttons
    document.querySelectorAll("[data-next]").forEach(b => b.addEventListener("click", () => goto(b.dataset.next)));
    document.querySelectorAll("[data-goto]").forEach(b => b.addEventListener("click", () => goto(b.dataset.goto)));
  }

  function renderCode(lesson) {
    const header = document.getElementById("code-header");
    const file = lesson.code.file;
    const parts = file.split("/");
    header.innerHTML = `
      <span class="file-icon"></span>
      <span class="file"><span class="muted">${parts.slice(0, -1).join("/")}/</span>${parts[parts.length - 1]}</span>
      <span class="right">python · ${lesson.code.lines.length} lines shown</span>
    `;
    const hl = new Set(lesson.code.highlight);
    const body = document.getElementById("code-body");
    let html = `<div class="code">`;
    lesson.code.lines.forEach((line, i) => {
      const lineNo = i + 1;
      const cls = hl.has(lineNo) ? "row hl" : "row";
      html += `<div class="${cls}"><span class="ln">${lineNo}</span><span class="ct">${highlight(line) || "&nbsp;"}</span></div>`;
    });
    html += `</div>`;
    body.innerHTML = html;
    body.scrollTop = 0;
    // Scroll first highlighted line into view within panel
    if (lesson.code.highlight.length) {
      const first = lesson.code.highlight[0];
      const rowH = 13 * 1.7; // approx
      const target = Math.max(0, (first - 3) * rowH);
      body.scrollTo({ top: target, behavior: "instant" in HTMLElement.prototype ? "auto" : "smooth" });
    }
  }

  function renderFooter() {
    const conf = localStorage.getItem(CONF_KEY) || META.resolution_label || (META.resolution >= 80 ? "high" : META.resolution >= 50 ? "medium" : "low");
    const pct = conf === "high" ? 87 : conf === "medium" ? 64 : 41;
    const degraded = localStorage.getItem(DEG_KEY) === "on";
    const version = META.wiedunflow_version;
    const label = conf === "high" ? "high confidence" : conf === "medium" ? "medium — partial resolution" : "low — consider pyright adapter (v2+)";

    document.getElementById("degraded-banner").style.display = degraded ? "flex" : "none";
    document.getElementById("degraded-count").textContent = "4 of 12";

    document.getElementById("tutorial-footer").innerHTML = `
      <div>
        <div class="meta-row">
          <span><label>repo</label> ${META.owner}/${META.project_name}</span>
          <span><label>commit</label> ${META.commit}</span>
          <span><label>branch</label> ${META.branch}</span>
          <span><label>generated</label> ${META.generated_at}</span>
          <span><label>files</label> ${META.file_count}</span>
        </div>
        <div class="meta-row" style="margin-top:6px">
          <span><label>resolution</label> <span class="conf-pill conf-${conf}">${pct}% · ${label}</span></span>
          <span><label>cost</label> $${(META.cost_haiku + META.cost_opus).toFixed(2)} (H $${META.cost_haiku.toFixed(2)} · O $${META.cost_opus.toFixed(2)})</span>
          <span><label>elapsed</label> ${Math.floor(META.elapsed_seconds/60)}m ${META.elapsed_seconds%60}s</span>
        </div>
        <div class="offline">Generated by WiedunFlow v${version} (Apache 2.0) — this document is fully offline.</div>
      </div>
      <div style="text-align:right; font-family: var(--mono); font-size: 11px; color: var(--muted)">
        schema v${META.schema_version}<br/>
        &lt;script type="application/json"&gt;<br/>
        ${META.total_lessons} lessons · ${degraded ? "4 skipped" : "0 skipped"}
      </div>
    `;
  }

  function goto(id) {
    if (!byId(id)) return;
    current = id;
    localStorage.setItem(STORAGE_KEY, id);
    location.hash = `#/lesson/${id}`;
    renderAll();
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function renderAll() {
    const lesson = byId(current);
    renderSidebar();
    renderBreadcrumb(lesson);
    renderProgress();
    renderNarration(lesson);
    renderCode(lesson);
    renderFooter();
  }

  // --- Deep link + keyboard ---
  function fromHash() {
    const m = location.hash.match(/#\/lesson\/(.+)$/);
    if (m && byId(m[1])) { current = m[1]; localStorage.setItem(STORAGE_KEY, current); }
  }
  window.addEventListener("hashchange", () => { fromHash(); renderAll(); });
  window.addEventListener("keydown", (e) => {
    if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;
    const idx = LESSONS.findIndex(l => l.id === current);
    if (e.key === "ArrowRight" && idx < LESSONS.length - 1) goto(LESSONS[idx+1].id);
    if (e.key === "ArrowLeft" && idx > 0) goto(LESSONS[idx-1].id);
  });

  // --- Tweaks panel ---
  function setupTweaks() {
    const panel = document.getElementById("tweaks");
    const toggleBtn = document.getElementById("tweak-toggle");
    toggleBtn.addEventListener("click", () => panel.classList.toggle("open"));

    function wireSeg(name, key, apply) {
      panel.querySelectorAll(`[data-tweak="${name}"] button`).forEach(btn => {
        btn.addEventListener("click", () => {
          panel.querySelectorAll(`[data-tweak="${name}"] button`).forEach(b => b.classList.remove("on"));
          btn.classList.add("on");
          const v = btn.dataset.value;
          localStorage.setItem(key, v);
          apply(v);
        });
      });
      // Set initial active
      const cur = localStorage.getItem(key);
      const target = panel.querySelector(`[data-tweak="${name}"] button[data-value="${cur}"]`);
      if (target) {
        panel.querySelectorAll(`[data-tweak="${name}"] button`).forEach(b => b.classList.remove("on"));
        target.classList.add("on");
      }
    }

    wireSeg("dir", DIR_KEY, (v) => { html.dataset.dir = v; renderAll(); });
    wireSeg("theme", THEME_KEY, (v) => { html.dataset.theme = v; renderFooter(); });
    wireSeg("font", FONT_KEY, (v) => { html.dataset.font = v; });
    wireSeg("conf", CONF_KEY, (v) => { renderFooter(); renderAll(); });
    wireSeg("deg", DEG_KEY, (v) => { renderAll(); });
    wireSeg("palette", PAL_KEY, (v) => { html.dataset.palette = v; renderAll(); });
  }

  // Theme quick-toggle button in topbar
  document.getElementById("theme-btn").addEventListener("click", () => {
    const cur = html.dataset.theme === "dark" ? "light" : "dark";
    html.dataset.theme = cur;
    localStorage.setItem(THEME_KEY, cur);
    const panelBtns = document.querySelectorAll(`[data-tweak="theme"] button`);
    panelBtns.forEach(b => b.classList.toggle("on", b.dataset.value === cur));
    renderFooter();
  });

  document.getElementById("dir-btn").addEventListener("click", () => {
    const cur = html.dataset.dir === "A" ? "B" : "A";
    html.dataset.dir = cur;
    localStorage.setItem(DIR_KEY, cur);
    document.querySelectorAll(`[data-tweak="dir"] button`).forEach(b => b.classList.toggle("on", b.dataset.value === cur));
    renderAll();
  });

  // --- Resizable splitter ---
  function setupSplitter() {
    const content = document.querySelector(".content");
    const splitter = document.getElementById("splitter");
    const FRAC_KEY = "wiedunflow:tweak:narr-frac";
    const saved = parseFloat(localStorage.getItem(FRAC_KEY));
    if (!isNaN(saved) && saved > 0.2 && saved < 0.8) {
      content.style.setProperty("--narr-frac", saved);
      splitter.style.left = (saved * 100) + "%";
    } else {
      splitter.style.left = "50%";
    }

    let dragging = false;
    function onDown(e) {
      if (window.innerWidth < 1024) return;
      dragging = true;
      splitter.classList.add("dragging");
      document.body.classList.add("is-resizing");
      e.preventDefault();
    }
    function onMove(e) {
      if (!dragging) return;
      const rect = content.getBoundingClientRect();
      const x = (e.clientX || (e.touches && e.touches[0].clientX) || 0) - rect.left;
      let frac = x / rect.width;
      frac = Math.max(0.28, Math.min(0.72, frac));
      content.style.setProperty("--narr-frac", frac);
      splitter.style.left = (frac * 100) + "%";
      localStorage.setItem(FRAC_KEY, frac);
    }
    function onUp() {
      if (!dragging) return;
      dragging = false;
      splitter.classList.remove("dragging");
      document.body.classList.remove("is-resizing");
    }
    splitter.addEventListener("mousedown", onDown);
    splitter.addEventListener("touchstart", onDown, { passive: false });
    window.addEventListener("mousemove", onMove);
    window.addEventListener("touchmove", onMove, { passive: false });
    window.addEventListener("mouseup", onUp);
    window.addEventListener("touchend", onUp);
    // Keep splitter positioned correctly after layout changes
    window.addEventListener("resize", () => {
      const f = parseFloat(getComputedStyle(content).getPropertyValue("--narr-frac")) || 0.5;
      splitter.style.left = (f * 100) + "%";
    });
  }

  // Init
  fromHash();
  renderAll();
  setupTweaks();
  setupSplitter();

  // Edit-mode (Tweaks toolbar toggle)
  window.addEventListener("message", (ev) => {
    if (!ev.data || typeof ev.data !== "object") return;
    if (ev.data.type === "__activate_edit_mode") document.getElementById("tweaks").classList.add("open");
    if (ev.data.type === "__deactivate_edit_mode") document.getElementById("tweaks").classList.remove("open");
  });
  window.parent.postMessage({ type: "__edit_mode_available" }, "*");
})();
