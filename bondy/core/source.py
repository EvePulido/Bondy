"""Source-side view of a page: its start tags and where they are (no browser).

Used to attach a line number to findings that only carry a selector or an
outerHTML snippet (axe, contrast, ...) and to decide which findings an inline
``bondy-ignore`` comment refers to. Matching is deliberately conservative: when
a finding cannot be tied to one element with confidence it gets no line and is
never suppressed by an inline comment.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser

_WS = re.compile(r"\s+")


@dataclass(frozen=True)
class Element:
    """A start tag in the source: name, normalized attributes and 1-based line."""

    tag: str
    attrs: tuple[tuple[str, str], ...]
    line: int

    @property
    def signature(self) -> tuple[str, tuple[tuple[str, str], ...]]:
        return self.tag, self.attrs

    @property
    def id(self) -> str | None:
        return dict(self.attrs).get("id") or None

    @property
    def classes(self) -> frozenset[str]:
        return frozenset(dict(self.attrs).get("class", "").split())


def normalize_attrs(attrs) -> tuple[tuple[str, str], ...]:
    out: dict[str, str] = {}
    for key, value in attrs:
        value = _WS.sub(" ", value or "").strip()
        if key.lower() == "class":
            value = " ".join(sorted(value.split()))
        out[key.lower()] = value
    return tuple(sorted(out.items()))


class ElementCollector(HTMLParser):
    """Records every start tag; subclasses may also react to comments."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.elements: list[Element] = []

    def handle_starttag(self, tag, attrs):
        self.elements.append(
            Element(tag.lower(), normalize_attrs(attrs), self.getpos()[0])
        )


def parse_elements(html: str) -> list[Element]:
    parser = ElementCollector()
    parser.feed(html)
    parser.close()
    return parser.elements


def element_from_snippet(snippet: str) -> Element | None:
    """First start tag of an outerHTML snippet (None if it is cut or absent)."""
    if not snippet or "<" not in snippet:
        return None
    head = snippet[snippet.find("<") :]
    close = head.find(">")
    if close == -1:  # truncated inside the start tag
        return None
    elements = parse_elements(head[: close + 1])
    return elements[0] if elements else None


# ----- CSS selector (only the part axe/our scanners emit) -----
_ATTR_SEL = re.compile(r"\[[^\]]*\]")
_PSEUDO = re.compile(r"::?[\w-]+(\([^)]*\))?")


def _last_compound(selector: str) -> str | None:
    text = _PSEUDO.sub("", _ATTR_SEL.sub("", selector)).strip()
    parts = [p for p in re.split(r"\s*[>+~]\s*|\s+", text) if p]
    return parts[-1] if parts else None


class PageIndex:
    """Elements of one page, searchable by outerHTML snippet or CSS selector."""

    def __init__(self, html: str):
        self.elements = parse_elements(html)
        self._bondy_by_sig: dict[tuple, list[Element]] = {}
        for el in self.elements:
            self._bondy_by_sig.setdefault(el.signature, []).append(el)

    def by_selector(self, selector: str) -> list[Element]:
        """The single element a (simple) selector designates, else ``[]``."""
        compound = _last_compound(selector)
        if not compound:
            return []
        tag_m = re.match(r"[A-Za-z][\w-]*", compound)
        tag = tag_m.group(0).lower() if tag_m else None
        ids = re.findall(r"#([\w-]+)", compound)
        classes = set(re.findall(r"\.([\w-]+)", compound))
        if not (tag or ids or classes):
            return []
        found = [
            el
            for el in self.elements
            if (tag is None or el.tag == tag)
            and (not ids or el.id == ids[0])
            and classes <= el.classes
        ]
        return found if len(found) == 1 else []

    def candidates(self, snippet: str | None, selector: str | None) -> list[Element]:
        """Elements a finding may refer to.

        An outerHTML snippet matches every element with the same tag and
        attributes (identical elements are indistinguishable); a selector only
        counts when it designates exactly one element.
        """
        if snippet:
            el = element_from_snippet(snippet)
            if el is not None:
                return list(self._bondy_by_sig.get(el.signature, []))
        if selector:
            return self.by_selector(selector)
        return []

    def html_element(self) -> Element | None:
        return next((e for e in self.elements if e.tag == "html"), None)

    def line_for(
        self, snippet: str | None, selector: str | None, page_level: bool = False
    ) -> int | None:
        """Line of the one element the finding refers to, else ``None``."""
        found = self.candidates(snippet, selector)
        if len(found) == 1:
            return found[0].line
        if page_level and not snippet and not selector:
            root = self.html_element()
            return root.line if root else None
        return None
