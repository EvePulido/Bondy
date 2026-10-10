"""E4: bondy-ignore comments and [[ignore]] entries (reason mandatory)."""

import json
import re

import pytest

from bondy import cli
from bondy.config import ConfigError, load_settings
from bondy.scan import SCANNERS


def labels(html):
    return [
        {
            "scanner": "labels",
            "wcag": ["1.3.1", "4.1.2"],
            "severity": "critical",
            "message": f"control #{m} has no label",
            "nodes": [{"selector": f"#{m}", "html": f'<input id="{m}">'}],
        }
        for m in re.findall(r'<input id="(\w+)">', html)
    ]


def lang(html):
    return (
        []
        if "lang=" in html
        else [
            {
                "scanner": "lang",
                "wcag": ["3.1.1"],
                "severity": "critical",
                "message": "<html lang> is missing",
            }
        ]
    )


@pytest.fixture
def proj(tmp_path, monkeypatch):
    for name in SCANNERS:
        monkeypatch.setitem(SCANNERS, name, lambda html: [])
    monkeypatch.setitem(SCANNERS, "labels", labels)
    monkeypatch.setitem(SCANNERS, "lang", lang)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "site").mkdir()
    return tmp_path


def write(proj, body, name="a.html", head='<html lang="en">'):
    (proj / "site" / name).write_text(
        f"{head}<body>\n{body}\n</body></html>", encoding="utf-8"
    )


def scan(*argv):
    return cli.main(["scan", "site", "--no-llm", "--format", "json", *argv])


def payload(capsys):
    return json.loads(capsys.readouterr().out)


def test_inline_ignore_applies_to_the_next_element_only(proj, capsys):
    write(
        proj,
        "<!-- bondy-ignore: labels -- legacy widget, label added by script -->\n"
        '<input id="one">\n<input id="two">',
    )
    code = scan()
    out = payload(capsys)
    assert code == 1
    assert [f["selector"] for f in out["files"][0]["findings"]] == ["#two"]
    (supp,) = out["suppressed"]
    assert supp["selector"] == "#one"
    assert supp["suppressed_by"]["reason"].startswith("legacy widget")
    assert out["suppressions"][0]["status"] == "applied"
    assert out["summary"]["findings"]["suppressed"] == 1


def test_wcag_token_and_multiple_rules_in_one_comment(proj, capsys):
    write(
        proj,
        "<!-- bondy-ignore: WCAG 1.3.1, nonexistent-rule -- covered by manual test -->\n"
        '<input id="one">',
    )
    code = scan()
    out = payload(capsys)
    assert code == 0
    statuses = {s["rule"]: s["status"] for s in out["suppressions"]}
    assert statuses == {"1.3.1": "applied", "nonexistent-rule": "obsolete"}


def test_page_level_finding_is_suppressed_from_a_comment_before_html(proj, capsys):
    (proj / "site" / "a.html").write_text(
        "<!-- bondy-ignore: lang -- language is set by the CMS at runtime -->\n"
        "<html><body></body></html>",
        encoding="utf-8",
    )
    assert scan() == 0
    assert payload(capsys)["summary"]["findings"]["suppressed"] == 1


@pytest.mark.parametrize(
    "comment",
    [
        "<!-- bondy-ignore: labels -->",
        "<!-- bondy-ignore: labels -- -->",
        "<!-- bondy-ignore: labels --   -->",
        "<!-- bondy-ignore -- just because -->",
        "<!-- bondy-ignore: -- reason -->",
        "<!-- bondy-ignore: not a rule! -- reason -->",
    ],
)
def test_missing_reason_or_bad_rule_is_an_actionable_usage_error(
    proj, capsys, monkeypatch, comment
):
    write(proj, f'{comment}\n<input id="one">')
    monkeypatch.setitem(SCANNERS, "labels", lambda h: pytest.fail("ran the scan"))
    code = scan()
    err = capsys.readouterr().err
    assert code == 2
    assert "a.html: line 2" in err and "bondy-ignore: <rule|wcag>" in err


def test_ignore_on_a_missing_element_is_obsolete_and_reported(proj, capsys):
    write(proj, '<input id="one">\n<!-- bondy-ignore: labels -- was a spinner -->')
    code = scan()
    out = payload(capsys)
    (s,) = out["suppressions"]
    assert code == 1  # #one is not suppressed; obsolete ones never fail a run
    assert s["status"] == "obsolete" and "no element follows" in s["detail"]
    assert out["summary"]["suppressions"]["obsolete"] == 1


def test_obsolete_is_listed_in_terminal_and_does_not_change_exit(proj, capsys):
    write(proj, "<!-- bondy-ignore: labels -- old --><p>no inputs</p>")
    code = cli.main(["scan", "site", "--no-llm"])
    out = capsys.readouterr().out
    assert code == 0 and "Obsolete suppressions" in out and "a.html:2" in out
    assert "Remove the 1 obsolete ignore(s)" in out


def test_config_ignore_by_path_glob_and_rule(proj, capsys):
    write(proj, '<input id="one">', "legacy.html")
    write(proj, '<input id="two">', "new.html")
    (proj / "bondy.toml").write_text(
        '[[ignore]]\npath = "legacy*.html"\nrule = "labels"\n'
        'reason = "legacy section is being rewritten"\n',
        encoding="utf-8",
    )
    code = scan()
    out = payload(capsys)
    assert code == 1
    by_file = {f["path"]: len(f["findings"]) for f in out["files"]}
    assert by_file == {"legacy.html": 0, "new.html": 1}
    sup = out["suppressions"][0]
    assert sup["source"] == "config" and sup["reason"].startswith("legacy section")


def test_config_ignore_that_matches_nothing_is_obsolete(proj, capsys):
    write(proj, "<p>x</p>")
    (proj / "bondy.toml").write_text(
        '[[ignore]]\npath = "gone/**"\nrule = "labels"\nreason = "was removed"\n',
        encoding="utf-8",
    )
    scan()
    s = payload(capsys)["suppressions"][0]
    assert s["status"] == "obsolete" and "matches no scanned file" in s["detail"]


@pytest.mark.parametrize(
    ("toml", "needle"),
    [
        ('path = "a.html"\nrule = "labels"\n', "missing reason"),
        ('path = "a.html"\nrule = "labels"\nreason = "  "\n', "'reason' must say why"),
        ('path = "a.html"\nreason = "x"\n', "missing rule"),
        ('path = "../outside/**"\nrule = "labels"\nreason = "x"\n', "'..'"),
        ('path = "/etc/*"\nrule = "labels"\nreason = "x"\n', "relative"),
        ('path = \'C:\\x\\*\'\nrule = "labels"\nreason = "x"\n', "relative"),
        ('path = "~/x"\nrule = "labels"\nreason = "x"\n', "relative"),
        ('path = "a/../../b"\nrule = "labels"\nreason = "x"\n', "'..'"),
        ('path = "a.html"\nrule = "Bad Rule!"\nreason = "x"\n', "not a rule id"),
        ('path = "a.html"\nrule = "labels"\nreason = "x"\nwhy = 1\n', "unknown key"),
    ],
)
def test_invalid_config_ignore_is_rejected_with_exit_2(
    proj, capsys, monkeypatch, toml, needle
):
    write(proj, '<input id="one">')
    (proj / "bondy.toml").write_text("[[ignore]]\n" + toml, encoding="utf-8")
    monkeypatch.setitem(SCANNERS, "labels", lambda h: pytest.fail("ran the scan"))
    code = scan()
    err = capsys.readouterr().err
    assert code == 2 and needle in err and "[[ignore]] #1" in err


def test_config_loader_returns_normalized_rules(tmp_path):
    (tmp_path / "bondy.toml").write_text(
        '[[ignore]]\npath = \'docs\\*.html\'\nrule = "WCAG 1.4.3"\nreason = " why "\n',
        encoding="utf-8",
    )
    s = load_settings(env={}, start_dir=tmp_path)
    (r,) = s.ignore
    assert (r.path, r.rule, r.reason) == ("docs/*.html", "1.4.3", "why")
    with pytest.raises(ConfigError):
        load_settings(env={}, flags={"ignore": 1}, start_dir=tmp_path / "x")


def test_suppressed_items_are_not_baselined_or_in_sarif(proj, capsys):
    write(
        proj,
        "<!-- bondy-ignore: labels -- reviewed by hand -->\n"
        '<input id="one">\n<input id="two">',
    )
    cli.main(["baseline", "create", "site", "--no-llm", "-o", "b.json"])
    doc = json.loads((proj / "b.json").read_text(encoding="utf-8"))
    assert [f["selector"] for f in doc["findings"]] == ["#two"]
    capsys.readouterr()
    cli.main(["scan", "site", "--no-llm", "--format", "sarif"])
    sarif = json.loads(capsys.readouterr().out)
    assert len(sarif["runs"][0]["results"]) == 1
    assert sarif["runs"][0]["properties"]["bondy"]["suppressed"] == 1


def test_markdown_and_html_list_suppressions_with_their_reason(proj, capsys):
    write(
        proj,
        '<!-- bondy-ignore: labels -- <b>reviewed</b> by hand -->\n<input id="one">',
    )
    for fmt in ("markdown", "html"):
        cli.main(["scan", "site", "--no-llm", "--format", fmt])
        text = capsys.readouterr().out
        assert "reviewed" in text and "<b>reviewed</b>" not in text


def test_a_comment_elsewhere_does_not_hide_other_findings(proj, capsys):
    write(proj, '<input id="one">\n<!-- bondy-ignore: labels -- x -->\n<p>y</p>')
    assert scan() == 1
