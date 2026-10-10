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

### Fixed
- `pyproject.toml`: eliminado el paquete inexistente `frontend` de hatch.
- `web/app.js` (`applyFix`): `originalText` fuera del `try` (evita `ReferenceError` en el `catch`).
- `web/app.js`: respuesta no-array ya no rompe el render de resultados.
- `fast_api_app.py`: ya no se oculta el error de formato JSON bajo "timed out".

### Removed
- Modelos sin uso en `agent.py`: `Evidence`, `Finding`, `FixSuggestion`, `FindingsReport`, `FixesReport`.

### Pendiente
- Aplicar `validate_public_url` en `contrast.py`.
- `load_dotenv(override=True)`, rutas dependientes del CWD, `ALLOWED_SOURCES` sin uso.
- Criterios WCAG 2.2 que axe no cubre (2.4.7 focus visible, 1.4.4 zoom).
- Auditar URLs públicas reales.
- Progreso real por SSE en lugar de la animación fija.
