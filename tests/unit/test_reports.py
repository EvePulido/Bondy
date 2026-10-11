"""E1: one report model, five formats. Scanned content is untrusted in all of them."""

import json
import os
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

from bondy import cli
from bondy.core import formats
from bondy.core.models import ScanReport, UsageSummary
from bondy.core.report import (
    Item,
    Report,
    build_report,
    relative_path,
)
from bondy.scan import SCANNERS, FileResult

EVIL = '<script>alert("x")</script>" onload="x\' --> `|[a](http://evil.test)'
HTML = (
    '<html lang="en"><body>\n'
    '<img src="a.png">\n'
    '<button class="x">   </button>\n'
    "</body></html>"
)
AXE = {
    "scanner": "axe",
    "rule": "button-name",
    "wcag": ["4.1.2"],
    "severity": "critical",
    "message": "Buttons must have discernible text",
    "count": 1,
    "nodes": [
        {
            "selector": "button.x",
            "html": '<button class="x">   </button>',
            "failure": "Fix any of the following:\n  Element has no text",
        }
    ],
}
LANG = {
    "scanner": "lang",
    "wcag": ["3.1.1"],
    "severity": "critical",
    "message": "<html lang> is missing",
}
WARN = {
    "scanner": "focus-order",
    "wcag": ["2.4.3"],
    "severity": "warning",
    "message": "positive tabindex",
}


def scan_report(tmp_path, findings=(AXE, LANG, WARN), name="sub dir/a.html", html=HTML):
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    fr = FileResult(path=str(path), findings=[dict(f) for f in findings], html=html)
    return ScanReport(files=[fr], usage=UsageSummary(mode="no-llm"))


def model(tmp_path, **kw):
    return build_report(scan_report(tmp_path, **kw), tmp_path, version="9.9.9")


# ----- the model -----
def test_items_are_per_element_with_relative_posix_paths(tmp_path):
    r = model(tmp_path)
    assert [i.file for i in r.items] == ["sub dir/a.html"] * 3
    assert r.files[0].path == "sub dir/a.html"
    assert {i.rule for i in r.items} == {"button-name", "lang", "focus-order"}
    axe = r.items[0]
    assert axe.selector == "button.x" and axe.line == 3  # located in the source
    assert axe.fix == "Fix any of the following: Element has no text"
    lang = r.items[1]
    assert lang.line == 1  # page-level <html lang> finding -> the <html> tag


def test_a_finding_with_several_nodes_becomes_several_items(tmp_path):
    f = dict(AXE, count=2, nodes=[AXE["nodes"][0], {"selector": "a", "html": "<a>"}])
    r = model(tmp_path, findings=[f])
    assert len(r.items) == 2
    assert r.items[0].fingerprint != r.items[1].fingerprint


def test_no_absolute_path_in_any_format(tmp_path):
    sr = scan_report(tmp_path)
    sr.files[0].errors = [f"boom reading {sr.files[0].path}"]
    sr.notes = [f"note about {tmp_path}"]
    r = build_report(sr, tmp_path, version="1")
    for fmt in formats.FORMATS:
        text = formats.render(fmt, r, 1)
        assert str(tmp_path) not in text, fmt
        assert tmp_path.as_posix() not in text, fmt


def test_relative_path_never_returns_an_absolute_path(tmp_path):
    outside = Path(os.path.abspath(tmp_path.parent / "elsewhere" / "x.html"))
    assert relative_path(outside, tmp_path) == "x.html"


def test_fingerprint_is_stable_across_line_moves_and_distinguishes_duplicates(
    tmp_path,
):
    a = model(tmp_path)
    shifted = HTML.replace("<body>\n", "<body>\n\n\n\n")
    b = model(tmp_path, html=shifted)
    assert a.items[0].line != b.items[0].line
    assert [i.fingerprint for i in a.items] == [i.fingerprint for i in b.items]
    twin = dict(AXE, nodes=[AXE["nodes"][0], AXE["nodes"][0]], count=2)
    fps = [i.fingerprint for i in model(tmp_path, findings=[twin]).items]
    assert len(set(fps)) == 2 and fps[1].startswith(fps[0])


def test_line_is_not_guessed_for_identical_elements(tmp_path):
    html = (
        '<html lang="en"><body><button class="x"></button>\n<button class="x"></button>'
    )
    f = dict(
        AXE, nodes=[{"selector": "button.x", "html": '<button class="x"></button>'}]
    )
    r = model(tmp_path, findings=[f], html=html)
    assert r.items[0].line is None


# ----- hostile content -----
def hostile_report() -> Report:
    item = Item(
        file=f"a{EVIL}.html",
        scanner="axe",
        rule=f"rule{EVIL}",
        wcag=["1.1.1"],
        severity="critical",
        message=f"msg {EVIL}",
        selector=f"sel {EVIL}",
        snippet=f"<img alt='{EVIL}'>",
        line=3,
        fix=f"fix {EVIL}",
        fingerprint="f" * 32,
    )
    from bondy.core.report import FileEntry

    return Report(
        version="1",
        mode="no-llm",
        files=[FileEntry(path=item.file, errors=[f"err {EVIL}"], skipped=f"s {EVIL}")],
        items=[item],
        fixes=[],
        notes=[f"note {EVIL}"],
        usage=UsageSummary(mode="no-llm"),
    )


class _Tags(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags: list[tuple[str, dict]] = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


ALLOWED_TAGS = {
    "html", "head", "meta", "title", "style", "body", "a", "header", "h1", "h2",
    "h3", "p", "main", "section", "table", "caption", "thead", "tbody", "tr",
    "th", "td", "ul", "li", "span", "code", "pre", "dl", "dt", "dd", "strong",
    "footer",
}  # fmt: skip


def test_html_report_is_self_contained_accessible_and_escapes_everything():
    text = formats.render_html(hostile_report(), 1)
    parser = _Tags()
    parser.feed(text)
    names = {t for t, _ in parser.tags}
    assert names <= ALLOWED_TAGS, names - ALLOWED_TAGS
    for tag, attrs in parser.tags:
        assert not any(k.startswith("on") for k in attrs), (tag, attrs)
        if tag == "a":
            assert attrs["href"].startswith("#")  # in-page only
        if tag == "meta":
            assert "http" not in " ".join(str(v) for v in attrs.values())
    assert "<script" not in text.lower() and "@import" not in text
    assert "url(" not in text.split("</style>")[1]  # no remote CSS/resources
    assert "&lt;script&gt;" in text  # the hostile string is shown, escaped
    assert '<html lang="en">' in text
    assert "<main" in text and "<header>" in text and "<footer>" in text
    assert text.count("<h1>") == 1 and "Content-Security-Policy" in text


def test_html_report_text_and_background_colors_have_aa_contrast():
    css = formats._CSS
    pairs = {
        "light": [("--fg", "--bg"), ("--muted", "--bg"), ("--crit", "--bg"),
                  ("--warn", "--bg"), ("--fg", "--code")],
        "dark": [("--fg", "--bg"), ("--muted", "--bg"), ("--crit", "--bg"),
                 ("--warn", "--bg"), ("--fg", "--code")],
    }  # fmt: skip
    light = dict(re.findall(r"(--[a-z]+):(#[0-9a-fA-F]{3,6})", css.split("@media")[0]))
    dark = dict(re.findall(r"(--[a-z]+):(#[0-9a-fA-F]{3,6})", css.split("@media")[1]))

    def lum(h):
        h = h.lstrip("#")
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        ch = [int(h[i : i + 2], 16) / 255 for i in (0, 2, 4)]
        ch = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in ch]
        return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2]

    def ratio(a, b):
        hi, lo = sorted((lum(a), lum(b)), reverse=True)
        return (hi + 0.05) / (lo + 0.05)

    for name, palette in (("light", light), ("dark", {**light, **dark})):
        for fg, bg in pairs[name]:
            assert ratio(palette[fg], palette[bg]) >= 4.5, (name, fg, bg)


def test_markdown_report_neutralizes_markup_and_cannot_break_out():
    text = formats.render_markdown(hostile_report(), 1)
    prose = re.sub(r"(`+).+?(?:\1)", "", text)  # code spans render literally
    assert not re.search(r"(?<!\\)<", prose)  # no raw HTML in prose
    assert not re.search(r"(?<!\\)\[[^\]]*\]\(", prose)  # no live links
    for line in text.splitlines():
        if line.startswith(("- Message", "- Suggested fix")):
            assert "\\[a\\]" in line
    assert re.search(r"- Selector: (`+)sel ", text)  # untrusted value in a code span


def test_md_code_fence_is_longer_than_inner_backticks():
    out = formats.md_code("a ``` b")
    assert out.startswith("````") and out.endswith("````")


def test_terminal_output_strips_control_characters():
    r = hostile_report()
    r.items[0].message = "bad \x1b[31mred\x1b[0m\rline"
    text = formats.render_terminal(r)
    assert "\x1b" not in text and "\r" not in text


# ----- SARIF -----
def test_sarif_has_every_required_member_and_stable_fingerprints(tmp_path):
    r = model(tmp_path)
    doc = json.loads(formats.render_sarif(r, 1, prefix="web/site"))
    assert doc["version"] == "2.1.0" and doc["$schema"].endswith(
        "sarif-schema-2.1.0.json"
    )
    (run,) = doc["runs"]
    driver = run["tool"]["driver"]
    assert driver["name"] == "Bondy" and driver["version"] == "9.9.9"
    rules = {x["id"]: i for i, x in enumerate(driver["rules"])}
    assert len(rules) == len(driver["rules"])
    assert len(run["results"]) == 3
    for res in run["results"]:
        assert res["ruleId"] in rules and res["ruleIndex"] == rules[res["ruleId"]]
        assert res["level"] in ("error", "warning", "note", "none")
        assert res["message"]["text"]
        loc = res["locations"][0]["physicalLocation"]
        assert loc["artifactLocation"]["uri"].startswith("web/site/sub%20dir/")
        assert not re.match(r"^[a-zA-Z]:|^/", loc["artifactLocation"]["uri"])
        assert re.fullmatch(
            r"[0-9a-f]{32}(~\d+)?",
            res["partialFingerprints"][formats.SARIF_FINGERPRINT_KEY],
        )
    levels = {x["ruleId"]: x["level"] for x in run["results"]}
    assert levels["button-name"] == "error" and levels["focus-order"] == "warning"
    with_region = [
        x for x in run["results"] if "region" in x["locations"][0]["physicalLocation"]
    ]
    assert with_region and all(
        x["locations"][0]["physicalLocation"]["region"]["startLine"] >= 1
        for x in with_region
    )
    again = json.loads(formats.render_sarif(model(tmp_path), 1, prefix="web/site"))
    assert [x["partialFingerprints"] for x in again["runs"][0]["results"]] == [
        x["partialFingerprints"] for x in run["results"]
    ]


def test_sarif_validates_against_the_official_schema_when_available(tmp_path):
    schema_path = os.environ.get("BONDY_SARIF_SCHEMA")
    jsonschema = pytest.importorskip("jsonschema")
    if not schema_path or not Path(schema_path).is_file():
        pytest.skip("set BONDY_SARIF_SCHEMA to the OASIS sarif-schema-2.1.0.json")
    schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
    doc = json.loads(formats.render_sarif(model(tmp_path), 1))
    jsonschema.Draft4Validator(schema).validate(doc)


def test_sarif_with_hostile_content_stays_valid_json_data():
    doc = json.loads(formats.render_sarif(hostile_report(), 1))
    res = doc["runs"][0]["results"][0]
    assert EVIL in res["message"]["text"]  # data, never interpreted
    assert (
        "%3Cscript"
        in res["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]
    )


# ----- CLI: formats, --output, --fail-on -----
@pytest.fixture
def stubbed(tmp_path, monkeypatch):
    for name in SCANNERS:
        monkeypatch.setitem(SCANNERS, name, lambda html: [])
    monkeypatch.setitem(SCANNERS, "axe", lambda html: [dict(AXE)])
    monkeypatch.setitem(SCANNERS, "focus-order", lambda html: [dict(WARN)])
    (tmp_path / "p.html").write_text(HTML, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.mark.parametrize("fmt", formats.FORMATS)
@pytest.mark.parametrize(
    ("fail_on", "expected"), [("critical", 1), ("warning", 1), ("never", 0)]
)
def test_exit_code_is_the_same_for_every_format(
    stubbed, capsys, fmt, fail_on, expected
):
    code = cli.main(
        ["scan", str(stubbed), "--no-llm", "--format", fmt, "--fail-on", fail_on]
    )
    assert code == expected
    assert capsys.readouterr().out.strip()


def test_warning_only_exit_code_respects_threshold(stubbed, monkeypatch, capsys):
    monkeypatch.setitem(SCANNERS, "axe", lambda html: [])
    for fmt in formats.FORMATS:
        assert cli.main(["scan", ".", "--no-llm", "--format", fmt]) == 0
        assert cli.main(["scan", ".", "--no-llm", "--format", fmt,
                         "--fail-on", "warning"]) == 1  # fmt: skip
    capsys.readouterr()


@pytest.mark.parametrize("fmt", ["json", "markdown", "html", "sarif"])
def test_output_file_gets_the_format_and_stdout_the_summary(stubbed, capsys, fmt):
    out = stubbed / "report.out"
    code = cli.main(
        ["scan", ".", "--no-llm", "--format", fmt, "--output", str(out), "--fail-on",
         "never"]
    )  # fmt: skip
    printed = capsys.readouterr().out
    body = out.read_text(encoding="utf-8")
    assert code == 0 and "report written to" in printed and "finding(s)" in printed
    if fmt in ("json", "sarif"):
        json.loads(body)
    elif fmt == "html":
        assert body.startswith("<!doctype html>")
    else:
        assert body.startswith("# Bondy accessibility report")


def test_output_to_a_directory_is_a_usage_error(stubbed, capsys):
    code = cli.main(["scan", ".", "--no-llm", "--output", str(stubbed)])
    assert code == 2 and "cannot write --output" in capsys.readouterr().err


def test_json_paths_are_relative(stubbed, capsys):
    cli.main(["scan", str(stubbed), "--no-llm", "--format", "json"])
    payload = json.loads(capsys.readouterr().out)
    assert [f["path"] for f in payload["files"]] == ["p.html"]
    assert payload["files"][0]["findings"][0]["fingerprint"]


def test_exit_code_parity_with_the_pipeline_function(tmp_path):
    from bondy.core.pipeline import exit_code

    for findings in ([], [WARN], [AXE], [AXE, WARN]):
        for partial in (False, True):
            for errors in (False, True):
                sr = scan_report(tmp_path, findings=findings)
                sr.usage.partial = partial
                if errors:
                    sr.files[0].errors = ["x"]
                rep = build_report(sr, tmp_path)
                for fail_on in ("critical", "warning", "never"):
                    assert rep.exit_code(fail_on) == exit_code(sr, fail_on)


def test_api_key_never_appears_in_any_report_format(stubbed, monkeypatch, capsys):
    from bondy.core.providers.fake import FakeProvider
    from bondy.core.providers.gemini import GeminiProvider

    sentinel = "SENTINEL-API-KEY-55ff"
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 32
    (stubbed / "i.png").write_bytes(png)
    (stubbed / "p.html").write_text(
        '<html lang="en"><body><img src="i.png" alt="x"></body></html>',
        encoding="utf-8",
    )
    fake = FakeProvider()
    monkeypatch.setattr(
        GeminiProvider, "from_settings", classmethod(lambda cls, s, **kw: fake)
    )
    monkeypatch.setenv("GEMINI_API_KEY", sentinel)
    for fmt in formats.FORMATS:
        out = stubbed / f"r.{fmt}"
        cli.main(["scan", ".", "--format", fmt, "--output", str(out), "--no-cache"])
        shown = capsys.readouterr()
        assert sentinel not in shown.out + shown.err + out.read_text(encoding="utf-8")
