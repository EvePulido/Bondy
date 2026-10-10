---
name: document-language-validator
description: |
  Checks if the HTML document's root tag (<html>) has a valid lang attribute conforming to BCP 47 (e.g., 'es', 'en-US') to ensure screen readers parse correct voice outputs. Use this as part of base document structure audits (WCAG 3.1.1).
---

## Instructions

1. Receives the `html_root_tag` as a string parameter.
2. Executes the Python script `scripts/check_lang.py` passing the HTML content via standard input (stdin).
3. Returns the `issue` object according to the technical contract: `{ "present": bool, "value": string|null, "valid": bool }`.

## When NOT to activate this skill

- If you do not have access to the page's HTML code.
- If the audit does not include a review of the root document (e.g., you are only evaluating a partial component without the `<html>` tag).
