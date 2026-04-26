# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michal Kaminski
"""US-069: SecretFilter pattern coverage + edge cases."""

from __future__ import annotations

from pathlib import Path

import pytest

from wiedunflow.cli.secret_filter import redact, redact_path, truncate_source

_REDACTED = "[REDACTED]"


@pytest.mark.parametrize(
    "input_str,must_redact,must_not_contain",
    [
        # Anthropic sk-ant-api03 prefix
        ("api_key=sk-ant-api03-" + "x" * 80, _REDACTED, "sk-ant-api03"),
        # Anthropic sk-ant prefix (short prefix)
        ("Bearer sk-ant-" + "x" * 100, _REDACTED, "sk-ant-"),
        # OpenAI classic sk-
        ("OPENAI_API_KEY=sk-" + "x" * 48, _REDACTED, "sk-" + "x" * 48),
        # OpenAI project sk-proj-
        ("sk-proj-" + "x" * 64, _REDACTED, "sk-proj-"),
        # Bearer token (generic OAuth)
        (
            "Authorization: Bearer abcdefghijklmnopqrstuvwxyz0123456789ABCDEF",
            _REDACTED,
            "abcdefghijkl",
        ),
        # Authorization header with Token scheme
        ("authorization: Token abc123xyz890mnop", _REDACTED, "abc123xyz890"),
        # HuggingFace token
        ("hf_" + "a" * 30, _REDACTED, "hf_"),
        # Generic long hex (SHA-256 shape)
        ("hash=" + "a" * 64, _REDACTED, "a" * 64),
        # NEGATIVE: normal log message must pass through unchanged
        ("normal log message", "normal log message", ""),
        # NEGATIVE: short hex (short ids, lesson refs) must NOT be redacted
        ("lesson-007 passed", "lesson-007 passed", ""),
        # NEGATIVE: short alphanumeric ok
        ("file_hash=abc123", "file_hash=abc123", ""),
    ],
)
def test_redact_patterns(
    input_str: str,
    must_redact: str,
    must_not_contain: str,
) -> None:
    """redact() should replace known secrets and leave benign strings alone."""
    result = redact(input_str)
    assert must_redact in result, (
        f"Expected {must_redact!r} in result for {input_str!r}, got {result!r}"
    )
    if must_not_contain:
        assert must_not_contain not in result, (
            f"{must_not_contain!r} should not appear in result for {input_str!r}"
        )


def test_redact_leaves_benign_input_unchanged() -> None:
    """Pure benign strings must survive redact() unmodified."""
    benign = [
        "stage 1/7 ingestion complete",
        "PageRank computation took 2.3s",
        "lesson-003: BM25 retrieval",
        "Generating HTML output...",
    ]
    for msg in benign:
        assert redact(msg) == msg, f"Benign message altered: {msg!r}"


def test_redact_multiple_secrets_in_one_string() -> None:
    """Both Anthropic and OpenAI keys in the same log line are both redacted."""
    combined = "anthropic=sk-ant-api03-" + "A" * 80 + " openai=sk-" + "B" * 48
    result = redact(combined)
    assert _REDACTED in result
    assert "sk-ant-api03" not in result
    assert "sk-" + "B" * 48 not in result


def test_redact_path_replaces_external_absolute(tmp_path: Path) -> None:
    """redact_path() replaces paths outside repo_root with <external>."""
    repo_root = tmp_path / "myrepo"
    repo_root.mkdir()
    external_path = "/usr/local/lib/python3.11/site-packages/mylib"
    msg = f"loading from {external_path}"
    result = redact_path(msg, repo_root)
    assert "<external>" in result
    assert external_path not in result


def test_redact_path_keeps_internal_path(tmp_path: Path) -> None:
    """Paths INSIDE repo_root must NOT be replaced by redact_path()."""
    repo_root = tmp_path / "myrepo"
    repo_root.mkdir()
    internal = str(repo_root / "src" / "codeguide" / "cli" / "main.py")
    msg = f"parsing {internal}"
    result = redact_path(msg, repo_root)
    # Internal paths are kept - only external absolute paths are replaced
    assert internal in result


def test_redact_path_none_repo_root() -> None:
    """When repo_root=None, redact_path() is a no-op."""
    msg = "/usr/local/lib/python3.11/secret"
    assert redact_path(msg, None) == msg


def test_truncate_source_returns_hash_colon_symbol() -> None:
    """truncate_source() must return hash:symbol regardless of body size."""
    body = "def my_func():\n    return 42\n" * 100
    result = truncate_source(body, "deadbeef", "my_func")
    assert result == "deadbeef:my_func"


def test_truncate_source_default_max_chars_triggers_truncation() -> None:
    """truncate_source with max_chars=0 should always return the hash:symbol form."""
    body = "x" * 10_000
    result = truncate_source(body, "cafebabe", "BigClass", max_chars=0)
    assert result == "cafebabe:BigClass"
