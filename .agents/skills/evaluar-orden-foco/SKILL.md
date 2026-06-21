---
name: evaluar-orden-foco
description: |
  Simula pulsaciones de Tab con Playwright y registra la secuencia real de
  elementos enfocados. Compara contra el orden visual/DOM esperado.
  Usar para detectar saltos de foco ilógicos (ej. que tabular salte del header
  directo al footer sin pasar por el contenido principal).
---

## Instrucciones

1. Recibe una `url_o_html` de la página a evaluar.
2. Ejecuta `scripts/focus_order.py` pasándole el contenido HTML o URL.
3. Evalúa la secuencia de foco resultante para detectar anomalías.
4. Devuelve el resultado según el contrato de la Sección 4.5 de la spec técnica.

## Cuándo NO activar este skill

- Cuando la página no tiene elementos interactivos.
