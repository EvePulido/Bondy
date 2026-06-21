---
name: focus-order-validator
description: |
  Simulates keyboard tab navigation sequence on a page using Playwright, records the actual sequence of focused elements, and compares it to the visually expected or DOM logical structure to identify focus order jumps (e.g. tab bypassing main content or jumping randomly). Use this when testing tab order consistency and WCAG 2.4.3 compliance.
---

## Instrucciones

1. Recibe una `url_o_html` de la página a evaluar.
2. Ejecuta `scripts/focus_order.py` pasándole el contenido HTML o URL.
3. Evalúa la secuencia de foco resultante para detectar anomalías.
4. Devuelve el resultado según el contrato de la Sección 4.5 de la spec técnica.

## Cuándo NO activar este skill

- Cuando la página no tiene elementos interactivos.
