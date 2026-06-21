---
name: validar-contraste-texto
description: |
  Calcula el ratio de contraste entre texto y fondo para cada elemento de texto
  visible en una página web. Determina si cumple el mínimo WCAG 2 AA (4.5:1 texto
  normal, 3:1 texto grande).
  Usar cuando se necesite verificar legibilidad de texto contra su fondo.
  NO usar para contraste de elementos no textuales (iconos, gráficos, bordes).
---

## Instrucciones

1. Recibe el `dom_snapshot` serializado por Playwright.
2. Para cada nodo de texto visible, extrae color de texto (`fg`) y color de fondo efectivo (`bg`), resolviendo transparencias si las hay.
3. Ejecuta `scripts/contrast.py fg_hex bg_hex` para obtener el ratio.
4. Determina el umbral requerido según tamaño/peso de fuente (ver `references/` si existe).
5. Devuelve la lista de `issues` según el contrato de la Sección 4.1 de la spec técnica.

## Cuándo NO activar este skill

- Si el nodo no contiene texto visible (solo íconos, imágenes, bordes).
- Si el texto está oculto (`display:none`, `visibility:hidden`, `aria-hidden="true"`).
