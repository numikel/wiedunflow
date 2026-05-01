from __future__ import annotations

import logging
import os

import pytest

log = logging.getLogger(__name__)


@pytest.fixture(scope="session", autouse=True)
def _openai_key_probe() -> None:
    """Validate OPENAI_API_KEY before spending money on LLM calls.

    No-op when OPENAI_API_KEY is unset (eval_api_key fixture handles the
    skip logic for the suite-level gate).
    """
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        return

    log.info(
        "Eval budget: $19 across 5 repos"
        " (click $2, requests $4, starlette $4, python-sdk-mcp $6, dateutil $3)"
    )

    try:
        from openai import AuthenticationError, OpenAI

        client = OpenAI(api_key=api_key)
        models = list(client.models.list().data)
        log.info("OPENAI_API_KEY valid — %d models reachable", len(models))
    except AuthenticationError as exc:
        pytest.exit(
            f"OPENAI_API_KEY is invalid (AuthenticationError: {exc}). "
            "Fix the key before running the eval suite.",
            returncode=1,
        )
    except Exception as exc:
        log.warning("OpenAI key probe failed unexpectedly: %s — proceeding anyway", exc)
