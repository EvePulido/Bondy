---
name: validar-calidad-alt-text
description: |
  Compara cada imagen real contra su atributo alt usando un modelo con visión.
  Determina si el alt describe fielmente el contenido/función de la imagen en su
  contexto (¿está dentro de un link/botón? ¿hay un figcaption adyacente?).
  NO asume automáticamente que un caption adyacente hace innecesario el alt —
  solo lo marca como "posible redundancia, revisar".
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
