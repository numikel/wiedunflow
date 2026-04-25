# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Re-render an existing ``tutorial.html`` with the current templates.

Pulls the lesson / cluster / meta JSON envelopes out of an existing report
and runs them through the bundled Jinja template + tokens.css + tutorial.css
+ tutorial.js. Lets you iterate on UI changes (CSS variables, JS handlers,
template structure) without paying for another LLM run.

Usage:
    uv run python scripts/rerender_html.py <input.html> [output.html]

If ``output.html`` is omitted the source file is overwritten in place.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from codeguide.adapters.jinja_renderer import _TEMPLATES_DIR, JinjaRenderer


_TRIM_THRESHOLD = 60
_TRIM_CONTEXT = 8


def _retrim_code_snippets(lessons: list[dict[str, Any]]) -> None:
    """In-place: clip overlong ``code_snippet`` arrays to a window centred on
    the highlighted range. Mirrors the trim logic in
    :mod:`codeguide.adapters.jinja_renderer` so static rerenders apply the
    same UX improvement without re-running the LLM pipeline.
    """
    for lesson in lessons:
        snip = lesson.get("code_snippet")
        if not isinstance(snip, dict):
            continue
        lines = snip.get("lines")
        highlight = snip.get("highlight") or []
        start_line = snip.get("start_line", 1)
        if not isinstance(lines, list) or not highlight:
            continue
        if len(lines) <= _TRIM_THRESHOLD:
            continue
        # Highlight numbers are absolute (1-indexed file line numbers).
        # Translate to indices within the current ``lines`` slice using
        # ``start_line`` so re-trimming an already-trimmed payload still works.
        rel_min = min(highlight) - start_line  # 0-indexed
        rel_max = max(highlight) - start_line
        first_idx = max(0, rel_min - _TRIM_CONTEXT)
        last_idx = min(len(lines), rel_max + 1 + _TRIM_CONTEXT)
        snip["lines"] = lines[first_idx:last_idx]
        snip["start_line"] = start_line + first_idx


def _extract_json_block(html: str, block_id: str) -> Any:
    """Pull the contents of ``<script type="application/json" id="...">``."""
    pattern = re.compile(
        r'<script type="application/json" id="' + re.escape(block_id) + r'">(.*?)</script>',
        re.DOTALL,
    )
    match = pattern.search(html)
    if match is None:
        raise SystemExit(f"Block #{block_id} not found in source HTML")
    return json.loads(match.group(1))


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        sys.stderr.write("usage: rerender_html.py <input.html> [output.html]\n")
        return 2

    src = Path(argv[1])
    dst = Path(argv[2]) if len(argv) > 2 else src
    if not src.is_file():
        sys.stderr.write(f"input file not found: {src}\n")
        return 1

    html = src.read_text(encoding="utf-8")
    meta = _extract_json_block(html, "tutorial-meta")
    clusters = _extract_json_block(html, "tutorial-clusters")
    lessons = _extract_json_block(html, "tutorial-lessons")

    # v0.3.x — apply the renderer's auto-trim so old reports get the same
    # focused code-panel view as fresh generations after the upgrade.
    _retrim_code_snippets(lessons)

    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
        auto_reload=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("tutorial.html.j2")

    rendered = template.render(
        repo_name=meta.get("repo", "unknown"),
        repo_branch=meta.get("branch", "main"),
        repo_commit_hash=meta.get("sha", "0000000"),
        codeguide_version=meta.get("codeguide_version", "0.3.0"),
        generated_at=meta.get("generated_at", ""),
        run_status=meta.get("run_status", "ok"),
        skipped_count=meta.get("skipped_count", 0),
        total_planned=meta.get("total_lessons", len(lessons)),
        doc_coverage=None,  # Missing from the embedded meta block; footer
        # falls back gracefully when the template guards on `is not none`.
        meta_json=json.dumps(meta, ensure_ascii=False),
        clusters_json=json.dumps(clusters, ensure_ascii=False),
        lessons_json=json.dumps(lessons, ensure_ascii=False),
        tokens_css=JinjaRenderer._tokens_css(),
        tutorial_css=JinjaRenderer._tutorial_css(),
        tutorial_js=JinjaRenderer._tutorial_js(),
    )

    dst.write_text(rendered, encoding="utf-8")
    size_kb = len(rendered.encode("utf-8")) // 1024
    sys.stdout.write(f"Rerendered: {dst} ({size_kb} KB)\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
