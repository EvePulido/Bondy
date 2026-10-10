"""Single data contract for audit results and tolerant parsing of LLM output."""

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ValidationError, field_validator

PARSE_ERROR_MESSAGE = (
    "The AI failed to format its response as a valid JSON array. "
    "Recovery: Please click 'Run accessibility audit' again to let the AI try "
    "generating the correct format."
)


class AuditFix(BaseModel):
    """One accessibility finding with its suggested fix (matches the agent's output)."""

    finding_id: str
    wcag: str
    severity: Literal["critical", "warning", "info"] = "warning"
    title: str
    before: str
    after: str
    explanation: str = ""

    @field_validator("severity", mode="before")
    @classmethod
    def normalize_severity(cls, v: Any) -> Any:
        return v.strip().lower() if isinstance(v, str) else v


def _load_json(text: str) -> Any:
    """Extracts JSON from raw text, markdown code blocks or outer array/object bounds."""
    candidates = [text.strip()]
    candidates += [
        m.strip() for m in re.findall(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    ]
    for open_c, close_c in (("[", "]"), ("{", "}")):
        start, end = text.find(open_c), text.rfind(close_c)
        if start != -1 and end > start:
            candidates.append(text[start : end + 1])

    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    raise ValueError(PARSE_ERROR_MESSAGE)


def parse_audit_response(text: str) -> list[AuditFix]:
    """Parses and validates the agent's response into a list of AuditFix.

    Raises:
        ValueError: if the text is not valid JSON or does not match the schema.
    """
    data = _load_json(text)
    if isinstance(data, dict):
        data = data.get("fixes", data.get("findings", [data]))
    if not isinstance(data, list):
        raise ValueError(PARSE_ERROR_MESSAGE)

    # Tolerate items sent as JSON strings instead of objects
    items = []
    for item in data:
        if isinstance(item, str):
            try:
                item = json.loads(item)
            except json.JSONDecodeError:
                continue
        items.append(item)

    try:
        return [AuditFix.model_validate(item) for item in items]
    except ValidationError as e:
        raise ValueError(f"{PARSE_ERROR_MESSAGE} Details: {e.errors()[0]['msg']}") from e
