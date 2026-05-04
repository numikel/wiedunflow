/*
 * SPDX-License-Identifier: Apache-2.0
 * Copyright 2026 Michał Kamiński
 *
 * WiedunFlow tutorial.html vanilla JS navigation (Sprint 5 track C).
 * Inlined into tutorial.html.j2 via {% include %} — no external script tags.
 * Namespace: window.WiedunFlow (contract anchored by ADR-0009).
 */

(function () {
  "use strict";

  var SCHEMA_VERSION_SUPPORTED = "1.0.0";
  var BREAKPOINT_PX = 1024;

  var WiedunFlow = (window.WiedunFlow = window.WiedunFlow || {});
  WiedunFlow._errors = [];

  function safeJSON(id) {
    var el = document.getElementById(id);
    if (!el) {
      WiedunFlow._errors.push("missing-" + id);
      return null;
    }
    try {
      return JSON.parse(el.textContent || "null");
    } catch (e) {
      WiedunFlow._errors.push("parse-" + id);
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
        console.warn("WiedunFlow: unknown schema_version '" + v + "', supported: " + SCHEMA_VERSION_SUPPORTED);
      } catch (e) { /* no console */ }
    }
  }

  function renderNarration(lesson) {
    var root = document.getElementById("tutorial-narration-body");
    if (!root) { return; }
    root.innerHTML = "";
    // v0.3.x — visual cue that this is a special-layout lesson (closing,
    // README appendix). Rendered above the lesson title so the reader does
    // not mistake the missing right pane for a rendering bug.
    if (lesson.layout === "single" || lesson.id === "lesson-readme") {
      var badge = document.createElement("span");
      badge.className = "lesson-type-badge";
      badge.textContent = lesson.id === "lesson-readme" ? "REFERENCE" : "CLOSING";
      root.appendChild(badge);
    }
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
          tmpl.innerHTML = DOMPurify.sanitize(seg.text, {USE_PROFILES: {html: true}});
          root.appendChild(tmpl.content);
        } else if (seg.kind === "p") {
          var p = document.createElement("p"); p.innerHTML = DOMPurify.sanitize(seg.text, {USE_PROFILES: {html: true}}); root.appendChild(p);
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

    // Helper appendix (closing lesson) — populated by skip_trivial via
    // jinja_renderer; consumed only as the top-level lesson.helper_appendix
    // payload field (the legacy meta.helper_appendix branch was never wired).
    var helpers = Array.isArray(lesson.helper_appendix) ? lesson.helper_appendix : null;
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

  function _lessonHasExplicitCode(lesson) {
    // Returns true when the lesson has code that should be shown in the right pane.
    // Conservative: code_snippet (server-built from lesson.code_refs) counts —
    // the lesson was planned with code. Only truly code-free lessons (no code_refs
    // at all, and no code_panel_html) collapse to single-column layout.
    if (!lesson) { return false; }
    if (typeof lesson.code_panel_html === "string" && lesson.code_panel_html.length) { return true; }
    if (lesson.code_snippet) { return true; }
    var segs = lesson.segments;
    if (segs && segs.length) {
      for (var i = 0; i < segs.length; i++) {
        if (segs[i].code_ref) { return true; }
      }
    }
    return false;
  }

  function applyLayout(lesson) {
    // v0.3.0 — toggle the .layout-single class on #tutorial-content so CSS
    // can collapse the right code pane (closing lesson). Default "split"
    // strips the class so the standard 2-pane layout is restored.
    // v0.8.0 — also collapse when the lesson has no explicit code reference
    // (only the server-side code_snippet fallback), so narration-only lessons
    // don't show an unreferenced code block on the right.
    var content = document.getElementById("tutorial-content");
    var codePane = document.getElementById("tutorial-code");
    var splitter = document.getElementById("tutorial-splitter");
    if (!content) { return; }
    var single = !!(lesson && (lesson.layout === "single" || !_lessonHasExplicitCode(lesson)));
    content.classList.toggle("layout-single", single);
    // Belt-and-braces: also flip inline style so the collapse works even if
    // a later CSS rule wins specificity. Cleared on the next non-single
    // navigation so the standard 2-pane layout snaps back.
    if (codePane) { codePane.style.display = single ? "none" : ""; }
    if (splitter) { splitter.style.display = single ? "none" : ""; }
    content.style.gridTemplateColumns = single ? "1fr" : "";
  }

  function renderCode(lesson) {
    var root = document.getElementById("tutorial-code-body");
    var head = document.getElementById("tutorial-code-head");
    if (!root || !head) { return; }
    root.innerHTML = ""; head.textContent = "";

    // v0.3.0 — code pane override (used by the Project README lesson).
    // The pre-rendered HTML is sanitised by mistune at build time; we trust
    // the string and skip syntax highlighting / line numbers entirely.
    if (typeof lesson.code_panel_html === "string" && lesson.code_panel_html.length) {
      head.textContent = "Project README";
      var wrap = document.createElement("div");
      wrap.className = "code-readme prose";
      wrap.innerHTML = DOMPurify.sanitize(lesson.code_panel_html, {USE_PROFILES: {html: true}});
      root.appendChild(wrap);
      return;
    }
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
      // v0.3.x — match highlight against absolute file line numbers so
      // trimmed views (start_line > 1) still highlight the right rows.
      var absoluteLine = startLine + idx;
      row.className = "code-row" + (highlight.has(absoluteLine) ? " hl" : "");
      var ln = document.createElement("span"); ln.className = "ln";
      ln.textContent = String(absoluteLine);
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
    // v0.4.0 — append the footer directly under #tutorial-narration (the
    // scrolling container) instead of #tutorial-narration-body. Sticky needs
    // its parent to be the scroll surface; nesting it inside the body div
    // pinned the footer to the body's height and broke the bottom anchor.
    var narration = document.getElementById("tutorial-narration");
    if (!narration) { return; }
    // Strip any previous footer left over from the prior lesson before we
    // append a fresh one — otherwise repeated navigations stack footers.
    var existing = narration.querySelector(":scope > .lesson-footer");
    if (existing) { existing.remove(); }
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
      // v0.3.x — surface keyboard shortcuts at the highest-attention moment
      // (last lesson). Also discoverable via the cog dropdown, but most users
      // never open settings on a tutorial they're reading once.
      var hint = document.createElement("div");
      hint.className = "lesson-footer-hint";
      hint.innerHTML =
        'Tip: <kbd>J</kbd> / <kbd>K</kbd> to navigate · <kbd>?</kbd> for all shortcuts';
      footer.appendChild(hint);
    }
    narration.appendChild(footer);
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
      try { console.warn("WiedunFlow: unknown lesson id '" + id + "', falling back to first"); } catch (e) { /* noop */ }
      id = lessons[0].id; idx = 0;
    }
    // v0.3.0 — any intentional navigation (Next/Prev buttons, sidebar click,
    // keyboard J/K, inline next-btn) marks the lesson the user is leaving as
    // visited. Skipped for hash routing (URL paste / first load) and no-op
    // re-navigations to the same lesson so we don't paint freshly-opened
    // bookmarks as already-read.
    if (!options.fromHash && WiedunFlow._activeId && WiedunFlow._activeId !== id) {
      markVisited(repoId, WiedunFlow._activeId);
    }
    var lesson = lessons[idx];
    applyLayout(lesson);
    renderNarration(lesson); renderCode(lesson); setActiveLink(id); updateProgress(idx, lessons.length);
    renderLessonFooter(lessons, repoId, idx);
    updateNavButtons(idx, lessons.length);
    // v0.2.1/v0.4.0 — scroll narration body back to the top so each new lesson
    // starts with the heading in view. The body div is the actual scroller in
    // the flex-column layout (the parent has overflow:hidden); reset both for
    // safety on mobile (where the parent is the scroller).
    var narrationBody = document.getElementById("tutorial-narration-body");
    if (narrationBody) { narrationBody.scrollTop = 0; }
    var narrationParent = document.getElementById("tutorial-narration");
    if (narrationParent) { narrationParent.scrollTop = 0; }
    scrollHighlightIntoView();
    if (!options.fromHash) { location.hash = "#/lesson/" + id; }
    writeStorage("wiedunflow:" + repoId + ":last-lesson", id);
    WiedunFlow._activeIndex = idx; WiedunFlow._activeId = id;
    // B6: schedule visited after 5s of dwell (reading signal)
    scheduleVisited(repoId, id);
  }

  function initNavButtons(lessons, repoId) {
    var prev = document.getElementById("tutorial-prev");
    var next = document.getElementById("tutorial-next");
    if (prev) {
      prev.addEventListener("click", function () {
        if (WiedunFlow._activeIndex > 0) {
          navigateTo(lessons, repoId, lessonIdFromIndex(lessons, WiedunFlow._activeIndex - 1), {});
        }
      });
    }
    if (next) {
      next.addEventListener("click", function () {
        if (WiedunFlow._activeIndex < lessons.length - 1) {
          // B6: intentional Next click = mark current lesson visited immediately
          if (WiedunFlow._activeId) { markVisited(repoId, WiedunFlow._activeId); }
          navigateTo(lessons, repoId, lessonIdFromIndex(lessons, WiedunFlow._activeIndex + 1), {});
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
      if (e.key === "ArrowLeft" && WiedunFlow._activeIndex > 0) {
        navigateTo(lessons, repoId, lessonIdFromIndex(lessons, WiedunFlow._activeIndex - 1), {});
      } else if (e.key === "ArrowRight" && WiedunFlow._activeIndex < lessons.length - 1) {
        navigateTo(lessons, repoId, lessonIdFromIndex(lessons, WiedunFlow._activeIndex + 1), {});
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

    var saved = parseFloat(readStorage("wiedunflow:tweak:narr-frac:v2", "0.5"));
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
      if (m) { writeStorage("wiedunflow:tweak:narr-frac:v2", String(parseFloat(m[1]) / 100)); }
    });
  }

  // v0.3.0 — system theme follows OS preference via prefers-color-scheme.
  var _systemThemeMql = null;
  function _resolveTheme(theme) {
    if (theme === "system") {
      try {
        return (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches)
          ? "dark" : "light";
      } catch (e) { return "light"; }
    }
    return theme === "dark" ? "dark" : "light";
  }
  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", _resolveTheme(theme));
    // Re-bind the system listener so toggling between explicit/system works
    // without leaking duplicate listeners.
    if (_systemThemeMql && _systemThemeMql.handler) {
      try { _systemThemeMql.removeEventListener("change", _systemThemeMql.handler); }
      catch (e) { /* legacy MediaQueryList */ }
      _systemThemeMql = null;
    }
    if (theme === "system" && window.matchMedia) {
      _systemThemeMql = window.matchMedia("(prefers-color-scheme: dark)");
      _systemThemeMql.handler = function () { applyTheme("system"); };
      try { _systemThemeMql.addEventListener("change", _systemThemeMql.handler); }
      catch (e) { /* private mode / older browser */ }
    }
  }

  function applyFontSize(size) {
    var html = document.documentElement;
    if (size === "sm" || size === "lg") {
      html.setAttribute("data-font-size", size);
    } else {
      html.removeAttribute("data-font-size");  // "md" = default; remove attr
    }
  }

  function applyTocHidden(hidden) {
    var app = document.getElementById("tutorial-app");
    if (!app) { return; }
    if (hidden) { app.classList.add("toc-hidden"); }
    else { app.classList.remove("toc-hidden"); }
  }

  function setSegOn(panel, attrName, value) {
    var segButtons = panel.querySelectorAll("[" + attrName + "]");
    segButtons.forEach(function (b) {
      b.classList.toggle("on", b.getAttribute(attrName) === value);
    });
  }

  function _activeRepoId() {
    var meta = window.WiedunFlow && window.WiedunFlow._meta;
    return (meta && meta.repo) ? meta.repo : "default";
  }

  function resetVisitedMarkers() {
    var repoId = _activeRepoId();
    try { localStorage.removeItem(visitedKey(repoId)); }
    catch (e) { /* private mode — silent */ }
    paintVisited(repoId);
  }

  function showShortcutsModal(open) {
    var modal = document.getElementById("shortcuts-modal");
    if (!modal) { return; }
    if (open) {
      modal.classList.add("open");
      modal.setAttribute("aria-hidden", "false");
    } else {
      modal.classList.remove("open");
      modal.setAttribute("aria-hidden", "true");
    }
  }

  function initTweaksPanel() {
    var panel = document.getElementById("tweaks-panel");
    var openBtn = document.getElementById("tweaks-open");
    var modal = document.getElementById("shortcuts-modal");
    if (!panel || !openBtn) { return; }

    function _syncTweaksOpenClass() {
      // v0.3.x — body.tweaks-open powers the pointer-events guard that keeps
      // taps on narration/code panes from dismissing the dropdown on touch.
      document.body.classList.toggle("tweaks-open", panel.classList.contains("open"));
    }
    openBtn.addEventListener("click", function (e) {
      e.stopPropagation();
      panel.classList.toggle("open");
      _syncTweaksOpenClass();
    });
    document.addEventListener("click", function (e) {
      if (panel.classList.contains("open") && !panel.contains(e.target) && e.target !== openBtn) {
        panel.classList.remove("open");
        _syncTweaksOpenClass();
      }
      // Click outside the shortcuts modal closes it.
      if (modal && modal.classList.contains("open") && !modal.contains(e.target)) {
        showShortcutsModal(false);
      }
    });

    // Theme buttons
    var themeBtns = panel.querySelectorAll("[data-theme-set]");
    themeBtns.forEach(function (btn) {
      btn.addEventListener("click", function () {
        var t = btn.getAttribute("data-theme-set") || "light";
        applyTheme(t); writeStorage("wiedunflow:tweak:theme:v2", t);
        setSegOn(panel, "data-theme-set", t);
      });
    });

    // Font-size buttons
    var fontBtns = panel.querySelectorAll("[data-font-size-set]");
    fontBtns.forEach(function (btn) {
      btn.addEventListener("click", function () {
        var s = btn.getAttribute("data-font-size-set") || "md";
        applyFontSize(s); writeStorage("wiedunflow:tweak:font-size:v1", s);
        setSegOn(panel, "data-font-size-set", s);
      });
    });

    // Action buttons
    panel.querySelectorAll("[data-action]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var action = btn.getAttribute("data-action");
        if (action === "toggle-toc") {
          var app = document.getElementById("tutorial-app");
          var nowHidden = !(app && app.classList.contains("toc-hidden"));
          applyTocHidden(nowHidden);
          writeStorage("wiedunflow:tweak:toc-hidden:v1", nowHidden ? "1" : "0");
          btn.textContent = nowHidden ? "Show TOC sidebar" : "Hide TOC sidebar";
          btn.classList.toggle("on", nowHidden);
        } else if (action === "reset-visited") {
          // Two-click destructive pattern: first click arms the action and
          // changes the label; second click within 3 s actually resets. Any
          // later click reverts to the unarmed state with no data loss.
          if (btn.dataset.armed === "1") {
            resetVisitedMarkers();
            btn.textContent = "Cleared — reload to undo";
            btn.classList.remove("armed");
            delete btn.dataset.armed;
            setTimeout(function () { btn.textContent = "Reset visited markers"; }, 2500);
          } else {
            var origLabel = btn.textContent;
            btn.dataset.armed = "1";
            btn.classList.add("armed");
            btn.textContent = "Confirm reset?";
            setTimeout(function () {
              if (btn.dataset.armed === "1") {
                btn.textContent = origLabel;
                btn.classList.remove("armed");
                delete btn.dataset.armed;
              }
            }, 3000);
          }
        }
        // Note: "show-shortcuts" used to live here but the dedicated menu
        // entry was removed in v0.3.x — readers find shortcuts via the cog
        // tooltip ("? for keyboard shortcuts") and the lesson-footer-hint on
        // the final lesson. The `?` keyboard binding still toggles the modal.
      });
    });

    // Modal close button
    if (modal) {
      modal.querySelectorAll('[data-action="close-shortcuts"]').forEach(function (btn) {
        btn.addEventListener("click", function () { showShortcutsModal(false); });
      });
    }
  }

  function _isEditableTarget(el) {
    if (!el) { return false; }
    var tag = el.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") { return true; }
    return !!el.isContentEditable;
  }

  function initGlobalShortcuts(lessons, repoId) {
    document.addEventListener("keydown", function (e) {
      // Always-on: Escape closes overlays.
      if (e.key === "Escape") {
        var panel = document.getElementById("tweaks-panel");
        if (panel) {
          panel.classList.remove("open");
          document.body.classList.remove("tweaks-open");
        }
        showShortcutsModal(false);
        return;
      }
      // Skip when the user is typing into a form / contentEditable region.
      if (_isEditableTarget(e.target)) { return; }
      // Skip when modifier keys (other than plain Shift for "G") are held.
      if (e.ctrlKey || e.metaKey || e.altKey) { return; }

      var key = e.key;
      var idx = (window.WiedunFlow && typeof WiedunFlow._activeIndex === "number")
        ? WiedunFlow._activeIndex : 0;

      if (key === "j" || key === "ArrowDown") {
        if (idx < lessons.length - 1) {
          e.preventDefault();
          navigateTo(lessons, repoId, lessons[idx + 1].id, {});
        }
      } else if (key === "k" || key === "ArrowUp") {
        if (idx > 0) {
          e.preventDefault();
          navigateTo(lessons, repoId, lessons[idx - 1].id, {});
        }
      } else if (key === "G" && e.shiftKey) {
        e.preventDefault();
        navigateTo(lessons, repoId, lessons[lessons.length - 1].id, {});
      } else if (key === "g" && !e.shiftKey) {
        e.preventDefault();
        navigateTo(lessons, repoId, lessons[0].id, {});
      } else if (key === "?" || (e.shiftKey && key === "/")) {
        // Some keyboard layouts surface "?" as Shift+"/" with e.key="/" so we
        // accept either form to keep the shortcut reliable cross-platform.
        e.preventDefault();
        var modal = document.getElementById("shortcuts-modal");
        var alreadyOpen = modal && modal.classList.contains("open");
        showShortcutsModal(!alreadyOpen);
      }
    });
  }

  function _initTweaksFromStorage(panel) {
    if (!panel) { return; }
    var savedTheme = readStorage("wiedunflow:tweak:theme:v2", "light");
    applyTheme(savedTheme);
    setSegOn(panel, "data-theme-set", savedTheme);

    var savedSize = readStorage("wiedunflow:tweak:font-size:v1", "md");
    applyFontSize(savedSize);
    setSegOn(panel, "data-font-size-set", savedSize);

    var savedTocHidden = readStorage("wiedunflow:tweak:toc-hidden:v1", "0") === "1";
    applyTocHidden(savedTocHidden);
    var tocBtn = panel.querySelector('[data-action="toggle-toc"]');
    if (tocBtn) {
      tocBtn.textContent = savedTocHidden ? "Show TOC sidebar" : "Hide TOC sidebar";
      tocBtn.classList.toggle("on", savedTocHidden);
    }
  }

  // ── Visited-lesson tracking (B6: Track B v0.2.1) ─────────────────────────
  // A lesson is marked visited either:
  //   (a) 5 seconds after navigation (reading signal), or
  //   (b) immediately when the user explicitly clicks Next/TOC link.
  // State persisted to localStorage under "wiedunflow:<repoId>:visited-lessons:v1".

  var VISITED_TIMEOUT_MS = 5000;
  var _visitedTimer = null;

  function visitedKey(repoId) {
    return "wiedunflow:" + repoId + ":visited-lessons:v1";
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

  WiedunFlow.init = function () {
    var meta = safeJSON("tutorial-meta");
    var clusters = safeJSON("tutorial-clusters") || [];
    var lessons = safeJSON("tutorial-lessons") || [];
    WiedunFlow._meta = meta; WiedunFlow._clusters = clusters; WiedunFlow._lessons = lessons;
    if (!lessons.length) { return; }

    validateSchema(meta);

    var repoId = (meta && meta.repo) ? meta.repo : "default";

    initTOC(clusters, lessons, repoId);
    paintVisited(repoId); // B6: restore visited checkmarks from previous sessions
    initSplitter();
    initScrollSync();
    initArrowNav(lessons, repoId);
    initNavButtons(lessons, repoId);
    initHashRouting(lessons, repoId);
    initTweaksPanel();
    _initTweaksFromStorage(document.getElementById("tweaks-panel"));
    initGlobalShortcuts(lessons, repoId);

    var startId = activeLessonId() || readStorage("wiedunflow:" + repoId + ":last-lesson", lessons[0].id);
    navigateTo(lessons, repoId, startId || lessons[0].id, { fromHash: !!activeLessonId() });
  };
})();
