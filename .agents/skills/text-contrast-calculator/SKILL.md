---
name: text-contrast-calculator
description: |
  Calculates the color contrast ratio between text (foreground) and its background element for all visible text nodes in a DOM snapshot to verify legibility. Evaluates if they satisfy the WCAG 2 AA minimum ratio limits (4.5:1 for normal text, 3.0:1 for large text). Use this tool for checking color accessibility.
---

## Instrucciones

1. Recibe el `dom_snapshot` serializado por Playwright.
2. Para cada nodo de texto visible, extrae color de texto (`fg`) y color de fondo efectivo (`bg`), resolviendo transparencias si las hay.
3. Ejecuta `scripts/contrast.py fg_hex bg_hex` para obtener el ratio.
4. Determina el umbral requerido según tamaño/peso de fuente (ver `references/` si existe).
5. Devuelve la lista de `issues` según el contrato de la Sección 4.1 de la spec técnica.

## Cuándo NO activar este skill

- Si el nodo no contiene texto visible (solo íconos, imágenes, bordes).
- Si el texto está oculto (`display:none`, `visibility:hidden`, `aria-hidden="true"`).
