# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Persistent YAML-backed consent store (US-007).

Stores per-provider consent in a dedicated ``consent.yaml`` file inside the
user-level config directory (platform-appropriate via ``platformdirs``).
File permissions are set to ``0o600`` after every write so the file is not
readable by other users on multi-user systems.

The store is independent of ``config.yaml``: deleting ``consent.yaml`` clears
all consent without touching LLM provider settings (ADR-0010).
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import platformdirs
import yaml


class YamlConsentStore:
    """YAML-backed persistent consent store implementing the ``ConsentStore`` port.

    Args:
        path: Optional explicit path to the ``consent.yaml`` file.  When
            ``None``, defaults to
            ``<user_config_dir>/wiedunflow/consent.yaml``.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path: Path = path or (
            Path(platformdirs.user_config_dir("wiedunflow")) / "consent.yaml"
        )
        self._warned_windows: bool = False

    # ------------------------------------------------------------------
    # Public API (ConsentStore protocol)
    # ------------------------------------------------------------------

    def is_granted(self, provider: str) -> bool:
        """Return ``True`` iff a valid consent entry exists for *provider*.

        Args:
            provider: Provider name (e.g. ``"anthropic"`` or ``"openai"``).

        Returns:
            ``True`` when the store contains ``{provider: {granted: true}}``.
        """
        data = self._load()
        entry = data.get(provider)
        return isinstance(entry, dict) and entry.get("granted") is True

    def grant(self, provider: str, timestamp: datetime) -> None:
        """Persist consent for *provider* with the wall-clock *timestamp*.

        Creates the backing file (and parent directories) if absent.  File
        permissions are set to ``0o600`` on POSIX systems after every write.

        Args:
            provider: Provider name to grant consent for.
            timestamp: The wall-clock time the user accepted the banner.
        """
        data = self._load()
        data[provider] = {
            "granted": True,
            "granted_at": timestamp.isoformat(),
        }
        self._save(data)

    def revoke(self, provider: str) -> None:
        """Remove any previously granted consent for *provider*.

        If *provider* is not present the call is a no-op.

        Args:
            provider: Provider name whose consent entry should be deleted.
        """
        data = self._load()
        data.pop(provider, None)
        self._save(data)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load(self) -> dict[str, Any]:
        """Load and return the current consent data.

        Returns an empty dict when the file is absent or empty.
        """
        if not self._path.is_file():
            return {}
        try:
            with self._path.open("r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
            return data if isinstance(data, dict) else {}
        except (OSError, yaml.YAMLError):
            return {}

    def _save(self, data: dict[str, Any]) -> None:
        """Persist *data* to the backing YAML file.

        Creates parent directories as needed.  Sets file permissions to
        ``0o600`` on POSIX systems (skipped on Windows where the permission
        model differs).
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("w", encoding="utf-8") as fh:
            yaml.safe_dump(data, fh, default_flow_style=False, allow_unicode=True)
        if sys.platform != "win32":
            os.chmod(self._path, 0o600)
        elif not self._warned_windows:
            # On Windows we cannot replicate POSIX 0o600 without optional deps;
            # warn the user once per process so multi-user / RDP machines are
            # not silently exposed.
            sys.stderr.write(
                "[wiedunflow] consent.yaml stored at "
                f"{self._path} relies on the default Windows ACL of %APPDATA%; "
                "if this is a shared / RDP / domain-joined machine, "
                "review or remove the file manually after generation. "
                "(See README Privacy section.)\n"
            )
            self._warned_windows = True
