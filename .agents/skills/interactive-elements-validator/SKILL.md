---
name: interactive-elements-validator
description: |
  Scans all links (<a>) and button tags to verify they contain an accessible name (either visible text, an aria-label, aria-labelledby, or image alt text). Use this tool to prevent empty links and empty buttons (WCAG 2.4.4 / 4.1.2).
---

## Instrucciones

1. Recibe una lista de nodos <a>/<button> con su contenido HTML interno.
2. Verifica si tienen texto interno, atributo `aria-label`, o `aria-labelledby`.
3. Ejecuta `scripts/accessible_name.py` enviando el HTML por stdin.
4. Devuelve la lista de `issues` según el contrato de la Sección 4.3 de la spec técnica.

## Cuándo NO activar este skill

- Si el elemento no es interactivo (no es `<a>` con `href` ni `<button>`).
- Elementos ocultos con `aria-hidden="true"`.
