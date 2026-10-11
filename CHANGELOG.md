# Changelog

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/).

## [Unreleased]

### Added
- `bondy/app_utils/browser.py`: lanzador único de navegador (Chromium de Playwright -> Chrome -> Edge del sistema, con error accionable) y `open_page()`, que aborta toda petición salvo `file://` del propio archivo, `data:` y `about:` (y deshabilita descargas, service workers y WebSockets).
- Modo estático: sin navegador utilizable `bondy scan` no falla; ejecuta lang/labels/accessible-name/img-alt por HTML, indica qué checks omitió en `notes` (`static_mode`, `omitted_checks` en JSON) y mantiene los códigos de salida 0/1.
- `bondy doctor` lanza el navegador y reporta cuál se usará (o avisa del modo estático con el comando de instalación).
- `tests/unit/test_network_guard.py` (0 peticiones a un servidor local por escáner, política, fallback del lanzador) y `tests/unit/test_static_mode.py`.
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

- `bondy/core/` (sin FastAPI ni ADK): pipeline por código `escáneres -> etapa semántica de imágenes -> fixes -> reporte` (`run_scan`). `bondy scan` sin `--no-llm` y con API key lo usa; sin key avisa y corre solo lo determinista.
- `LLMProvider` mínima (`bondy/core/providers/`): `GeminiProvider` (`google-genai`, modelos desde `Settings`, key explícita y redactada de los errores), política de reintentos única (429 por minuto espera, `PerDay` no se reintenta, modelo de respaldo) y `FakeProvider` para tests (429 minuto/día, 503, JSON inválido, timeout).
- Etapa semántica por lotes: una llamada por `batch_size` imágenes (def. 8) que fusiona verify+classify con esquema JSON; dedup por (src, alt); triage determinista (decorativas, prefijo redundante); imágenes no cargables (404, no imagen, enorme, formato no soportado, `data:`, fuera de la raíz) -> `needs_manual_review` con motivo; un reintento si el JSON es inválido; la decisión final sigue en código.
- Topes duros `--max-requests`, `--max-usd`, `--max-pages`, `--max-images` (flag > env `BONDY_MAX_*` > `bondy.toml`; 0 = sin límite): resultado PARCIAL con motivo y código de salida 3. `max_requests` vale **50 por defecto**; al alcanzarlo el aviso dice que es el valor por defecto y cómo subirlo (`--max-requests N` / `0`).
- `--no-remote-images` (`remote_images`, `BONDY_REMOTE_IMAGES`): opt-out de la descarga de imágenes http(s); por defecto se descargan (hosts públicos). Con el opt-out van a `needs_manual_review` con el motivo.
- `bondy estimate <ruta>` y `bondy scan --dry-run`: rango de peticiones, tokens y costo sin llamar al modelo; precios configurables (`price_input_per_mtok`, `price_output_per_mtok`, **sin valores por defecto**): sin precios se muestran peticiones y tokens y el costo figura como no disponible (`cost_usd: null` + `cost_unavailable_reason`); `--max-usd` sin precios termina con código 2 antes de llamar al modelo.
- Resumen de uso al final de `scan` (y en JSON: `usage`, `fixes`): peticiones, lotes, imágenes verificadas/resueltas en código/omitidas, tokens y costo estimado, resultado parcial.
- Nuevas claves de configuración: `batch_size`, `max_requests`, `max_usd`, `max_pages`, `max_images`, `price_input_per_mtok`, `price_output_per_mtok`, `tokens_per_image`, `remote_images`.
- `bondy/core/checks.py`: fuente única de checks y mapeo WCAG.
- Tests `test_pipeline.py`, `test_providers.py`, `test_semantic.py`, `test_limits.py`, `test_estimate.py` (sin red ni cuota).

- Caché de veredictos (B4) en `.bondy/cache/verdicts/`: clave = bytes de la imagen + alt + contexto enviado + modelo + huella del prompt/esquema; escritura atómica; entradas corruptas = miss; sin key ni rutas absolutas. Un segundo escaneo idéntico hace 0 peticiones. Flags `--no-cache`, `--clear-cache`, `--cache-dir`, comando `bondy cache clear [--keep-state]`; ajustes `cache`, `cache_dir` (`BONDY_CACHE`, `BONDY_CACHE_DIR`). El resumen de uso muestra aciertos/fallos de caché.
- Escaneo incremental (B9): `--changed-only` reutiliza el resultado de las páginas cuyo HTML e imágenes locales no cambiaron (invalida al cambiar versión de Bondy, checks, modelo, escáneres o prompt) y marca `reused` en el reporte; `--since <git-ref>` escanea solo lo cambiado y reutiliza el resultado guardado (mismo hash y configuración) de las demás páginas.
- Reanudación (B10): cuota diaria, topes, `--scan-timeout` y Ctrl+C dejan `resume.json` y el trabajo ya hecho; `--resume` continúa sin repetir peticiones. Ctrl+C termina con gracia y exit 3.
- `bondy doctor --check-key`: valida la key con 1 petición mínima (opt-in); distingue key rechazada, cuota y red. En `scan`, una key inválida aborta en el primer lote con exit 2, sin reintentos (`ErrorKind` `invalid_key`, `network`).
- Navegador compartido (`browser_session`) con `--timeout` por página (def. 60 s) y `--scan-timeout` (def. 900 s; ajustes `timeout`, `scan_timeout`); cierre garantizado también con error o Ctrl+C.
- `bondy/core/alt_rules.py`: reglas de grounding, heurísticas y `quota_retry_delay` compartidas; `vision_tools` (modo agente) las importa de ahí.
- Tests `test_cache.py`, `test_incremental.py`, `test_resume.py`, `test_apikey.py`, `test_browser_session.py`, `test_shared_rules.py`.

- Formatos de reporte (E1): `--format terminal|json|markdown|html|sarif` y `--output FILE`; un único modelo interno (`bondy/core/report.py`) del que salen todos (`bondy/core/formats.py`). HTML autocontenido y accesible (sin JS ni recursos remotos, CSP), SARIF 2.1.0 (validado contra el esquema oficial de OASIS), Markdown con escape. Todo contenido del proyecto escaneado se escapa por formato y la terminal descarta caracteres de control. `--sarif-prefix` para escanear subcarpetas del repositorio.
- Baseline (E2): `bondy baseline create <ruta> [-o archivo]` y `scan --baseline` (`baseline` en `bondy.toml`, `BONDY_BASELINE`): huella = regla + ruta relativa + selector/fragmento normalizado (sin línea); solo los hallazgos nuevos cuentan para el exit code; informa ocultos y resueltos; archivo corrupto, de otra versión o inexistente = exit 2 antes de escanear.
- Supresiones versionables (E4): `<!-- bondy-ignore: <regla|wcag> -- <motivo> -->` y `[[ignore]]` (`path`, `rule`, `reason`) en `bondy.toml`; el motivo es obligatorio (exit 2 si falta); el reporte lista las aplicadas con su motivo y avisa de las obsoletas; globs absolutos o con `..` se rechazan.
- Redacción de secretos (D3, `bondy/core/redact.py`): claves/tokens/JWT/PEM, asignaciones `api_key=`/`token=`/`password=` y URLs con credenciales o `?token=` pasan a `[REDACTED]` antes de enviarse al modelo, antes de calcular la clave de la caché y en los snippets de los reportes; las páginas cuyos hallazgos citan secretos no se guardan para reutilización; `.env`, `*.pem`, `id_rsa`... nunca se cargan como imagen. Es una detección por patrones, no una garantía.
- Integraciones CI (E3): `action.yml` (composite; instala Bondy, escanea y sube SARIF con `github/codeql-action/upload-sarif` fijado por SHA), `.pre-commit-hooks.yaml` (solo HTML cambiado respecto a HEAD, offline) y `docs/ci-example.yml` (no activo).
- Resumen final (E5): nuevos por severidad, ocultos por baseline, suprimidos, resueltos, páginas escaneadas/reutilizadas/omitidas y siguiente paso accionable; el JSON trae lo mismo en `summary`.
- `bondy/core/source.py`: índice de elementos del HTML para asignar línea a hallazgos de axe/selectores.
- Tests `test_reports.py`, `test_baseline.py`, `test_suppress.py`, `test_redact.py`, `test_ci_files.py`, `test_summary.py`.

- `bondy/core/web_audit.py`: la UI web y `POST /api/audit` usan `run_scan` (pipeline determinista + etapa semantica) en vez del agente ADK. `scan_to_payload` es un adaptador puro `ScanReport` -> contrato de la UI; `run_web_audit` escribe `raw_html` en un directorio temporal que siempre se elimina. Sin API key (o con `BONDY_NO_LLM`) corre en modo no-llm y devuelve la nota en `notes`.
- `/api/audit` anade a la respuesta `notes`, `mode` y `partial` (retrocompatible); `stats` sale del `axe` del propio pipeline (`FileResult.axe_stats`), sin segunda ejecucion.
- `GET /api/checks` y `bondy.core.checks` (`GROUPS`, `resolve_criteria`, `describe_checks`): unica fuente del mapeo checks -> WCAG. `enabled_checks` acepta ids de grupo (`images`, `forms`, `keyboard`, `contrast`), ids de check con WCAG y criterios (`WCAG 1.1.1`); un valor desconocido es 403.
- `tests/unit/test_web_audit.py` (FakeProvider, sin red ni cuota).

### Changed
- `web/app.js` ya no mapea checks -> WCAG: envia los ids de grupo y muestra las `notes` del servidor; las reglas sin criterio WCAG se etiquetan "Best practice".
- `/api/audit`: "Apply to File" solo se ofrece para parches reales (fixes de imagen); los hallazgos que solo traen una recomendacion no llevan `before_occurrences`. Una cuota diaria agotada sigue siendo 429; una key rechazada, 500 con mensaje accionable.
- JSON de `scan`: los hallazgos son ahora uno por elemento afectado (`selector`, `snippet`, `line`, `fix`, `fingerprint`; ya no hay `nodes`/`count`), con rutas relativas a la carpeta escaneada y `/`; nuevas claves `summary`, `baseline`, `suppressions`, `suppressed`.
- `bondy scan` calcula el exit code sobre los hallazgos nuevos (no baselined ni suprimidos); la lógica de los códigos 0/1/2/3 no cambia.
- `bondy/scan.py`: `load_page`/`scan_loaded` separan lectura y escaneo; el HTML se lee una sola vez y se hashea (`FileResult.html`, `sha256`, `reused`).
- El pipeline ejecuta la etapa semántica antes de los escáneres (una key inválida falla antes de lanzar el navegador); los scripts de los escáneres usan `playwright_context()` y comparten el navegador del escaneo.
- `vision_tools._generate` (modo agente) pasa la API key explícita leída de `Settings` (sin cambiar el resto del comportamiento).
- `scan` escribe `.bondy/` en la carpeta escaneada solo cuando hace falta (LLM, `--changed-only`, `--since`, `--resume`; desactivable con `--no-cache`) y crea dentro un `.gitignore` con `*`; un `scan --no-llm` simple no escribe nada.
- `bondy scan` devuelve 3 cuando el resultado es parcial y no hay hallazgos al umbral de `--fail-on`.
- `scan.py`: el mapeo WCAG de cada escáner sale de `bondy/core/checks.py`; `scan_path` acepta `max_files`. `fast_api_app.py` toma la lista "auditar todo" de la misma fuente.
- Regla 3 de `.agents/AGENTS.md`: el pipeline por código es el predeterminado (D1); el agente ADK es el modo opcional.
- `contrast.py`, `focus_trap.py` y `focus_order.py` ya no navegan a contenido que empieza por `http(s)://` ni cargan recursos remotos (antes no tenían bloqueo de red); `axe_scan.py` ya no permite `file:` ajenos. `render_page.py` usa el mismo guard (mantiene los hosts públicos verificados).
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
- `render_page.py` ya no permite hosts http(s) remotos: la captura de visión es solo local (`file://` del archivo y `demo_sites/`).
- `bondy scan --static` (o `BONDY_STATIC=1` / `static = true`): fuerza el modo estático sin lanzar navegador, útil en CI.

### Fixed
- `pyproject.toml`: eliminado el paquete inexistente `frontend` de hatch.
- `web/app.js` (`applyFix`): `originalText` fuera del `try` (evita `ReferenceError` en el `catch`).
- `web/app.js`: respuesta no-array ya no rompe el render de resultados.
- `fast_api_app.py`: ya no se oculta el error de formato JSON bajo "timed out".
- Una página con `Content-Security-Policy` estricta ya no hace fallar a axe (`bypass_csp` en el contexto del navegador; la guardia de red sigue activa).
- El reporte HTML de Bondy escrito dentro de la carpeta escaneada se omite en el siguiente escaneo (marca `<meta name="generator" content="bondy-report">`) en lugar de auditarse y salir con código 2.

### Removed
- Modelos sin uso en `agent.py`: `Evidence`, `Finding`, `FixSuggestion`, `FindingsReport`, `FixesReport`.
- `bondy/fast_api_app.py`: `InMemoryRunner`/agente ADK en `/api/audit`, `_build_fallback_app`, `FALLBACK_MODEL`, `_skip_note`, `_compute_axe_stats` y el bucle de reintentos propio (ahora los cubre la politica unica de `bondy/core/providers`). `bondy/agent.py` y el modo agente no cambian.

### Pendiente

**Funcionalidad**
- [ ] Criterios WCAG 2.2 que axe no cubre: 2.4.7 (focus visible sin `outline`) y 1.4.4 (zoom).
- [ ] Auditar URLs públicas reales (reutilizando `validate_public_url`).
- [ ] Progreso real por SSE en lugar de la animación de tiempos fijos.
- [ ] Mapear checks del frontend de forma completa (`forms` -> 1.3.1 + 4.1.2; separar 3.1.1 de `contrast`). El mapeo ya vive solo en `bondy/core/checks.py` (`GROUPS`); falta ajustar los grupos.

**Seguridad**
- [ ] Aplicar `validate_public_url` en `.agents/skills/text-contrast-calculator/scripts/contrast.py` (`page.goto(url)`).
- [x] `load_dotenv(override=True)` pisa variables reales del entorno (Cloud Run).
- [ ] Autenticación para `/feedback` y para los endpoints `/run` que expone `get_fast_api_app`.
- [ ] Mitigar prompt injection en `req.source` y `raw_html` interpolados en el prompt. (`/api/audit` ya no interpola `raw_html` en un prompt; queda el contexto de imagen de la etapa semantica, cubierto por `test_semantic.py` y la redaccion de secretos.)

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
