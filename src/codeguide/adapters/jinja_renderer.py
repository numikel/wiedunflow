# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from jinja2 import Environment, FileSystemLoader, select_autoescape

if TYPE_CHECKING:
    from codeguide.entities.lesson_plan import LessonPlan


_TEMPLATES_DIR = Path(__file__).parent.parent / "renderer" / "templates"


class JinjaRenderer:
    """Renders LessonPlan to a self-contained HTML file using a minimal Jinja2 template."""

    def __init__(self) -> None:
        self._env = Environment(
            loader=FileSystemLoader(str(_TEMPLATES_DIR)),
            autoescape=select_autoescape(["html"]),
            auto_reload=False,
        )

    def render(
        self,
        lesson_plan: LessonPlan,
        repo_name: str,
        codeguide_version: str,
        generated_at: str,
    ) -> str:
        """Return the rendered HTML as a string.

        Args:
            lesson_plan: The ordered collection of lessons to embed.
            repo_name: Human-readable repository name shown in the page title.
            codeguide_version: Package version string for the footer.
            generated_at: ISO-8601 timestamp string for the footer.

        Returns:
            Fully rendered HTML string with all lesson data embedded as JSON.
        """
        template = self._env.get_template("tutorial_minimal.html.j2")

        # Build the JSON payload for the <script type="application/json"> block.
        lessons_data = []
        for lesson in lesson_plan.lessons:
            # Convert double newlines into paragraph tags for the narrative HTML.
            paragraphs = lesson.narrative.split("\n\n")
            narrative_html = "<p>" + "</p><p>".join(paragraphs) + "</p>"
            lessons_data.append(
                {
                    "id": lesson.id,
                    "title": lesson.title,
                    "narrative": lesson.narrative,
                    "narrative_html": narrative_html,
                    "code_refs": list(lesson.code_refs),
                    "status": lesson.status,
                }
            )

        tutorial_data = {
            "schema_version": "1.0.0",
            "repo_name": repo_name,
            "lessons": lessons_data,
        }

        # tutorial_data_json is marked | safe in the template; we pass a plain
        # JSON string and rely on Jinja2's autoescape bypass via the safe filter.
        return str(
            template.render(
                repo_name=repo_name,
                repo_branch=lesson_plan.repo_branch,
                repo_commit_hash=lesson_plan.repo_commit_hash,
                codeguide_version=codeguide_version,
                generated_at=generated_at,
                tutorial_data_json=json.dumps(tutorial_data, ensure_ascii=False),
            )
        )
