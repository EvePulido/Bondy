# Bondy: Plan de Desarrollo y Migración (Checklist Unificado)

Este checklist detalla los pasos secuenciales de migración y desarrollo para consolidar el proyecto final **Bondy (A11y-Forge)** en la raíz bajo la arquitectura **Google ADK 2.0**.

---

## Checklist de Migración e Implementación (Orden Estricto)

### Fase 1: Mapeo de Carpeta y Estructura Base
- [x] Copiar las 9 skills del prototipo previo a la carpeta raíz `.agents/skills/`.
- [x] Copiar los sitios demo del prototipo previo a `demo_sites/` en la raíz.
- [x] Conservar la estructura del scaffold de `app/` generado por ADK.

### Fase 2: Configuración del Entorno Seguro
- [x] Ejecutar sincronización de dependencias con `uv sync`.
- [x] Instalar navegadores de Playwright: `uv run playwright install --with-deps chromium`.
- [x] Configurar el hook de pre-commit de git que ejecute `agents-cli lint` y chequeos estáticos.

### Fase 3: Implementación del Módulo de Seguridad
- [ ] Crear el archivo de seguridad en `app/app_utils/security.py`.
- [ ] Migrar el guardrail determinístico que valida e interrumpe cualquier URL o source que no esté en `ALLOWED_SOURCES` (sitios demo autorizados o HTML crudo).

### Fase 4: Grafo del Workflow en `app/agent.py`
- [ ] Definir a los agentes `Auditor` y `Refactorizador` como agentes en `app/agent.py`.
- [ ] Implementar la orquestación utilizando la API `Workflow` de ADK 2.0 (conectando la salida de hallazgos del Auditor a la entrada del Refactorizador).

### Fase 5: Servidor MCP e Interfaz FastAPI
- [ ] Configurar el servidor MCP en `mcp_server/github_server.py`.
- [ ] Desarrollar la aplicación FastAPI en `app/fast_api_app.py` que sirva la interfaz web del usuario (UI premium) para ingresar un sitio demo o pegar HTML crudo, y visualizar el `AuditReport` final con sus propuestas de corrección.

### Fase 6: Evaluaciones y Pruebas Unitarias
- [ ] Crear pruebas de Pytest bajo `tests/` para validar el runner de seguridad y las 6 skills determinísticas.
- [ ] Configurar `eval_config.yaml` y ejecutar `agents-cli eval run` para calibrar el comportamiento del LLM y de los agentes.

### Fase 7: Cierre y Entrega Final
- [ ] Crear el workflow de CI/CD en `.github/workflows/bondy-audit.yml`.
- [ ] Escribir el `README.md` del repositorio con las instrucciones de arquitectura, setup y uso.
- [ ] Preparar y grabar el video de demostración de 5 minutos.
- [ ] Redactar el ensayo/writeup final del proyecto.
