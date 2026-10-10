"""Deterministic WCAG baseline: axe-core + Chromium accessibility tree.

Reads a full HTML document from stdin and prints a JSON report to stdout.
Only inline HTML is accepted (no URLs) and every non-local network request made by
the page is aborted, so the scan cannot be used for SSRF.
"""

import json
import sys
from pathlib import Path

try:
    from bondy.app_utils.browser import open_page, playwright_context
except ImportError:  # run as a standalone script: put the package root on sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parents[5]))
    from bondy.app_utils.browser import open_page, playwright_context

AXE_PATH = Path(__file__).parent / "axe.min.js"
AXE_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"]
MAX_NODES_PER_RULE = 5
SNIPPET_LEN = 300

# Roles that must expose an accessible name to assistive technologies
NAMED_ROLES = {
    "button",
    "link",
    "textbox",
    "searchbox",
    "combobox",
    "listbox",
    "checkbox",
    "radio",
    "switch",
    "slider",
    "spinbutton",
    "menuitem",
    "tab",
    "img",
}


def _wcag_criteria(tags: list[str]) -> list[str]:
    """Converts axe tags such as 'wcag143' into '1.4.3'."""
    out = []
    for tag in tags:
        if tag.startswith("wcag") and tag[4:].isdigit() and len(tag) >= 7:
            digits = tag[4:]
            out.append(".".join([digits[0], digits[1], digits[2:]]))
    return out


def _impact_to_severity(impact: str | None) -> str:
    return "critical" if impact in ("critical", "serious") else "warning"


def _unnamed_interactive_nodes(page) -> list[dict]:
    """Uses Chromium's full accessibility tree to find controls without a name."""
    cdp = page.context.new_cdp_session(page)
    cdp.send("DOM.enable")
    cdp.send("Accessibility.enable")
    nodes = cdp.send("Accessibility.getFullAXTree")["nodes"]

    issues = []
    for node in nodes:
        if node.get("ignored"):
            continue
        role = (node.get("role") or {}).get("value", "")
        if role not in NAMED_ROLES:
            continue
        name = ((node.get("name") or {}).get("value") or "").strip()
        if name:
            continue
        backend_id = node.get("backendDOMNodeId")
        if backend_id is None:
            continue
        try:
            html = cdp.send("DOM.getOuterHTML", {"backendNodeId": backend_id})[
                "outerHTML"
            ]
        except Exception:
            continue
        # <img alt=""> is a valid decorative image: it has the "presentation" role,
        # but be explicit in case Chromium reports it as img.
        if role == "img" and 'alt=""' in html:
            continue
        issues.append(
            {
                "role": role,
                "html": html[:SNIPPET_LEN],
                "problem": f"Element with role '{role}' has no accessible name",
            }
        )
    return issues


def scan(html: str) -> dict:
    axe_source = AXE_PATH.read_text(encoding="utf-8")

    with playwright_context() as p:
        # open_page aborts every request except the temp file, data: and about:
        with open_page(p, html=html) as page:
            page.add_script_tag(content=axe_source)

            raw = page.evaluate(
                "tags => axe.run(document, {runOnly: {type: 'tag', values: tags}})",
                AXE_TAGS,
            )
            unnamed = _unnamed_interactive_nodes(page)

    violations = []
    for rule in raw.get("violations", []):
        nodes = rule.get("nodes", [])
        violations.append(
            {
                "rule_id": rule["id"],
                "wcag": _wcag_criteria(rule.get("tags", [])),
                "severity": _impact_to_severity(rule.get("impact")),
                "impact": rule.get("impact"),
                "help": rule.get("help"),
                "total_nodes": len(nodes),
                "nodes": [
                    {
                        "selector": " ".join(str(s) for s in n.get("target", [])),
                        "html": (n.get("html") or "")[:SNIPPET_LEN],
                        "failure": (n.get("failureSummary") or "").strip(),
                    }
                    for n in nodes[:MAX_NODES_PER_RULE]
                ],
            }
        )

    return {
        "engine": f"axe-core {raw.get('testEngine', {}).get('version', '?')}",
        "summary": {
            "violations": len(violations),
            "passes": len(raw.get("passes", [])),
            "needs_review": len(raw.get("incomplete", [])),
            "inapplicable": len(raw.get("inapplicable", [])),
        },
        "violations": violations,
        "needs_review": [
            {"rule_id": r["id"], "help": r.get("help"), "nodes": len(r.get("nodes", []))}
            for r in raw.get("incomplete", [])
        ],
        "unnamed_interactive_elements": unnamed,
        "note": (
            "'html' values are serialized by the browser and may differ from the "
            "original source. Locate the element in the source before building a fix."
        ),
    }


if __name__ == "__main__":
    content = sys.stdin.read()
    if not content.strip():
        print(json.dumps({"error": "No input provided"}))
        sys.exit(1)
    print(json.dumps(scan(content), indent=2))
