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
      return;
    }
    segments.forEach(function (seg) {
      if (seg.kind === "p") {
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
    if (!ref) { head.textContent = "(no code reference)"; return; }
    head.textContent = ref.file + " · " + (ref.lang || "python");
    var highlight = new Set((ref.highlight || []));
    (ref.lines || []).forEach(function (line, idx) {
      var row = document.createElement("div");
      row.className = "code-row" + (highlight.has(idx + 1) ? " hl" : "");
      var ln = document.createElement("span"); ln.className = "ln"; ln.textContent = String(idx + 1);
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

  function navigateTo(lessons, repoId, id, options) {
    options = options || {};
    var idx = indexOfLesson(lessons, id);
    if (idx < 0) {
      try { console.warn("CodeGuide: unknown lesson id '" + id + "', falling back to first"); } catch (e) { /* noop */ }
      id = lessons[0].id; idx = 0;
    }
    var lesson = lessons[idx];
    renderNarration(lesson); renderCode(lesson); setActiveLink(id); updateProgress(idx, lessons.length);
    if (!options.fromHash) { location.hash = "#/lesson/" + id; }
    writeStorage("codeguide:" + repoId + ":last-lesson", id);
    CodeGuide._activeIndex = idx; CodeGuide._activeId = id;
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
        btn.textContent = l.title;
        btn.addEventListener("click", function () { navigateTo(lessons, repoId, l.id, {}); });
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
    // Jednokierunkowy scroll-sync (decision #3): narration scroll drives code panel.
    var narr = document.getElementById("tutorial-narration");
    var code = document.getElementById("tutorial-code");
    if (!narr || !code) { return; }
    narr.addEventListener("scroll", function () {
      var ratio = narr.scrollTop / Math.max(1, narr.scrollHeight - narr.clientHeight);
      code.scrollTop = ratio * Math.max(1, code.scrollHeight - code.clientHeight);
    });
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
    initSplitter();
    initScrollSync();
    initArrowNav(lessons, repoId);
    initHashRouting(lessons, repoId);
    initTweaksPanel();

    var startId = activeLessonId() || readStorage("codeguide:" + repoId + ":last-lesson", lessons[0].id);
    navigateTo(lessons, repoId, startId || lessons[0].id, { fromHash: !!activeLessonId() });
  };
})();
