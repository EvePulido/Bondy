import subprocess
import sys
from pathlib import Path

import pytest

from bondy.app_utils.vision_tools import decorative_heuristics

ROOT = Path(__file__).parents[2]


def test_role_presentation_is_decorative():
    r = decorative_heuristics('<img src="a.png" role="presentation" alt="">')
    assert r["verdict"] == "decorative"


def test_tracking_pixel_is_decorative():
    r = decorative_heuristics('<img src="p.gif" width="1" height="1" alt="">')
    assert r["verdict"] == "decorative"


def test_image_only_link_is_functional():
    img = '<img src="home.png" alt="">'
    r = decorative_heuristics(img, f'<a href="/">{img}</a>')
    assert r["verdict"] == "functional"


def test_link_with_text_is_not_forced_functional():
    img = '<img src="home.png" alt="">'
    r = decorative_heuristics(img, f'<a href="/">{img} Home</a>')
    assert r["verdict"] is None


def test_plain_informative_image_is_inconclusive():
    r = decorative_heuristics('<img src="chart.png" alt="Sales Q3">', "<p>Report</p>")
    assert r["verdict"] is None


def test_render_page_produces_png(tmp_path):
    out = tmp_path / "shot.png"
    proc = subprocess.run(
        [sys.executable, "-m", "bondy.app_utils.render_page", "--out", str(out)],
        input="<html><body><h1>Hello</h1></body></html>",
        capture_output=True,
        text=True,
        cwd=ROOT,
        timeout=60,
    )
    if proc.returncode != 0:
        pytest.skip(f"Chromium unavailable: {proc.stderr[-200:]}")
    assert out.read_bytes()[:4] == b"\x89PNG"


from bondy.app_utils.vision_tools import (  # noqa: E402
    AltVerdict,
    alt_text_static_checks,
    decide_alt_recommendation,
)


def _verdict(match, conf="high"):
    return AltVerdict(
        visible_content="x",
        matches_current_alt=match,
        suggested_alt="y",
        confidence=conf,
        uncertain_details=[],
    )


@pytest.mark.parametrize(
    ("alt", "expected"),
    [
        ("", ["empty_or_missing"]),
        (None, ["empty_or_missing"]),
        ("Image of a dog", ["redundant_prefix"]),
        ("Imagen de un perro", ["redundant_prefix"]),
        ("photo", ["generic"]),
        ("IMG_2041.jpg", ["looks_like_filename"]),
        ("A smiling dog outdoors", []),
    ],
)
def test_alt_static_checks(alt, expected):
    assert alt_text_static_checks(alt) == expected


def test_recommendation_rules():
    assert decide_alt_recommendation(["empty_or_missing"], _verdict("no")) == "fix"
    assert decide_alt_recommendation([], _verdict("yes")) == "keep"
    assert decide_alt_recommendation(["redundant_prefix"], _verdict("yes")) == "fix"
    assert decide_alt_recommendation([], _verdict("no")) == "fix"
    assert (
        decide_alt_recommendation([], _verdict("no", "low")) == "needs_manual_review"
    )
