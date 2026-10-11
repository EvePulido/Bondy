"""E3: CI integration files. Nothing is executed in the cloud."""

import json
import re
import shlex
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


def test_action_skips_sarif_upload_for_read_only_tokens():
    """Fork/Dependabot PRs cannot write code scanning: skip, keep an artifact."""
    steps = load("action.yml")["runs"]["steps"]
    (upload,) = [
        s for s in steps if "github/codeql-action/upload-sarif@" in s.get("uses", "")
    ]
    assert upload["continue-on-error"] is True
    cond = upload["if"]
    assert "github.event.pull_request.head.repo.full_name == github.repository" in cond
    assert "dependabot[bot]" in cond and "github.event_name != 'pull_request'" in cond
    (artifact,) = [s for s in steps if "actions/upload-artifact@" in s.get("uses", "")]
    assert "head.repo.full_name != github.repository" in artifact["if"]
    # the exit code is still propagated after the (possibly skipped) upload
    assert steps[-1]["name"].startswith("Fail if Bondy reported")


def test_ci_type_checks_bondy_and_tests():
    runs = [
        s.get("run", "")
        for job in load(".github/workflows/ci.yml")["jobs"].values()
        for s in job["steps"]
    ]
    assert "uv run ty check bondy tests" in runs


def test_action_never_interpolates_inputs_into_shell_code():
    text = (ROOT / "action.yml").read_text(encoding="utf-8")
    for block in re.findall(r"run: \|\n((?:[ ]{8}.*\n?)+)", text):
        assert "${{" not in block, block


def test_action_records_the_exit_code_under_bash_e():
    """GitHub runs `bash -e`: the scan step must survive a non-zero exit."""
    text = (ROOT / "action.yml").read_text(encoding="utf-8")
    assert 'bondy "${args[@]}" || code=$?' in text
    assert not re.search(r'^\s*bondy "\$\{args\[@\]\}"\s*$', text, re.M)


def test_example_workflow_is_not_active():
    assert (ROOT / "docs" / "ci-example.yml").is_file()
    workflows = ROOT / ".github" / "workflows"
    for f in workflows.glob("*") if workflows.is_dir() else []:
        assert "Bondy accessibility scan" not in f.read_text(encoding="utf-8")


def test_precommit_hook_scans_exactly_the_files_pre_commit_passes(
    tmp_path, monkeypatch, capsys
):
    (hook,) = load(".pre-commit-hooks.yaml")
    assert hook["pass_filenames"] is True and hook["types"] == ["html"]
    argv = shlex.split(hook["entry"])
    assert argv[:2] == ["bondy", "scan"] and "--no-llm" in argv
    assert "--no-cache" in argv and "." not in argv

    page = '<html lang="en"><body><p>x</p></body></html>'
    (tmp_path / "sub").mkdir()
    for rel in ("staged.html", "sub/other.html", "untouched.html"):
        (tmp_path / rel).write_text(page + f"<!-- {rel} -->", encoding="utf-8")

    seen = []
    for name in SCANNERS:
        monkeypatch.setitem(SCANNERS, name, lambda html: seen.append(html) or [])
    monkeypatch.chdir(tmp_path)
    # what pre-commit does: the hook's entry + args + the staged file names
    staged = ["staged.html", str(Path("sub") / "other.html")]
    code = cli.main([*argv[1:], "--format", "json", *staged])
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and not (tmp_path / ".bondy").exists()
    assert sorted(f["path"] for f in out["files"]) == ["staged.html", "sub/other.html"]
    assert len(set(seen)) == 2  # untouched.html was not scanned
