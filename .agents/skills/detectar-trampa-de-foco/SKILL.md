---
name: detectar-trampa-de-foco
description: |
  Simula Tab repetidamente (mínimo 30 pulsaciones) y detecta si el foco entra
  en un ciclo del que no puede salir (ej. un modal sin botón de cierre
  accesible por teclado). Usar en cualquier componente tipo modal/dropdown/popup.
---

## Instrucciones

1. Recibe una `url_o_html` de la página en Playwright.
2. Ejecuta `scripts/focus_trap.py` simulando Tab repetidamente para detectar si el foco se atasca en un ciclo pequeño.
3. Devuelve los resultados de acuerdo al contrato de la Sección 4.6.

## Cuándo NO activar este skill

- En páginas sin modales, popups u otros componentes superpuestos interactivos.
