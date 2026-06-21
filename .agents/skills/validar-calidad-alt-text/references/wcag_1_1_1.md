# Criterio de Conformidad WCAG 1.1.1: Contenido No Textual

Todo contenido no textual que se presenta al usuario tiene una alternativa textual que cumple el mismo propósito, excepto en las situaciones enumeradas a continuación.

## Directrices para el Texto Alternativo (alt)

- **Imágenes Informativas**: Imágenes que representan conceptos e información, como fotos, gráficos y diagramas. El texto alternativo debe ser al menos una breve descripción que transmita la misma información que la imagen.
- **Imágenes Decorativas**: Se proporcionan solo con fines estéticos, no aportan información y no tienen funcionalidad. Deben tener un atributo alt vacío (`alt=""`) para que las tecnologías de asistencia las ignoren.
- **Imágenes Funcionales**: Imágenes utilizadas como enlaces o botones (ej. un ícono de lupa para buscar). El texto alternativo debe describir la función o destino del enlace/botón, NO describir la imagen (ej. "Buscar" y no "Lupa").

## Evaluando la Calidad

Un alt text es **deficiente** si:
- Es demasiado largo o detalla información irrelevante (spam de palabras clave).
- Describe el archivo ("imagen de", "foto de", "logo.png").
- No refleja adecuadamente la intención o función de la imagen en su contexto.
- En una gráfica/diagrama, no transmite los datos clave o el mensaje principal.
