---
name: focus-trap-detector
description: |
  Simulates keyboard tab navigation (at least 30 focus cycles) using Playwright to detect if keyboard focus becomes trapped inside an interactive container like a modal dialog, dropdown, or popup menu with no way to exit via keyboard controls. Use this skill when evaluating keyboard accessibility (WCAG 2.1.2) for any overlay components.
---

## Instructions

1. Receives a `url_o_html` parameter representing the page to evaluate.
2. Executes the script `scripts/focus_trap.py` simulating Tab repeatedly to detect if the focus is stuck in a small cycle.
3. Returns the results according to the technical contract: `{ "trap_detected": bool, "involved_selectors": list, "num_presses_without_exit": int }`.

## When NOT to activate this skill

- On pages without modals, popups, or other interactive overlay components.
