---
name: focus-order-validator
description: |
  Simulates keyboard tab navigation sequence on a page using Playwright, records the actual sequence of focused elements, and compares it to the visually expected or DOM logical structure to identify focus order jumps (e.g. tab bypassing main content or jumping randomly). Use this when testing tab order consistency and WCAG 2.4.3 compliance.
---

## Instructions

1. Receives the `url_o_html` parameter representing the page to evaluate.
2. Executes the script `scripts/focus_order.py` passing the HTML content or URL.
3. Evaluates the resulting focus sequence to detect anomalies.
4. Returns the result according to the technical contract: `{ "focus_sequence": list, "anomalies": list }`.

## When NOT to activate this skill

- When the page does not contain any interactive elements.
