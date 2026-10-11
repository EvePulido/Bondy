"""B4: persistent verdict cache. FakeProvider only: no network, no API quota."""

import json
import threading

import pytest

from bondy import cli, config
from bondy.core import semantic
from bondy.core.pipeline import run_scan
from bondy.core.providers.fake import FakeProvider
from bondy.core.store import Store, resolve_cache_dir

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32
STUB = {"stub": lambda html: []}
SENTINEL = "SENTINEL-KEY-4c1f"


def settings(tmp_path, **flags):
    flags.setdefault("api_key", "test-key")
    return config.load_settings(flags=flags, env={}, start_dir=tmp_path)


def project(tmp_path, n=3, alt="alt"):
    body = "".join(f'<img src="i{i}.png" alt="{alt} {i}">' for i in range(n))
    (tmp_path / "index.html").write_text(
        f'<html lang="en"><body>{body}</body></html>', encoding="utf-8"
    )
    for i in range(n):
        (tmp_path / f"i{i}.png").write_bytes(PNG + bytes([i]))
    return tmp_path


def scan(tmp_path, provider=None, **kw):
    flags = kw.pop("flags", {})
    p = provider if provider is not None else FakeProvider()
    r = run_scan(tmp_path, settings(tmp_path, **flags), scanners=STUB, provider=p, **kw)
    return r, p


def cache_dir(tmp_path):
    return tmp_path / ".bondy" / "cache"


def test_second_identical_scan_makes_zero_requests(tmp_path):
    project(tmp_path)
    first, p1 = scan(tmp_path)
    assert p1.http_requests == 1 and first.usage.cache_misses == 3
    assert first.usage.cache_writes == 3 and first.usage.cache_hits == 0
    second, p2 = scan(tmp_path)
    assert p2.http_requests == 0 and second.usage.requests == 0
    assert second.usage.cache_hits == 3 and second.usage.cache_misses == 0
    # same decisions from cached verdicts
    assert [(o.recommendation, o.suggested_alt) for o in second.images] == [
        (o.recommendation, o.suggested_alt) for o in first.images
    ]


def test_cache_lives_under_the_project_not_elsewhere(tmp_path):
    project(tmp_path)
    scan(tmp_path)
    assert list((cache_dir(tmp_path) / "verdicts").glob("*.json"))
    assert resolve_cache_dir("", tmp_path) == cache_dir(tmp_path)
    assert resolve_cache_dir("custom", tmp_path) == tmp_path / "custom"


def test_entries_hold_no_key_and_no_absolute_paths(tmp_path):
    project(tmp_path)
    scan(tmp_path, flags={"api_key": SENTINEL})
    text = " ".join(
        p.read_text(encoding="utf-8") for p in cache_dir(tmp_path).rglob("*.json")
    )
    assert text and SENTINEL not in text
    assert str(tmp_path) not in text and str(tmp_path).replace("\\", "/") not in text


@pytest.mark.parametrize(
    "change",
    ["model", "prompt", "alt", "image", "context"],
)
def test_key_invalidates_on_every_ingredient(tmp_path, monkeypatch, change):
    project(tmp_path, n=1)
    scan(tmp_path)
    flags = {}
    if change == "model":
        flags["vision_model"] = "another-model"
    elif change == "prompt":
        monkeypatch.setattr(semantic, "PROMPT_FINGERPRINT", "different-prompt")
    elif change == "alt":
        project(tmp_path, n=1, alt="other alt")
    elif change == "image":
        (tmp_path / "i0.png").write_bytes(PNG + b"changed")
    elif change == "context":
        html = (tmp_path / "index.html").read_text(encoding="utf-8")
        (tmp_path / "index.html").write_text(
            html.replace("<body>", "<body><p>new surrounding text</p>"),
            encoding="utf-8",
        )
    r, p = scan(tmp_path, flags=flags)
    assert p.http_requests == 1 and r.usage.cache_hits == 0


def test_schema_change_invalidates_through_the_fingerprint():
    assert len(semantic.PROMPT_FINGERPRINT) == 16
    # fingerprint covers prompt text + schema: both are part of the hash input
    import inspect

    src = inspect.getsource(semantic)
    assert "BATCH_RULES" in src and "model_json_schema" in src


def test_corrupt_entry_is_a_miss_not_a_crash(tmp_path):
    project(tmp_path, n=2)
    scan(tmp_path)
    files = sorted((cache_dir(tmp_path) / "verdicts").glob("*.json"))
    files[0].write_text("{ this is not json", encoding="utf-8")
    files[1].write_text(json.dumps({"schema": 1, "analysis": {"bad": 1}}))
    r, p = scan(tmp_path)
    assert p.http_requests == 1  # both entries re-requested, in one batch
    assert r.usage.cache_hits == 0
    # healed: the entries are valid again
    r3, p3 = scan(tmp_path)
    assert p3.http_requests == 0 and r3.usage.cache_hits == 2


def test_truncated_and_empty_entries_are_misses(tmp_path):
    project(tmp_path, n=1)
    scan(tmp_path)
    (entry,) = (cache_dir(tmp_path) / "verdicts").glob("*.json")
    entry.write_bytes(b"")
    assert scan(tmp_path)[1].http_requests == 1


def test_unwritable_cache_degrades_to_no_cache(tmp_path, monkeypatch):
    project(tmp_path)

    def denied(*a, **k):
        raise PermissionError("read-only directory")

    monkeypatch.setattr("bondy.core.store.tempfile.mkstemp", denied)
    r, p = scan(tmp_path)
    assert p.http_requests == 1 and r.usage.cache_writes == 0
    assert any("not writable" in n for n in r.notes)
    assert all(o.recommendation == "fix" for o in r.images)  # scan unaffected


def test_unwritable_cache_dir_path_is_a_file(tmp_path):
    project(tmp_path)
    (tmp_path / ".bondy").write_text("i am a file, not a directory")
    r, p = scan(tmp_path)
    assert p.http_requests == 1 and any("not writable" in n for n in r.notes)


def test_no_cache_touches_nothing_and_always_requests(tmp_path):
    project(tmp_path)
    _, p1 = scan(tmp_path, flags={"cache": False})
    _, p2 = scan(tmp_path, flags={"cache": False})
    assert p1.http_requests == 1 and p2.http_requests == 1
    assert not (tmp_path / ".bondy").exists()


def test_clear_cache_flag_forces_new_requests(tmp_path):
    project(tmp_path)
    scan(tmp_path)
    r, p = scan(tmp_path, clear_cache=True)
    assert p.http_requests == 1 and r.usage.cache_hits == 0


def test_cache_clear_command_only_removes_bondy_files(tmp_path, capsys):
    project(tmp_path)
    scan(tmp_path)
    mine = cache_dir(tmp_path) / "do-not-delete.txt"
    mine.write_text("user file")
    assert cli.main(["cache", "clear", str(tmp_path)]) == 0
    assert "Removed" in capsys.readouterr().out
    assert mine.exists()
    assert not list((cache_dir(tmp_path) / "verdicts").glob("*.json"))
    assert not (cache_dir(tmp_path) / "pages.json").exists()


def test_cache_clear_keep_state(tmp_path):
    project(tmp_path)
    scan(tmp_path)
    assert (cache_dir(tmp_path) / "pages.json").exists()
    cli.main(["cache", "clear", str(tmp_path), "--keep-state"])
    assert (cache_dir(tmp_path) / "pages.json").exists()
    assert not (cache_dir(tmp_path) / "verdicts").exists()


def test_cache_settings_precedence(tmp_path):
    (tmp_path / "bondy.toml").write_text('cache = false\ncache_dir = "from-file"\n')
    s = config.load_settings(flags={}, env={}, start_dir=tmp_path)
    assert s.cache is False and s.cache_dir == "from-file"
    e = config.load_settings(
        flags={},
        env={"BONDY_CACHE": "1", "BONDY_CACHE_DIR": "from-env"},
        start_dir=tmp_path,
    )
    assert e.cache is True and e.cache_dir == "from-env"
    f = config.load_settings(
        flags={"cache": False, "cache_dir": "from-flag"},
        env={"BONDY_CACHE": "1"},
        start_dir=tmp_path,
    )
    assert f.cache is False and f.cache_dir == "from-flag"
    assert f.sources["cache"] == "flag"


def test_custom_cache_dir_is_used(tmp_path):
    project(tmp_path)
    scan(tmp_path, flags={"cache_dir": "elsewhere"})
    assert list((tmp_path / "elsewhere" / "verdicts").glob("*.json"))
    assert not (tmp_path / ".bondy").exists()


def test_two_concurrent_scans_share_the_cache_safely(tmp_path):
    project(tmp_path, n=6)
    errors: list[BaseException] = []
    results: list = []

    def worker():
        try:
            results.append(scan(tmp_path, flags={"batch_size": 2}))
        except BaseException as e:
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors and len(results) == 2
    # every file on disk is valid JSON and no temp files are left behind
    for p in cache_dir(tmp_path).rglob("*"):
        if p.is_file():
            json.loads(p.read_text(encoding="utf-8"))
            assert not p.name.startswith(".tmp-")
    _, p3 = scan(tmp_path, flags={"batch_size": 2})
    assert p3.http_requests == 0


def test_store_get_verdict_rejects_wrong_schema_version(tmp_path):
    s = Store(tmp_path)
    (tmp_path / "verdicts").mkdir()
    (tmp_path / "verdicts" / "k.json").write_text(
        json.dumps({"schema": 999, "analysis": {}})
    )
    assert s.get_verdict("k") is None


def test_usage_summary_shows_cache_hits_and_misses(tmp_path, monkeypatch, capsys):
    from bondy import scan as scan_mod
    from bondy.core.providers.gemini import GeminiProvider

    project(tmp_path, n=2)
    for name in list(scan_mod.SCANNERS):
        monkeypatch.setitem(scan_mod.SCANNERS, name, lambda h: [])
    fake = FakeProvider()
    monkeypatch.setattr(
        GeminiProvider, "from_settings", classmethod(lambda cls, s, **kw: fake)
    )
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.chdir(tmp_path)
    cli.main(["scan", str(tmp_path)])
    first = capsys.readouterr().out
    assert "cache: 0 hit(s), 2 miss(es), 2 saved" in first
    cli.main(["scan", str(tmp_path)])
    second = capsys.readouterr().out
    assert "cache: 2 hit(s), 0 miss(es)" in second and "requests: 0" in second
    cli.main(["scan", str(tmp_path), "--no-cache"])
    assert "cache: disabled" in capsys.readouterr().out
