# Patrones de Corrección (Fix Patterns) para Bondy

Al generar un fragmento de código corregido (`after`), aplica estos patrones recomendados según la falla detectada:

## 1. Falta Atributo de Idioma (`validar-idioma-documento`)
- **Fix:** Agrega o corrige el atributo `lang` en la etiqueta `<html>`.
- **Regla:** Usa códigos BCP 47 válidos (ej. `lang="es"`, `lang="en-US"`).
- **Ejemplo:** `<html lang="es">`

## 2. Nombre Accesible Ausente (`validar-nombre-accesible-interactivo`)
- **Fix:**
  - Si es un ícono de acción sin texto visible, usa `aria-label="<Acción>"`.
  - Si el botón tiene texto oculto pero no semántico, considera `aria-labelledby` o texto dentro de un `<span class="sr-only">`.
- **Regla:** Sé conciso. No escribas "Botón para buscar", simplemente "Buscar".

## 3. Falta Label en Formularios (`validar-labels-formularios`)
- **Fix:** 
  - Preferentemente, agrega un `<label for="[id-del-input]">` explícito.
  - Alternativa: Envuelve el input dentro del `<label>`.
  - Como último recurso para inputs ocultos visualmente (ej. barras de búsqueda), usa `aria-label`.

## 4. Contraste Insuficiente (`validar-contraste-texto`)
- **Fix:** Cambia el código de color CSS para que cumpla con el ratio de 4.5:1. 
- **Regla:** Trata de mantener el tono o matiz original, solo ajustando la luminosidad (oscureciendo textos o aclarando fondos).

## 5. Imagen Decorativa Verbosa (`clasificar-imagen-decorativa`)
- **Fix:** Reemplaza el texto del atributo `alt="..."` por `alt=""`. No lo elimines, déjalo vacío explícitamente.

## 6. Alt Text Deficiente (`validar-calidad-alt-text`)
- **Fix:** Reescribe el `alt` para que sea descriptivo y contextual.
- **Regla:** No inicies con "Imagen de..." ni "Gráfico de...".

**Nota importante:** ¡NO reescribas código ajeno a la falla original! Si el botón tenía `class="btn primary mb-3"`, debes mantener esa clase exacta en el bloque `after`.
