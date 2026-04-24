# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Aggregate Apache-2.0 NOTICE files from runtime dependencies (US-062).

Used by the release workflow to ensure the project NOTICE file contains
attribution for every Apache-2.0 dependency we ship with.

Usage:
    # Write / refresh NOTICE
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

This product includes software developed by third parties:

"""


def _find_apache_deps() -> list[tuple[str, str]]:
    """Return ``[(package_name, license_classifier)]`` for Apache-2.0 deps.

    A distribution is considered Apache-2.0 when its ``Classifier`` field
    contains the string ``"Apache"`` or its ``License`` field does.
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
        classifiers = dist.metadata.get_all("Classifier") or []
        try:
            license_str = dist.metadata["License"] or ""
        except KeyError:
            license_str = ""
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

    new_content = "".join(lines)

    if missing:
        print(
            f"warning: missing NOTICE for {len(missing)} deps: {', '.join(missing)}",
            file=sys.stderr,
        )

    if check:
        if not output_path.exists():
            print(f"error: {output_path} does not exist", file=sys.stderr)
            return 1
        existing = output_path.read_text(encoding="utf-8")
        if existing != new_content:
            print(
                f"error: {output_path} is out of date — re-run aggregate_notice.py",
                file=sys.stderr,
            )
            return 1
        return 0

    output_path.write_text(new_content, encoding="utf-8")
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
    args = parser.parse_args()
    return aggregate(args.output, check=args.check)


if __name__ == "__main__":
    raise SystemExit(main())
