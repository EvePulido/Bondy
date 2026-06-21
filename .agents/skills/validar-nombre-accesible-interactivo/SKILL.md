---
name: validar-nombre-accesible-interactivo
description: |
  Verifica que cada <a> y <button> tenga un nombre accesible: texto visible,
  aria-label, aria-labelledby, o alt de una imagen contenida. Cubre las
  categorías "Empty Links" y "Empty Buttons" del WebAIM Million en un solo skill.
  Usar para auditar todos los elementos interactivos de navegación/acción.
---

## Instrucciones

1. Recibe una lista de nodos <a>/<button> con su contenido HTML interno.
2. Verifica si tienen texto interno, atributo `aria-label`, o `aria-labelledby`.
3. Ejecuta `scripts/accessible_name.py` enviando el HTML por stdin.
4. Devuelve la lista de `issues` según el contrato de la Sección 4.3 de la spec técnica.

## Cuándo NO activar este skill

- Si el elemento no es interactivo (no es `<a>` con `href` ni `<button>`).
- Elementos ocultos con `aria-hidden="true"`.
