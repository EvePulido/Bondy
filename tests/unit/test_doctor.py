from bondy import doctor


def test_python_range():
    assert doctor.check_python((3, 12)).status == "ok"
    bad = doctor.check_python((3, 9))
    assert bad.status == "fail" and bad.fix


def test_api_key_is_never_printed():
    c = doctor.check_api_key({"GEMINI_API_KEY": "super-secret-value"})
    assert c.status == "ok" and "super-secret-value" not in c.detail
    missing = doctor.check_api_key({})
    assert missing.status == "warn" and "GEMINI_API_KEY" in (missing.fix or "")


def test_axe_and_write_access(tmp_path):
    assert doctor.check_axe().status == "ok"
    assert doctor.check_write_access(tmp_path).status == "ok"
    assert doctor.check_write_access(tmp_path / "nope").status == "fail"


def test_run_checks_returns_every_check_with_fix_on_problems():
    checks = doctor.run_checks()
    assert {c.name for c in checks} >= {"python", "browser", "api-key", "config"}
    assert all(c.fix for c in checks if c.status == "fail")
