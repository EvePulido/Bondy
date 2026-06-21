---
name: clasificar-imagen-decorativa
description: |
  Determina si una imagen es puramente decorativa (no aporta información
  única más allá de lo estético) y por lo tanto debería llevar alt="" en vez
  de una descripción innecesaria. Usa el contexto del DOM circundante.
---

## Instrucciones

1. Recibe la URL o bytes de la imagen (`imagen_url_o_bytes`) y su `contexto_dom` (texto/headings circundantes).
2. Analiza el contenido visual de la imagen frente a la información textual adyacente.
3. Evalúa si la imagen provee información adicional, funcionalidad o contexto vital (ver `references/decorativa_vs_informativa.md`).
4. Devuelve si la imagen es puramente decorativa (`es_decorativa`) y una justificación detallada de acuerdo al contrato de la Sección 4.8.
5. Modelo: gemini-3.5-flash (confirmar disponibilidad vigente antes de implementar).

## Cuándo NO activar este skill

- Si el elemento es un ícono o imagen utilizado como único contenido dentro de un enlace o botón interactivo (eso la hace funcional, no decorativa).
