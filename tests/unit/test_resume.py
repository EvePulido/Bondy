"""B10: quota/limit/Ctrl+C leave resumable state; --resume repeats nothing."""

import json

from bondy import cli, config
from bondy.core.pipeline import EXIT_PARTIAL, exit_code, run_scan
from bondy.core.providers.base import MediaPart
from bondy.core.providers.fake import (
    RATE_LIMIT_DAY,
    FakeProvider,
)
from bondy.scan import INTERRUPTED_SKIP

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


def settings(tmp_path, **flags):
    flags.setdefault("api_key", "test-key")
    flags.setdefault("batch_size", 2)
    return config.load_settings(flags=flags, env={}, start_dir=tmp_path)


def pages(tmp_path, names="abc", per_page=2, text="hello"):
    for n in names:
        body = "".join(
            f'<img src="{n}{i}.png" alt="x {n}{i}">' for i in range(per_page)
        )
        (tmp_path / f"{n}.html").write_text(
            f'<html lang="en"><body><p>{text}</p>{body}</body></html>',
            encoding="utf-8",
        )
        for i in range(per_page):
            (tmp_path / f"{n}{i}.png").write_bytes(PNG + f"{n}{i}".encode())


def accurate(request):
    """Every image 'matches': no findings, so exit codes show only partiality."""
    n = sum(isinstance(p, MediaPart) for p in request.parts)
    items = [
        {
            "index": i,
            "visible_content": "x",
            "matches_current_alt": "yes",
            "classification": "informative",
            "suggested_alt": "x",
            "confidence": "high",
            "uncertain_details": [],
        }
        for i in range(n)
    ]
    return json.dumps({"results": items})


STUB = {"stub": lambda html: []}


def go(tmp_path, provider, scanners=None, **kw):
    flags = kw.pop("flags", {})
    return run_scan(
        tmp_path,
        settings(tmp_path, **flags),
        scanners=scanners or STUB,
        provider=provider,
        **kw,
    )


def images_sent(provider):
    return [
        p.data for r in provider.requests for p in r.parts if isinstance(p, MediaPart)
    ]


def marker(tmp_path):
    return tmp_path / ".bondy" / "cache" / "resume.json"


def test_daily_quota_midway_then_resume_repeats_nothing(tmp_path):
    pages(tmp_path)  # 3 pages x 2 images, batch of 2 -> 3 requests
    quota = FakeProvider(
        [accurate, Exception(RATE_LIMIT_DAY), Exception(RATE_LIMIT_DAY)],
        responder=accurate,
    )
    first = go(tmp_path, quota)
    assert first.partial and "daily API quota" in first.usage.partial_reasons[0]
    assert quota.http_requests == 3  # 1 ok + primary and fallback models refused
    assert marker(tmp_path).exists()
    assert exit_code(first, "critical") == EXIT_PARTIAL

    healthy = FakeProvider(responder=accurate)
    second = go(tmp_path, healthy, resume=True)
    assert second.usage.resumed and not second.partial
    assert second.usage.pages_reused == 1  # page a finished in the first run
    assert healthy.http_requests == 2  # only b and c
    # nothing asked twice: images of the two runs are disjoint
    done_first = set(images_sent(quota)[:2])
    assert done_first.isdisjoint(images_sent(healthy))
    assert not marker(tmp_path).exists()  # a complete scan clears the marker
    assert exit_code(second, "critical") == 0


def test_resume_inside_one_page_uses_cached_verdicts(tmp_path):
    pages(tmp_path, names="a", per_page=6)  # 3 batches in a single page
    quota = FakeProvider(
        [accurate, Exception(RATE_LIMIT_DAY), Exception(RATE_LIMIT_DAY)],
        responder=accurate,
    )
    first = go(tmp_path, quota)
    assert first.partial and first.usage.cache_writes == 2
    healthy = FakeProvider(responder=accurate)
    second = go(tmp_path, healthy, resume=True)
    assert second.usage.cache_hits == 2 and healthy.http_requests == 2
    assert not second.partial


def test_ctrl_c_in_the_semantic_stage_returns_partial_and_resumes(tmp_path):
    pages(tmp_path)

    def ctrl_c(request):
        raise KeyboardInterrupt

    interrupted = FakeProvider([accurate, ctrl_c], responder=accurate)
    report = go(tmp_path, interrupted)  # must not raise
    assert report.partial
    assert any("Ctrl+C" in r for r in report.usage.partial_reasons)
    assert exit_code(report, "critical") == EXIT_PARTIAL
    assert marker(tmp_path).exists()
    # the batch in flight was dropped whole: its images are not cached
    assert report.usage.cache_writes == 2

    healthy = FakeProvider(responder=accurate)
    second = go(tmp_path, healthy, resume=True)
    assert healthy.http_requests == 2 and not second.partial
    assert second.usage.pages_reused == 1


def test_ctrl_c_during_scanners_keeps_finished_pages(tmp_path):
    pages(tmp_path)
    calls = []

    def scanner(html):
        calls.append(html)
        if len(calls) == 2:
            raise KeyboardInterrupt
        return []

    provider = FakeProvider(responder=accurate)
    report = go(tmp_path, provider, scanners={"s": scanner})
    states = [r.skipped for r in report.files]
    assert states == [None, INTERRUPTED_SKIP, INTERRUPTED_SKIP]
    assert report.partial and marker(tmp_path).exists()

    healthy = FakeProvider(responder=accurate)
    second = go(tmp_path, healthy, scanners={"s": lambda h: []}, resume=True)
    assert second.usage.pages_reused == 1 and second.usage.pages_scanned == 2
    assert healthy.http_requests == 0  # verdicts came from the cache
    assert not second.partial


def test_cli_ctrl_c_exits_3_and_writes_marker(tmp_path, monkeypatch, capsys):
    from bondy import scan as scan_mod
    from bondy.core.providers.gemini import GeminiProvider

    pages(tmp_path)

    def ctrl_c(request):
        raise KeyboardInterrupt

    fake = FakeProvider([accurate, ctrl_c], responder=accurate)
    for name in list(scan_mod.SCANNERS):
        monkeypatch.setitem(scan_mod.SCANNERS, name, lambda h: [])
    monkeypatch.setattr(
        GeminiProvider, "from_settings", classmethod(lambda cls, s, **kw: fake)
    )
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.chdir(tmp_path)
    code = cli.main(["scan", str(tmp_path), "--batch-size", "2"])
    out = capsys.readouterr().out
    assert code == 3 and "PARTIAL RESULT" in out and "Ctrl+C" in out
    assert marker(tmp_path).exists()


def test_resume_after_the_project_changed_in_between(tmp_path):
    pages(tmp_path)
    quota = FakeProvider(
        [accurate, Exception(RATE_LIMIT_DAY), Exception(RATE_LIMIT_DAY)],
        responder=accurate,
    )
    go(tmp_path, quota)
    # a (finished) is edited; d is new; b's image is replaced
    pages(tmp_path, names="a", text="edited after the interruption")
    pages(tmp_path, names="d")
    (tmp_path / "b0.png").write_bytes(PNG + b"new b0")
    healthy = FakeProvider(responder=accurate)
    report = go(tmp_path, healthy, resume=True)
    assert report.usage.pages_reused == 0  # stale a is NOT trusted
    assert report.usage.pages_scanned == 4
    # a's images were cached from run 1 (their bytes/alt/context are unchanged)
    # except where the surrounding context changed; everything gets verified
    assert not report.partial and len(report.images) == 8
    assert all(o.recommendation == "keep" for o in report.images)


def test_resume_without_marker_is_a_normal_scan(tmp_path):
    pages(tmp_path, names="a")
    report = go(tmp_path, FakeProvider(responder=accurate), resume=True)
    assert any("no interrupted scan" in n for n in report.notes)
    assert not report.usage.resumed and report.usage.pages_scanned == 1


def test_resume_discards_state_when_config_changed(tmp_path):
    pages(tmp_path)
    quota = FakeProvider(
        [accurate, Exception(RATE_LIMIT_DAY), Exception(RATE_LIMIT_DAY)],
        responder=accurate,
    )
    go(tmp_path, quota)
    report = go(
        tmp_path,
        FakeProvider(responder=accurate),
        resume=True,
        flags={"vision_model": "another-model"},
    )
    assert any("changed since the interrupted scan" in n for n in report.notes)
    assert report.usage.pages_reused == 0


def test_max_requests_partial_also_resumes(tmp_path):
    pages(tmp_path)
    first = go(tmp_path, FakeProvider(responder=accurate), flags={"max_requests": 1})
    assert first.partial and any(
        "--max-requests" in r for r in first.usage.partial_reasons
    )
    healthy = FakeProvider(responder=accurate)
    second = go(tmp_path, healthy, resume=True, flags={"max_requests": 5})
    assert healthy.http_requests == 2 and not second.partial


def test_scan_timeout_marks_partial_and_is_resumable(tmp_path):
    import time

    pages(tmp_path, per_page=0)

    def slow(html):
        time.sleep(0.06)
        return []

    report = go(
        tmp_path,
        FakeProvider(responder=accurate),
        scanners={"slow": slow},
        flags={"scan_timeout": 0.05},
    )
    assert report.partial
    assert any("--scan-timeout" in r for r in report.usage.partial_reasons)
    assert exit_code(report, "critical") == EXIT_PARTIAL
    assert marker(tmp_path).exists()
