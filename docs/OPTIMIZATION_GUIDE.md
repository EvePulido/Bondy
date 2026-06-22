# ⚙️ Guía de Optimización de Quotas y Tokens en Bondy

Esta guía contiene consejos prácticos y recomendados para optimizar el consumo de tokens y evitar exceder los límites de velocidad (RPM) y solicitudes diarias (RPD) del plan gratuito (*Free Tier*) de Google AI Studio.

---

## 1. Modularización de Habilidades (Skills Activas)
El flujo de Bondy lee dinámicamente todas las habilidades ubicadas en la carpeta [.agents/skills/](file:///C:/Users/evely/OneDrive/Desktop/Bondy/bondy/.agents/skills/). En cada llamada de API, el agente le envía a Gemini las descripciones y esquemas de todas las herramientas disponibles.

* **Recomendación:** Si solo vas a auditar o presentar un tipo específico de incidencia (por ejemplo, validar textos alternativos en imágenes), **mueve temporalmente las otras carpetas de skills fuera del directorio `.agents/skills/`** (por ejemplo, a una carpeta de respaldo externa).
* **Beneficio:** 
  * Reduce significativamente el tamaño del prompt del sistema (*system instructions*), ahorrando miles de tokens de entrada en cada turno del agente.
  * Evita que el Auditor consuma cuotas adicionales intentando evaluar reglas secundarias (como contrastes, trampas de foco o etiquetas) que no son relevantes para esa prueba específica.

---

### 2. Ahorro de Latencia y Costo (Context Overhead)

Gemini (y cualquier LLM) necesita leer la definición completa (esquema JSON) de cada herramienta en cada interacción del
agente. Si tienes 10 herramientas complejas, estás enviando miles de tokens repetidamente solo para recordarle al modelo
qué herramientas existen. Reducir las herramientas al mínimo reduce la latencia de respuesta (el tiempo que tarda en
empezar a escribir) y la factura de la API.

### 3. El estándar de oro: Agentes Especializados (Multi-Agent Design)

En lugar de tener un "Agente Generalista Gigante" con todas las habilidades, Bondy implementa una arquitectura de subagentes especializados y concurrentes de forma predeterminada en su grafo de Workflow:

* **`ImageAuditor`**: Encargado exclusivamente de imágenes y textos alternativos (2 habilidades).
* **`FormAuditor`**: Encargado de verificar etiquetas de formulario (1 habilidad).
* **`KeyboardAuditor`**: Simula y valida la navegación del foco por teclado (2 habilidades).
* **`DocAuditor`**: Valida metadatos estructurales, idioma, nombres accesibles de elementos y contrastes (3 habilidades).

Al dividir el flujo en subagentes paralelos y concurrentes, estás aplicando las mejores prácticas de la industria para construir sistemas de agentes robustos, reduciendo drásticamente el consumo de tokens de entrada al enviar solo las descripciones de las herramientas relevantes a cada agente en particular.

---

## 4. Pruebas de Contraste con Estilos Asociados
Para que la calculadora de contrastes (`text-contrast-calculator`) funcione matemáticamente, necesita conocer el color del texto y el fondo del elemento. 

Dado que poner estilos en línea en el HTML (`style="..."`) es una mala práctica en entornos de producción:

* **Recomendación en Demos:** En tus archivos de demostración local, puedes vincular una hoja de estilo CSS local o incluir los estilos dentro de una etiqueta `<style>` limpia en la cabecera `<head>` de la página.
* **Cómo opera Playwright:** Al usar la ruta local (`demo_sites/...`), Bondy levanta un navegador virtual (Playwright) que renderiza la página y aplica las clases CSS de forma estándar. De esta forma, la calculadora de contraste obtiene los colores finales renderizados sin alterar las buenas prácticas de diseño web.

---

## 5. Habilitación del Plan de Pago por Uso (Pay-as-you-go)
Si necesitas realizar auditorías de sitios web completos o en producción sin toparte con interrupciones por límites de cuota:

* **Recomendación:** Ve a [Google AI Studio](https://aistudio.google.com/), ingresa a la configuración de facturación y asocia tu cuenta a un plan de pago por uso.
* **Beneficio:** Tu cuota diaria ilimitada se activará de inmediato y tu velocidad por minuto subirá a **1000 RPM**. Las tarifas de la familia *Flash* de Gemini son sumamente bajas (centavos de dólar por millones de tokens), por lo que pagarás montos mínimos únicamente por lo que consumas.
