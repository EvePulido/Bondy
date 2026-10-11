"""Gemini-vision tools for the Bondy agent.

- analyze_rendered_page: looks at a screenshot of the rendered page.
- classify_image_decorative: deterministic heuristics + vision verdict for one image.
"""

import json
import mimetypes
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from bondy.core.alt_rules import (  # noqa: F401 - re-exported for agent mode
    ALT_SYSTEM_RULES,
    FILENAME_ALT,
    GENERIC_ALT,
    REDUNDANT_PREFIX,
    AltVerdict,
    alt_text_static_checks,
    decide_alt_recommendation,
    decorative_heuristics,
    quota_retry_delay,
)

BASE_DIR = Path(__file__).resolve().parents[2]
MAX_IMAGE_BYTES = 10 * 1024 * 1024


# ----- Shared helpers -----
def _models() -> tuple[str, str]:
    """``(vision_model, fallback_model)`` from Settings, resolved at call time.

    Precedence flag > ``BONDY_VISION_MODEL``/``BONDY_FALLBACK_MODEL`` >
    ``bondy.toml`` > default; an empty fallback disables it.
    """
    from bondy.config import load_settings_lenient

    s = load_settings_lenient()
    return s.vision_model, s.fallback_model


def _client_kwargs() -> dict:
    """Explicit API key from Settings (flag/env/toml precedence) for AI Studio.

    With ``GOOGLE_GENAI_USE_VERTEXAI`` set (Vertex AI, no key) or no key at all
    the SDK keeps resolving credentials from the environment, as before.
    """
    from bondy.config import load_settings_lenient, use_vertexai

    if use_vertexai():
        return {}
    key = load_settings_lenient().api_key
    return {"vertexai": False, "api_key": key} if key else {}


def _generate(contents: list, json_output: bool = False, schema=None) -> str:
    """Calls Gemini with the primary vision model, then the fallback if it is busy.

    Runs at temperature 0 for reproducible audits. When a pydantic `schema` is
    given the response is constrained to it (structured output).
    """
    from google.genai import Client, types

    client = Client(**_client_kwargs())
    config = types.GenerateContentConfig(
        temperature=0,
        response_mime_type="application/json" if (json_output or schema) else None,
        response_schema=schema,
    )
    last_error: Exception | None = None
    for model in [m for m in _models() if m]:
        for attempt in range(2):
            try:
                res = client.models.generate_content(
                    model=model, contents=contents, config=config
                )
                return res.text or ""
            except Exception as e:  # 503 / quota / model unavailable
                last_error = e
                delay = quota_retry_delay(e)
                if delay is None or attempt == 1:
                    break  # not a quota error, or already retried: next model
                time.sleep(delay)  # wait out the per-minute quota, retry same model
    raise RuntimeError(f"All vision models failed: {last_error}")


def _load_image(url: str) -> tuple[bytes, str]:
    """Loads an image from a public URL or from the local examples folder."""
    if url.startswith(("http://", "https://")):
        from bondy.core.netguard import fetch_public_bytes

        res = fetch_public_bytes(url, MAX_IMAGE_BYTES, 10)
        mime = res.content_type
        return res.data, mime if mime.startswith("image/") else "image/jpeg"

    demo_dir = (BASE_DIR / "examples").resolve()
    suffix = url.replace("/", os.sep).lstrip(os.sep)
    for root, _, files in os.walk(demo_dir):
        for name in files:
            full = Path(root) / name
            if str(full).endswith(suffix):
                mime, _ = mimetypes.guess_type(str(full))
                return full.read_bytes(), mime or "image/jpeg"
    raise FileNotFoundError(f"Local image not found for '{url}'")


def verify_image_alt_text(url: str, current_alt: str, context_html: str = "") -> str:
    """Verifies with Gemini Vision that the alt text matches the real image (WCAG 1.1.1).

    MUST be used for every <img>. Combines deterministic checks on the alt string
    with a grounded visual comparison.

    Args:
        url: The image URL (https://...) or the local src path from the HTML.
        current_alt: The existing alt text found in the HTML ('' if empty/missing).
        context_html: Optional surrounding HTML (a few lines) for context.

    Returns:
        JSON string with: static_problems, visible_content, matches_current_alt,
        suggested_alt, confidence, uncertain_details, recommendation
        ("keep" | "fix" | "needs_manual_review").
    """
    from google.genai import types

    static = alt_text_static_checks(current_alt)

    try:
        data, mime = _load_image(url)
    except Exception as e:
        return json.dumps(
            {
                "static_problems": static,
                "error": f"Could not load image '{url}': {e}",
                "recommendation": "needs_manual_review",
            }
        )

    prompt = (
        f"{ALT_SYSTEM_RULES}\n"
        f"<current_alt>{current_alt or ''}</current_alt>\n"
        f"<html_context>{context_html[:1500]}</html_context>\n"
        "Respond with the JSON object only."
    )
    try:
        raw = _generate(
            [types.Part.from_bytes(data=data, mime_type=mime), prompt],
            schema=AltVerdict,
        )
        verdict = AltVerdict.model_validate_json(raw)
    except Exception as e:
        return json.dumps(
            {
                "static_problems": static,
                "error": f"Vision analysis failed: {e}",
                "recommendation": "needs_manual_review",
            }
        )

    return json.dumps(
        {
            "static_problems": static,
            "visible_content": verdict.visible_content,
            "matches_current_alt": verdict.matches_current_alt,
            "suggested_alt": verdict.suggested_alt,
            "confidence": verdict.confidence,
            "uncertain_details": verdict.uncertain_details,
            "recommendation": decide_alt_recommendation(static, verdict),
        }
    )


# ----- Tools exposed to the agent -----
def classify_image_decorative(url: str, img_html: str, context_html: str = "") -> str:
    """Decides if an image is decorative, informative or functional (WCAG 1.1.1).

    Combines deterministic heuristics with a Gemini Vision verdict.

    Args:
        url: The image URL or local path (the src attribute).
        img_html: The exact <img ...> tag from the HTML source.
        context_html: The surrounding HTML (parent element, a few lines) so the
            tool can see links/buttons and adjacent text.

    Returns:
        JSON string: {"classification": "decorative|informative|functional",
        "expected_alt": "empty string for decorative, else guidance",
        "signals": [...], "reason": str}
    """
    heur = decorative_heuristics(img_html, context_html)

    try:
        from google.genai import types

        data, mime = _load_image(url)
        prompt = (
            "Classify this image for web accessibility (WCAG 1.1.1).\n"
            f"HTML tag: {img_html}\nSurrounding HTML: {context_html[:1500]}\n"
            f"Deterministic signals: {heur['signals']}\n\n"
            'Answer ONLY JSON: {"classification": "decorative"|"informative"|'
            '"functional", "reason": "<one sentence>"}\n'
            "decorative = adds no information (ornament, spacer, redundant with "
            "adjacent text) -> alt must be empty.\n"
            "informative = conveys content -> needs a meaningful alt.\n"
            "functional = it is the only content of a link/button -> alt must "
            "describe the action/destination."
        )
        raw = _generate(
            [types.Part.from_bytes(data=data, mime_type=mime), prompt],
            json_output=True,
        )
        parsed = json.loads(raw)
        classification = parsed.get("classification", "informative")
        reason = parsed.get("reason", "")
    except Exception as e:
        # Vision unavailable: fall back to heuristics only
        classification = heur["verdict"] or "informative"
        reason = f"Vision unavailable ({e}); based on heuristics only."

    # A deterministic 'functional' result always wins: the control needs a name
    if heur["verdict"] == "functional":
        classification = "functional"

    expected = {
        "decorative": 'alt="" (empty)',
        "informative": "meaningful description of the content",
        "functional": "describe the action or destination, not the image",
    }.get(classification, "meaningful description")
    return json.dumps(
        {
            "classification": classification,
            "expected_alt": expected,
            "signals": heur["signals"],
            "reason": reason,
        }
    )


def analyze_rendered_page(source: str = "", html: str = "") -> str:
    """Looks at a screenshot of the rendered page with Gemini Vision.

    Use it to judge what code alone cannot show: text embedded in images, icons
    with no visible label, visually hidden or overlapping content, reading order
    that differs from the DOM, low-contrast areas, and whether images are
    decorative in their visual context.

    Args:
        source: Demo site folder, e.g. 'examples/site_1_bad_alt' (preferred, so
            relative CSS/images load). Leave empty when passing raw html.
        html: Full HTML document, used only when source is empty.

    Returns:
        A text description of visual accessibility problems found.
    """
    if not source and not html.strip():
        return "Error: provide either source or html."

    out_png = None
    try:
        from google.genai import types

        fd, out_png = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        cmd = [sys.executable, "-m", "bondy.app_utils.render_page", "--out", out_png]
        if source:
            cmd += ["--source", source]
        proc = subprocess.run(
            cmd,
            input=None if source else html,
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(BASE_DIR),
        )
        if proc.returncode != 0:
            return f"Error rendering page: {proc.stderr.strip()[-500:]}"

        image = Path(out_png).read_bytes()
        prompt = (
            "You are a web accessibility auditor looking at a screenshot of a page. "
            "List ONLY concrete visual accessibility problems you can SEE, each with "
            "the WCAG criterion: text that is hard to read against its background "
            "(1.4.3), text rendered inside images (1.4.5), icons or controls with no "
            "visible label (1.1.1/2.4.4), elements that look interactive but seem to "
            "have no text, overlapping or cut-off content (1.4.10), purely ornamental "
            "images, and information conveyed only by color (1.4.1). "
            "Mention where each problem is (heading/section/visible text). "
            "If you see no problems, say so. Do not invent issues."
        )
        text = _generate(
            [types.Part.from_bytes(data=image, mime_type="image/png"), prompt]
        )
        return f"Visual analysis: {text}"
    except Exception as e:
        return f"Error analyzing rendered page: {e}"
    finally:
        if out_png:
            try:
                os.remove(out_png)
            except OSError:
                pass
