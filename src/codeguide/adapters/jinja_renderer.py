# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Jinja2-backed HTML renderer for the Sprint 5 pixel-perfect tutorial template.

Output contract (ADR-0009 schema v1.0.0):
  #tutorial-meta      -> {repo, sha, branch, generated_at, codeguide_version,
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

from jinja2 import Environment, FileSystemLoader, select_autoescape

from codeguide import __version__ as _codeguide_version
from codeguide.adapters.pygments_highlighter import highlight_python

if TYPE_CHECKING:
    from codeguide.entities.doc_coverage import DocCoverage
    from codeguide.entities.lesson import Lesson
    from codeguide.entities.lesson_plan import LessonPlan


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


def _lesson_to_payload(lesson: Lesson) -> dict[str, Any]:
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
        paragraphs = [p.strip() for p in lesson.narrative.split("\n\n") if p.strip()]
        segments = [{"kind": "p", "text": p} for p in paragraphs]

    return {
        "id": lesson.id,
        "cluster_id": _DEFAULT_CLUSTER_ID,
        "title": lesson.title,
        "confidence": lesson.confidence,
        "status": lesson.status,
        "narrative": lesson.narrative,
        "segments": segments,
        "code_refs": list(lesson.code_refs),
    }


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
        "codeguide_version": _codeguide_version,
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
        codeguide_version: str | None = None,
        generated_at: str,
        doc_coverage: DocCoverage | None = None,
        has_readme: bool = True,
        skipped_count: int = 0,
        degraded: bool = False,
        total_planned: int = 0,
        clusters: list[dict[str, Any]] | None = None,
    ) -> str:
        """Return the rendered HTML string.

        Args:
            lesson_plan: Ordered collection of lessons to embed.
            repo_name: Human-readable repository name.
            codeguide_version: Package version string (defaults to :mod:`codeguide.__version__`).
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
        version = codeguide_version or _codeguide_version

        lessons_payload = [_lesson_to_payload(lesson) for lesson in lesson_plan.lessons]
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
                codeguide_version=version,
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
