"""Bondy configuration: ``bondy.toml`` + environment variables + CLI flags.

Precedence (highest first): **flag > environment variable > bondy.toml > default**.

This module only depends on the standard library so it can be used by the core
package (CLI, doctor) without FastAPI or ADK. It is the single place that reads
Bondy's environment variables (``tests/unit/test_settings_only.py`` enforces it).
``load_settings`` / ``load_server_settings`` never modify ``os.environ``; the only
writer is ``export_dotenv_to_environ``, which the web server calls explicitly.

The API key is deliberately *not* readable from ``bondy.toml``: that file is
meant to be committed to the repository. It comes from ``GEMINI_API_KEY`` or
``GOOGLE_API_KEY`` (in that order), from a ``.env`` file of the project (only
those two variables are read from it; nothing is exported) or, programmatically,
from a flag. Precedence: flag > environment > ``.env``.
"""

from __future__ import annotations

import os
import re
import tomllib
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass, field, replace
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


def _number(
    kind: type, *, minimum: float, optional: bool = False, zero_is_none: bool = True
):
    """Converter for ints/floats.

    ``optional`` accepts "" as None; ``zero_is_none`` also maps 0 to None
    ("no limit"). Prices use optional without zero_is_none (0 is a valid price).
    """

    def convert(value: Any, where: str):
        if isinstance(value, bool):
            raise ConfigError(f"{where}: expected a number, got {value!r}.")
        if isinstance(value, str):
            text = value.strip()
            if optional and text == "":
                return None
            try:
                value = kind(text)
            except ValueError:
                raise ConfigError(
                    f"{where}: expected a number, got {value!r}."
                ) from None
        elif isinstance(value, int | float):
            value = kind(value)
        else:
            raise ConfigError(f"{where}: expected a number, got {value!r}.")
        if optional and zero_is_none and value == 0:
            return None
        if value < minimum:
            raise ConfigError(f"{where}: must be >= {minimum:g}; got {value!r}.")
        return value

    return convert


def _choice(*options: str):
    def convert(value: Any, where: str) -> str:
        text = _to_str(value, where).strip().lower()
        if text not in options:
            raise ConfigError(
                f"{where}: must be one of {', '.join(options)}; got {value!r}."
            )
        return text

    return convert


_RULE_TOKEN = re.compile(
    r"^(?:(?:wcag\s*)?(\d\.\d\.\d{1,2})|([a-z][a-z0-9_-]*))$", re.I
)


def normalize_rule_token(token: str, where: str) -> str:
    """``"WCAG 1.4.3"`` -> ``"1.4.3"``; ``"Color-Contrast"`` -> ``"color-contrast"``."""
    m = _RULE_TOKEN.match(token.strip())
    if not m:
        raise ConfigError(
            f"{where}: {token!r} is not a rule id (e.g. image-alt) or a WCAG "
            "criterion (e.g. 1.4.3)."
        )
    return (m.group(1) or m.group(2)).lower()


@dataclass(frozen=True)
class IgnoreRule:
    """One ``[[ignore]]`` entry of bondy.toml. ``path`` is a glob relative to
    the scanned folder (never absolute, never leaving it)."""

    path: str
    rule: str
    reason: str
    index: int = 0


def _ignore_path(value: Any, where: str) -> str:
    text = _to_str(value, where).strip().replace("\\", "/")
    parts = text.split("/")
    if (
        not text
        or text.startswith(("/", "~"))
        or re.match(r"^[A-Za-z]:", text)
        or ".." in parts
        or "\x00" in text
    ):
        raise ConfigError(
            f"{where}: path {value!r} must be a glob relative to the scanned "
            "folder (no absolute paths, '~' or '..')."
        )
    return text


def _to_ignore_list(value: Any, where: str) -> tuple[IgnoreRule, ...]:
    if not isinstance(value, list | tuple):
        raise ConfigError(f"{where}: expected a list of [[ignore]] tables.")
    out = []
    for n, entry in enumerate(value, 1):
        label = f"{where} [[ignore]] #{n}"
        if not isinstance(entry, dict):
            raise ConfigError(f"{label}: expected a table with path, rule, reason.")
        unknown = sorted(set(entry) - {"path", "rule", "reason"})
        if unknown:
            raise ConfigError(
                f"{label}: unknown key(s): {', '.join(unknown)}. Valid keys: "
                "path, rule, reason."
            )
        missing = [k for k in ("path", "rule", "reason") if k not in entry]
        if missing:
            raise ConfigError(f"{label}: missing {', '.join(missing)}.")
        reason = _to_str(entry["reason"], f"{label} reason").strip()
        if not reason:
            raise ConfigError(
                f"{label}: 'reason' must say why this is ignored (it is shown "
                "in every report)."
            )
        out.append(
            IgnoreRule(
                path=_ignore_path(entry["path"], f"{label} path"),
                rule=normalize_rule_token(
                    _to_str(entry["rule"], f"{label} rule"), f"{label} rule"
                ),
                reason=reason,
                index=n,
            )
        )
    return tuple(out)


# field -> (converter, environment variable or None, default)
_FIELDS: dict[str, tuple[Any, str | None, Any]] = {
    "model": (_to_str, "BONDY_MODEL", "gemini-flash-latest"),
    "vision_model": (_to_str, "BONDY_VISION_MODEL", "gemini-flash-latest"),
    # An empty string disables the fallback model (same as the old env var).
    "fallback_model": (_to_str, "BONDY_FALLBACK_MODEL", "gemini-3.5-flash-lite"),
    "no_llm": (_to_bool, "BONDY_NO_LLM", False),
    # Force browser-free (static) mode, e.g. in CI without a browser.
    "static": (_to_bool, "BONDY_STATIC", False),
    "format": (
        _choice("terminal", "json", "markdown", "html", "sarif"),
        "BONDY_FORMAT",
        "terminal",
    ),
    "fail_on": (_choice("critical", "warning", "never"), "BONDY_FAIL_ON", "critical"),
    "checks": (_to_str_list, "BONDY_CHECKS", []),
    "include": (_to_str_list, "BONDY_INCLUDE", ["**/*.html", "**/*.htm"]),
    "exclude": (
        _to_str_list,
        "BONDY_EXCLUDE",
        ["node_modules/**", ".git/**", "dist/**", "build/**"],
    ),
    # Images per LLM request (semantic stage).
    "batch_size": (_number(int, minimum=1), "BONDY_BATCH_SIZE", 8),
    # Hard limits; None (0 or empty) means unlimited. On reaching one the scan
    # stops and returns a PARTIAL result. max_requests has a safe default of 50;
    # pass 0 to remove it.
    "max_requests": (
        _number(int, minimum=1, optional=True),
        "BONDY_MAX_REQUESTS",
        50,
    ),
    "max_usd": (_number(float, minimum=0, optional=True), "BONDY_MAX_USD", None),
    "max_pages": (_number(int, minimum=1, optional=True), "BONDY_MAX_PAGES", None),
    "max_images": (_number(int, minimum=1, optional=True), "BONDY_MAX_IMAGES", None),
    # Prices in USD per million tokens. No defaults: Bondy does not know your
    # model's price. Without them cost is reported as "not available".
    "price_input_per_mtok": (
        _number(float, minimum=0, optional=True, zero_is_none=False),
        "BONDY_PRICE_INPUT_PER_MTOK",
        None,
    ),
    "price_output_per_mtok": (
        _number(float, minimum=0, optional=True, zero_is_none=False),
        "BONDY_PRICE_OUTPUT_PER_MTOK",
        None,
    ),
    # Persistent cache/state (verdicts, page results, resume marker). Relative
    # cache_dir is resolved against the scanned project root; "" = .bondy/cache.
    "cache": (_to_bool, "BONDY_CACHE", True),
    "cache_dir": (_to_str, "BONDY_CACHE_DIR", ""),
    # Seconds; 0 = no limit. timeout is per page (browser work), scan_timeout is
    # for the whole scan (checked between pages/scanners/batches).
    "timeout": (_number(float, minimum=0, optional=True), "BONDY_TIMEOUT", 60.0),
    "scan_timeout": (
        _number(float, minimum=0, optional=True),
        "BONDY_SCAN_TIMEOUT",
        900.0,
    ),
    # Suppressions with a mandatory reason: [[ignore]] tables (file only).
    "ignore": (_to_ignore_list, None, ()),
    # Baseline file (E2). From bondy.toml it is relative to that file's folder;
    # from a flag or the environment, relative to the working directory.
    "baseline": (_to_str, "BONDY_BASELINE", ""),
    # Download http(s) images (public hosts only) so the model can see them.
    "remote_images": (_to_bool, "BONDY_REMOTE_IMAGES", True),
    # Rough input tokens one image costs (used only by estimate/dry-run and the
    # pre-request budget check; real usage is read from the provider).
    "tokens_per_image": (_number(int, minimum=1), "BONDY_TOKENS_PER_IMAGE", 1100),
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
    batch_size: int
    max_requests: int | None
    max_usd: float | None
    max_pages: int | None
    max_images: int | None
    price_input_per_mtok: float | None
    price_output_per_mtok: float | None
    remote_images: bool
    cache: bool
    cache_dir: str
    timeout: float | None
    scan_timeout: float | None
    tokens_per_image: int
    baseline: str
    ignore: tuple[IgnoreRule, ...]
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


DOTENV_FILENAME = ".env"
_PROJECT_MARKERS = (".git", CONFIG_FILENAME)


def _parse_dotenv_value(raw: str) -> str:
    value = raw.strip()
    if value[:1] in ("'", '"'):
        quote = value[0]
        end = value.find(quote, 1)
        return value[1:end] if end != -1 else value[1:]
    # unquoted: an inline comment starts at " #"
    return value.split(" #", 1)[0].strip()


def read_dotenv_key(
    start: Path | str | None = None,
) -> tuple[str, str, Path] | None:
    """Finds an API key in the project's ``.env``: ``(key, variable, file)``.

    Looks in ``start`` (default cwd) and then its ancestors, stopping at the
    first project root (a directory with ``.git`` or ``bondy.toml``); outside a
    project only ``start`` itself is checked, so a stray ``.env`` in a parent or
    home folder is never picked up. Only ``GEMINI_API_KEY``/``GOOGLE_API_KEY``
    are read; no other variable is looked at or exported. Never raises: an
    unreadable file is treated as absent.
    """
    current = Path(start or Path.cwd()).resolve()
    if current.is_file():
        current = current.parent
    for directory in (current, *current.parents):
        found = _key_from_dotenv(directory / DOTENV_FILENAME)
        if found:
            return (*found, directory / DOTENV_FILENAME)
        if any((directory / m).exists() for m in _PROJECT_MARKERS):
            return None
    return None


def _read_dotenv(path: Path) -> dict[str, str]:
    """All ``NAME=value`` pairs of a ``.env`` file (nothing is exported).

    Never raises: an unreadable file is treated as empty. Quotes and inline
    comments are handled; there is no interpolation and no multi-line values.
    """
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return {}
    values: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, raw = line.partition("=")
        name = name.strip().removeprefix("export ").strip()
        if name:
            values[name] = _parse_dotenv_value(raw)
    return values


def _key_from_dotenv(path: Path) -> tuple[str, str] | None:
    values = _read_dotenv(path)
    for name in API_KEY_ENV_VARS:  # same order as the environment
        if values.get(name):
            return values[name], name
    return None


# Variables the web server may take from the project's ``.env`` (see
# ``export_dotenv_to_environ``). Everything else in the file is ignored: a
# stray PATH/HOME/etc. never reaches ``os.environ``.
DOTENV_EXPORT_PREFIXES = ("BONDY_", "GOOGLE_", "GEMINI_", "GENAI_", "OTEL_")
DOTENV_EXPORT_NAMES = ("ALLOW_ORIGINS", "LOGS_BUCKET_NAME", "COMMIT_SHA")


def export_dotenv_to_environ(
    path: Path | str, env: MutableMapping[str, str] | None = None
) -> list[str]:
    """Copies the allowlisted variables of a ``.env`` into the environment.

    This is what the web server does at start-up (ADK, ``google-genai`` and the
    telemetry hooks read their credentials/options from ``os.environ``).
    Variables already set win (``override=False``). Only ``DOTENV_EXPORT_*``
    names are copied, so the file is no longer loaded wholesale. Returns the
    names that were exported.
    """
    env = os.environ if env is None else env
    exported: list[str] = []
    for name, value in _read_dotenv(Path(path)).items():
        allowed = name in DOTENV_EXPORT_NAMES or name.startswith(DOTENV_EXPORT_PREFIXES)
        if allowed and name not in env:
            env[name] = value
            exported.append(name)
    return exported


def resolve_api_key(env: Mapping[str, str] | None = None) -> str | None:
    """First non-empty of ``GEMINI_API_KEY`` then ``GOOGLE_API_KEY``."""
    env = os.environ if env is None else env
    for name in API_KEY_ENV_VARS:
        value = env.get(name, "").strip()
        if value:
            return value
    return None


def use_vertexai(env: Mapping[str, str] | None = None) -> bool:
    """``GOOGLE_GENAI_USE_VERTEXAI`` is truthy (Vertex AI instead of an API key).

    It is read by the google-genai/ADK SDKs themselves; Bondy only needs to know
    it to avoid forcing an AI Studio key on top of it.
    """
    env = os.environ if env is None else env
    return env.get("GOOGLE_GENAI_USE_VERTEXAI", "").strip().lower() in {"1", "true"}


# Server (web UI / ADK) settings. They are not scan settings, so they are not in
# bondy.toml: they come from the environment (and the server's ``.env``).
APPLY_TOKEN_ENV = "BONDY_APPLY_TOKEN"
LEGACY_APPLY_TOKEN_ENV = "BONDY_API_KEY"  # deprecated alias; NOT the Gemini key


@dataclass(frozen=True)
class ServerSettings:
    """Settings of ``bondy.fast_api_app`` resolved from the environment."""

    # Token required in ``X-API-Key`` by /api/apply-fix and (when enabled) the
    # agent API. ``None`` -> only local clients. Unrelated to the Gemini key.
    apply_token: str | None = field(default=None, repr=False)
    enable_agent_api: bool = False  # BONDY_ENABLE_AGENT_API (P0-3 opt-in)
    allow_origins: list[str] | None = None  # ALLOW_ORIGINS (comma-separated)
    cloud_logging: bool = False  # BONDY_CLOUD_LOGGING
    logs_bucket: str | None = None  # LOGS_BUCKET_NAME
    deprecations: tuple[str, ...] = ()  # messages the server logs at start-up


def _env_flag(value: str) -> bool:
    """Opt-in flags: ``1``/``true``/``yes``/``on`` enable; anything else is off."""
    return value.strip().lower() in _TRUE


def load_server_settings(env: Mapping[str, str] | None = None) -> ServerSettings:
    """Resolves the web server settings from ``env`` (default ``os.environ``).

    ``BONDY_APPLY_TOKEN`` is the token; ``BONDY_API_KEY`` still works as a
    deprecated alias (the new name wins when both are set).
    """
    env = os.environ if env is None else env
    token = env.get(APPLY_TOKEN_ENV, "") or None
    legacy = env.get(LEGACY_APPLY_TOKEN_ENV, "") or None
    deprecations: list[str] = []
    if legacy:
        deprecations.append(
            f"{LEGACY_APPLY_TOKEN_ENV} is deprecated; use {APPLY_TOKEN_ENV} "
            "(same value, same X-API-Key header). It protects /api/apply-fix and "
            "the agent API and is unrelated to the Gemini API key."
            + (f" {APPLY_TOKEN_ENV} takes precedence." if token else "")
        )
        token = token or legacy
    origins = [o.strip() for o in env.get("ALLOW_ORIGINS", "").split(",")]
    return ServerSettings(
        apply_token=token,
        enable_agent_api=_env_flag(env.get("BONDY_ENABLE_AGENT_API", "")),
        allow_origins=[o for o in origins if o] or None,
        cloud_logging=_env_flag(env.get("BONDY_CLOUD_LOGGING", "")),
        logs_bucket=env.get("LOGS_BUCKET_NAME", "").strip() or None,
        deprecations=tuple(deprecations),
    )


def load_settings(
    flags: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
    config_path: Path | str | None = None,
    start_dir: Path | str | None = None,
    use_file: bool = True,
) -> Settings:
    """Resolves settings with precedence flag > env > file > default.

    Args:
        flags: Values from CLI flags. Keys with a value of ``None`` are treated
            as "not provided". May include ``api_key``.
        env: Environment mapping (defaults to ``os.environ``; never modified).
        config_path: Explicit ``bondy.toml`` (error if missing). When omitted the
            nearest one above ``start_dir`` / cwd is used, if any.
        start_dir: Where to start looking for ``bondy.toml``.
        use_file: ``False`` ignores ``bondy.toml`` (used by the lenient loader).
    """
    flags = dict(flags or {})
    env = os.environ if env is None else env

    path: Path | None
    if not use_file:
        path = None
    elif config_path is not None:
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
        if not api_key:
            dotenv = read_dotenv_key(start_dir)
            if dotenv:
                api_key, sources["api_key"] = dotenv[0], "dotenv"

    baseline = values["baseline"]
    if baseline and sources["baseline"] == "file" and path is not None:
        candidate = Path(baseline).expanduser()
        if not candidate.is_absolute():
            values["baseline"] = str(path.resolve().parent / candidate)

    return Settings(api_key=api_key, sources=sources, config_path=path, **values)


def load_settings_lenient(
    env: Mapping[str, str] | None = None, start_dir: Path | str | None = None
) -> Settings:
    """``load_settings`` that never raises, for agent-mode tool code.

    Falls back to the environment without ``bondy.toml`` and then to defaults
    (keeping the API key), so a broken config cannot crash a tool call halfway
    through an audit. The CLI/pipeline use the strict ``load_settings``.
    """
    env = os.environ if env is None else env
    try:
        return load_settings(env=env, start_dir=start_dir)
    except ConfigError:
        pass
    try:
        return load_settings(env=env, start_dir=start_dir, use_file=False)
    except ConfigError:
        pass
    return replace(load_settings(env={}, use_file=False), api_key=resolve_api_key(env))
