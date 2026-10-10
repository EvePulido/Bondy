"""Bondy configuration: ``bondy.toml`` + environment variables + CLI flags.

Precedence (highest first): **flag > environment variable > bondy.toml > default**.

This module only depends on the standard library so it can be used by the core
package (CLI, doctor) without FastAPI or ADK. It never modifies ``os.environ``.

The API key is deliberately *not* readable from ``bondy.toml``: that file is
meant to be committed to the repository. It comes from ``GEMINI_API_KEY`` or
``GOOGLE_API_KEY`` (in that order) or, programmatically, from a flag.
"""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CONFIG_FILENAME = "bondy.toml"
API_KEY_ENV_VARS = ("GEMINI_API_KEY", "GOOGLE_API_KEY")

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


class ConfigError(ValueError):
    """Raised for an unreadable or invalid configuration (message is actionable)."""


def _to_bool(value: Any, where: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in _TRUE | _FALSE:
        return value.strip().lower() in _TRUE
    raise ConfigError(f"{where}: expected a boolean (true/false), got {value!r}.")


def _to_str(value: Any, where: str) -> str:
    if isinstance(value, str):
        return value
    raise ConfigError(f"{where}: expected a string, got {value!r}.")


def _to_str_list(value: Any, where: str) -> list[str]:
    if isinstance(value, str):  # env / flag form: "a,b,c"
        return [p.strip() for p in value.split(",") if p.strip()]
    if isinstance(value, list | tuple) and all(isinstance(v, str) for v in value):
        return list(value)
    raise ConfigError(f"{where}: expected a list of strings, got {value!r}.")


def _choice(*options: str):
    def convert(value: Any, where: str) -> str:
        text = _to_str(value, where).strip().lower()
        if text not in options:
            raise ConfigError(
                f"{where}: must be one of {', '.join(options)}; got {value!r}."
            )
        return text

    return convert


# field -> (converter, environment variable or None, default)
_FIELDS: dict[str, tuple[Any, str | None, Any]] = {
    "model": (_to_str, "BONDY_MODEL", "gemini-flash-latest"),
    "vision_model": (_to_str, "BONDY_VISION_MODEL", "gemini-flash-latest"),
    # An empty string disables the fallback model (same as the old env var).
    "fallback_model": (_to_str, "BONDY_FALLBACK_MODEL", "gemini-3.5-flash-lite"),
    "no_llm": (_to_bool, "BONDY_NO_LLM", False),
    # Force browser-free (static) mode, e.g. in CI without a browser.
    "static": (_to_bool, "BONDY_STATIC", False),
    "format": (_choice("terminal", "json"), "BONDY_FORMAT", "terminal"),
    "fail_on": (_choice("critical", "warning", "never"), "BONDY_FAIL_ON", "critical"),
    "checks": (_to_str_list, "BONDY_CHECKS", []),
    "include": (_to_str_list, "BONDY_INCLUDE", ["**/*.html", "**/*.htm"]),
    "exclude": (
        _to_str_list,
        "BONDY_EXCLUDE",
        ["node_modules/**", ".git/**", "dist/**", "build/**"],
    ),
}


@dataclass(frozen=True)
class Settings:
    """Resolved settings. ``sources`` records where each value came from."""

    model: str
    vision_model: str
    fallback_model: str
    no_llm: bool
    static: bool
    format: str
    fail_on: str
    checks: list[str]
    include: list[str]
    exclude: list[str]
    api_key: str | None = field(default=None, repr=False)  # never printed
    sources: dict[str, str] = field(default_factory=dict)
    config_path: Path | None = None


def find_config_file(start: Path | str | None = None) -> Path | None:
    """Returns the nearest ``bondy.toml`` walking up from ``start`` (default cwd)."""
    current = Path(start or Path.cwd()).resolve()
    if current.is_file():
        current = current.parent
    for directory in (current, *current.parents):
        candidate = directory / CONFIG_FILENAME
        if candidate.is_file():
            return candidate
    return None


def _read_file(path: Path) -> dict[str, Any]:
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: invalid TOML ({e}).") from e
    except OSError as e:
        raise ConfigError(f"{path}: cannot be read ({e}).") from e
    unknown = sorted(set(data) - set(_FIELDS))
    if unknown:
        hint = (
            " The API key must not be stored in bondy.toml; set "
            f"{' or '.join(API_KEY_ENV_VARS)} instead."
            if "api_key" in unknown
            else ""
        )
        raise ConfigError(
            f"{path}: unknown key(s): {', '.join(unknown)}. "
            f"Valid keys: {', '.join(_FIELDS)}.{hint}"
        )
    return data


def resolve_api_key(env: Mapping[str, str] | None = None) -> str | None:
    """First non-empty of ``GEMINI_API_KEY`` then ``GOOGLE_API_KEY``."""
    env = os.environ if env is None else env
    for name in API_KEY_ENV_VARS:
        value = env.get(name, "").strip()
        if value:
            return value
    return None


def load_settings(
    flags: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
    config_path: Path | str | None = None,
    start_dir: Path | str | None = None,
) -> Settings:
    """Resolves settings with precedence flag > env > file > default.

    Args:
        flags: Values from CLI flags. Keys with a value of ``None`` are treated
            as "not provided". May include ``api_key``.
        env: Environment mapping (defaults to ``os.environ``; never modified).
        config_path: Explicit ``bondy.toml`` (error if missing). When omitted the
            nearest one above ``start_dir`` / cwd is used, if any.
        start_dir: Where to start looking for ``bondy.toml``.
    """
    flags = dict(flags or {})
    env = os.environ if env is None else env

    path: Path | None
    if config_path is not None:
        path = Path(config_path)
        if not path.is_file():
            raise ConfigError(f"Config file not found: {path}.")
    else:
        path = find_config_file(start_dir)
    file_values = _read_file(path) if path else {}

    unknown_flags = sorted(set(flags) - set(_FIELDS) - {"api_key"})
    if unknown_flags:
        raise ConfigError(f"Unknown flag setting(s): {', '.join(unknown_flags)}.")

    values: dict[str, Any] = {}
    sources: dict[str, str] = {}
    for name, (convert, env_name, default) in _FIELDS.items():
        if flags.get(name) is not None:
            values[name] = convert(flags[name], f"flag --{name.replace('_', '-')}")
            sources[name] = "flag"
        elif (
            env_name
            and env_name in env
            and (env[env_name] != "" or name == "fallback_model")
        ):
            values[name] = convert(env[env_name], f"environment variable {env_name}")
            sources[name] = "env"
        elif name in file_values:
            values[name] = convert(file_values[name], f"{path}: '{name}'")
            sources[name] = "file"
        else:
            values[name] = list(default) if isinstance(default, list) else default
            sources[name] = "default"

    if flags.get("api_key"):
        api_key, sources["api_key"] = str(flags["api_key"]).strip() or None, "flag"
    else:
        api_key = resolve_api_key(env)
        sources["api_key"] = "env" if api_key else "unset"

    return Settings(api_key=api_key, sources=sources, config_path=path, **values)
