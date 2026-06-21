---
name: form-labels-validator
description: |
  Audits form elements (text inputs, checkboxes, radio buttons, select tags, textareas) to verify they are associated with an accessible label via <label for>, label nesting, aria-label, or aria-labelledby. Use this skill when auditing form accessibility (WCAG 1.3.1 / 4.1.2).
---

## Instrucciones

1. Recibe una lista de nodos de formulario con su id, type, y contexto DOM circundante.
2. Ejecuta `scripts/form_labels.py` para parsear los inputs y determinar si cada uno tiene un label.
3. Devuelve la lista de `issues` según el contrato de la Sección 4.4 de la spec técnica.

## Cuándo NO activar este skill

- En elementos `input` de tipo `submit`, `reset`, `button`, `image` o `hidden`.
- En elementos no relacionados con formularios.
