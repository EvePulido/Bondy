"""Deterministic secret redaction for text that leaves the machine (D3).

``redact_secrets`` replaces the *value* of anything that looks like a credential
with ``[REDACTED]``: well-known key formats, ``Bearer``/JWT tokens, PEM private
keys, ``api_key=``/``token=``/``password=``-style assignments in attributes or
scripts, and URLs carrying credentials or ``?token=``/``?key=`` parameters.

It is applied to the HTML context and alt text sent to the model (and therefore
to the verdict-cache key, so secrets never reach the cache on disk) and to the
snippets shown in reports.

This is pattern matching, not a guarantee: a secret in an unusual format, one
inside an image's pixels, or one split by the context window is not caught.
Do not scan code you are not allowed to share with your model provider.
"""

from __future__ import annotations

import re
from typing import Any

REDACTED = "[REDACTED]"

# keywords that make an assignment/parameter name sensitive
_KW = (
    r"api[_-]?key|apikey|access[_-]?key|private[_-]?key|client[_-]?secret|secret"
    r"|token|passw(?:or)?d|pwd|authorization|credential"
)

_PEM = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?"
    r"(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|\Z)",
    re.DOTALL,
)
_URL_CREDENTIALS = re.compile(
    r"""\b([a-z][a-z0-9+.-]*://)[^\s/?#@"'<>]+(?::[^\s/?#@"'<>]*)?@""", re.IGNORECASE
)
_QUERY = re.compile(
    rf"""([?&;](?:[\w.-]*(?:{_KW})[\w.-]*|key|sig|signature|auth|sid|session)=)"""
    r"""[^&\s"'<>#]+""",
    re.IGNORECASE,
)
_KNOWN = re.compile(
    r"""\bAIza[0-9A-Za-z_-]{35}\b"""
    r"""|\bsk-[A-Za-z0-9_-]{20,}"""
    r"""|\bgh[pousr]_[A-Za-z0-9]{30,}"""
    r"""|\bgithub_pat_[A-Za-z0-9_]{20,}"""
    r"""|\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"""
    r"""|\bxox[abprs]-[A-Za-z0-9-]{10,}"""
)
_BEARER = re.compile(r"(\bBearer\s+)[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE)
_AUTH_SCHEME = re.compile(
    r"""(authorization["']?\s*[:=]\s*["']?)(?:basic|digest|token)\s+"""
    r"""[A-Za-z0-9._~+/=-]{8,}""",
    re.IGNORECASE,
)
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]*")
_ASSIGN = re.compile(
    rf"""(?P<name>\b[\w.-]*(?:{_KW})[\w.-]*)(?P<q0>["']?)(?P<sep>\s*[:=]\s*)"""
    r"""(?:(?P<q>["'])(?P<qval>[^"'\n]{1,500}?)(?P=q)"""
    r"""|(?P<val>[^\s"'&<>,;()\[\]{}]{3,}))""",
    re.IGNORECASE,
)


def _assign(m: re.Match[str]) -> str:
    name, q0, sep = m.group("name"), m.group("q0"), m.group("sep")
    if m.group("q"):
        if m.group("qval") == REDACTED:
            return m.group(0)
        q = m.group("q")
        return f"{name}{q0}{sep}{q}{REDACTED}{q}"
    if ":" in sep and "=" not in sep:
        return m.group(0)  # `password: text` is prose or CSS, not an assignment
    return f"{name}{q0}{sep}{REDACTED}"


def redact_secrets(text: str) -> str:
    """``text`` with secret-looking values replaced by ``[REDACTED]``."""
    if not text:
        return text
    text = _PEM.sub(REDACTED, text)
    text = _URL_CREDENTIALS.sub(rf"\1{REDACTED}@", text)
    text = _QUERY.sub(rf"\1{REDACTED}", text)
    text = _KNOWN.sub(REDACTED, text)
    text = _AUTH_SCHEME.sub(rf"\1{REDACTED}", text)
    text = _BEARER.sub(rf"\1{REDACTED}", text)
    text = _JWT.sub(REDACTED, text)
    return _ASSIGN.sub(_assign, text)


def contains_secret(value: Any) -> bool:
    """True if any string inside ``value`` (str/list/dict, recursively) would be
    changed by ``redact_secrets``."""
    if isinstance(value, str):
        return redact_secrets(value) != value
    if isinstance(value, dict):
        return any(contains_secret(v) for v in value.values())
    if isinstance(value, list | tuple):
        return any(contains_secret(v) for v in value)
    return False
