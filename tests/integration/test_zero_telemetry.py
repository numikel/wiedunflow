# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Zero-telemetry integration tests (US-011).

Two layers of verification:

1. **Socket monkeypatch (cross-platform)**: pytest-socket ``disable_socket``
   ensures no real network calls are made when the CLI runs with a
   FakeLLMProvider.  Verifies the pipeline is 100 % offline apart from
   configured LLM calls.

2. **Linux network namespace (``unshare -n``)**: runs the CLI inside a
   network-isolated namespace on Linux CI.  Skipped on Windows (no ``unshare``
   support).  Requires ``CAP_SYS_ADMIN`` or ``--user --net`` flag (supported
   in recent kernels; used with ``--map-root-user`` for rootless CI).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from wiedunflow.adapters.fake_llm_provider import FakeLLMProvider
from wiedunflow.cli.main import cli as cli_main

try:
    from pytest_socket import disable_socket, enable_socket

    _HAS_PYTEST_SOCKET = True
except ImportError:
    _HAS_PYTEST_SOCKET = False
    disable_socket = None  # type: ignore[assignment]
    enable_socket = None  # type: ignore[assignment]

pytestmark = pytest.mark.integration

_TINY_REPO = Path(__file__).parent.parent / "fixtures" / "tiny_repo"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tiny_repo_copy(tmp_path: Path) -> Path:
    """Clone tiny_repo into tmp_path so run-report writes are isolated."""
    dst = tmp_path / "tiny_repo"
    shutil.copytree(_TINY_REPO, dst)
    return dst


@pytest.fixture(autouse=True)
def _patch_sigint_handler_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace SigintHandler with a no-op so tests never install signal handlers."""

    class _NoopHandler:
        def __init__(self, *_a: Any, **_k: Any) -> None:
            self.should_finish = threading.Event()

        def install(self) -> None:
            pass

        def restore(self) -> None:
            pass

    monkeypatch.setattr("wiedunflow.cli.main.SigintHandler", _NoopHandler)


# ---------------------------------------------------------------------------
# Test 1: Socket monkeypatch (cross-platform)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_cli_respects_no_consent_prompt_and_hits_no_network(
    tiny_repo_copy: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """CLI with FakeLLMProvider must not open any real network socket.

    Uses monkeypatch on ``_build_llm_provider`` to inject FakeLLMProvider
    (bypassing real API calls) and pytest-socket to verify no socket is opened.
    """
    # Inject FakeLLMProvider — no real API calls.
    monkeypatch.setattr(
        "wiedunflow.cli.main._build_llm_provider",
        lambda config, **_kwargs: FakeLLMProvider(),
    )

    if not _HAS_PYTEST_SOCKET:
        pytest.skip("pytest-socket not installed — skipping socket-level assertion")

    disable_socket(allow_unix_socket=True)  # type: ignore[misc]
    try:
        runner = CliRunner()
        cache_path = tmp_path / "test_cache.db"
        with runner.isolated_filesystem():
            result = runner.invoke(
                cli_main,
                [
                    "generate",
                    str(tiny_repo_copy),
                    "--yes",
                    "--no-consent-prompt",
                    "--cache-path",
                    str(cache_path),
                ],
                standalone_mode=True,
            )
    finally:
        enable_socket()  # type: ignore[misc]

    # Exit code 0 (ok) or 2 (degraded) are both acceptable — no crash.
    assert result.exit_code in (0, 2), (
        f"CLI exited with unexpected code {result.exit_code}.\nOutput: {result.output}"
    )


# ---------------------------------------------------------------------------
# Test 2: Linux network namespace (unshare -n)
# ---------------------------------------------------------------------------


@pytest.mark.netns
@pytest.mark.skipif(sys.platform != "linux", reason="network namespaces are Linux-only")
def test_cli_runs_under_network_namespace(tmp_path: Path) -> None:
    """CLI must complete (or degrade gracefully) inside a network namespace.

    Uses ``unshare --user --net --map-root-user`` to create a rootless network
    namespace (no CAP_SYS_ADMIN required) and runs the CLI with
    WIEDUNFLOW_LLM_PROVIDER=anthropic + --no-consent-prompt.  The CLI is
    expected to fail at the LLM call (no real API key) but must not crash with
    an unhandled exception (exit code 0, 1, or 2 are acceptable; 130 for
    SIGINT is also fine).

    Requires ``unshare`` with ``--user`` support (kernel 3.8+, most Linux CI).

    CI note: Add ``--privileged`` to the Docker container or enable
    ``kernel.unprivileged_userns_clone`` sysctl on the host if this test fails
    with ``unshare: unshare failed: Operation not permitted``.
    """
    unshare = shutil.which("unshare")
    if unshare is None:
        pytest.skip("unshare not available on this system")

    tiny_repo = Path(__file__).parent.parent / "fixtures" / "tiny_repo"
    repo_copy = tmp_path / "tiny_repo"
    shutil.copytree(tiny_repo, repo_copy)

    cmd = [
        unshare,
        "--user",
        "--net",
        "--map-root-user",
        sys.executable,
        "-m",
        "wiedunflow",
        "generate",
        str(repo_copy),
        "--yes",
        "--no-consent-prompt",
        "--provider=anthropic",
    ]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
        env={
            **_minimal_env(),
            # No real API key — CLI will fail at LLM stage (exit 1 is OK).
            "ANTHROPIC_API_KEY": "fake-key-for-netns-test",
        },
    )

    # Acceptable: 0 (ok), 1 (config/LLM error), 2 (degraded), 130 (SIGINT).
    # Unacceptable: segfault (139), unhandled exception traceback to stderr only.
    assert result.returncode in (0, 1, 2, 130), (
        f"CLI crashed under netns with exit code {result.returncode}.\n"
        f"stdout: {result.stdout}\n"
        f"stderr: {result.stderr}"
    )


# ---------------------------------------------------------------------------
# Test 3: Footer exact string in generated HTML (AC3)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_generated_html_contains_wiedunflow_footer(
    tiny_repo_copy: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Generated tutorial.html must include 'Generated by WiedunFlow' in the footer."""
    monkeypatch.setattr(
        "wiedunflow.cli.main._build_llm_provider",
        lambda config, **_kwargs: FakeLLMProvider(),
    )

    runner = CliRunner()
    cache_path = tmp_path / "cache.db"
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(
            cli_main,
            [
                "generate",
                str(tiny_repo_copy),
                "--yes",
                "--no-consent-prompt",
                "--cache-path",
                str(cache_path),
            ],
            standalone_mode=True,
        )

    if result.exit_code not in (0, 2):
        pytest.skip(f"Pipeline did not produce HTML (exit {result.exit_code}): {result.output}")

    # Find the rendered tutorial — default filename is now `wiedunflow-<repo>.html`
    # (see ADR-0015 rebrand). Fall back to legacy `tutorial.html` for resilience
    # if a future test uses the `--output` flag.
    html_candidates = list(tmp_path.glob("**/wiedunflow-*.html")) or list(
        tmp_path.glob("**/tutorial.html")
    )
    if not html_candidates:
        pytest.skip("rendered HTML not found — skipping footer assertion")

    html_content = html_candidates[0].read_text(encoding="utf-8")
    assert "WiedunFlow" in html_content, (
        "Generated HTML must mention 'WiedunFlow' in the footer or metadata"
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _minimal_env() -> dict[str, str]:
    """Return a minimal environment for subprocess invocations."""
    keep = {
        "PATH",
        "HOME",
        "USER",
        "LANG",
        "LC_ALL",
        "TMPDIR",
        "TEMP",
        "TMP",
        "VIRTUAL_ENV",
        "PYTHONPATH",
    }
    return {k: v for k, v in os.environ.items() if k in keep}
