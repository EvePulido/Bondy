import shutil
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bondy.fast_api_app import _annotate_before_matches, app

DEMO = Path(__file__).parents[2] / "demo_sites"


@pytest.fixture
def site():
    name = f"_test_{uuid.uuid4().hex[:8]}"
    folder = DEMO / name
    folder.mkdir()
    (folder / "index.html").write_text(
        '<html><body><img src="a.png"><p>x</p><img src="b.png"><img src="b.png">'
        "</body></html>",
        encoding="utf-8",
    )
    yield f"demo_sites/{name}", folder / "index.html"
    shutil.rmtree(folder, ignore_errors=True)


@pytest.fixture
def local_client():
    return TestClient(app, client=("127.0.0.1", 50000))


def test_annotate_counts_occurrences(site):
    source, _ = site
    fixes = [
        {"before": '<img src="a.png">'},
        {"before": '<img src="b.png">'},
        {"before": "<missing>"},
    ]
    _annotate_before_matches(fixes, source)
    assert [f["before_occurrences"] for f in fixes] == [1, 2, 0]


def test_apply_unique_fix(site, local_client):
    source, path = site
    r = local_client.post(
        "/api/apply-fix",
        json={
            "file_path": source,
            "before": '<img src="a.png">',
            "after": '<img src="a.png" alt="A">',
        },
    )
    assert r.status_code == 200
    assert 'alt="A"' in path.read_text(encoding="utf-8")


def test_ambiguous_fix_is_rejected(site, local_client):
    source, path = site
    original = path.read_text(encoding="utf-8")
    r = local_client.post(
        "/api/apply-fix",
        json={"file_path": source, "before": '<img src="b.png">', "after": "<b>"},
    )
    assert r.status_code == 409
    assert path.read_text(encoding="utf-8") == original


def test_remote_client_is_rejected(site):
    source, _ = site
    r = TestClient(app).post(
        "/api/apply-fix",
        json={"file_path": source, "before": "x", "after": "y"},
    )
    assert r.status_code == 403
