# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Aggregate Apache-2.0 NOTICE files from runtime dependencies (US-062).

Used by the release workflow to ensure the project NOTICE file contains
attribution for every Apache-2.0 dependency we ship with.

Usage:
    # Write / refresh NOTICE (explicit)
    uv run python scripts/aggregate_notice.py --write

    # Write / refresh NOTICE (legacy default — same as --write)
    uv run python scripts/aggregate_notice.py

    # Release gate: fail if NOTICE is out of date
    uv run python scripts/aggregate_notice.py --check
"""

from __future__ import annotations

import argparse
import sys
from importlib import metadata
from pathlib import Path

_HEADER = """\
CodeGuide
Copyright 2026 Michał Kamiński

This product includes software developed at Astral (https://astral.sh/)
(uv, ruff — both licensed under MIT / Apache-2.0).

This product includes the Inter typeface, licensed under SIL OFL 1.1.
Copyright 2016-2024 The Inter Project Authors (https://github.com/rsms/inter).
See src/codeguide/renderer/fonts/OFL-Inter.txt for the full license.

This product includes the JetBrains Mono typeface, licensed under SIL OFL 1.1.
Copyright 2020 The JetBrains Mono Project Authors
(https://github.com/JetBrains/JetBrainsMono).
See src/codeguide/renderer/fonts/OFL-JetBrainsMono.txt for the full license.

This product includes software developed by third parties under the Apache-2.0
license. Their NOTICE attribution blocks follow:

"""


def _find_apache_deps() -> list[tuple[str, str]]:
    """Return ``[(package_name, license_classifier)]`` for Apache-2.0 deps.

    A distribution is considered Apache-2.0 when its ``Classifier`` field
    contains the string ``"Apache"`` or its ``License`` field does.

    The ``codeguide`` package itself is excluded — it is the project being
    built, not a third-party runtime dependency.
    """
    apache_deps: list[tuple[str, str]] = []
    for dist in metadata.distributions():
        # PackageMetadata exposes __getitem__ / get_all; the typeshed stub does
        # not model .get(), so use subscript access with KeyError fallback.
        try:
            name = dist.metadata["Name"]
        except KeyError:
            continue
        if not name:
            continue
        # Exclude the project itself — its NOTICE is the file we are writing,
        # not a third-party attribution block.
        if name.lower() == "codeguide":
            continue
        classifiers = dist.metadata.get_all("Classifier") or []
        # Use .get() to avoid DeprecationWarning from implicit None returns
        # on missing keys (importlib.metadata >= 3.12 behaviour change).
        license_str = dist.metadata.get("License") or ""
        if any("Apache" in c for c in classifiers) or "Apache" in license_str:
            apache_deps.append((name, "Apache-2.0"))
    return sorted(set(apache_deps))


def _get_notice_content(package_name: str) -> str | None:
    """Return the content of ``<package>/NOTICE`` if it exists.

    Looks for ``NOTICE``, ``NOTICE.TXT``, and ``NOTICE.MD`` (case-insensitive)
    in the distribution's recorded files.

    Args:
        package_name: Canonical distribution name (e.g. ``"anthropic"``).

    Returns:
        File content on success, or ``None`` if no NOTICE file is found.
    """
    try:
        files = metadata.files(package_name) or []
    except metadata.PackageNotFoundError:
        return None
    for f in files:
        if f.name.upper() in ("NOTICE", "NOTICE.TXT", "NOTICE.MD"):
            try:
                content = f.read_text()
            except (OSError, UnicodeDecodeError):
                continue
            if content.strip():
                return content
    return None


def aggregate(output_path: Path, *, check: bool = False) -> int:
    """Aggregate Apache-2.0 NOTICE content into *output_path*.

    When ``check=True``, the function compares the freshly generated content
    against the existing file and returns ``1`` if they differ — this is the
    release-gate mode used by the GitHub Actions workflow.

    Args:
        output_path: Destination file (usually ``NOTICE`` at project root).
        check: When ``True``, verify instead of write.

    Returns:
        Exit code: ``0`` on success, ``1`` on check-mode mismatch or error.
    """
    apache_deps = _find_apache_deps()
    lines: list[str] = [_HEADER]
    missing: list[str] = []

    for name, _license in apache_deps:
        notice = _get_notice_content(name)
        if notice is None:
            missing.append(name)
            lines.append(f"## {name}\n(no NOTICE file found in distribution)\n\n")
        else:
            lines.append(f"## {name}\n{notice}\n\n")

    # Strip trailing blank lines and ensure exactly one trailing LF so the
    # file satisfies the `end-of-file-fixer` pre-commit hook (which requires
    # exactly one newline at EOF) and stays byte-identical on re-runs.
    new_content = "".join(lines).rstrip("\n") + "\n"

    if missing:
        print(
            f"warning: missing NOTICE for {len(missing)} deps: {', '.join(missing)}",
            file=sys.stderr,
        )

    # Enforce LF line endings so the generated NOTICE is byte-identical
    # across POSIX (LF) and Windows (CRLF when using default text mode).
    new_bytes = new_content.replace("\r\n", "\n").encode("utf-8")

    if check:
        if not output_path.exists():
            print(f"error: {output_path} does not exist", file=sys.stderr)
            return 1
        existing_bytes = output_path.read_bytes().replace(b"\r\n", b"\n")
        if existing_bytes != new_bytes:
            print(
                f"error: {output_path} is out of date — re-run aggregate_notice.py",
                file=sys.stderr,
            )
            return 1
        return 0

    output_path.write_bytes(new_bytes)
    print(
        f"NOTICE written to {output_path} ({len(apache_deps)} Apache deps, {len(missing)} missing)",
        file=sys.stderr,
    )
    return 0


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Aggregate Apache-2.0 NOTICE files from runtime dependencies.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("NOTICE"),
        help="Destination NOTICE file (default: NOTICE).",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify that NOTICE is up to date (release gate — exits 1 if not).",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help=(
            "Explicitly regenerate NOTICE in place (same as the default behaviour, "
            "but makes the intent clear in scripts and CI)."
        ),
    )
    args = parser.parse_args()
    if args.check and args.write:
        parser.error("--check and --write are mutually exclusive")
    return aggregate(args.output, check=args.check)


if __name__ == "__main__":
    raise SystemExit(main())
