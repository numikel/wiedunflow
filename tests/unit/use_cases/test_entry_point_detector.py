# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Unit tests for detect_entry_points."""

from __future__ import annotations

from pathlib import Path

from codeguide.use_cases.entry_point_detector import detect_entry_points

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_py(tmp_path: Path, rel_name: str, source: str) -> Path:
    """Write source to tmp_path/rel_name and return the relative Path."""
    full = tmp_path / rel_name
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(source, encoding="utf-8")
    return Path(rel_name)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_def_main_at_module_level_detected(tmp_path: Path) -> None:
    """Top-level def main(): is detected as an entry point."""
    rel = _write_py(tmp_path, "app.py", "def main():\n    pass\n")
    result = detect_entry_points(tmp_path, (rel,))
    assert "app.main" in result


def test_def_cli_at_module_level_detected(tmp_path: Path) -> None:
    """Top-level def cli(): is detected as an entry point."""
    rel = _write_py(tmp_path, "cli.py", "def cli():\n    pass\n")
    result = detect_entry_points(tmp_path, (rel,))
    assert "cli.cli" in result


def test_run_underscore_pattern_detected(tmp_path: Path) -> None:
    """def run_app(): matches the run_\\w+ pattern → entry point."""
    rel = _write_py(tmp_path, "server.py", "def run_app():\n    pass\n")
    result = detect_entry_points(tmp_path, (rel,))
    assert "server.run_app" in result


def test_if_name_main_block_function_detected(tmp_path: Path) -> None:
    """Function called inside if __name__ == '__main__': is an entry point."""
    source = 'def foo():\n    pass\n\nif __name__ == "__main__":\n    foo()\n'
    rel = _write_py(tmp_path, "script.py", source)
    result = detect_entry_points(tmp_path, (rel,))
    assert "script.foo" in result


def test_click_command_decorator_detected(tmp_path: Path) -> None:
    """@click.command decorated function is detected as entry point."""
    source = "import click\n\n@click.command\ndef bar():\n    pass\n"
    rel = _write_py(tmp_path, "cli_app.py", source)
    result = detect_entry_points(tmp_path, (rel,))
    assert "cli_app.bar" in result


def test_click_command_with_parens_detected(tmp_path: Path) -> None:
    """@click.command() (call form) decorated function is detected as entry point."""
    source = "import click\n\n@click.command()\ndef run():\n    pass\n"
    rel = _write_py(tmp_path, "cli_call.py", source)
    result = detect_entry_points(tmp_path, (rel,))
    assert "cli_call.run" in result


def test_app_command_decorator_detected(tmp_path: Path) -> None:
    """@app.command decorated function (Typer-style) is detected."""
    source = "import typer\napp = typer.Typer()\n\n@app.command\ndef baz():\n    pass\n"
    rel = _write_py(tmp_path, "typer_app.py", source)
    result = detect_entry_points(tmp_path, (rel,))
    assert "typer_app.baz" in result


def test_argparse_in_body_detected(tmp_path: Path) -> None:
    """Function containing ArgumentParser() is detected as entry point."""
    source = (
        "import argparse\n"
        "\n"
        "def parse_args():\n"
        "    parser = argparse.ArgumentParser()\n"
        "    return parser.parse_args()\n"
    )
    rel = _write_py(tmp_path, "argparse_mod.py", source)
    result = detect_entry_points(tmp_path, (rel,))
    assert "argparse_mod.parse_args" in result


def test_main_module_with_def_main_detected(tmp_path: Path) -> None:
    """__main__.py containing def main(): is detected as entry point."""
    source = "def main():\n    print('hello')\n"
    rel = _write_py(tmp_path, "__main__.py", source)
    result = detect_entry_points(tmp_path, (rel,))
    assert "__main__.main" in result


def test_no_entry_points_returns_empty_frozenset(tmp_path: Path) -> None:
    """Repository without any entry-point patterns → empty frozenset."""
    source = (
        "def helper(a, b):\n"
        "    return a + b\n"
        "\n"
        "def internal_process(data):\n"
        "    return data.strip()\n"
    )
    rel = _write_py(tmp_path, "utils.py", source)
    result = detect_entry_points(tmp_path, (rel,))
    assert result == frozenset()


def test_returns_frozenset_type(tmp_path: Path) -> None:
    """Return type is always frozenset (even with matches)."""
    source = "def main():\n    pass\n"
    rel = _write_py(tmp_path, "m.py", source)
    result = detect_entry_points(tmp_path, (rel,))
    assert isinstance(result, frozenset)


def test_empty_file_list_returns_empty_frozenset(tmp_path: Path) -> None:
    """No files provided → empty frozenset."""
    result = detect_entry_points(tmp_path, ())
    assert result == frozenset()


def test_nonexistent_file_does_not_raise(tmp_path: Path) -> None:
    """Missing file is silently skipped; function does not raise."""
    result = detect_entry_points(tmp_path, (Path("no_such_file.py"),))
    assert result == frozenset()


def test_multiple_files_aggregated(tmp_path: Path) -> None:
    """Entry points from multiple files are all returned."""
    rel_a = _write_py(tmp_path, "a.py", "def main():\n    pass\n")
    rel_b = _write_py(tmp_path, "b.py", "def cli():\n    pass\n")
    result = detect_entry_points(tmp_path, (rel_a, rel_b))
    assert "a.main" in result
    assert "b.cli" in result


def test_nested_package_entry_point(tmp_path: Path) -> None:
    """Entry point in a nested package gets qualified name with dots."""
    source = "def run():\n    pass\n"
    rel = _write_py(tmp_path, "pkg/sub/entry.py", source)
    result = detect_entry_points(tmp_path, (rel,))
    assert "pkg.sub.entry.run" in result


def test_def_run_detected(tmp_path: Path) -> None:
    """def run(): matches the entry-point name pattern."""
    rel = _write_py(tmp_path, "srv.py", "def run():\n    pass\n")
    result = detect_entry_points(tmp_path, (rel,))
    assert "srv.run" in result
