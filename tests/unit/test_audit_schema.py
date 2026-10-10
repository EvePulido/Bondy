import pytest

from bondy.app_utils.audit_schema import parse_audit_response

FIX = (
    '{"finding_id":"img-001","wcag":"1.1.1","severity":"Critical","title":"t",'
    '"before":"<img>","after":"<img alt=\\"x\\">","explanation":"e"}'
)


def test_parses_raw_array():
    fixes = parse_audit_response(f"[{FIX}]")
    assert len(fixes) == 1
    assert fixes[0].severity == "critical"


def test_parses_markdown_block_and_wrapper_object():
    fixes = parse_audit_response(f'text\n```json\n{{"fixes":[{FIX}]}}\n```')
    assert fixes[0].finding_id == "img-001"


def test_empty_array():
    assert parse_audit_response("[]") == []


def test_invalid_text_raises():
    with pytest.raises(ValueError):
        parse_audit_response("no json here")


def test_missing_fields_raises():
    with pytest.raises(ValueError):
        parse_audit_response('[{"finding_id":"x"}]')
