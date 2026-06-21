---
name: suggestion-fix-generator
description: |
  Consumes a specific accessibility finding (such as bad alt, low contrast, or missing forms labels) along with the affected original DOM node HTML content, and generates the corrected HTML code snippet (with before/after diff) using target WCAG pattern templates. Use this as the final post-audit step to suggest immediate fixes.
---

## Instrucciones

1. Recibe un objeto `finding` (con la descripción del error) y el `nodo_dom_original`.
2. Analiza el error reportado y el contenido HTML del nodo.
3. Determina la corrección mínima y más limpia requerida (ver `references/patrones_de_fix.md`).
4. Genera el código HTML modificado sin alterar clases, ids o estructuras no relacionadas.
5. Devuelve la salida en formato `{before, after, explicacion}` según la Sección 4.9.
6. Modelo: gemini-3.5-flash (confirmar disponibilidad vigente antes de implementar).

## Cuándo NO activar este skill

- Si el `finding` no indica claramente una vulnerabilidad o error solucionable en el código.
- Durante la fase activa de auditoría y escaneo (solo se debe invocar al final del reporte).
