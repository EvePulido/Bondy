"""Regression: the focus-order scanner reports each invisible element ONCE."""

import pytest

from bondy.scan import _run_focus_order

EMPTY_LINK = (
    '<!doctype html><html lang="en"><head><title>t</title></head>'
    '<body><a href="#"></a></body></html>'
)
TWO_LINKS = (
    '<!doctype html><html lang="en"><head><title>t</title></head><body>'
    '<a href="#">ok</a><a href="#" class="x"></a><a href="#" class="y"></a>'
    "</body></html>"
)


def _run(html: str) -> list[dict]:
    try:
        return _run_focus_order(html)
    except Exception as e:  # no browser in this environment
        if type(e).__name__ == "BrowserUnavailableError":
            pytest.skip(f"browser unavailable: {e}")
        raise


def test_single_invisible_link_is_one_finding_with_its_own_location():
    findings = _run(EMPTY_LINK)
    assert len(findings) == 1
    f = findings[0]
    assert f["scanner"] == "focus-order"
    assert f["nodes"] == [{"html": '<a href="#"></a>'}]  # not "(whole page)"


def test_each_distinct_invisible_element_once_even_with_same_tag():
    findings = _run(TWO_LINKS)
    assert len(findings) == 2
    htmls = {f["nodes"][0]["html"] for f in findings}
    assert htmls == {'<a href="#" class="x"></a>', '<a href="#" class="y"></a>'}


def test_page_without_focusable_elements_has_no_findings():
    assert _run("<html lang=en><body><p>hi</p></body></html>") == []
