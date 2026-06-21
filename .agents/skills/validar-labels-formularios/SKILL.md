---
name: validar-labels-formularios
description: |
  Verifica que TODO input de formulario (text, checkbox, radio, select, textarea)
  tenga un label asociado vía <label for="">, envoltura <label>, o
  aria-label/aria-labelledby. Reemplaza y amplía el alcance original de
  "solo radio buttons" a todos los campos de formulario.
  Usar para auditar formularios completos, no elementos individuales sueltos.
---

## Instrucciones

1. Recibe una lista de nodos de formulario con su id, type, y contexto DOM circundante.
2. Ejecuta `scripts/form_labels.py` para parsear los inputs y determinar si cada uno tiene un label.
3. Devuelve la lista de `issues` según el contrato de la Sección 4.4 de la spec técnica.

## Cuándo NO activar este skill

- En elementos `input` de tipo `submit`, `reset`, `button`, `image` o `hidden`.
- En elementos no relacionados con formularios.
