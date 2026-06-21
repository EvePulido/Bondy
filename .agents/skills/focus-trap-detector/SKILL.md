---
name: focus-trap-detector
description: |
  Simulates keyboard tab navigation (at least 30 focus cycles) using Playwright to detect if keyboard focus becomes trapped inside an interactive container like a modal dialog, dropdown, or popup menu with no way to exit via keyboard controls. Use this skill when evaluating keyboard accessibility (WCAG 2.1.2) for any overlay components.
---

## Instrucciones

1. Recibe una `url_o_html` de la página en Playwright.
2. Ejecuta `scripts/focus_trap.py` simulando Tab repetidamente para detectar si el foco se atasca en un ciclo pequeño.
3. Devuelve los resultados de acuerdo al contrato de la Sección 4.6.

## Cuándo NO activar este skill

- En páginas sin modales, popups u otros componentes superpuestos interactivos.
