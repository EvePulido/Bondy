"""On-disk persistence under the cache directory (default ``<root>/.bondy/cache``).

Layout (only these names are ever written or deleted by Bondy)::

    <cache_dir>/verdicts/<sha256>.json   one model verdict per image (B4)
    <cache_dir>/pages.json               per-page hash + result (B9)
    <cache_dir>/resume.json              marker of an interrupted scan (B10)
    <.bondy>/.gitignore                  a single "*" so the folder never shows
                                         up in the scanned project's git status

The cache directory is only created when something needs it: a plain
deterministic scan writes nothing into the scanned project.

Rules: writes are atomic (temp file + ``os.replace``); every read tolerates a
missing, truncated or corrupt file (it is a miss, never a crash); entries hold
no API key and no absolute paths; an unwritable directory degrades to "no
cache" with a warning instead of failing the scan.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import tempfile
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from pydantic import ValidationError

STORE_SCHEMA = 1
VERDICTS_DIR = "verdicts"
PAGES_FILE = "pages.json"
RESUME_FILE = "resume.json"
DEFAULT_CACHE_DIR = Path(".bondy") / "cache"


def bondy_version() -> str:
    try:
        return version("bondy")
    except PackageNotFoundError:
        return "0.0.0+local"


def sha256_hex(*parts: bytes | str) -> str:
    h = hashlib.sha256()
    for p in parts:
        data = p.encode("utf-8") if isinstance(p, str) else p
        h.update(len(data).to_bytes(8, "big"))  # unambiguous concatenation
        h.update(data)
    return h.hexdigest()


def resolve_cache_dir(setting: str | None, root: Path) -> Path:
    """``cache_dir`` setting -> directory (relative paths are under ``root``)."""
    if not setting:
        return root / DEFAULT_CACHE_DIR
    p = Path(setting).expanduser()
    return p if p.is_absolute() else root / p


class Store:
    """Verdict cache + page state + resume marker. ``enabled=False`` = no I/O."""

    def __init__(self, directory: Path | None, enabled: bool = True):
        self.directory = directory
        self.enabled = enabled and directory is not None
        self.hits = 0
        self.misses = 0
        self.writes = 0
        self.warnings: list[str] = []
        self._write_failed = False

    # ----- low level -----
    def _warn(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)

    def _write_json(self, path: Path, data: Any) -> bool:
        if not self.enabled or self._write_failed:
            return False
        tmp: str | None = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._ensure_gitignore()
            fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(
                    data, f, ensure_ascii=False, separators=(",", ":"), default=str
                )
            os.replace(tmp, path)
            tmp = None
            return True
        except OSError as e:
            self._write_failed = True
            self._warn(
                f"cache directory is not writable ({type(e).__name__}); continuing "
                "without saving cache/state"
            )
            return False
        finally:
            if tmp:
                with contextlib.suppress(OSError):
                    os.remove(tmp)

    def _ensure_gitignore(self) -> None:
        """Writes ``.gitignore`` containing ``*`` once; never overwrites one."""
        assert self.directory is not None
        top = (
            self.directory.parent
            if self.directory.parent.name == ".bondy"
            else self.directory
        )
        try:
            with open(top / ".gitignore", "x", encoding="utf-8") as f:
                f.write("*\n")
        except OSError:  # exists already, or not writable (the write will warn)
            pass

    def _read_json(self, path: Path) -> Any | None:
        if not self.enabled:
            return None
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):  # missing, unreadable, truncated, corrupt
            return None

    # ----- verdicts (B4) -----
    def _verdict_path(self, key: str) -> Path:
        assert self.directory is not None
        return self.directory / VERDICTS_DIR / f"{key}.json"

    def get_verdict(self, key: str):
        """Cached ``ImageAnalysis`` or None (miss, corrupt or stale schema)."""
        from bondy.core.semantic import ImageAnalysis

        if not self.enabled:
            return None
        data = self._read_json(self._verdict_path(key))
        try:
            if not isinstance(data, dict) or data.get("schema") != STORE_SCHEMA:
                raise ValueError("bad entry")
            return ImageAnalysis.model_validate({**data["analysis"], "index": 0})
        except (ValueError, KeyError, TypeError, ValidationError):
            return None

    def put_verdict(self, key: str, analysis) -> None:
        body = analysis.model_dump()
        body.pop("index", None)
        if self._write_json(
            self._verdict_path(key), {"schema": STORE_SCHEMA, "analysis": body}
        ):
            self.writes += 1

    # ----- page state (B9) -----
    def load_pages(self, config_fp: str) -> dict[str, dict]:
        """Stored page results if they were produced with the same config."""
        if not self.enabled:
            return {}
        assert self.directory is not None
        data = self._read_json(self.directory / PAGES_FILE)
        if (
            not isinstance(data, dict)
            or data.get("schema") != STORE_SCHEMA
            or data.get("config") != config_fp
            or not isinstance(data.get("pages"), dict)
        ):
            return {}
        return data["pages"]

    def save_pages(self, config_fp: str, pages: dict[str, dict]) -> None:
        assert self.directory is not None
        self._write_json(
            self.directory / PAGES_FILE,
            {
                "schema": STORE_SCHEMA,
                "bondy": bondy_version(),
                "config": config_fp,
                "pages": pages,
            },
        )

    # ----- resume marker (B10) -----
    def load_resume(self) -> dict | None:
        if not self.enabled:
            return None
        assert self.directory is not None
        data = self._read_json(self.directory / RESUME_FILE)
        return data if isinstance(data, dict) else None

    def save_resume(self, config_fp: str, reasons: list[str], pending: int) -> None:
        assert self.directory is not None
        self._write_json(
            self.directory / RESUME_FILE,
            {
                "schema": STORE_SCHEMA,
                "config": config_fp,
                "reasons": reasons,
                "pages_pending": pending,
            },
        )

    def clear_resume(self) -> None:
        if self.enabled and self.directory is not None:
            with contextlib.suppress(OSError):
                os.remove(self.directory / RESUME_FILE)

    # ----- maintenance -----
    def clear(self, include_state: bool = True) -> int:
        """Deletes Bondy's own files only (never the directory tree itself)."""
        if self.directory is None:
            return 0
        removed = 0
        vdir = self.directory / VERDICTS_DIR
        if vdir.is_dir():
            for p in vdir.iterdir():
                if p.is_file() and p.suffix == ".json":
                    with contextlib.suppress(OSError):
                        p.unlink()
                        removed += 1
            with contextlib.suppress(OSError):
                vdir.rmdir()
        if include_state:
            for name in (PAGES_FILE, RESUME_FILE):
                p = self.directory / name
                if p.is_file():
                    with contextlib.suppress(OSError):
                        p.unlink()
                        removed += 1
        return removed
