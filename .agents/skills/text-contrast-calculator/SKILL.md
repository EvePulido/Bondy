---
name: text-contrast-calculator
description: |
  Calculates the color contrast ratio between text (foreground) and its background element for all visible text nodes in a DOM snapshot to verify legibility. Evaluates if they satisfy the WCAG 2 AA minimum ratio limits (4.5:1 for normal text, 3.0:1 for large text). Use this tool for checking color accessibility.
---

## Instructions

1. Receives the `dom_snapshot` serialized from Playwright.
2. For each visible text node, extracts the text color (`fg`) and the effective background color (`bg`), resolving transparencies if present.
3. Executes `scripts/contrast.py fg_hex bg_hex` to obtain the contrast ratio.
4. Determines the required threshold depending on the font size/weight.
5. Returns a list of `issues` according to the technical contract: `{ "issues": list }` where each issue contains: `{ "selector": string, "contrast_ratio": float, "passes_wcag": bool }`.

## When NOT to activate this skill

- If the node does not contain visible text (only icons, images, borders).
- If the text is hidden (`display:none`, `visibility:hidden`, `aria-hidden="true"`).
