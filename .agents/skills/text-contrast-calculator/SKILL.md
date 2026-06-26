---
name: text-contrast-calculator
description: |
  Calculates the color contrast ratio between text (foreground) and its background element for all visible text nodes in a DOM snapshot to verify legibility. Evaluates if they satisfy the WCAG 2 AA minimum ratio limits (4.5:1 for normal text, 3.0:1 for large text). Use this tool for checking color accessibility.
---

## Instructions

1. Receives the full HTML document (`content`) via stdin.
2. Executes `scripts/contrast.py` which launches Playwright and injects a script into the page.
3. For each visible text node, it automatically extracts the computed text color (`fg`) and the effective background color (`bg`), resolving transparencies if present.
4. Determines the required threshold depending on the computed font size and weight.
5. Returns a JSON string containing `{"issues": list}` where each issue contains: `{ "selector": string, "text_snippet": string, "contrast_ratio": float, "passes_wcag": bool, "required": float }`.

## When NOT to activate this skill

- If the node does not contain visible text (only icons, images, borders).
- If the text is hidden (`display:none`, `visibility:hidden`, `aria-hidden="true"`).
