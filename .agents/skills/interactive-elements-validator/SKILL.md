---
name: interactive-elements-validator
description: |
  Scans all links (<a>) and button tags to verify they contain an accessible name (either visible text, an aria-label, aria-labelledby, or image alt text). Use this tool to prevent empty links and empty buttons (WCAG 2.4.4 / 4.1.2).
---

## Instructions

1. Receives a list of `<a>` and `<button>` HTML elements as a string.
2. Executes the script `scripts/accessible_name.py` passing the HTML content via stdin to check if they have internal text, `aria-label`, or `aria-labelledby`.
3. Returns a list of `issues` according to the technical contract: `{ "issues": list }` where each issue contains: `{ "selector": string, "type": string, "has_accessible_name": bool, "method": string|null }`.

## When NOT to activate this skill

- If the element is not interactive (not an `<a>` with `href` nor a `<button>`).
- Elements hidden with `aria-hidden="true"`.
