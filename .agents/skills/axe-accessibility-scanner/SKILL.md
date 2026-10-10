---
name: axe-accessibility-scanner
description: |
  Runs the axe-core engine and Chromium's accessibility tree inside a headless Playwright browser against a full HTML document, returning a deterministic list of WCAG 2.0/2.1/2.2 A/AA violations (names, labels, roles, ARIA, landmarks, headings, tables, language, contrast, target size, etc.). Use this skill FIRST as the deterministic baseline of any accessibility audit, then complement it with the specialized skills and visual verification.
---

## Instructions

1. Receives the full HTML document via stdin.
2. Executes `scripts/axe_scan.py`, which renders the page offline in Chromium (all non-local network requests are aborted), injects the bundled `axe.min.js` (axe-core 4.10.2, MPL-2.0) and runs the `wcag2a`, `wcag2aa`, `wcag21a`, `wcag21aa`, `wcag22aa` and `best-practice` rule sets.
3. Reads the Chromium accessibility tree and lists interactive elements (button, link, textbox, ...) whose computed accessible name is empty.
4. Returns JSON: `{ "engine": string, "summary": {violations, passes, needs_review, inapplicable}, "violations": [{rule_id, wcag: [string], severity, impact, help, total_nodes, nodes: [{selector, html, failure}]}], "needs_review": list, "unnamed_interactive_elements": [{role, html, problem}], "note": string }`.

## Notes for the agent

- `summary.passes` and `summary.violations` are real counts: use them instead of estimating.
- `html` snippets are serialized by the browser; always copy the `before` string from the ORIGINAL source, never from this report.
- axe cannot judge whether alt text is *meaningful* or whether an image is decorative; keep using visual verification for WCAG 1.1.1.
- `needs_review` items are not failures: mention them only if relevant.

## When NOT to activate this skill

- When only a URL is available and no HTML content can be provided.
- To check keyboard traps or tab order: use `focus-trap-detector` and `focus-order-validator`.
