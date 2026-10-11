"""Our HTMLParser subclasses must not collide with CPython's private state.

Recent CPython patch releases made ``html.parser.HTMLParser`` keep its own
private attributes (e.g. ``_pending``, joined as ``str`` in ``close()``).
A subclass attribute with the same name broke ``close()`` on Linux CI
(``TypeError: sequence item 0: expected str instance, Directive found``).
"""

from html.parser import HTMLParser

import pytest

from bondy.core.images import extract_images
from bondy.core.source import ElementCollector, parse_elements
from bondy.core.suppress import _Parser, parse_directives

# The directive is the LAST thing in the page: no element follows it, so it is
# still pending when the parser is closed (the case that broke on CI).
HTML = (
    '<input id="one">\n<a href="/x"><img src="a.png"></a>\n'
    "<!-- bondy-ignore: labels -- was a spinner -->"
)


@pytest.fixture
def strict_base(monkeypatch):
    """HTMLParser as in recent CPython: private ``_pending`` list of str."""
    orig_init, orig_close = HTMLParser.__init__, HTMLParser.close

    def __init__(self, *a, **kw):
        orig_init(self, *a, **kw)
        self._pending = []

    def close(self):
        if self._pending:
            self.rawdata += "".join(self._pending)
            self._pending = []
        orig_close(self)

    monkeypatch.setattr(HTMLParser, "__init__", __init__)
    monkeypatch.setattr(HTMLParser, "close", close)


def test_suppress_parser_survives_a_base_with_private_pending(strict_base):
    directives, problems = parse_directives(HTML)
    assert [d.rules for d in directives] == [["labels"]] and not problems
    assert directives[0].target is None  # nothing follows it


def test_other_collectors_survive_it_too(strict_base):
    assert parse_elements(HTML)
    assert extract_images(HTML, "index.html", ".", ".")


def test_our_attribute_names_do_not_shadow_the_base_class():
    base_attrs = set(vars(HTMLParser()))
    base_names = set(dir(HTMLParser)) | base_attrs
    for cls in (ElementCollector, _Parser):
        ours = set(vars(cls())) - base_attrs  # attributes added by the subclass
        clash = {n for n in ours if n in base_names}
        assert not clash, f"{cls.__name__} shadows HTMLParser: {clash}"
        # the subclass's private state is namespaced: no future clash
        assert all(n.startswith("_bondy_") or not n.startswith("_") for n in ours)
