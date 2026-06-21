---
name: validar-idioma-documento
description: |
  Verifica que la etiqueta <html> tenga el atributo lang con un código de idioma
  válido (formato BCP 47, ej. "es", "en-US"). Es el check más simple del proyecto.
  Usar siempre como parte de la auditoría base.
---

## Instrucciones

1. Recibe el `html_root_tag` en formato string.
2. Ejecuta el script de Python `scripts/check_lang.py` pasándole el HTML por la entrada estándar (stdin).
3. Devuelve el objeto `issue` según el contrato técnico: `{ presente: bool, valor: string|null, valido: bool }`.

## Cuándo NO activar este skill

- Si no se tiene acceso al código HTML de la página.
- Si la auditoría no incluye la revisión del documento raíz (es decir, solo se está evaluando un componente parcial sin la etiqueta `<html>`).
