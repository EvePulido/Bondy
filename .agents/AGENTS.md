# Local Project Context & Secure Coding Standards — Bondy (A11y-Forge)

Este archivo define las reglas de contexto y estándares de seguridad persistentes que todos los agentes de desarrollo en este proyecto deben seguir de forma obligatoria.

---

## 1. Validación Obligatoria de Entradas (Seguridad Primero)
* **Regla:** Antes de invocar cualquier herramienta de navegación web o automatización con Playwright (como en los validadores de foco o trampas de foco), se debe validar obligatoriamente la entrada contra el módulo de seguridad determinístico en `app/app_utils/security.py` utilizando la función `validar_input_antes_de_auditar`.
* **Fuentes Permitidas:** Únicamente se permiten los directorios demo registrados estáticamente en `ALLOWED_SOURCES` (`demo_sites/...`) o HTML crudo pegado directamente. Queda terminantemente prohibido realizar peticiones HTTP a URLs de internet arbitrarias.

## 2. Calidad de Código y Ciclo de Corrección Pre-Commit
* **Regla:** Si un intento de `git commit` o la ejecución de pruebas falla debido a las validaciones de los hooks de `pre-commit` (como análisis de Ruff, ruff-format o chequeos de tipo), el agente debe:
  1. Detenerse inmediatamente y tratar el error como una tarea de refactorización prioritaria.
  2. Aplicar los arreglos correspondientes de estilo o sintaxis en los archivos afectados.
  3. Ejecutar `uv run pre-commit run --all-files` para verificar que el código pase el 100% de los chequeos limpios antes de continuar con otras tareas.

## 3. Arquitectura del Sistema (ADK 2.0 Workflows)
* **Regla:** La lógica de orquestación principal del proyecto debe estar implementada mediante el API de Grafos/Workflows nativo de **google-adk 2.0** en `app/agent.py`. Evitar la orquestación manual secuencial en Python sin un grafo definido si se busca mantener el estándar del framework.

## 4. Conservación del Código
* **Regla:** Solo se deben modificar los módulos o archivos directamente afectados por la solicitud del usuario, preservando intacto todo el código circundante, las configuraciones de los modelos de IA y el formateo estándar del proyecto.
