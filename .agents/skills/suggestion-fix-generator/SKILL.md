---
name: suggestion-fix-generator
description: |
  Consumes a specific accessibility finding (such as bad alt, low contrast, or missing forms labels) along with the affected original DOM node HTML content, and generates the corrected HTML code snippet (with before/after diff) using target WCAG pattern templates. Use this as the final post-audit step to suggest immediate fixes.
---

## Instructions

1. Receives a `finding` object (with description of the issue) and the `original_dom_node`.
2. Analyzes the reported error and the HTML content of the node.
3. Determines the minimal and cleanest fix required.
4. Generates the modified HTML code snippet without altering unrelated classes, IDs, or structures.
5. Returns the output in the format: `{ "before": string, "after": string, "explanation": string }`.
6. AI Model: gemini-3.5-flash.

## When NOT to activate this skill

- If the `finding` does not clearly state a resolvable vulnerability or issue in the code.
- During the active audit and scanning phase (it should only be invoked after reports are generated).
