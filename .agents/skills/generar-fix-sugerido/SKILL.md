---
name: generar-fix-sugerido
description: |
  Toma un hallazgo (de cualquiera de las 8 skills anteriores) junto con el nodo
  DOM afectado, y genera el snippet de código corregido en formato antes/después.
  Usar como último paso, después de que el Auditor haya generado todos los hallazgos.
  NO debe inventar selectores o nodos que no estén en el hallazgo recibido.
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
