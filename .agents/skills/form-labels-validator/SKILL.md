---
name: form-labels-validator
description: |
  Audits form elements (text inputs, checkboxes, radio buttons, select tags, textareas) to verify they are associated with an accessible label via <label for>, label nesting, aria-label, or aria-labelledby. Use this skill when auditing form accessibility (WCAG 1.3.1 / 4.1.2).
---

## Instructions

1. Receives form node elements as a string representation of the HTML.
2. Executes the script `scripts/form_labels.py` to parse the inputs and determine if each has an associated label.
3. Returns a list of `issues` according to the technical contract: `{ "issues": list }` where each issue contains: `{ "selector": string, "input_type": string, "has_label": bool, "detected_method": string|null }`.

## When NOT to activate this skill

- On `input` elements of type `submit`, `reset`, `button`, `image`, or `hidden`.
- On elements that are not related to forms.
