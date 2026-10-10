"""E3: CI integration files. Nothing is executed in the cloud."""

import re
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

from bondy import cli
from bondy.scan import SCANNERS

ROOT = Path(__file__).resolve().parents[2]
yaml = pytest.importorskip("yaml")


def load(name):
    return yaml.safe_load((ROOT / name).read_text(encoding="utf-8"))


def test_action_declares_the_documented_inputs_and_pins_third_party_actions():
    action = load("action.yml")
    assert action["runs"]["using"] == "composite"
    assert {
        "path", "fail-on", "format", "baseline", "changed-only", "since",
    } <= set(action["inputs"])  # fmt: skip
    uses = [s["uses"] for s in action["runs"]["steps"] if "uses" in s]
    assert any("github/codeql-action/upload-sarif@" in u for u in uses)
    for u in uses:  # third-party actions are pinned to a full commit SHA
        assert re.search(r"@[0-9a-f]{40}$", u.split()[0]), u


def test_action_never_interpolates_inputs_into_shell_code():
    text = (ROOT / "action.yml").read_text(encoding="utf-8")
    for block in re.findall(r"run: \|\n((?:[ ]{8}.*\n?)+)", text):
        assert "${{" not in block, block


def test_example_workflow_is_not_active():
    assert (ROOT / "docs" / "ci-example.yml").is_file()
    workflows = ROOT / ".github" / "workflows"
    for f in workflows.glob("*") if workflows.is_dir() else []:
        assert "Bondy accessibility scan" not in f.read_text(encoding="utf-8")


def test_precommit_hook_scans_only_changed_html(tmp_path, monkeypatch, capsys):
    (hook,) = load(".pre-commit-hooks.yaml")
    assert hook["pass_filenames"] is False and hook["types"] == ["html"]
    argv = shlex.split(hook["entry"])
    assert argv[0] == "bondy" and "--no-llm" in argv and "--since" in argv

    git = shutil.which("git")
    if not git:
        pytest.skip("git not available")

    def g(*a):
        subprocess.run(
            [git, "-c", "user.name=t", "-c", "user.email=t@t", *a],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )

    page = '<html lang="en"><body><p>x</p></body></html>'
    (tmp_path / "old.html").write_text(page, encoding="utf-8")
    (tmp_path / "edit.html").write_text(page, encoding="utf-8")
    g("init", "-q")
    g("add", ".")
    g("commit", "-q", "-m", "init")
    (tmp_path / "edit.html").write_text(page + "<!-- changed -->", encoding="utf-8")
    (tmp_path / "new.html").write_text(page, encoding="utf-8")

    seen = []
    for name in SCANNERS:
        monkeypatch.setitem(SCANNERS, name, lambda html: seen.append(html) or [])
    monkeypatch.chdir(tmp_path)
    code = cli.main([*argv[1:], "--format", "json"])
    out = capsys.readouterr().out
    assert code == 0 and not (tmp_path / ".bondy").exists()
    assert "unchanged since HEAD" in out  # old.html listed as skipped
    assert len(set(seen)) == 2  # edit.html and new.html were scanned
