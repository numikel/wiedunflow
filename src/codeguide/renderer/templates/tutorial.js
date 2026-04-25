/*
 * SPDX-License-Identifier: Apache-2.0
 * Copyright 2026 Michał Kamiński
 *
 * CodeGuide tutorial.html vanilla JS navigation (Sprint 5 track C).
 * Inlined into tutorial.html.j2 via {% include %} — no external script tags.
 * Namespace: window.CodeGuide (contract anchored by ADR-0009).
 */

(function () {
  "use strict";

  var SCHEMA_VERSION_SUPPORTED = "1.0.0";
  var BREAKPOINT_PX = 1024;

  var CodeGuide = (window.CodeGuide = window.CodeGuide || {});
  CodeGuide._errors = [];

  function safeJSON(id) {
    var el = document.getElementById(id);
    if (!el) {
      CodeGuide._errors.push("missing-" + id);
      return null;
    }
    try {
      return JSON.parse(el.textContent || "null");
    } catch (e) {
      CodeGuide._errors.push("parse-" + id);
      return null;
    }
  }

  function readStorage(key, fallback) {
    try {
      var v = localStorage.getItem(key);
      return v === null ? fallback : v;
    } catch (e) {
      return fallback;
    }
  }
  function writeStorage(key, value) {
    try { localStorage.setItem(key, String(value)); } catch (e) { /* ignore */ }
  }

  function validateSchema(meta) {
    if (!meta) { return; }
    var v = meta.schema_version;
    if (v && v !== SCHEMA_VERSION_SUPPORTED) {
      try {
        console.warn("CodeGuide: unknown schema_version '" + v + "', supported: " + SCHEMA_VERSION_SUPPORTED);
      } catch (e) { /* no console */ }
    }
  }

  function renderNarration(lesson) {
    var root = document.getElementById("tutorial-narration-body");
    if (!root) { return; }
    root.innerHTML = "";
    if (lesson.status === "skipped") {
      var box = document.createElement("section");
      box.className = "lesson-skipped";
      var pill = document.createElement("span");
      pill.className = "lesson-skipped__pill";
      pill.textContent = "SKIPPED";
      var msg = document.createElement("p");
      msg.className = "lesson-skipped__message";
      msg.textContent = lesson.narrative || "This lesson was skipped due to grounding failures.";
      box.appendChild(pill); box.appendChild(msg);
      root.appendChild(box);
      return;
    }
    var segments = lesson.segments && lesson.segments.length ? lesson.segments : [];
    if (!segments.length) {
      (lesson.narrative || "").split(/\n\n+/).forEach(function (chunk) {
        if (!chunk.trim()) { return; }
        var p = document.createElement("p"); p.textContent = chunk; root.appendChild(p);
      });
    } else {
      segments.forEach(function (seg) {
        if (seg.kind === "html") {
          // Pre-rendered HTML from server-side markdown parser (mistune). Append
          // as a document fragment so block elements (h1/h2/pre/ol/ul) land at
          // the top level of the narration column, not wrapped in <p>.
          var tmpl = document.createElement("template");
          tmpl.innerHTML = seg.text;
          root.appendChild(tmpl.content);
        } else if (seg.kind === "p") {
          var p = document.createElement("p"); p.innerHTML = seg.text; root.appendChild(p);
          if (seg.code_ref) {
            var inline = document.createElement("pre");
            inline.className = "mobile-inline-code";
            inline.textContent = (seg.code_ref.lines || []).join("\n");
            root.appendChild(inline);
          }
        } else if (seg.kind === "code") {
          var pre = document.createElement("pre"); pre.className = "mobile-inline-code";
          pre.textContent = seg.text; root.appendChild(pre);
        }
      });
    }

    // B7: helper appendix — rendered when Track A emits meta.helper_appendix
    // Checks both lesson.meta.helper_appendix and top-level lesson.helper_appendix.
    // TODO: remove guard + TODO comment once Track A ships meta.helper_appendix.
    var helpers = lesson.meta && Array.isArray(lesson.meta.helper_appendix)
      ? lesson.meta.helper_appendix
      : (Array.isArray(lesson.helper_appendix) ? lesson.helper_appendix : null);
    if (helpers && helpers.length) {
      var appendix = document.createElement("div");
      appendix.className = "helper-appendix";
      var heading = document.createElement("h3");
      heading.textContent = "Helper functions you’ll see along the way";
      appendix.appendChild(heading);
      var ul = document.createElement("ul");
      helpers.forEach(function (ref) {
        var li = document.createElement("li");
        var code = document.createElement("code");
        code.textContent = ref.symbol || "";
        li.appendChild(code);
        if (ref.file_path) {
          var refMeta = document.createElement("span");
          refMeta.className = "meta";
          refMeta.textContent = " — " + ref.file_path + (ref.line_start ? ":" + ref.line_start : "");
          li.appendChild(refMeta);
        }
        ul.appendChild(li);
      });
      appendix.appendChild(ul);
      root.appendChild(appendix);
    }
  }

  function renderCode(lesson) {
    var root = document.getElementById("tutorial-code-body");
    var head = document.getElementById("tutorial-code-head");
    if (!root || !head) { return; }
    root.innerHTML = ""; head.textContent = "";
    var ref = null;
    if (lesson.segments && lesson.segments.length) {
      for (var i = 0; i < lesson.segments.length; i++) {
        if (lesson.segments[i].code_ref) { ref = lesson.segments[i].code_ref; break; }
      }
    }
    // Fallback: server builds `code_snippet` from lesson.code_refs when no
    // segment-level code_ref exists (common path — Stage 5 emits markdown only).
    if (!ref && lesson.code_snippet) { ref = lesson.code_snippet; }
    if (!ref) { head.textContent = "(no code reference)"; return; }
    head.textContent = ref.file + " · " + (ref.lang || "python");
    var highlight = new Set((ref.highlight || []));
    var startLine = typeof ref.start_line === "number" ? ref.start_line : 1;
    (ref.lines || []).forEach(function (line, idx) {
      var row = document.createElement("div");
      row.className = "code-row" + (highlight.has(idx + 1) ? " hl" : "");
      var ln = document.createElement("span"); ln.className = "ln";
      ln.textContent = String(startLine + idx);
      var pre = document.createElement("pre"); pre.innerHTML = line || "&nbsp;";
      row.appendChild(ln); row.appendChild(pre); root.appendChild(row);
    });
  }

  function activeLessonId() {
    var hash = (location.hash || "").replace(/^#\/lesson\//, "");
    return hash || null;
  }

  function setActiveLink(lessonId) {
    var links = document.querySelectorAll(".lesson-link");
    links.forEach(function (el) {
      el.classList.toggle("active", el.getAttribute("data-lesson-id") === lessonId);
    });
  }

  function updateProgress(index, total) {
    var bar = document.querySelector("#tutorial-progress > span");
    if (!bar || total <= 1) { return; }
    bar.style.width = (((index + 1) / total) * 100).toFixed(1) + "%";
  }

  function lessonIdFromIndex(lessons, idx) {
    return lessons[Math.max(0, Math.min(lessons.length - 1, idx))].id;
  }

  function indexOfLesson(lessons, id) {
    for (var i = 0; i < lessons.length; i++) { if (lessons[i].id === id) { return i; } }
    return -1;
  }

  function renderLessonFooter(lessons, repoId, idx) {
    var root = document.getElementById("tutorial-narration-body");
    if (!root) { return; }
    var footer = document.createElement("div");
    footer.className = "lesson-footer";
    var isLast = idx >= lessons.length - 1;
    if (!isLast) {
      var nextLesson = lessons[idx + 1];
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "next-btn-inline";
      btn.innerHTML = "Next: " + escapeHtml(nextLesson.title) + " →";
      btn.addEventListener("click", function () {
        navigateTo(lessons, repoId, nextLesson.id, {});
      });
      footer.appendChild(btn);
    } else {
      var done = document.createElement("div");
      done.className = "lesson-footer-done";
      done.textContent = "✓ End of tutorial";
      footer.appendChild(done);
      var backBtn = document.createElement("button");
      backBtn.type = "button";
      backBtn.className = "next-btn-inline secondary";
      backBtn.textContent = "Back to start ↺";
      backBtn.addEventListener("click", function () {
        navigateTo(lessons, repoId, lessons[0].id, {});
      });
      footer.appendChild(backBtn);
    }
    root.appendChild(footer);
  }

  function escapeHtml(s) {
    var div = document.createElement("div");
    div.textContent = s == null ? "" : String(s);
    return div.innerHTML;
  }

  function scrollHighlightIntoView() {
    // After renderCode, bring the first highlighted row into view so nav
    // feels responsive (US-040/045 spirit — lesson switch must move focus).
    var codePane = document.getElementById("tutorial-code");
    var first = codePane && codePane.querySelector(".code-row.hl");
    if (first && typeof first.scrollIntoView === "function") {
      first.scrollIntoView({ block: "center", behavior: "auto" });
    } else if (codePane) {
      codePane.scrollTop = 0;
    }
  }

  function updateNavButtons(idx, total) {
    var prev = document.getElementById("tutorial-prev");
    var next = document.getElementById("tutorial-next");
    var label = document.getElementById("tutorial-progress-label");
    if (prev) { prev.disabled = idx <= 0; }
    if (next) { next.disabled = idx >= total - 1; }
    // B4: "Lesson N / M" chip — English for multi-audience HTML output
    if (label) { label.textContent = "Lesson " + (idx + 1) + " / " + total; }
  }

  function navigateTo(lessons, repoId, id, options) {
    options = options || {};
    var idx = indexOfLesson(lessons, id);
    if (idx < 0) {
      try { console.warn("CodeGuide: unknown lesson id '" + id + "', falling back to first"); } catch (e) { /* noop */ }
      id = lessons[0].id; idx = 0;
    }
    var lesson = lessons[idx];
    renderNarration(lesson); renderCode(lesson); setActiveLink(id); updateProgress(idx, lessons.length);
    renderLessonFooter(lessons, repoId, idx);
    updateNavButtons(idx, lessons.length);
    scrollHighlightIntoView();
    if (!options.fromHash) { location.hash = "#/lesson/" + id; }
    writeStorage("codeguide:" + repoId + ":last-lesson", id);
    CodeGuide._activeIndex = idx; CodeGuide._activeId = id;
    // B6: schedule visited after 5s of dwell (reading signal)
    scheduleVisited(repoId, id);
  }

  function initNavButtons(lessons, repoId) {
    var prev = document.getElementById("tutorial-prev");
    var next = document.getElementById("tutorial-next");
    if (prev) {
      prev.addEventListener("click", function () {
        if (CodeGuide._activeIndex > 0) {
          navigateTo(lessons, repoId, lessonIdFromIndex(lessons, CodeGuide._activeIndex - 1), {});
        }
      });
    }
    if (next) {
      next.addEventListener("click", function () {
        if (CodeGuide._activeIndex < lessons.length - 1) {
          // B6: intentional Next click = mark current lesson visited immediately
          if (CodeGuide._activeId) { markVisited(repoId, CodeGuide._activeId); }
          navigateTo(lessons, repoId, lessonIdFromIndex(lessons, CodeGuide._activeIndex + 1), {});
        }
      });
    }
  }

  function initTOC(clusters, lessons, repoId) {
    var sidebar = document.getElementById("tutorial-sidebar");
    if (!sidebar) { return; }
    var lessonsByCluster = {};
    lessons.forEach(function (l) {
      (lessonsByCluster[l.cluster_id] = lessonsByCluster[l.cluster_id] || []).push(l);
    });
    clusters.forEach(function (c) {
      var wrap = document.createElement("div"); wrap.className = "cluster";
      var t = document.createElement("div"); t.className = "cluster-title"; t.textContent = c.label;
      wrap.appendChild(t);
      (lessonsByCluster[c.id] || []).forEach(function (l) {
        var btn = document.createElement("button");
        btn.className = "lesson-link" + (l.status === "skipped" ? " skipped" : "");
        btn.setAttribute("data-lesson-id", l.id);
        // B5: prepend checkmark indicator (visited state painted separately)
        var check = document.createElement("span");
        check.className = "lesson-check";
        check.setAttribute("aria-hidden", "true");
        btn.appendChild(check);
        var label = document.createElement("span");
        label.className = "lesson-link-text";
        label.textContent = l.title;
        btn.appendChild(label);
        btn.addEventListener("click", function () {
          // B6: intentional click = mark visited immediately (no 5s wait)
          markVisited(repoId, l.id);
          navigateTo(lessons, repoId, l.id, {});
        });
        wrap.appendChild(btn);
      });
      sidebar.appendChild(wrap);
    });
  }

  function initArrowNav(lessons, repoId) {
    document.addEventListener("keydown", function (e) {
      var el = document.activeElement;
      if (el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable)) { return; }
      if (e.key === "ArrowLeft" && CodeGuide._activeIndex > 0) {
        navigateTo(lessons, repoId, lessonIdFromIndex(lessons, CodeGuide._activeIndex - 1), {});
      } else if (e.key === "ArrowRight" && CodeGuide._activeIndex < lessons.length - 1) {
        navigateTo(lessons, repoId, lessonIdFromIndex(lessons, CodeGuide._activeIndex + 1), {});
      }
    });
  }

  function initHashRouting(lessons, repoId) {
    window.addEventListener("hashchange", function () {
      var id = activeLessonId();
      if (!id) { return; }
      navigateTo(lessons, repoId, id, { fromHash: true });
    });
  }

  function initScrollSync() {
    // v0.2.0: scroll-sync disabled by user request. Earlier "decision #3"
    // mirrored narration scroll into the code panel; users found it
    // disorienting because moving narration *also* moved the code, even
    // when they wanted to read both independently. Per-panel scroll is
    // now achieved purely by CSS (each column has its own ``overflow-y:
    // auto`` inside an ``overflow: hidden`` parent — see tutorial.css
    // ``#tutorial-content``). The function is kept as a placeholder so
    // a future opt-in toggle can re-enable it from the Tweaks panel.
    return;
  }

  function initSplitter() {
    var content = document.getElementById("tutorial-content");
    var splitter = document.getElementById("tutorial-splitter");
    if (!content || !splitter) { return; }

    function applyFrac(frac) {
      var clamped = Math.max(0.28, Math.min(0.72, frac));
      content.style.gridTemplateColumns = (clamped * 100).toFixed(2) + "% 10px " + ((1 - clamped) * 100).toFixed(2) + "%";
    }

    var saved = parseFloat(readStorage("codeguide:tweak:narr-frac:v2", "0.5"));
    applyFrac(isNaN(saved) ? 0.5 : saved);

    var dragging = false;
    splitter.addEventListener("pointerdown", function (e) {
      if (window.innerWidth < BREAKPOINT_PX) { return; }
      dragging = true; splitter.classList.add("dragging");
      splitter.setPointerCapture(e.pointerId);
    });
    splitter.addEventListener("pointermove", function (e) {
      if (!dragging) { return; }
      var rect = content.getBoundingClientRect();
      var frac = (e.clientX - rect.left) / rect.width;
      applyFrac(frac);
    });
    splitter.addEventListener("pointerup", function (e) {
      if (!dragging) { return; }
      dragging = false; splitter.classList.remove("dragging");
      try { splitter.releasePointerCapture(e.pointerId); } catch (err) { /* noop */ }
      var style = content.style.gridTemplateColumns || "";
      var m = style.match(/^([\d.]+)%/);
      if (m) { writeStorage("codeguide:tweak:narr-frac:v2", String(parseFloat(m[1]) / 100)); }
    });
  }

  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme === "dark" ? "dark" : "light");
  }

  function initTweaksPanel() {
    var panel = document.getElementById("tweaks-panel");
    var openBtn = document.getElementById("tweaks-open");
    if (!panel || !openBtn) { return; }
    openBtn.addEventListener("click", function (e) {
      e.stopPropagation();
      panel.classList.toggle("open");
    });
    document.addEventListener("click", function (e) {
      if (panel.classList.contains("open") && !panel.contains(e.target) && e.target !== openBtn) {
        panel.classList.remove("open");
      }
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") { panel.classList.remove("open"); }
    });
    var buttons = panel.querySelectorAll("[data-theme-set]");
    buttons.forEach(function (btn) {
      btn.addEventListener("click", function () {
        var t = btn.getAttribute("data-theme-set") || "light";
        applyTheme(t); writeStorage("codeguide:tweak:theme:v2", t);
        buttons.forEach(function (b) { b.classList.toggle("on", b === btn); });
      });
    });
  }

  // ── Visited-lesson tracking (B6: Track B v0.2.1) ─────────────────────────
  // A lesson is marked visited either:
  //   (a) 5 seconds after navigation (reading signal), or
  //   (b) immediately when the user explicitly clicks Next/TOC link.
  // State persisted to localStorage under "codeguide:<repoId>:visited-lessons:v1".

  var VISITED_TIMEOUT_MS = 5000;
  var _visitedTimer = null;

  function visitedKey(repoId) {
    return "codeguide:" + repoId + ":visited-lessons:v1";
  }

  function readVisited(repoId) {
    try {
      var raw = localStorage.getItem(visitedKey(repoId));
      return raw ? JSON.parse(raw) : [];
    } catch (e) { return []; }
  }

  function markVisited(repoId, lessonId) {
    try {
      var current = readVisited(repoId);
      if (current.indexOf(lessonId) === -1) {
        current.push(lessonId);
        localStorage.setItem(visitedKey(repoId), JSON.stringify(current));
      }
    } catch (e) { /* private mode — silent */ }
    paintVisited(repoId);
  }

  function paintVisited(repoId) {
    var visited = readVisited(repoId);
    var links = document.querySelectorAll(".lesson-link");
    for (var i = 0; i < links.length; i++) {
      var lid = links[i].getAttribute("data-lesson-id");
      if (lid && visited.indexOf(lid) !== -1) {
        links[i].classList.add("visited");
      } else {
        links[i].classList.remove("visited");
      }
    }
  }

  function scheduleVisited(repoId, lessonId) {
    if (_visitedTimer) { clearTimeout(_visitedTimer); }
    _visitedTimer = setTimeout(function () {
      markVisited(repoId, lessonId);
    }, VISITED_TIMEOUT_MS);
  }

  // ─────────────────────────────────────────────────────────────────────────

  CodeGuide.init = function () {
    var meta = safeJSON("tutorial-meta");
    var clusters = safeJSON("tutorial-clusters") || [];
    var lessons = safeJSON("tutorial-lessons") || [];
    CodeGuide._meta = meta; CodeGuide._clusters = clusters; CodeGuide._lessons = lessons;
    if (!lessons.length) { return; }

    validateSchema(meta);

    var repoId = (meta && meta.repo) ? meta.repo : "default";
    var savedTheme = readStorage("codeguide:tweak:theme:v2", "light");
    applyTheme(savedTheme);
    var currentBtn = document.querySelector('[data-theme-set="' + savedTheme + '"]');
    if (currentBtn) { currentBtn.classList.add("on"); }

    initTOC(clusters, lessons, repoId);
    paintVisited(repoId); // B6: restore visited checkmarks from previous sessions
    initSplitter();
    initScrollSync();
    initArrowNav(lessons, repoId);
    initNavButtons(lessons, repoId);
    initHashRouting(lessons, repoId);
    initTweaksPanel();

    var startId = activeLessonId() || readStorage("codeguide:" + repoId + ":last-lesson", lessons[0].id);
    navigateTo(lessons, repoId, startId || lessons[0].id, { fromHash: !!activeLessonId() });
  };
})();
