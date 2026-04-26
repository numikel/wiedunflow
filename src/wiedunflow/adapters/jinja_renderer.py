# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Jinja2-backed HTML renderer for the Sprint 5 pixel-perfect tutorial template.

Output contract (ADR-0009 schema v1.0.0):
  #tutorial-meta      -> {repo, sha, branch, generated_at, wiedunflow_version,
                          run_status, total_lessons, skipped_count}
  #tutorial-clusters  -> [{id, label, kicker?, description?}]
  #tutorial-lessons   -> [{id, cluster_id, title, confidence, status,
                            narrative, segments[], code_refs[]}]
"""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

import mistune
from jinja2 import Environment, FileSystemLoader, select_autoescape

from wiedunflow import __version__ as _wiedunflow_version
from wiedunflow.adapters.pygments_highlighter import highlight_python


class _OfflineHTMLRenderer(mistune.HTMLRenderer):
    """Markdown HTML renderer that preserves the ``file://`` offline invariant.

    WiedunFlow tutorials must not contain any external URLs (FR-14 / US-040).
    Opus narration occasionally cites external docs as markdown links; rendering
    them as ``<a href="https://...">`` trips ``validate_offline_invariant``.
    We strip the href and emit the link text only. Images are dropped entirely
    (alt text kept so the reader still gets context).
    """

    def link(
        self, text: str, url: str, title: str | None = None
    ) -> str:  # Drop href; keep visible text so narrative still reads naturally.
        return text

    def image(
        self, text: str, url: str, title: str | None = None
    ) -> str:  # Replace with alt text in italics; no external resource fetch.
        return f"<em>{text}</em>" if text else ""


# Module-level markdown parser. `escape=True` prevents lesson authors (LLM) from
# injecting raw HTML into the output; we only trust the markdown syntax itself.
# Default `plugins=None` keeps auto-linking disabled; our custom renderer also
# strips any explicit `[text](url)` href.
_markdown_to_html = mistune.create_markdown(
    escape=True, hard_wrap=False, renderer=_OfflineHTMLRenderer()
)

if TYPE_CHECKING:
    from wiedunflow.entities.code_symbol import CodeSymbol
    from wiedunflow.entities.doc_coverage import DocCoverage
    from wiedunflow.entities.lesson import Lesson
    from wiedunflow.entities.lesson_plan import LessonPlan

# Hard ceiling for a single code-panel render (very large files can inflate HTML
# size past the 8 MB PERFORMANCE_BUDGETS target; clamp here as a safety net).
_CODE_SNIPPET_FILE_LINE_CAP = 2000

# v0.3.x — code-panel trim. Files longer than the threshold are clipped to a
# window centred on the highlighted range (`highlight_range ± CONTEXT`) so the
# reader sees the function under discussion, not the whole module surrounding it.
_CODE_SNIPPET_TRIM_THRESHOLD = 60
_CODE_SNIPPET_CONTEXT = 8


_RENDERER_DIR = Path(__file__).parent.parent / "renderer"
_TEMPLATES_DIR = _RENDERER_DIR / "templates"
_FONTS_DIR = _RENDERER_DIR / "fonts"
_DEFAULT_CLUSTER_ID = "default"
_DEFAULT_CLUSTER_LABEL = "Tutorial"

_FONT_URL_PATTERN = re.compile(r"""url\(["']\.\./fonts/([^"')]+)["']\)""")


def _load_tokens_css_with_inline_fonts() -> str:
    """Return tokens.css with every ``url("../fonts/X.woff2")`` replaced by a data URI.

    This is required to satisfy US-040 (zero external deps on ``file://``): the
    rendered HTML ships as a single file, so the WOFF2 fonts must be embedded
    rather than referenced by relative path.
    """
    css_text = (_TEMPLATES_DIR / "tokens.css").read_text(encoding="utf-8")

    def replace(match: re.Match[str]) -> str:
        font_name = match.group(1)
        font_path = _FONTS_DIR / font_name
        if not font_path.is_file():
            return match.group(0)
        encoded = base64.b64encode(font_path.read_bytes()).decode("ascii")
        return f'url("data:font/woff2;base64,{encoded}")'

    return _FONT_URL_PATTERN.sub(replace, css_text)


def _build_code_snippet(
    lesson: Lesson,
    symbol_lookup: dict[str, CodeSymbol],
    repo_root: Path,
) -> dict[str, Any] | None:
    """Build a code-panel snippet for ``lesson`` from its primary ``code_refs``.

    Walks ``lesson.code_refs`` (symbol names emitted by Stage 5), picks the first
    that resolves via ``symbol_lookup``, reads the containing file, and returns
    the file path plus a slice of up to :data:`_CODE_SNIPPET_MAX_LINES` lines
    starting at the symbol's declaration. Returns ``None`` if no reference
    resolves (e.g. uncertain dynamic symbols) — caller emits a placeholder.
    """
    for ref_name in lesson.code_refs:
        symbol = symbol_lookup.get(ref_name)
        if symbol is None:
            continue
        file_abs = (repo_root / symbol.file_path).resolve()
        try:
            text = file_abs.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        all_lines = text.splitlines()[:_CODE_SNIPPET_FILE_LINE_CAP]
        if not all_lines:
            continue
        lang = "python" if symbol.file_path.suffix == ".py" else "text"
        # Highlight the full symbol body (decl line … end_lineno inclusive).
        # Falls back to a single-line highlight when the parser did not report
        # an end position (e.g. Jedi-only resolution for dynamic imports).
        end = symbol.end_lineno if symbol.end_lineno is not None else symbol.lineno
        highlight_range = list(range(symbol.lineno, min(end, len(all_lines)) + 1))

        # v0.3.x — Auto-trim long files to a window centred on the highlighted
        # range so the reader does not scroll a 200-line file to find a 5-line
        # function. Window = highlight ± _CODE_SNIPPET_CONTEXT lines, clamped
        # to file bounds. ``start_line`` becomes the absolute line number of
        # the first kept row so the gutter still shows real source positions.
        # NB: this is symbol-level trimming; per-lesson focus_range (showing
        # different fragments of the same long function for lessons that
        # discuss separate aspects of it) is a v0.5.0 follow-up requiring an
        # LLM-aware ``code_refs[*].focus_range`` field.
        first_visible = 1
        last_visible = len(all_lines)
        if highlight_range and (last_visible - first_visible + 1) > _CODE_SNIPPET_TRIM_THRESHOLD:
            first_visible = max(1, min(highlight_range) - _CODE_SNIPPET_CONTEXT)
            last_visible = min(len(all_lines), max(highlight_range) + _CODE_SNIPPET_CONTEXT)
        kept_slice = all_lines[first_visible - 1 : last_visible]
        highlighted_lines = [
            highlight_python(line) if lang == "python" else line for line in kept_slice
        ]
        return {
            "file": str(symbol.file_path).replace("\\", "/"),
            "lang": lang,
            "lines": highlighted_lines,
            "highlight": highlight_range,
            "start_line": first_visible,
        }
    return None


def _lesson_to_payload(
    lesson: Lesson,
    symbol_lookup: dict[str, CodeSymbol] | None = None,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Serialize a ``Lesson`` entity into the JSON payload expected by tutorial.js."""
    segments: list[dict[str, Any]] = []
    for seg in lesson.segments:
        entry: dict[str, Any] = {"kind": seg.kind, "text": seg.text}
        if seg.code_ref is not None:
            entry["code_ref"] = {
                "file": seg.code_ref.file,
                "lang": seg.code_ref.lang,
                "lines": [
                    highlight_python(line) if seg.code_ref.lang == "python" else line
                    for line in seg.code_ref.lines
                ],
                "highlight": list(seg.code_ref.highlight),
            }
        segments.append(entry)

    if not segments:
        # Narrative is markdown emitted by Stage 5 (Opus). Parse to HTML so the
        # browser receives rendered headings/code fences/lists instead of raw
        # markdown syntax. `escape=True` sanitises any stray HTML from the LLM.
        # `mistune.create_markdown()` with default renderer returns str, but the
        # type stub exposes `str | list[...]` (to cover AST renderers). Cast for mypy.
        rendered = _markdown_to_html(lesson.narrative)
        narrative_html = rendered.strip() if isinstance(rendered, str) else ""
        segments = [{"kind": "html", "text": narrative_html}]

    payload: dict[str, Any] = {
        "id": lesson.id,
        "cluster_id": _DEFAULT_CLUSTER_ID,
        "title": lesson.title,
        "confidence": lesson.confidence,
        "status": lesson.status,
        "narrative": lesson.narrative,
        "segments": segments,
        "code_refs": list(lesson.code_refs),
    }

    # v0.2.1 A6 — closing lesson "Helper functions you'll see along the way"
    # appendix; populated by use_cases.skip_trivial when planning_skip_trivial_helpers
    # is enabled. Track B JS reads `lesson.helper_appendix` from the JSON envelope.
    if lesson.helper_appendix:
        payload["helper_appendix"] = [
            {
                "symbol": h.symbol,
                "file_path": h.file_path,
                "line_start": h.line_start,
                "line_end": h.line_end,
            }
            for h in lesson.helper_appendix
        ]

    # v0.3.0 — non-default split layout (closing lesson runs single-column).
    if lesson.layout != "split":
        payload["layout"] = lesson.layout

    # v0.3.0 — pre-rendered HTML override for the right code pane (used by the
    # synthetic Project README lesson). When set, the JS bypasses the standard
    # source-highlighting render and injects this HTML verbatim (already
    # sanitised by mistune at build time).
    if lesson.code_panel_html:
        payload["code_panel_html"] = lesson.code_panel_html

    # Attach a lookup-based code snippet when the lesson has no inline
    # segment-level `code_ref` (the common Stage 5 output today). The browser
    # uses this to populate the right-hand code panel; without it the panel
    # shows "(no code reference)".
    has_inline_ref = any("code_ref" in seg for seg in segments)
    if not has_inline_ref and symbol_lookup is not None and repo_root is not None:
        snippet = _build_code_snippet(lesson, symbol_lookup, repo_root)
        if snippet is not None:
            payload["code_snippet"] = snippet

    return payload


def _build_meta(
    lesson_plan: LessonPlan,
    repo_name: str,
    generated_at: str,
    run_status: str,
    total_planned: int,
    skipped_count: int,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "wiedunflow_version": _wiedunflow_version,
        "repo": repo_name,
        "sha": lesson_plan.repo_commit_hash,
        "branch": lesson_plan.repo_branch,
        "generated_at": generated_at,
        "run_status": run_status,
        "total_lessons": total_planned or len(lesson_plan.lessons),
        "skipped_count": skipped_count,
    }


def _default_clusters(lessons_count: int) -> list[dict[str, Any]]:
    return [
        {
            "id": _DEFAULT_CLUSTER_ID,
            "label": _DEFAULT_CLUSTER_LABEL,
            "kicker": "All lessons",
            "description": "",
            "lesson_count": lessons_count,
        }
    ]


class JinjaRenderer:
    """Renders a ``LessonPlan`` into a single self-contained ``tutorial.html`` string."""

    _tokens_css_cache: str | None = None
    _tutorial_css_cache: str | None = None
    _tutorial_js_cache: str | None = None

    def __init__(self) -> None:
        self._env = Environment(
            loader=FileSystemLoader(str(_TEMPLATES_DIR)),
            autoescape=select_autoescape(["html"]),
            auto_reload=False,
            trim_blocks=True,
            lstrip_blocks=True,
        )

    @classmethod
    def _tokens_css(cls) -> str:
        if cls._tokens_css_cache is None:
            cls._tokens_css_cache = _load_tokens_css_with_inline_fonts()
        return cls._tokens_css_cache

    @classmethod
    def _tutorial_css(cls) -> str:
        if cls._tutorial_css_cache is None:
            cls._tutorial_css_cache = (_TEMPLATES_DIR / "tutorial.css").read_text(encoding="utf-8")
        return cls._tutorial_css_cache

    @classmethod
    def _tutorial_js(cls) -> str:
        if cls._tutorial_js_cache is None:
            cls._tutorial_js_cache = (_TEMPLATES_DIR / "tutorial.js").read_text(encoding="utf-8")
        return cls._tutorial_js_cache

    def render(
        self,
        lesson_plan: LessonPlan,
        *,
        repo_name: str,
        wiedunflow_version: str | None = None,
        generated_at: str,
        doc_coverage: DocCoverage | None = None,
        has_readme: bool = True,
        skipped_count: int = 0,
        degraded: bool = False,
        total_planned: int = 0,
        clusters: list[dict[str, Any]] | None = None,
        symbols: list[CodeSymbol] | None = None,
        repo_root: Path | None = None,
    ) -> str:
        """Return the rendered HTML string.

        Args:
            lesson_plan: Ordered collection of lessons to embed.
            repo_name: Human-readable repository name.
            wiedunflow_version: Package version string (defaults to :mod:`wiedunflow.__version__`).
            generated_at: ISO-8601 timestamp string.
            doc_coverage: Optional resolver coverage metrics (footer badge).
            has_readme: False triggers info banner about missing README.
            skipped_count: Number of skipped lessons (US-031).
            degraded: True renders DEGRADED banner (US-079).
            total_planned: Total planned lessons (DEGRADED "N of M" text).
            clusters: Optional cluster metadata. Defaults to a single cluster
                containing every lesson.
        """
        template = self._env.get_template("tutorial.html.j2")
        run_status = "degraded" if degraded else "ok"
        version = wiedunflow_version or _wiedunflow_version

        symbol_lookup = {s.name: s for s in symbols} if symbols else None
        lessons_payload = [
            _lesson_to_payload(lesson, symbol_lookup, repo_root) for lesson in lesson_plan.lessons
        ]
        clusters_payload = (
            clusters if clusters is not None else _default_clusters(len(lessons_payload))
        )
        meta_payload = _build_meta(
            lesson_plan=lesson_plan,
            repo_name=repo_name,
            generated_at=generated_at,
            run_status=run_status,
            total_planned=total_planned or len(lessons_payload),
            skipped_count=skipped_count,
        )

        return str(
            template.render(
                repo_name=repo_name,
                repo_branch=lesson_plan.repo_branch,
                repo_commit_hash=lesson_plan.repo_commit_hash,
                wiedunflow_version=version,
                generated_at=generated_at,
                doc_coverage=doc_coverage,
                has_readme=has_readme,
                skipped_count=skipped_count,
                degraded=degraded,
                run_status=run_status,
                total_planned=total_planned or len(lessons_payload),
                tokens_css=self._tokens_css(),
                tutorial_css=self._tutorial_css(),
                tutorial_js=self._tutorial_js(),
                meta_json=json.dumps(meta_payload, ensure_ascii=False),
                clusters_json=json.dumps(clusters_payload, ensure_ascii=False),
                lessons_json=json.dumps(lessons_payload, ensure_ascii=False),
            )
        )
