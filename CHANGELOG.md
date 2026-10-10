# Changelog

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/).

## [Unreleased]

### Added
- `/api/audit` anota cada fix con `before_occurrences`; la UI solo ofrece "Apply to File" si el fragmento aparece exactamente una vez y explica por qué no cuando son 0 o más de 1.
- `tests/unit/test_apply_fix.py`: tests de aplicación única, ambigüedad (409) y rechazo de clientes remotos.
- `app/app_utils/render_page.py`: renderiza páginas a PNG con Chromium en un subproceso. Solo permite `file://` dentro de `demo_sites/` y hosts http(s) públicos (anti-SSRF).
- `app/app_utils/vision_tools.py`: herramientas `analyze_rendered_page` (Gemini ve la página renderizada) y `classify_image_decorative` (heurísticas deterministas + veredicto de visión: decorative / informative / functional). Ambas usan `BONDY_VISION_MODEL` con respaldo `BONDY_FALLBACK_MODEL`.
- `tests/unit/test_vision_tools.py`: tests de heurísticas y del render.
- Skill `axe-accessibility-scanner` (`.agents/skills/`): línea base determinista con axe-core 4.10.2 (WCAG 2.0/2.1/2.2 A/AA + best-practice) y árbol de accesibilidad de Chromium para detectar controles sin nombre accesible. Corre offline (aborta peticiones de red de la página). Devuelve conteos reales de `passes`/`violations`.
- `tests/unit/test_axe_scanner.py`: tests del escáner (se omite el test de navegador si Chromium no está instalado).
- `app/app_utils/audit_schema.py`: contrato único `AuditFix` y `parse_audit_response()` para validar la salida del agente.
- `validate_public_url()` en `security.py`: guardrail anti-SSRF (solo http(s) a IPs públicas).
- `/api/apply-fix` exige `X-API-Key` (`BONDY_API_KEY`) o petición local.
- `tests/unit/test_audit_schema.py`: tests del parser.
- CLI `bondy` (`bondy scan <archivo|carpeta> --no-llm`, `bondy doctor`): escaneo determinista local sin API key, salida terminal/JSON y códigos de salida (0 limpio, 1 hallazgos al umbral, 2 error).
- `bondy.toml` + variables de entorno + flags con precedencia flag > env > archivo (`bondy/config.py`). La API key se rechaza en `bondy.toml` a propósito.
- Extras de instalación: `server` (FastAPI/uvicorn), `agent` (ADK), `gcp` (Cloud Logging/OpenTelemetry/gcsfs) y `mcp`. El núcleo queda en `playwright`, `google-genai` y `pydantic`.
- `tests/unit/test_latency_controls.py`, `test_config.py`, `test_cli_scan.py`, `test_doctor.py`.
- `docs/improvement-plan.md`: plan v2 (herramienta local, portable y con la API key del propio desarrollador).

### Changed
- `/api/apply-fix` rechaza con 409 los reemplazos ambiguos (el `before` aparece más de una vez).
- `.env.example` y README: opción gratuita con API key de AI Studio, variables `BONDY_*`, descripción de seguridad actualizada.
- `verify_image_alt_text` movida a `vision_tools.py` y rediseñada: reglas de grounding (solo lo visible, sin inventar raza/ropa/marca), datos no confiables delimitados, ejemplos few-shot, temperatura 0, salida estructurada (`AltVerdict`), chequeos estáticos deterministas del alt y decisión `keep`/`fix`/`needs_manual_review` en código. La instrucción del agente indica cómo usar `recommendation` y `suggested_alt`.
- `agent.py`: registra las dos herramientas nuevas; la instrucción añade el paso 1.7 (revisión visual) y la comprobación de imágenes decorativas/funcionales.
- `verify_image_alt_text` usa `BONDY_VISION_MODEL` (por defecto `gemini-flash-latest`) en lugar de `gemini-2.5-flash`, que ya no está disponible para cuentas nuevas.
- Modelo de respaldo ante 503: tras el primer fallo por saturación, `/api/audit` reintenta con `BONDY_FALLBACK_MODEL` (por defecto `gemini-3.5-flash-lite`; vacío lo desactiva).
- `/api/audit` reintenta también ante 503/UNAVAILABLE con backoff exponencial (5/10/20 s) y hasta 4 intentos.
- `/api/audit` devuelve `stats` (`passes`, `violations`, `needs_review`) calculados por axe-core; `web/app.js` usa esos conteos reales para el score y el contador "Passed" (la estimación de 8 elementos por categoría queda solo como fallback si el baseline no puede correr).
- `agent.py`: nuevo paso 1.5 en la instrucción: el agente debe ejecutar axe y reportar sus hallazgos como objetivos antes de las verificaciones semánticas.
- `fast_api_app.py` usa `parse_audit_response` en lugar del parseo JSON anidado con regex; el endpoint devuelve el error real de parseo.
- `verify_image_alt_text` valida la URL y limita la descarga a 10 MB.
- `Dockerfile` copia `.agents/`, `web/` y `demo_sites/`.
- `docs/architecture.md`: contrato de datos actualizado a `AuditFix`.
- `web/app.js`: el error de red/parseo muestra la pantalla "Audit Failed" con el mensaje real en lugar de `alert()`.
- Paquete `app` renombrado a `bondy`; skills, `web/` y `fix_patterns.md` viven en `bondy/resources/` (package data, localizados con `importlib.resources`, sin depender del cwd). La `App` de ADK y su `app_name` pasan a `bondy` (rutas `/apps/bondy/...`).
- Cloud Logging es opt-in (`BONDY_CLOUD_LOGGING=1`); la telemetría queda apagada por defecto. El `Dockerfile` instala los extras `server`, `agent` y `gcp`.
- `load_dotenv` ya no usa `override=True`: no pisa las variables reales del entorno.
- Auditorías solo de WCAG 1.1.1 omiten axe y `analyze_rendered_page` (menos peticiones a Gemini).
- Reintento de la petición fallida (429/503) con `HttpRetryOptions` en vez de reiniciar toda la auditoría; la cuota diaria (`PerDay`) no se reintenta y `/api/audit` responde 429 con un mensaje claro.
- La skill `git-commit-formatter` sale del proyecto y pasa a `~/.claude/skills/` (global, solo para desarrollo).
- `.gitignore`: se quita `Bondy/`, que por ser insensible a mayúsculas ignoraba también el paquete `bondy/`.

### Fixed
- `pyproject.toml`: eliminado el paquete inexistente `frontend` de hatch.
- `web/app.js` (`applyFix`): `originalText` fuera del `try` (evita `ReferenceError` en el `catch`).
- `web/app.js`: respuesta no-array ya no rompe el render de resultados.
- `fast_api_app.py`: ya no se oculta el error de formato JSON bajo "timed out".

### Removed
- Modelos sin uso en `agent.py`: `Evidence`, `Finding`, `FixSuggestion`, `FindingsReport`, `FixesReport`.

### Pendiente

**Funcionalidad**
- [ ] Criterios WCAG 2.2 que axe no cubre: 2.4.7 (focus visible sin `outline`) y 1.4.4 (zoom).
- [ ] Auditar URLs públicas reales (reutilizando `validate_public_url`).
- [ ] Progreso real por SSE en lugar de la animación de tiempos fijos.
- [ ] Mapear checks del frontend de forma completa (`forms` -> 1.3.1 + 4.1.2; separar 3.1.1 de `contrast`).

**Seguridad**
- [ ] Aplicar `validate_public_url` en `.agents/skills/text-contrast-calculator/scripts/contrast.py` (`page.goto(url)`).
- [x] `load_dotenv(override=True)` pisa variables reales del entorno (Cloud Run).
- [ ] Autenticación para `/feedback` y para los endpoints `/run` que expone `get_fast_api_app`.
- [ ] Mitigar prompt injection en `req.source` y `raw_html` interpolados en el prompt.

**Calidad y pruebas**
- [ ] Tests de `security.py` (traversal, rutas absolutas, `..`).
- [ ] Golden files de hallazgos esperados por demo site y dataset de evaluación (`tests/eval/`) en CI opcional.
- [ ] `ruff format --check` en el CI y reducir `--all-extras`.
- [ ] Evitar duplicados entre axe y `text-contrast-calculator` (comprobar en una corrida real).

**Deuda técnica**
- [ ] `ALLOWED_SOURCES` sin uso en `security.py` (usar `Path.resolve()` + `is_relative_to()`).
- [x] Rutas dependientes del CWD (`skills_dir`, `FileResponse("web/index.html")`).
- [x] `git-commit-formatter` se carga en el toolset del agente aunque no es de accesibilidad (movida a `~/.claude/skills/`).
- [ ] `github_server.py` sin uso y con `token` expuesto como argumento de herramienta.
- [ ] Frontend: `onclick` inline, `alert()`, `aria-expanded` en `finding-header`, estilos inline.
- [ ] `pyproject.toml`: autor/descripción placeholder y `ty` con `python-version = "3.10"`.
- [ ] **Refactorizar el código con el agente `refactor`** (auditoría de código limpio, SOLID y deuda técnica; foco en `fast_api_app.py`, `agent.py`, `vision_tools.py` y `web/app.js`).
