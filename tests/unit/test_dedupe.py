"""Merging of findings that report the same problem on the same element."""

import itertools
import json
import random

import pytest

from bondy import cli, config
from bondy.config import IgnoreRule
from bondy.core import pipeline
from bondy.core.baseline import Baseline
from bondy.core.dedupe import dedupe_items, element_key, family, same_element
from bondy.core.formats import to_json_dict, to_sarif_dict
from bondy.core.models import ScanReport, UsageSummary
from bondy.core.pipeline import run_scan
from bondy.core.report import Item, build_report
from bondy.scan import SCANNERS, FileResult

SEARCH = '<a href="/search"><img src="search.png"></a>'
PAGE = f'<html lang="en"><body><main>{SEARCH}</main></body></html>'


# ----- synthetic findings, shaped like what the real scanners return -----
def axe(rule, selector, html, wcag=("2.4.4", "4.1.2"), severity="critical"):
    return {
        "scanner": "axe",
        "rule": rule,
        "wcag": list(wcag),
        "severity": severity,
        "message": "Links must have discernible text",
        "count": 1,
        "nodes": [{"selector": selector, "html": html, "failure": "Fix any of..."}],
    }


def tree(html, role="link"):
    return {
        "scanner": "axe-tree",
        "wcag": ["4.1.2"],
        "severity": "critical",
        "message": f"Element with role '{role}' has no accessible name",
        "nodes": [{"html": html}],
    }


def name(selector, html=None, tag="a"):
    f = {
        "scanner": "accessible-name",
        "wcag": ["2.4.4", "4.1.2"],
        "severity": "critical",
        "message": f"<{tag}> '{selector}' has no accessible name",
        "selector": selector,
    }
    if html:
        f["nodes"] = [{"selector": selector, "html": html}]
    return f


def label(selector, html=None):
    f = {
        "scanner": "labels",
        "wcag": ["1.3.1", "4.1.2"],
        "severity": "critical",
        "message": f"Form control '{selector}' has no accessible label",
        "selector": selector,
    }
    if html:
        f["nodes"] = [{"selector": selector, "html": html}]
    return f


def contrast(selector, text="low contrast text"):
    return {
        "scanner": "contrast",
        "wcag": ["1.4.3"],
        "severity": "critical",
        "message": "Contrast 1.61:1 is below 4.5:1",
        "selector": selector,
        "text": text,
    }


def build(tmp_path, pages, **kw):
    """``pages``: {name: (html, findings)} -> Report built from raw findings."""
    files = []
    for fname, (html, findings) in pages.items():
        files.append(
            FileResult(
                path=str(tmp_path / fname),
                findings=[json.loads(json.dumps(f)) for f in findings],
                html=html,
            )
        )
    scan = ScanReport(files=files, usage=UsageSummary(mode="no-llm"))
    return build_report(scan, tmp_path, **kw)


def one(tmp_path, html, findings, **kw):
    return build(tmp_path, {"a.html": (html, findings)}, **kw)


def search_findings():
    return [
        axe("link-name", 'a[href$="search"]', SEARCH),
        tree(SEARCH),
        name("a", SEARCH),
    ]


def shape(report):
    return sorted(
        (
            i.file,
            i.rule,
            i.fingerprint,
            tuple(sorted(m["fingerprint"] for m in i.merged_from)),
        )
        for i in report.items
    )


# ----- regression: the magnifying-glass link -----
def test_search_link_reports_one_problem_with_the_best_evidence(tmp_path):
    findings = [
        *search_findings(),
        axe("image-alt", "img", '<img src="search.png">', ("1.1.1",)),
    ]
    r = one(tmp_path, PAGE, findings)
    assert len(r.items) == 2
    link = next(i for i in r.items if i.rule == "link-name")
    assert link.scanner == "axe"
    assert link.selector == 'a[href$="search"]'
    assert link.snippet == SEARCH and link.line == 1
    assert link.severity == "critical"
    assert {m["rule"] for m in link.merged_from} == {"axe-tree", "accessible-name"}
    assert all(m["fingerprint"] for m in link.merged_from)
    assert r.duplicates_merged == 2
    # the image's own problem (fix the cause) is a different finding
    assert any(i.rule == "image-alt" and not i.merged_from for i in r.items)


def test_merge_does_not_depend_on_the_order_of_the_findings(tmp_path):
    findings = [
        *search_findings(),
        axe("image-alt", "img", '<img src="search.png">', ("1.1.1",)),
    ]
    results = set()
    for perm in itertools.permutations(findings):
        r = one(tmp_path, PAGE, list(perm))
        results.add(
            tuple(
                sorted(
                    (i.rule, tuple(sorted(m["rule"] for m in i.merged_from)))
                    for i in r.items
                )
            )
        )
    assert len(results) == 1


def test_dedupe_is_idempotent(tmp_path):
    r = one(tmp_path, PAGE, search_findings())
    again, merged = dedupe_items(r.items, {})
    assert merged == 0 and shape_items(again) == shape_items(r.items)
    # also with the page indexes (selector resolution)
    from bondy.core.source import PageIndex

    again, merged = dedupe_items(r.items, {"a.html": PageIndex(PAGE)})
    assert merged == 0 and shape_items(again) == shape_items(r.items)


def shape_items(items):
    return [(i.rule, i.fingerprint, len(i.merged_from), tuple(i.wcag)) for i in items]


# ----- what merges -----
def test_unnamed_button_and_input_merge_with_axe_and_html_checks(tmp_path):
    btn = "<button><svg></svg></button>"
    inp = '<input type="text" id="q">'
    html = f'<html lang="en"><body>{btn}{inp}</body></html>'
    r = one(
        tmp_path,
        html,
        [
            tree(btn, "button"),
            name("button", btn, "button"),
            axe("button-name", "button", btn, ("4.1.2",)),
            tree(inp, "textbox"),
            label("input#q", inp),
            axe("label", "#q", inp, ("4.1.2",)),
        ],
    )
    assert sorted(i.rule for i in r.items) == ["button-name", "label"]
    lab = next(i for i in r.items if i.rule == "label")
    assert {m["rule"] for m in lab.merged_from} == {"axe-tree", "labels"}
    assert lab.wcag == ["1.3.1", "4.1.2"]  # union of the criteria


def test_html_check_alone_keeps_the_most_informative_finding(tmp_path):
    # no axe (e.g. --checks filtered it): accessible-name beats axe-tree
    r = one(tmp_path, PAGE, [tree(SEARCH), name("a", SEARCH)])
    assert len(r.items) == 1 and r.items[0].rule == "accessible-name"
    assert [m["rule"] for m in r.items[0].merged_from] == ["axe-tree"]


def test_contrast_scanner_merges_with_axe_color_contrast(tmp_path):
    p = '<p style="color:#ccc">low contrast text</p>'
    html = f'<html lang="en"><body>{p}</body></html>'
    r = one(
        tmp_path,
        html,
        [axe("color-contrast", "p", p, ("1.4.3",)), contrast("p")],
    )
    assert [i.rule for i in r.items] == ["color-contrast"]
    assert r.items[0].merged_from[0]["scanner"] == "contrast"


def test_selector_only_finding_is_tied_to_a_unique_element(tmp_path):
    html = '<html lang="en"><body><a id="go" href="/x"></a></body></html>'
    r = one(
        tmp_path,
        html,
        [
            axe("link-name", "#go", '<a id="go" href="/x"></a>'),
            name("a#go"),  # old-style finding: selector only
        ],
    )
    assert [i.rule for i in r.items] == ["link-name"]


def test_cut_snippets_still_match(tmp_path):
    long = '<a href="/s"><img src="a.png"><span>' + "x" * 400 + "</span></a>"
    html = f'<html lang="en"><body>{long}</body></html>'
    r = one(
        tmp_path,
        html,
        [
            axe("link-name", "a", long[:300]),
            tree(long[:120]),  # cut in the middle of a tag
        ],
    )
    assert len(r.items) == 1 and r.items[0].rule == "link-name"


# ----- what must NOT merge -----
def test_different_natures_on_one_element_stay_apart(tmp_path):
    html = '<html lang="en"><body><a href="/x" style="color:#ccc">go</a></body></html>'
    a = '<a href="/x" style="color:#ccc">go</a>'
    r = one(
        tmp_path,
        html,
        [
            axe("color-contrast", "a", a, ("1.4.3",)),
            axe("link-name", "a", a),
            {
                "scanner": "focus-order",
                "wcag": ["2.4.3"],
                "severity": "warning",
                "message": "Element a receives focus but is not visible.",
                "nodes": [{"html": a}],
            },
            axe("region", "a", a, ()),
        ],
    )
    assert len(r.items) == 4 and r.duplicates_merged == 0


def test_image_problem_is_not_merged_into_the_link_name(tmp_path):
    alt = {
        "scanner": "alt-text",
        "wcag": ["1.1.1"],
        "severity": "critical",
        "message": 'line 1: set alt="Search": icon',
        "line": 1,
        "suggested_alt": "Search",
        "nodes": [{"html": '<img src="search.png">'}],
    }
    r = one(tmp_path, PAGE, [*search_findings(), alt])
    assert sorted(i.scanner for i in r.items) == ["alt-text", "axe"]


def test_identical_elements_are_separate_problems(tmp_path):
    two = '<a href="/x"></a><a href="/x"></a>'
    html = f'<html lang="en"><body>{two}</body></html>'
    a = '<a href="/x"></a>'
    r = one(
        tmp_path,
        html,
        [
            axe("link-name", 'a[href="/x"]', a),
            axe("link-name", 'a[href="/x"]', a),
            tree(a),
            tree(a),
        ],
    )
    # two elements, each reported twice -> two items (never collapsed to one)
    assert len(r.items) == 2 and r.duplicates_merged == 2
    assert all(len(i.merged_from) == 1 for i in r.items)


def test_a_different_element_with_the_same_tag_is_not_merged(tmp_path):
    other = '<a href="/other"></a>'
    html = f'<html lang="en"><body>{SEARCH}{other}</body></html>'
    r = one(tmp_path, html, [axe("link-name", "a", SEARCH), tree(other)])
    assert len(r.items) == 2


def test_ambiguous_selector_without_html_is_not_merged(tmp_path):
    html = '<html lang="en"><body><a href="/1"></a><a href="/2"></a></body></html>'
    r = one(
        tmp_path,
        html,
        [axe("link-name", 'a[href="/1"]', '<a href="/1"></a>'), name("a")],
    )
    assert len(r.items) == 2 and r.duplicates_merged == 0


def test_same_html_in_two_files_is_not_merged(tmp_path):
    pages = {
        "a.html": (PAGE, [axe("link-name", "a", SEARCH)]),
        "b.html": (PAGE, [tree(SEARCH)]),
    }
    r = build(tmp_path, pages)
    assert len(r.items) == 2


def test_items_on_different_lines_are_not_merged(tmp_path):
    html = f'<html lang="en"><body>\n{SEARCH}\n{SEARCH}\n</body></html>'
    a = axe("link-name", "a", SEARCH)
    a["line"] = 2
    b = tree(SEARCH)
    b["line"] = 3
    r = one(tmp_path, html, [a, b])
    assert len(r.items) == 2


def test_unrelated_rules_are_left_alone(tmp_path):
    assert family(Item("a", "axe", "image-alt", [], "critical", "m")) is None
    assert family(Item("a", "focus-order", "focus-order", [], "warning", "m")) is None
    assert family(Item("a", "axe", "link-name", [], "critical", "m")) == (
        family(Item("a", "axe-tree", "axe-tree", [], "critical", "m"))
    )
    r = one(tmp_path, PAGE, [axe("image-alt", "a", SEARCH, ("1.1.1",))] * 2)
    assert len(r.items) == 2


def test_severity_is_the_worst_of_the_merged(tmp_path):
    w = axe("link-name", "a", SEARCH, severity="warning")
    r = one(tmp_path, PAGE, [w, tree(SEARCH)])
    assert len(r.items) == 1 and r.items[0].severity == "critical"
    assert r.exit_code("critical") == 1


def test_element_helpers():
    sigs = element_key(Item("a", "axe", "r", [], "critical", "m", snippet=SEARCH), None)
    assert [s[0] for s in sigs] == ["a", "img"]
    assert same_element(sigs[:1], sigs) and not same_element((), sigs)


# ----- ignore, baseline, exit code -----
def test_inline_ignore_by_any_merged_rule_suppresses_the_item(tmp_path):
    for rule in ("link-name", "accessible-name", "axe-tree", "2.4.4", "4.1.2"):
        html = (
            '<html lang="en"><body>'
            f"<!-- bondy-ignore: {rule} -- icon link, labelled by CSS -->"
            f"{SEARCH}</body></html>"
        )
        r = one(tmp_path, html, search_findings())
        assert [i.status for i in r.items] == ["suppressed"], rule
        assert r.exit_code("critical") == 0
        assert r.suppressions[0].matched == 1 and r.suppressions[0].status == "applied"


def test_ignore_rule_from_config_by_merged_rule(tmp_path):
    ign = IgnoreRule(path="*.html", rule="axe-tree", reason="legacy", index=0)
    r = one(tmp_path, PAGE, search_findings(), ignore_rules=(ign,))
    assert [i.status for i in r.items] == ["suppressed"]


def test_a_different_ignore_does_not_suppress(tmp_path):
    html = (
        '<html lang="en"><body><!-- bondy-ignore: color-contrast -- ok -->'
        f"{SEARCH}</body></html>"
    )
    r = one(tmp_path, html, search_findings())
    assert [i.status for i in r.items] == ["new"]


def entries(*fps):
    return {fp: {"fingerprint": fp, "file": "a.html", "scanner": "axe"} for fp in fps}


def test_baseline_with_old_duplicate_fingerprints_still_matches(tmp_path):
    raw = one(tmp_path, PAGE, search_findings())
    link = raw.items[0]
    by_rule = {m["rule"]: m["fingerprint"] for m in link.merged_from}
    for fps in (
        [link.fingerprint],  # new baseline: winner only
        [by_rule["axe-tree"]],  # old baseline, a merged-away entry only
        [link.fingerprint, *by_rule.values()],  # old baseline: all three
    ):
        r = one(
            tmp_path,
            PAGE,
            search_findings(),
            baseline=Baseline("b.json", entries(*fps)),
        )
        assert [i.status for i in r.items] == ["baselined"]
        assert r.baseline.matched == 1 and r.baseline.resolved == 0
        assert r.exit_code("critical") == 0


def test_winner_fingerprint_is_the_one_it_had_before_merging(tmp_path):
    merged = one(tmp_path, PAGE, search_findings()).items[0]
    alone = one(tmp_path, PAGE, [search_findings()[0]]).items[0]
    assert merged.fingerprint == alone.fingerprint


def test_fail_on_counts_merged_items_once(tmp_path):
    r = one(tmp_path, PAGE, search_findings())
    assert len(r.new_items) == 1
    assert r.summary()["findings"]["new"]["total"] == 1
    assert r.summary()["findings"]["duplicates_merged"] == 2
    assert r.exit_code("critical") == 1 and r.exit_code("never") == 0


# ----- presentation -----
def test_formats_keep_the_trace(tmp_path):
    r = one(tmp_path, PAGE, search_findings())
    doc = to_json_dict(r, 1)
    f = doc["files"][0]["findings"][0]
    assert [m["rule"] for m in f["merged_from"]] == ["accessible-name", "axe-tree"]
    sarif = to_sarif_dict(r, 1)
    res = sarif["runs"][0]["results"][0]
    assert len(res["properties"]["mergedFrom"]) == 2
    assert sarif["runs"][0]["properties"]["bondy"]["duplicatesMerged"] == 2
    # nothing merged -> no extra keys
    plain = one(tmp_path, PAGE, [axe("link-name", "a", SEARCH)])
    assert "merged_from" not in to_json_dict(plain, 0)["files"][0]["findings"][0]


# ----- through the real pipeline: static scanners, cache, resume -----
def test_real_html_checks_alone_never_merge(tmp_path, monkeypatch, capsys):
    """Static mode: only HTML-parsing checks run and none of them overlap."""
    crlf = chr(13) + chr(10)
    body = crlf.join(
        [
            "<html>",
            "<body>",
            SEARCH,
            "<button></button>",
            '<input type="text" id="q">',
            "</body></html>",
            "",
        ]
    )
    # UTF-8 BOM + CRLF, as saved by Windows editors
    (tmp_path / "p.html").write_bytes(body.encode("utf-8-sig"))
    monkeypatch.chdir(tmp_path)
    code = cli.main(
        ["scan", "p.html", "--no-llm", "--static", "--format", "json", "--no-cache"]
    )
    doc = json.loads(capsys.readouterr().out)
    scanners = sorted(f["scanner"] for f in doc["files"][0]["findings"])
    assert code == 1
    assert scanners == [
        "accessible-name",
        "accessible-name",
        "img-alt",
        "labels",
        "lang",
    ]
    assert doc["summary"]["findings"]["duplicates_merged"] == 0
    # the HTML checks now carry the element, so each one has its line
    assert all(f["line"] for f in doc["files"][0]["findings"] if f["scanner"] != "lang")


@pytest.fixture
def fake_scanners(monkeypatch):
    def axe_like(html):
        return [axe("link-name", 'a[href$="search"]', SEARCH)]

    def tree_like(html):
        return [tree(SEARCH)]

    def name_like(html):
        return [name("a", SEARCH)]

    return {"axe": axe_like, "axe-tree": tree_like, "accessible-name": name_like}


def _settings(tmp_path):
    return config.load_settings(flags={"no_llm": True}, env={}, start_dir=tmp_path)


def test_resume_and_changed_only_give_the_same_merged_result(tmp_path, fake_scanners):
    for n in ("a", "b"):
        (tmp_path / f"{n}.html").write_text(PAGE, encoding="utf-8")
    s = _settings(tmp_path)
    plain = build_report(run_scan(tmp_path, s, scanners=fake_scanners), tmp_path)
    # changed_only saves the (raw) pages; the next run reuses them
    run_scan(tmp_path, s, scanners=fake_scanners, changed_only=True)
    reused = run_scan(tmp_path, s, scanners=fake_scanners, changed_only=True)
    assert reused.usage.pages_reused == 2 and reused.usage.pages_scanned == 0
    second = build_report(reused, tmp_path)
    assert shape(plain) == shape(second)
    first = plain
    assert len(first.items) == 2 and first.duplicates_merged == 4


def test_saved_pages_keep_raw_findings_and_a_schema_bump_invalidates(
    tmp_path, fake_scanners, monkeypatch
):
    (tmp_path / "a.html").write_text(PAGE, encoding="utf-8")
    s = _settings(tmp_path)
    fp1 = pipeline.config_fingerprint(s, False, fake_scanners)
    monkeypatch.setattr(pipeline, "FINDINGS_SCHEMA", pipeline.FINDINGS_SCHEMA + 1)
    assert pipeline.config_fingerprint(s, False, fake_scanners) != fp1
    r = run_scan(tmp_path, s, scanners=fake_scanners, changed_only=True)
    assert len(r.files[0].findings) == 3  # raw: merging happens in the report


def test_random_shuffles_of_a_realistic_page_are_stable(tmp_path):
    inp = '<input type="text" id="q">'
    btn = "<button></button>"
    html = f'<html lang="en"><body>{SEARCH}{btn}{inp}</body></html>'
    base = [
        *search_findings(),
        tree(btn, "button"),
        name("button", btn, "button"),
        axe("button-name", "button", btn, ("4.1.2",)),
        tree(inp, "textbox"),
        label("input#q", inp),
        axe("label", "#q", inp, ("4.1.2",)),
    ]
    want = None
    rng = random.Random(7)
    for _ in range(25):
        shuffled = base[:]
        rng.shuffle(shuffled)
        r = one(tmp_path, html, shuffled)
        got = sorted(
            (i.rule, tuple(sorted(m["rule"] for m in i.merged_from))) for i in r.items
        )
        want = want or got
        assert got == want
    assert [g[0] for g in want] == ["button-name", "label", "link-name"]


def test_scanners_registry_untouched():
    # dedupe is a report-stage step: no scanner was added or renamed
    assert set(SCANNERS) == {
        "axe",
        "contrast",
        "focus-trap",
        "focus-order",
        "lang",
        "labels",
        "accessible-name",
    }


def test_real_browser_search_link_and_demo_like_controls(tmp_path, monkeypatch):
    """End to end with the real scanners (skipped without a browser)."""
    html = (
        '<!DOCTYPE html><html lang="en"><head><title>t</title></head><body><main>'
        f'{SEARCH}<button><svg width="10" height="10"></svg></button>'
        '<input type="button"><input type="text" id="q">'
        '<p style="color:#ccc;background:#fff">low contrast text</p>'
        "</main></body></html>"
    )
    (tmp_path / "m.html").write_text(html, encoding="utf-8")
    s = config.load_settings(flags={"no_llm": True}, env={}, start_dir=tmp_path)
    scan = run_scan(tmp_path / "m.html", s)
    if scan.files[0].omitted:
        pytest.skip("no browser available: static mode")
    report = build_report(scan, tmp_path)
    raw = sum(len(f.findings) for f in scan.files)
    assert raw >= 15  # axe + axe-tree + accessible-name + labels + contrast...
    by_rule = {i.rule: i for i in report.items if i.merged_from}
    assert {"link-name", "button-name", "input-button-name", "label"} <= set(by_rule)
    assert "color-contrast" in by_rule
    assert not [i for i in report.items if i.scanner in ("axe-tree", "contrast")]
    link = next(i for i in report.items if i.rule == "link-name")
    assert {m["rule"] for m in link.merged_from} == {"axe-tree", "accessible-name"}
    # the image's own problem is still reported once, as its own finding
    assert sum(1 for i in report.items if i.rule == "image-alt") == 1
