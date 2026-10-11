"""B9 incremental scans and the edge cases around file handling."""

import hashlib
import json
import subprocess

import pytest

from bondy import cli, config
from bondy.core import pipeline
from bondy.core.pipeline import changed_since, run_scan
from bondy.core.providers.fake import FakeProvider

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


class CountingScanner:
    """Stub scanner that records which pages it was asked to scan."""

    def __init__(self, finding=None):
        self.seen: list[str] = []
        self.finding = finding

    def __call__(self, html):
        self.seen.append(html)
        return [dict(self.finding)] if self.finding else []


def settings(tmp_path, **flags):
    flags.setdefault("api_key", "test-key")
    return config.load_settings(flags=flags, env={}, start_dir=tmp_path)


def page(tmp_path, name, imgs=1, text="hello", alt="alt"):
    body = "".join(f'<img src="{name}_{i}.png" alt="{alt} {i}">' for i in range(imgs))
    (tmp_path / f"{name}.html").write_text(
        f'<html lang="en"><body><p>{text}</p>{body}</body></html>', encoding="utf-8"
    )
    for i in range(imgs):
        (tmp_path / f"{name}_{i}.png").write_bytes(PNG + name.encode() + bytes([i]))


def go(tmp_path, scanner=None, provider=None, flags=None, **kw):
    scanner = scanner or CountingScanner()
    provider = provider or FakeProvider()
    report = run_scan(
        tmp_path,
        settings(tmp_path, **(flags or {})),
        scanners={"count": scanner},
        provider=provider,
        **kw,
    )
    return report, scanner, provider


def test_changed_only_reuses_unchanged_pages(tmp_path):
    for n in "abc":
        page(tmp_path, n, imgs=2)
    first, s1, p1 = go(tmp_path)
    assert len(s1.seen) == 3 and p1.http_requests == 1
    second, s2, p2 = go(tmp_path, changed_only=True)
    assert s2.seen == [] and p2.http_requests == 0
    assert second.usage.pages_reused == 3 and second.usage.pages_scanned == 0
    assert all(r.reused for r in second.files)
    # reused results are the same findings, fixes and image outcomes
    assert len(second.fixes) == len(first.fixes) == 6
    assert [o.suggested_alt for o in second.images] == [
        o.suggested_alt for o in first.images
    ]


def test_changed_only_rescans_only_the_changed_page(tmp_path):
    for n in "abc":
        page(tmp_path, n, imgs=1)
    go(tmp_path)
    page(tmp_path, "b", imgs=1, text="changed text")
    report, scanner, _ = go(tmp_path, changed_only=True)
    assert len(scanner.seen) == 1 and "changed text" in scanner.seen[0]
    assert report.usage.pages_scanned == 1 and report.usage.pages_reused == 2
    reused = {r.path.split("\\")[-1].split("/")[-1]: r.reused for r in report.files}
    assert reused == {"a.html": True, "b.html": False, "c.html": True}


def test_changed_image_with_same_html_invalidates_the_page(tmp_path):
    page(tmp_path, "a", imgs=1)
    go(tmp_path)
    (tmp_path / "a_0.png").write_bytes(PNG + b"edited")
    report, scanner, provider = go(tmp_path, changed_only=True)
    assert len(scanner.seen) == 1 and provider.http_requests == 1
    assert report.usage.pages_reused == 0


def test_plain_scan_never_reuses(tmp_path):
    page(tmp_path, "a")
    go(tmp_path)
    _, scanner, _ = go(tmp_path)  # no changed_only
    assert len(scanner.seen) == 1


def test_changed_only_without_previous_state_scans_everything(tmp_path):
    page(tmp_path, "a")
    report, scanner, _ = go(tmp_path, changed_only=True)
    assert len(scanner.seen) == 1 and report.usage.pages_reused == 0


@pytest.mark.parametrize("what", ["version", "checks", "model", "scanners", "static"])
def test_state_is_invalidated_by_version_config_or_checks(tmp_path, monkeypatch, what):
    page(tmp_path, "a")
    go(tmp_path)
    flags = {}
    scanner = CountingScanner()
    scanners = {"count": scanner}
    if what == "version":
        monkeypatch.setattr(pipeline, "bondy_version", lambda: "999.0.0")
    elif what == "checks":
        flags["checks"] = "WCAG 1.1.1"
    elif what == "model":
        flags["vision_model"] = "some-other-model"
    elif what == "scanners":
        scanners = {"count": scanner, "extra": lambda h: []}
    elif what == "static":
        flags["static"] = True
    report = run_scan(
        tmp_path,
        settings(tmp_path, **flags),
        scanners=scanners,
        provider=FakeProvider(),
        changed_only=True,
    )
    assert report.usage.pages_reused == 0 and len(scanner.seen) == 1


def test_changed_only_requires_cache(tmp_path):
    page(tmp_path, "a")
    with pytest.raises(config.ConfigError, match="cache"):
        go(tmp_path, flags={"cache": False}, changed_only=True)


def test_deleted_page_is_forgotten_and_new_page_scanned(tmp_path):
    page(tmp_path, "a")
    page(tmp_path, "b")
    go(tmp_path)
    (tmp_path / "a.html").unlink()
    page(tmp_path, "c")
    report, scanner, _ = go(tmp_path, changed_only=True)
    assert len(scanner.seen) == 1 and report.usage.pages_reused == 1
    pages = json.loads((tmp_path / ".bondy/cache/pages.json").read_text())["pages"]
    assert sorted(pages) == ["b.html", "c.html"]


def test_findings_are_reported_again_when_reused(tmp_path):
    page(tmp_path, "a", imgs=0)
    finding = {
        "scanner": "count",
        "wcag": ["3.1.1"],
        "severity": "critical",
        "message": "m",
    }
    go(tmp_path, scanner=CountingScanner(finding))
    report, scanner, _ = go(
        tmp_path, scanner=CountingScanner(finding), changed_only=True
    )
    assert scanner.seen == []
    assert report.files[0].findings == [finding]
    assert pipeline.exit_code(report, "critical") == 1


def test_file_changed_while_scanning_is_not_saved_for_reuse(tmp_path):
    page(tmp_path, "a", imgs=0)
    target = tmp_path / "a.html"

    def racing_scanner(html):
        target.write_text(html.replace("hello", "edited mid-scan"), encoding="utf-8")
        return []

    report = run_scan(
        tmp_path,
        settings(tmp_path),
        scanners={"race": racing_scanner},
        provider=FakeProvider(),
    )
    assert any("changed while being scanned" in n for n in report.notes)
    # the next incremental scan must NOT trust the stale result
    scanner = CountingScanner()
    report2 = run_scan(
        tmp_path,
        settings(tmp_path),
        scanners={"count": scanner},
        provider=FakeProvider(),
        changed_only=True,
    )
    assert len(scanner.seen) == 1 and "edited mid-scan" in scanner.seen[0]
    assert report2.usage.pages_reused == 0


def test_empty_project_leaves_no_trace(tmp_path, capsys):
    report, _, _ = go(tmp_path)
    assert report.files == [] and "No HTML files found" in " ".join(report.notes)
    assert not (tmp_path / ".bondy").exists()
    assert cli.main(["scan", str(tmp_path)]) == 0


def test_bom_and_crlf_pages(tmp_path):
    raw = (
        b'\xef\xbb\xbf<html lang="es">\r\n<body>\r\n'
        b'<img\r\n   src="a.png"\r\n   alt="Imagen de un perro">\r\n'
        b"</body></html>\r\n"
    )
    (tmp_path / "p.html").write_bytes(raw)
    (tmp_path / "a.png").write_bytes(PNG)
    report, scanner, provider = go(tmp_path)
    (r,) = report.files
    assert r.sha256 == hashlib.sha256(raw).hexdigest()  # hash of the raw bytes
    assert scanner.seen[0].startswith("<html")  # BOM stripped for scanning
    (fix,) = report.fixes
    assert "\r\n" in fix.before and fix.before.startswith("<img")
    assert fix.before in scanner.seen[0]  # exact text, CRLF kept
    sent = " ".join(x for x in provider.requests[0].parts if isinstance(x, str))
    assert "<page_lang>es</page_lang>" in sent


def test_latin1_page_is_scanned(tmp_path):
    (tmp_path / "p.html").write_bytes(
        '<html lang="es"><body><p>Descripción</p></body></html>'.encode("latin-1")
    )
    report, scanner, _ = go(tmp_path)
    assert "Descripción" in scanner.seen[0] and not report.files[0].errors


# ----- --since (git) -----
def _git(tmp_path, *args):
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "-c",
            "user.email=a@b.c",
            "-c",
            "user.name=t",
            *args,
        ],
        check=True,
        capture_output=True,
    )


@pytest.fixture
def repo(tmp_path):
    try:
        _git(tmp_path, "init", "-q")
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("git not available")
    page(tmp_path, "a", imgs=0)
    page(tmp_path, "b", imgs=0)
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "base")
    return tmp_path


def test_since_scans_only_changed_and_untracked(repo):
    page(repo, "a", imgs=0, text="modified")
    page(repo, "new", imgs=0)
    names = {p.split("\\")[-1].split("/")[-1] for p in changed_since(repo, "HEAD")}
    assert names == {"a.html", "new.html"}
    report, scanner, _ = go(repo, since="HEAD")
    assert len(scanner.seen) == 2
    skipped = [r for r in report.files if r.skipped]
    # no state was saved yet, so the untouched page cannot be reused
    assert [r.skipped for r in skipped] == [
        "unchanged since HEAD (no saved result to reuse)"
    ]
    assert not report.partial  # selection is not a partial result


def test_since_reuses_saved_state_for_untouched_pages(repo):
    go(repo)  # a normal scan seeds the saved state
    page(repo, "a", imgs=0, text="modified")
    report, scanner, _ = go(repo, since="HEAD")
    assert len(scanner.seen) == 1 and "modified" in scanner.seen[0]
    by_name = {r.path.split("\\")[-1].split("/")[-1]: r for r in report.files}
    assert by_name["b.html"].reused and not by_name["b.html"].skipped
    assert not by_name["a.html"].reused
    assert report.usage.pages_reused == 1 and not report.partial


def test_since_ignores_state_from_another_configuration(repo):
    go(repo, flags={"checks": "WCAG 1.1.1"})  # state saved for other checks
    page(repo, "a", imgs=0, text="modified")
    report, scanner, _ = go(repo, since="HEAD")
    assert len(scanner.seen) == 1
    skipped = [r.skipped for r in report.files if r.skipped]
    assert skipped == ["unchanged since HEAD (no saved result to reuse)"]


def test_since_content_hash_wins_over_git(repo):
    go(repo)
    page(repo, "b", imgs=0, text="edited then committed")
    _git(repo, "commit", "-qam", "edit b")  # git says: unchanged since HEAD
    report, scanner, _ = go(repo, since="HEAD")
    assert scanner.seen == []
    by_name = {r.path.split("\\")[-1].split("/")[-1]: r for r in report.files}
    assert by_name["a.html"].reused  # same hash as the saved result
    assert by_name["b.html"].skipped  # saved result is for older content
    assert not by_name["b.html"].reused


@pytest.mark.parametrize("ref", ["--output=/tmp/x", "-p", "a b", "HEAD;rm -rf /", ""])
def test_since_rejects_option_like_refs(repo, ref):
    with pytest.raises(config.ConfigError):
        changed_since(repo, ref)


def test_since_unknown_ref_is_a_clear_error(repo):
    with pytest.raises(config.ConfigError, match="git failed"):
        changed_since(repo, "no-such-ref")


def _tree(root):
    return sorted(
        (str(p.relative_to(root)), p.stat().st_mtime_ns) for p in root.rglob("*")
    )


def test_plain_deterministic_scan_writes_nothing_into_the_project(tmp_path):
    page(tmp_path, "a", imgs=1)
    before = _tree(tmp_path)
    report, scanner, provider = go(tmp_path, flags={"no_llm": True})
    assert len(scanner.seen) == 1 and provider.http_requests == 0
    assert _tree(tmp_path) == before
    assert not (tmp_path / ".bondy").exists()
    assert report.usage.cache_enabled is False


def test_state_folder_ignores_itself_in_git(tmp_path):
    page(tmp_path, "a", imgs=1)
    go(tmp_path)  # LLM scan: verdict cache + page state are written
    ignore = tmp_path / ".bondy" / ".gitignore"
    assert ignore.read_text(encoding="utf-8").strip() == "*"
    assert (tmp_path / ".bondy" / "cache" / "pages.json").is_file()


def test_existing_gitignore_in_state_folder_is_not_overwritten(tmp_path):
    page(tmp_path, "a", imgs=1)
    (tmp_path / ".bondy").mkdir()
    (tmp_path / ".bondy" / ".gitignore").write_text("custom\n", encoding="utf-8")
    go(tmp_path)
    assert (tmp_path / ".bondy" / ".gitignore").read_text() == "custom\n"


def test_deterministic_scan_with_changed_only_does_persist(tmp_path):
    page(tmp_path, "a", imgs=0)
    go(tmp_path, flags={"no_llm": True}, changed_only=True)
    assert (tmp_path / ".bondy" / "cache" / "pages.json").is_file()
    assert (tmp_path / ".bondy" / ".gitignore").is_file()


def test_deterministic_scan_with_since_does_persist(repo):
    go(repo, flags={"no_llm": True}, since="HEAD")
    assert (repo / ".bondy" / "cache" / "pages.json").is_file()
