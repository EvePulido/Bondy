---
name: document-language-validator
description: |
  Checks if the HTML document's root tag (<html>) has a valid lang attribute conforming to BCP 47 (e.g., 'es', 'en-US') to ensure screen readers parse correct voice outputs. Use this as part of base document structure audits (WCAG 3.1.1).
---

## Instrucciones

1. Recibe el `html_root_tag` en formato string.
2. Ejecuta el script de Python `scripts/check_lang.py` pasándole el HTML por la entrada estándar (stdin).
3. Devuelve el objeto `issue` según el contrato técnico: `{ presente: bool, valor: string|null, valido: bool }`.

## Cuándo NO activar este skill

- Si no se tiene acceso al código HTML de la página.
- Si la auditoría no incluye la revisión del documento raíz (es decir, solo se está evaluando un componente parcial sin la etiqueta `<html>`).
