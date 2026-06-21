---
name: alt-text-quality-analyzer
description: |
  Analyzes a web page image against its current alt attribute text using multimodal vision models. Evaluates if the alt text accurately describes the image context, checking if it is empty, generic, or mismatched with the visual content. Use this to verify descriptive quality of image alt tags (WCAG 1.1.1).
---

## Instrucciones

1. Recibe la URL o bytes de la imagen (`imagen_url_o_bytes`), el alt actual (`alt_actual`), y el contexto DOM (`contexto_dom`).
2. Utiliza visión por computadora para analizar la imagen.
3. Compara el contenido de la imagen con el atributo `alt_actual`.
4. Evalúa la calidad según las directrices WCAG 1.1.1 (ver `references/wcag_1_1_1.md`).
5. Devuelve un veredicto (`buena`, `deficiente`, `ausente`, `posible_redundancia`), una explicación detallada, y una sugerencia de fix de acuerdo a la Sección 4.7 de la spec técnica.
6. Modelo: gemini-3.5-flash (confirmar disponibilidad vigente antes de implementar).

## Cuándo NO activar este skill

- Si el elemento evaluado no es una etiqueta `<img>` o no tiene un rol de imagen.
- Si la imagen ha sido previamente clasificada definitivamente como puramente decorativa.
