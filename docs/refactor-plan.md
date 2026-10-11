# Plan de refactor y deuda técnica

Fecha del análisis: 2026-10-11. Rama al analizar: `docs/rewrite-readme-byok` (el encargo
mencionaba `feat/cache-and-resume`; el contenido auditado es el árbol de trabajo actual,
HEAD `7cc6785`). Alcance: solo análisis, ningún cambio de código.

Línea base medida hoy:

| Medida | Resultado |
|---|---|
| `uv run pytest tests/unit -q` | 492 passed, 1 skipped (73 s) |
| `uv run ty check bondy` | 0 errores (en CI) |
| `uv run ty check bondy tests` | **34 diagnósticos** (el plan decía 9; ver P1-3) |
| Código en `bondy/` | ~8 200 líneas, 40 módulos |
| Función más compleja | `core/pipeline.py::run_scan` (CC ~63, 197 líneas) |

Convención: Esfuerzo S (< 2 h), M (medio día), L (> 1 día). Riesgo = riesgo de regresión
o de ruptura de contrato.

---

## 1. Estado verificado de los 9 pendientes

| # | Pendiente | Estado real | Prioridad |
|---|---|---|---|
| 1 | Config leída fuera de `Settings` | **Hecho** (P1-1) | P1 |
| 2 | `--mode agent` en la CLI | **Vigente**; decisión de producto antes de implementar (P2-1) | P2 |
| 3 | `ty` sobre tests | **Vigente, cifra desactualizada**: 34 diagnósticos, no 9 (P1-3) | P1 |
| 4 | `upload-sarif` en forks | **Vigente** (P0-2) | P0 |
| 5 | Bucle JS bloquea `page.evaluate` | **Hecho** (P1-2) | P1 |
| 6 | `app.js` con mapeo propio | **Parcialmente resuelto**: el mapeo checks->WCAG ya no está; queda un fallback heurístico muerto (P2-3) | P2 |
| 7 | E7 plantillas / B8 Batch API | **Vigente**, es trabajo de producto (P2-5) | P2 |
| 8 | `render_page.py` conserva hosts públicos | **Obsoleto en `render_page`** (ya no los permite), pero el riesgo real está en otros tres sitios (P0-1) | P0 |
| 9 | `INSTALL_CHROMIUM=true` sin probar | **Hecho** (P1-4; probado en local, falta ejecutar el job en GitHub) | P1 |

---

## 2. Prioridad P0 (seguridad; hacer primero)

### P0-1. SSRF / DNS rebinding en la descarga de imágenes remotas (pendiente 8, reformulado) — HECHO

**Estado verificado**

- `bondy/app_utils/render_page.py`: **ya no** permite hosts http(s). Llama a `open_page`
  sin `allow_remote` y el test `tests/unit/test_static_mode.py:127`
  (`test_render_page_allows_no_remote_hosts`) lo fija. La línea del CHANGELOG
  ("Solo permite `file://` ... y hosts http(s) públicos") es histórica y está desfasada.
- El riesgo de DNS rebinding sí existe donde se descargan imágenes:
  - `bondy/app_utils/security.py:51-74` `validate_public_url` resuelve con
    `socket.getaddrinfo` y después `urllib` vuelve a resolver el host al conectar
    (TOCTOU: un DNS con TTL 0 puede devolver IP pública en la comprobación y
    `127.0.0.1`/metadata en la conexión).
  - `bondy/core/images.py:196-228` (`_PublicRedirects`, `_load_remote`): valida cada
    redirección pero con el mismo TOCTOU.
  - `bondy/app_utils/vision_tools.py:90-100` (`_load_image`): `urlopen` **sin** guard de
    redirecciones (un 302 a `http://169.254.169.254/` se sigue).
  - `bondy/resources/skills/alt-text-quality-analyzer/scripts/fetch_image.py:17-21`:
    `urlopen` sobre cualquier URL que empiece por `http`, **sin ningún guard** (ni
    público, ni redirecciones, ni tope de bytes: `response.read()` sin límite). No está
    referenciado en ningún `SKILL.md` ni en Python, pero `SkillToolset` del agente ADK
    puede ejecutarlo.
- `validate_public_url` usa `parsed.port or 443` también para `http://` (inocuo para
  `getaddrinfo`, pero impreciso).

**Cambio propuesto**

1. Un único `fetch_public_bytes(url, max_bytes, timeout)` en `bondy/core/images.py`
   (o `bondy/core/netguard.py`) que: resuelve una vez, valida **todas** las IP, y
   conecta a la IP validada (con `Host`/SNI originales; p. ej. un `HTTPConnection`
   subclass que usa la IP ya resuelta) y repite el ciclo en cada redirección (máx. 3).
2. `vision_tools._load_image` y `fetch_image.py` delegan en esa función (o se elimina
   `fetch_image.py` si no se usa: grep sin consumidores).
3. Corregir el prefijo de puerto por esquema y rechazar credenciales en la URL
   (`user:pass@`).
4. Actualizar la línea desfasada del CHANGELOG (sección Added, `render_page.py`).

**Riesgo**: medio (cambia el cliente HTTP de la descarga; los tests de `test_images*`
usan servidores locales y `FakeProvider`). **Esfuerzo**: M.

**Verificación**: tests nuevos con un servidor local que redirige a `127.0.0.1` y un
resolver falso que alterna IP pública/privada (monkeypatch de `socket.getaddrinfo`);
`uv run pytest tests/unit -k "images or network or vision" -q`; `rg "urlopen" bondy`
debe listar un solo uso.

**Dependencias**: ninguna. Conviene hacerlo antes que P1-1 (comparten `vision_tools.py`).

### P0-2. `upload-sarif` falla en PRs desde forks (pendiente 4) — HECHO

**Estado verificado**: `action.yml:129-134`. La condición es
`always() && inputs.upload-sarif == 'true' && inputs.format == 'sarif' && hashFiles(...) != ''`.
En un PR de fork (y en PRs de Dependabot) el `GITHUB_TOKEN` es de solo lectura, el
paso falla y, como es el último antes del paso que propaga el exit code, ensucia el
resultado con un error ajeno al escaneo. Además, en repos privados sin GitHub Advanced
Security el paso falla igual.

**Cambio propuesto** (en `action.yml` y documentado en README / `docs/ci-example.yml`)

- Condición: añadir
  `(github.event_name != 'pull_request' || github.event.pull_request.head.repo.full_name == github.repository)`.
- Añadir `continue-on-error: true` al paso de subida y un paso previo que emita
  `::notice::` cuando se omite por fork, indicando que el SARIF queda como artefacto.
- Opcional: subir el SARIF con `actions/upload-artifact` (SHA verificado con
  `git ls-remote`) para forks, así el resultado sigue accesible.
- Documentar en el README los permisos necesarios (`security-events: write`) y el
  requisito de Code Scanning en repos privados.

**Riesgo**: bajo (solo YAML; `tests/unit/test_ci_files.py` ya valida la estructura).
**Esfuerzo**: S.

**Verificación**: `uv run pytest tests/unit/test_ci_files.py -q` (añadir una aserción
sobre la condición); validar el YAML con el test existente; la ejecución real exige un
PR de fork (no verificable en local, dejarlo anotado igual que el resto de CI).

**Dependencias**: ninguna. Se puede agrupar con P1-4 y P1-3 (todo CI/infra).

**Resultado (hecho)**: `action.yml` omite la subida cuando `github.event_name == 'pull_request'` y el
repo de la cabecera no es el del workflow, o el actor es `dependabot[bot]`; en ese caso emite
`::notice::` y sube el SARIF con `actions/upload-artifact@cf430e0... # v7.0.2` (SHA verificado con
`git ls-remote`) como `bondy-sarif`. El paso `upload-sarif` lleva `continue-on-error: true`.
`docs/ci-example.yml` documenta permisos y el requisito de Code Scanning en repos privados;
**la sección equivalente del README queda pendiente** (README tiene cambios sin commitear, no tocado) para el
commit `docs:`. Tests: `test_action_skips_sarif_upload_for_read_only_tokens`. **Sin verificar**:
ejecucion real en un PR de fork (solo local: YAML valido + test estructural).

### P0-3. La app web monta la API completa de ADK y escucha en 0.0.0.0 (hallazgo nuevo)

**Estado verificado**: `bondy/fast_api_app.py:66-73` crea la app con
`google.adk.cli.fast_api.get_fast_api_app(agents_dir=AGENT_DIR, ...)`. Esa fábrica
registra las rutas del servidor de desarrollo de ADK (según la API de ADK:
`/list-apps`, `/run`, `/run_sse`, sesiones...), todas **sin la protección** de
`BONDY_API_KEY` que solo cubre `/api/apply-fix`. El `Dockerfile:63` arranca con
`--host 0.0.0.0`. Quien alcance el puerto puede invocar al agente con la key de Gemini
del propietario (coste) y usar herramientas con SSRF (P0-1). *Inferido de la librería;
confirmar con `GET /list-apps` contra `uvicorn bondy.fast_api_app:app`.*

**Cambio propuesto**

- Montar ADK solo si `BONDY_ENABLE_AGENT_API=1` (por defecto desactivado), o servir la
  UI y `/api/*` con un `FastAPI()` propio y dejar `get_fast_api_app` detrás de la
  bandera. La UI actual no usa el agente (`/api/audit` va por `run_scan`).
- Si se desactiva por defecto: documentar el cambio de comportamiento en CHANGELOG y
  README (hoy el agente ADK solo corre desde la web, ver P2-1).
- Enlaza con la deuda `agent` extra obligatorio para `server` (P2-2): si ADK deja de
  ser necesario para la UI, `server` puede instalarse sin `agent`.

**Riesgo**: medio (cambia qué rutas existen; los tests `test_server_e2e.py` y
`test_web_audit.py` cubren la app). **Esfuerzo**: M.

**Verificación**: test nuevo que lista `app.routes` y comprueba que sin la bandera no
hay `/run`; `uv run pytest tests/unit -q`; `BONDY_NO_LLM=1 uvicorn ...` y `GET /`,
`POST /api/audit`.

**Dependencias**: coordinar con P1-1 (config) y P2-1 (`--mode agent`); decidir primero
si el agente ADK sigue siendo una superficie soportada.

**Estado (2026-10-11, hecho)**

- **Riesgo CONFIRMADO** (TestClient sobre `bondy.fast_api_app:app`, `BONDY_NO_LLM=1`, sin
  `BONDY_API_KEY`, cliente simulado `203.0.113.9`): `GET /list-apps` 200 (lista `bondy`,
  `dist`, `docs`, `examples`, `mcp_server`, `tests`), `GET /docs` 200, `GET /openapi.json`
  200, `GET/POST /apps/bondy/users/u/sessions` 200 (crea y lista sesiones), `POST /run` y
  `POST /run_sse` 422 (la ruta existe y se alcanza; solo falla la validación del cuerpo,
  sin 401/403). Mismo resultado desde `testclient` (local) y desde la IP remota. `/run_live`
  (websocket) también registrado. Con la clave real una llamada válida a `/run` invocaría
  al agente con la key de Gemini (no se probó para no gastar cuota).
- **Corrección**: `_build_app()` devuelve un `FastAPI()` propio (con `/health`) salvo
  `BONDY_ENABLE_AGENT_API=1`; con la bandera monta ADK y añade `_AgentApiGuard` (ASGI,
  HTTP y websocket): fuera de `/`, `/static/`, `/api/*`, `/feedback` y `/health` exige
  `X-API-Key` si hay `BONDY_API_KEY`, o cliente local si no. `/api/apply-fix` reutiliza
  `_is_authorized`. Verificado tras el cambio: `/list-apps` 404 y `/` , `/health`,
  `/api/checks` 200 con uvicorn real en 127.0.0.1.
- **Tests**: `tests/unit/test_agent_api_guard.py` (23). `pytest tests/unit`: 543 pasan,
  1 omitido; `ruff check`, `ruff format --check`, `ty check bondy tests` limpios.
- **Pendiente / no cambiado**: (1) `Dockerfile` sigue con `--host 0.0.0.0` (necesario en
  contenedor; ya no expone ADK por defecto, pero `/api/audit` y `/feedback` siguen sin
  autenticación y `/api/audit` puede gastar cuota de Gemini: decisión de diseño previa);
  (2) README no actualizado (documentar `BONDY_ENABLE_AGENT_API`; no tocado por
  instrucción); (3) el import de ADK sigue siendo necesario solo con la bandera, así que
  P2-2 (`server` sin `agent`) queda desbloqueado, no hecho; (4) `agents_dir=AGENT_DIR`
  expone toda la raíz del repo como "apps" en `/list-apps` cuando la bandera está activa;
  (5) detrás de un proxy inverso `request.client.host` es el del proxy (regla heredada).

---

## 3. Prioridad P1

### P1-1. Configuración fuera de `bondy/config.py` (pendiente 1) — HECHO

**Estado verificado**

| Archivo:línea | Lectura directa | ¿Vigente? |
|---|---|---|
| `bondy/app_utils/vision_tools.py:30-31` | `os.getenv("BONDY_VISION_MODEL"...)`, `os.getenv("BONDY_FALLBACK_MODEL"...)` en import time; mismos defaults que `config.py:188-190` | Sí |
| `bondy/app_utils/vision_tools.py:45` | `GOOGLE_GENAI_USE_VERTEXAI` | Sí (no está en Settings) |
| `bondy/agent.py:~70` | `model="gemini-flash-latest"` **literal**, ignora `BONDY_MODEL` | Sí |
| `bondy/fast_api_app.py:21-22` | `load_dotenv(AGENT_DIR/.env)`: carga **todo** el `.env` en `os.environ`, contradice la política de `config.py` (solo la API key, sin tocar `os.environ`) | Sí |
| `bondy/fast_api_app.py:45,59,63,207` | `BONDY_CLOUD_LOGGING`, `ALLOW_ORIGINS`, `LOGS_BUCKET_NAME`, `BONDY_API_KEY` | Sí (no son del escaneo) |

Matiz: `fast_api_app.py` **no** lee `BONDY_VISION_MODEL`/`BONDY_FALLBACK_MODEL`; el
pendiente original lo incluía por error. Además `BONDY_API_KEY` (token de
`/api/apply-fix`) se parece a `Settings.api_key` (la key de Gemini): es una fuente de
confusión de nombres.

**Cambio propuesto**

1. `vision_tools`: reemplazar las constantes de módulo por una función
   `_models() -> tuple[str, str]` que usa `load_settings()` (ya lo hace `_client_kwargs`).
   Mantener los nombres `VISION_MODEL`/`FALLBACK_MODEL` solo si algún test los importa
   (`rg "VISION_MODEL" tests`).
2. `agent.py`: construir `Gemini(model=load_settings().model, ...)`.
3. Añadir a `Settings` (o a un `ServerSettings` aparte en `config.py`) los ajustes del
   servidor: `apply_fix_token`, `allow_origins`, `cloud_logging`, `logs_bucket`. Aceptar
   `BONDY_API_KEY` como alias heredado y documentar el nombre nuevo
   (`BONDY_APPLY_TOKEN`) en README y `.env.example` (ambos con cambios sin commitear:
   **no tocarlos hasta que se commiteen**; dejar anotado para el commit de docs).
4. `fast_api_app`: sustituir `load_dotenv` por el lector de `config.py`, o limitarlo a
   las variables `BONDY_*`.
5. Test de arquitectura: `rg "os\.(getenv|environ)" bondy` solo debe aparecer en
   `config.py`, `doctor.py`, `telemetry.py` y la lista blanca del servidor.

**Riesgo**: medio-bajo (comportamiento por defecto idéntico; cuidado con tests que
parchean `vision_tools.VISION_MODEL`). **Esfuerzo**: M.

**Verificación**: `uv run pytest tests/unit/test_config.py tests/unit/test_vision_tools.py tests/unit/test_shared_rules.py tests/unit/test_latency_controls.py -q`;
test nuevo "BONDY_VISION_MODEL cambia el modelo de `_generate`" con
`monkeypatch.setenv`.

**Dependencias**: tras P0-1 (mismo archivo); condiciona P2-1 y P2-2.

**Estado (2026-10-11, hecho)**

- `bondy/config.py`: nuevos `ServerSettings` + `load_server_settings()` (token, `enable_agent_api`,
  `allow_origins`, `cloud_logging`, `logs_bucket`, `deprecations`), `use_vertexai()`,
  `load_settings_lenient()` (nunca lanza; para herramientas del agente), `use_file=` en
  `load_settings` y `export_dotenv_to_environ()` (único escritor del entorno, lista blanca
  de prefijos `BONDY_/GEMINI_/GOOGLE_/GENAI_/OTEL_` + `ALLOW_ORIGINS`, `LOGS_BUCKET_NAME`,
  `COMMIT_SHA`; sin pisar variables existentes). `_read_dotenv` generaliza el parser que ya
  usaba la CLI (sin cambio de comportamiento para la API key).
- `vision_tools.py`: `_models()` por llamada; sin `VISION_MODEL`/`FALLBACK_MODEL` ni alias
  `_quota_retry_delay`. `agent.py`: `model=load_settings_lenient().model`.
  `fast_api_app.py`: sin `load_dotenv` ni lecturas de `os.environ`; sin `noqa: E402`.
  `web_audit.py`: ya no usa `os.environ` (pasa `env` tal cual a `load_settings`).
- Token: `BONDY_APPLY_TOKEN` (nuevo) con `BONDY_API_KEY` como alias heredado y aviso en el log;
  el encabezado `X-API-Key` no cambia. `/api/audit` y `/feedback` siguen sin autenticación
  (decisión: Bondy es local) y `BONDY_ENABLE_AGENT_API` se mantiene como opt-in.
- Test de arquitectura (AST, no regex) en `tests/unit/test_settings_only.py` (21 tests): fuera
  de `config.py`, `doctor.py` y `app_utils/telemetry.py` no hay `os.getenv`/`os.environ`, y los
  nombres `BONDY_MODEL/VISION_MODEL/FALLBACK_MODEL/API_KEY/APPLY_TOKEN/ENABLE_AGENT_API/
  CLOUD_LOGGING` solo aparecen en `config.py`. Más: precedencia env > toml > default de los
  modelos de `_generate`, `agent.py` respeta `BONDY_MODEL` (subproceso, sin Gemini),
  `bondy.toml` roto no tumba las herramientas, alias del token, lista blanca del `.env`.
- Verificado: `pytest tests/unit` 564 pasan / 1 omitido (base 543/1); `tests/integration/
  test_server_e2e.py` 3 pasan; `ruff check`, `ruff format --check`, `ty check bondy tests` limpios.
- **Para el commit de docs (no tocado: README.md / .env.example / docs/architecture.md tienen
  cambios sin commitear)**: README líneas ~163 (el servidor ya no "carga el `.env` en su entorno":
  solo las variables permitidas), ~193 y ~149/~304/~347 (documentar `BONDY_APPLY_TOKEN`, marcar
  `BONDY_API_KEY` como deprecado, añadir `BONDY_ENABLE_AGENT_API`), tabla de extras línea ~115
  (`python-dotenv` ya no se usa); `.env.example:26` (`BONDY_APPLY_TOKEN`); `docs/architecture.md`
  (el agente ADK toma el modelo de `Settings.model`).
- **Pendiente / no hecho**: (1) `python-dotenv` sigue en el extra `server` de `pyproject.toml`
  (ya sin uso; quitarlo requiere regenerar `uv.lock`); (2) `telemetry.py` conserva sus lecturas
  de `LOGS_BUCKET_NAME`/`OTEL_*` (escribe valores por defecto para SDK de terceros; en la lista
  blanca del test); (3) `agent.py` mantiene `# ruff: noqa` de archivo y `file_locks`/extracción de
  `apply_fix` (resto de P2-4) sin tocar; (4) el parser de `.env` no interpola ni admite
  valores multilínea (python-dotenv sí); (5) `GOOGLE_GENAI_USE_VERTEXAI` y las `GOOGLE_*` siguen
  siendo del SDK, no de `Settings`: solo se consultan con `use_vertexai()`.

### P1-2. Sin watchdog duro por página (pendiente 5) — HECHO

**Estado verificado**: el mecanismo de timeouts es cooperativo.
`bondy/scan.py::scan_loaded` solo comprueba `deadline` **entre** páginas
(`scan.py:~452`); `BrowserSession` fija `set_default_timeout`
(`browser.py:315-318`), pero `page.evaluate` no tiene timeout en Playwright: si la
página entra en un bucle JS tras `load`, `axe_scan.py:104`, `focus_order.py:69`,
`focus_trap.py:26` o `contrast.py:17` esperan hasta que el hilo principal del renderer
vuelva (~85 s observados) o indefinidamente. `--scan-timeout` y Ctrl+C no interrumpen
una llamada bloqueada. Solo `render_page` está protegido (subproceso con
`timeout=60`, `vision_tools.py:152`).

**Cambio propuesto**

Opción recomendada, de menor a mayor invasividad:

- **A (mínima)**: un `threading.Timer` armado por página en `scan_loaded` con
  presupuesto `settings.timeout * 2`; al vencer, mata el proceso del navegador
  (los hijos nuevos de Chromium desde el lanzamiento, con `psutil` como dependencia
  opcional o `taskkill /T`/`os.killpg`). `BrowserSession.browser()` ya detecta
  `is_connected() == False` y relanza (`browser.py:213-222`); el scanner en curso
  lanza `TargetClosedError`, que `run_scanners` ya convierte en error de página.
- **B (aislamiento fuerte)**: ejecutar los escáneres de navegador de cada página en un
  subproceso `python -m bondy.core.page_worker` con `subprocess.run(timeout=...)`.
  Más robusto y portable, pero cuesta un lanzamiento de navegador por página (se pierde
  el navegador compartido) y cambia la forma de pasar `FileResult`.

Empezar con A; B solo si A resulta frágil en macOS/Linux.

El resultado de la página: error `page-timeout` en `errors` (exit 2) o `skipped`
con motivo (exit 3, resultado parcial reanudable con `--resume`); decidirlo y
documentarlo (hoy `scan_timeout` produce parcial).

**Riesgo**: medio-alto (procesos hijos, plataformas distintas, limpieza de temporales).
**Esfuerzo**: M (A) / L (B).

**Verificación**: fixture HTML con `window.onload = () => setTimeout(() => { for(;;); })`;
test (con `need_browser`) que asegura que `run_scan` termina en < `timeout`+margen, que
la página queda marcada y que la página siguiente sí se escanea. Comprobar que
`tests/unit/test_browser_session.py` sigue verde (navegador relanzado, `launches`).

**Dependencias**: ninguna; **no** agrupar con otros cambios de `scan.py` (P2-4).

**Hecho (opción A, con una variante)**:

- `bondy/app_utils/browser.py`: `page_watchdog(seconds)` arma un `threading.Timer` por página
  dentro de `browser_session`; al vencer mata el árbol de procesos del **driver** de
  Playwright (`taskkill /F /T` en Windows; `pkill -P` + `SIGKILL` en POSIX; sin `psutil`).
  Se mata el driver y no solo Chromium porque Playwright no expone el PID del navegador y
  el PID del driver sí se alcanza (`_impl_obj._connection._transport._proc.pid`, atributo
  privado leído con `getattr` defensivo: si desaparece, el watchdog queda inactivo y todo
  sigue como antes). `BrowserSession.browser()` detecta `_driver_dead`, hace `pw.stop()` y
  arranca driver y navegador nuevos. `is_connected()` NO sirve tras matar el driver
  (seguía devolviendo True): por eso hay un indicador propio.
- `bondy/scan.py::scan_loaded`: presupuesto = `session.page_timeout` (**no** `timeout * 2`:
  `--timeout` ya está documentado como "segundos por página"), acotado por
  `deadline - now`, así `--scan-timeout` también deja de ser solo cooperativo. Antes de
  armar el temporizador se llama a `session.prepare()` para que lanzar (o relanzar) el
  navegador no consuma el tiempo de la página. Con `--timeout 0` o fuera de sesión no hay
  watchdog.
- Decisión del resultado: la página queda en `skipped` (no en `errors`):
  `PAGE_TIMEOUT_SKIP (N s)`, o `SCAN_TIMEOUT_SKIP` si el límite fue el global. Es un
  resultado **parcial** (exit 3 salvo que haya hallazgos de otras páginas, que mandan: exit
  1), consistente con `--scan-timeout`; se escribe `resume.json` con `pages_pending` y la
  página no entra en `pages.json`. Sus hallazgos parciales se descartan. Los escáneres de
  navegador restantes de esa página no se ejecutan (`PageHungError`), los estáticos sí
  corren pero su salida se descarta junto con la página.
- Tests: `tests/unit/test_page_watchdog.py` (7). Con Chromium real: `for(;;);` 50 ms
  después de `load`, `timeout=4`; la página colgada tarda 4.2-4.3 s, las otras dos se
  escanean (axe_stats presentes), `resume.json` con `pages_pending == 1`, `pages.json` con
  a y c pero no b. Sin navegador: skip + resto escaneado, escáneres restantes omitidos,
  tope por `--scan-timeout`, sin watchdog sin sesión o con 0, temporizador desarmado,
  relanzado del navegador.
- **Límites conocidos / no verificado**: (1) solo probado en Windows; la rama POSIX
  (`pkill -P` + `SIGKILL`) no se ha ejecutado en macOS/Linux (CI lo cubrirá con el test
  de Chromium real; si es frágil, opción B). (2) Cada kill deja el directorio
  `playwright_chromiumdev_profile-*` en el temporal del SO (Chromium no pudo limpiarlo; no
  hay forma segura de identificarlo sin `psutil`). (3) El watchdog solo actúa dentro de
  `browser_session` (CLI, `run_scan`, web); las llamadas sueltas a un escáner como librería
  conservan su comportamiento. (4) Una página colgada seguirá colgando en cada `--resume`
  hasta excluirla (`--exclude`) o arreglarla.
- **Para el commit de docs (no tocado)**: README, sección de `--timeout`/`--scan-timeout`
  (el primero es ahora un límite duro por página que mata el navegador y deja la página
  pendiente/exit 3) y tabla de códigos de salida; `docs/architecture.md` (watchdog en
  `browser.py`/`scan.py`); el texto de ayuda de `--timeout` en `bondy/cli.py` conviene
  ampliarlo igual.

### P1-3. `ty check bondy tests` (pendiente 3) — HECHO

**Estado verificado** (ejecutado hoy): 34 diagnósticos, no 9.

| Causa | Cantidad | Archivos |
|---|---|---|
| `scanners=` de `run_scan` con stubs `(html) -> list` frente al alias `Scanner = Callable[[str], list[dict]]` | 13 | `test_redact`, `test_limits`, `test_semantic`, `test_resume`, `test_incremental`, `test_cache` |
| Tipos `None` sin estrechar (`str \| None`, `TokenUsage \| None`, `LoadedImage \| None`, `Literal in None`, `<` con `int\|float\|None`) | 14 | `test_static_mode`, `test_estimate`, `test_providers`, `test_batch_bytes`, `test_dedupe` |
| `importlib.util.spec_from_file_location` sin comprobar `spec`/`loader` | 7 | `test_network_guard`, `test_axe_scanner` |

**Cambio propuesto**

1. Un único helper `load_script(skill, script)` en `tests/conftest.py` (con la
   comprobación de `spec.loader` que ya tiene `scan._load_script`; de hecho los tests
   pueden reutilizar `bondy.scan._load_script`).
2. Alias de tipo más permisivo para el parámetro (`Mapping[str, Callable[[str], Sequence[Mapping[str, Any]]]]`)
   o tipar los stubs de los tests; preferible lo primero: es API pública de `run_scan`.
3. `assert x is not None` antes de usar, en los tests concretos.
4. Añadir `uv run ty check bondy tests` a `.github/workflows/ci.yml` (hoy `:72` solo
   comprueba `bondy`).

**Riesgo**: bajo (solo tests y un alias). **Esfuerzo**: S-M.

**Verificación**: `uv run ty check bondy tests` en 0; `uv run pytest tests/unit -q`
sigue en 492 passed.

**Dependencias**: ninguna; agrupable con P0-2 y P1-4 en una rama "ci-hardening".

**Resultado (hecho)**: 0 diagnosticos (partia de 35). Desviacion del plan: en vez de un alias
nuevo se tipó `scanners=` como `Mapping[str, Scanner]` en `pipeline.py` y `scan.py` (la causa real
era la invarianza de `dict`; `Mapping` es covariante en el valor, sin cambio de comportamiento ni de
contrato). Los `None` se estrecharon con `assert`/filtros y la carga de scripts comprueba `spec`/
`loader`; sin `ignore`s. Se corrigio ademas `log_message` de `test_netguard.py` (diagnostico nuevo
de P0-1). `uv run ty check bondy tests` se ejecuta ahora en `ci.yml`. Tests:
`uv run pytest tests/unit` 520 passed, 1 skipped.

### P1-4. `INSTALL_CHROMIUM=true` sin probar (pendiente 9) — HECHO

**Estado verificado**: `Dockerfile:42-46` ejecuta `playwright install --with-deps chromium`
tras `uv sync`. Nunca se construyó (daemon apagado). Riesgos leídos del archivo:

- `uv==0.8.13` en el Dockerfile frente a `uv==0.11.21` en `ci.yml`: dos versiones.
- Contenedor como `root` sin `USER`; el navegador se instala en `/root/.cache/ms-playwright`
  (si se añade un usuario no root, hay que fijar `PLAYWRIGHT_BROWSERS_PATH`).
- Sin `HEALTHCHECK`, y `bondy doctor` no se usa para validar la imagen.
- `--with-deps` ejecuta `apt-get`; en `python:3.12-slim` funciona pero aumenta ~400 MB.

**Cambio propuesto**

1. Construir y probar: `docker build --build-arg INSTALL_CHROMIUM=true -t bondy:chromium .`
   y `docker run --rm bondy:chromium bondy doctor` (debe reportar el navegador) y
   `docker run -p 8080:8080 ...` + `POST /api/audit` sobre `examples/site_1_bad_alt`
   comprobando que `notes` no contiene `STATIC MODE`.
2. Si pasa: añadir un job de CI (solo `workflow_dispatch` o en release) que haga ese
   build y `bondy doctor`.
3. Alinear la versión de `uv` (una sola fuente: variable/ARG).
4. Anotar el resultado en `docs/improvement-plan.md` ("Sin verificar" -> verificado).

**Riesgo**: bajo (no cambia código). **Esfuerzo**: S (si Docker arranca) + S (CI).

**Verificación**: los comandos anteriores; tamaño de imagen; tiempo de `doctor`.

**Dependencias**: tras P0-3 (la imagen es la que expone el puerto).

**Resultado (2026-10-11, hecho)**: construido y probado con Docker Desktop 28.3.3 (daemon local).

| Comando | Resultado |
|---|---|
| `docker build --build-arg INSTALL_CHROMIUM=true -t bondy-p14-test:chromium .` (con `uv==0.8.13`) | OK, 3 min 10 s; imagen 2.48 GB |
| `docker run --rm bondy-p14-test:chromium bondy doctor` | exit 0, 5.8 s: `[OK] browser: Scans will use: Playwright Chromium` (playwright 1.60.0, axe-core 4.10.2); solo `[WARN] api-key` (esperado, sin key) |
| `docker run --rm bondy-p14-test:chromium bondy scan examples --no-llm` | exit 1 (hay hallazgos), 9 s: 4 archivos, 36 hallazgos, sin nota `STATIC MODE`; axe, `focus-order`, `focus-trap` y contraste ejecutados |
| `docker run -d -p 18080:8080 ...` + `POST /api/audit` (`examples/site_3_mixed_errors/index.html`, `enabled_checks` WCAG 1.4.3/3.1.1) | `/health` ok; `status: success`, `mode: no-llm`, 3 hallazgos, `notes` sin `STATIC MODE` (sin key de Gemini en el contenedor: 0 llamadas) |
| Alinear `uv`: `ARG UV_VERSION=0.11.21` en `Dockerfile` y rebuild con Chromium | OK (2 min 10 s); `uv --version` -> `uv 0.11.21`; doctor y scan idénticos |
| `docker build -t bondy-p14-test:static .` (sin build-arg) | OK; imagen 1.02 GB; `doctor` -> `[WARN] browser: ... STATIC mode`; `bondy scan examples --no-llm` y `--static --no-llm`: 16 hallazgos (solo checks HTML) y nota `STATIC MODE` como antes |

Cambios: `Dockerfile` (`ARG UV_VERSION=0.11.21`, mismo valor que `ci.yml`; nueva fuente única por ARG, el
valor de `ci.yml` sigue siendo literal y hay que mantener ambos a mano) y `.github/workflows/ci.yml`
(trigger `workflow_dispatch` y job `docker`: build con Chromium, `bondy doctor` y
`bondy scan examples --no-llm`; exige "Playwright Chromium" en doctor, exit 1 en el scan y ausencia de
`STATIC MODE`; corre en push a main y a demanda, no en PRs). Los pasos `run` del job se simularon
localmente con `bash -e` contra la imagen (positivo OK; contra la imagen sin Chromium falla, como debe).
YAML validado con `yaml.safe_load`.

**Hallazgos / no resuelto**

- **Usuario no root: no soportado todavía.** La imagen corre como `root` y Playwright instala en
  `/root/.cache/ms-playwright`. `docker run --user 1000:1000 ... bondy doctor` da `[WARN] browser: No
  usable browser` (STATIC) y `[FAIL] write-access: Cannot write to /code`. Si se quiere `USER` no root:
  fijar `PLAYWRIGHT_BROWSERS_PATH=/ms-playwright` antes de `playwright install`, `chown` de `/code` y
  HOME escribible. No se hizo (cambia el modelo de permisos de Cloud Run y de `/api/apply-fix`).
- Chromium como root arranca sin problemas en el contenedor (el lanzador de `browser.py` funciona);
  no se investigó el flag `--no-sandbox` porque no hizo falta.
- Sin `HEALTHCHECK` (la imagen slim no trae `curl`; haría falta `python -c urllib`). `bondy doctor` ya
  valida la imagen en CI. Pendiente opcional.
- Falta un test que compare las versiones de `uv` de `Dockerfile` y `ci.yml` (`tests/unit/test_ci_files.py`
  tenía cambios de otro agente; no se tocó).
- Sin verificar: ejecución real del job `docker` en GitHub Actions (solo local). Anotar en
  `docs/improvement-plan.md` ("Sin verificar" -> verificado) queda para el commit `docs:`
  (no se editó ese archivo en esta pasada).

### P1-5. Contrato público desalineado con la realidad (hallazgo nuevo, documental)

- `bondy/app_utils/security.py:4-8,15`: `ALLOWED_SOURCES` es una constante **muerta**
  (solo se cita en el docstring y en `.agents/AGENTS.md:9`); el código real permite
  cualquier ruta bajo `examples/`. Eliminar la constante y corregir ambos textos.
- `security.py:34`: `resolved_path.startswith(base_dir)` sin separador (prefijo
  `/code` vs `/code-evil`); inocuo porque el chequeo posterior es más estricto, pero
  debe usar `os.path.commonpath` o `Path.is_relative_to`.
- `render_page.py:2-9`/CHANGELOG: texto desfasado sobre hosts públicos (ver P0-1).

**Riesgo**: bajo. **Esfuerzo**: S. **Verificación**: `uv run pytest tests/unit -k "security or web_audit or apply" -q`.
Agrupar con P0-1 (misma zona).

---

## 4. Prioridad P2

### P2-1. `--mode agent` en la CLI (pendiente 2)

**Estado verificado**: `rg "mode|agent" bondy/cli.py` no muestra ningún modo; el agente
(`bondy/agent.py`) solo es alcanzable por la web (ADK) y por `eval_config.yaml`.

**Recomendación**: **no implementarlo ahora**. La ruta por código (`run_scan`) es la
soportada, determinista y con topes/caché; un modo agente duplicaría el pipeline sin
presupuesto de peticiones (`--max-requests`/`--max-usd` no aplican al bucle de ADK) ni
reportes SARIF. Alternativas, en orden: (a) documentar que el agente es experimental y
se ejecuta con `adk web`/`eval`; (b) si se quiere, `bondy scan --mode agent` como
envoltorio fino que ejecuta el `Runner` de ADK sobre un archivo y emite el JSON del
agente, marcado como experimental, sin baseline ni topes.

Decidir junto con P0-3 si el agente sigue siendo una superficie soportada; si no, se
puede degradar a extra `agent` solo para evaluación (y eliminar `fetch_image.py` y
parte de `vision_tools`, ver P2-6).

**Riesgo**: medio. **Esfuerzo**: L (b) / S (a). **Verificación**: (a) revisión de
README; (b) test con `FakeProvider` no es posible (ADK usa su propio cliente); sería
solo humo. **Dependencias**: P0-3, P1-1.

### P2-2. Acoplamiento `server` -> `agent` y módulos grandes

- `pyproject.toml` (comentario de `server`): "Requires `agent` as well today"; la UI
  y `/api/audit` no necesitan ADK, solo el montaje de P0-3. Al hacer opcional el
  montaje, separar extras (`server` sin `agent`) reduce la instalación y la superficie.
- Módulos y funciones grandes (métricas de hoy):

| Ubicación | Métrica | Propuesta |
|---|---|---|
| `core/pipeline.py::run_scan` (`:322`) | CC ~63, 197 líneas, 11 parámetros | Extraer fases (`_prepare`, `_scan_pages`, `_semantic_stage`, `_finalize`) y un `ScanContext`; sin cambiar el orden ni las salidas |
| `core/semantic.py::analyze_images` (`:511`) | CC ~39, 114 líneas | Separar triage, agrupación en lotes y aplicación de resultados |
| `core/formats.py` (628 líneas, 5 renderizadores) | Módulo grande | Paquete `formats/` (`terminal`, `markdown`, `html`, `sarif`) con la misma API pública |
| `cli.py::build_parser` | 156 líneas | Un helper por subcomando |
| `scan.py` (551 líneas) | Mezcla descubrimiento, carga, ejecución y fallbacks estáticos | Dividir en `discovery.py` y `runner.py` (después de P1-2) |
| `core/estimate.py::estimate_scan` | 107 líneas, repite la preparación de `run_scan` | Reutilizar el helper `_prepare` |

**Riesgo**: medio (refactor puro; la red de seguridad son 492 tests y los golden de
formato). **Esfuerzo**: L en total; hacer un archivo por rama. **Verificación**:
`uv run pytest tests/unit -q`, `uv run ty check bondy`, comparar `bondy scan examples --format json`
antes/después (byte a byte, con `--no-llm`). **Dependencias**: tras P1-2 para `scan.py`;
`run_scan` tras P1-1.

### P2-3. `app.js`: fallback heurístico muerto (pendiente 6, resto)

**Estado verificado**: el mapeo checks -> WCAG de la UI ya salió de `app.js`
(`/api/checks`; `web_audit.py:72-74,102-104` siempre envía `wcag` y `title`). Lo que
queda es `classifyFinding` (`bondy/resources/web/app.js:662-721`): ~60 líneas que
adivinan WCAG por texto (`id.includes('img')`...). La primera rama (`fix.wcag && fix.title`)
siempre se cumple con el servidor actual, así que el resto es código muerto y una
segunda fuente de verdad potencial.

**Cambio propuesto**: reducir `classifyFinding` a la rama con datos del servidor y
un valor por defecto "Best practice"; eliminar las ramas heurísticas.
**Riesgo**: bajo. **Esfuerzo**: S. **Verificación**: `tests/unit/test_web_audit.py` +
revisión en navegador real (pendiente de P1 del plan original: "UI en un navegador
real"; dejar la comprobación manual con `BONDY_NO_LLM=1`). **Dependencias**: ninguna.

### P2-4. Deuda menor de la capa web y utilidades

- `fast_api_app.py:162`: `from collections import defaultdict` a mitad de archivo y
  `file_locks` crece sin límite (un `Lock` por ruta tocada). Mover imports y usar un
  `dict` con limpieza o un único lock global (el endpoint es local y poco concurrente).
- Lógica de negocio en el handler `apply_fix` (`fast_api_app.py:166-232`): extraer a
  `bondy/core/apply_fix.py` (puro, testeable sin FastAPI).
- `# ruff: noqa` global en `agent.py:1` y E402 en `fast_api_app.py:14` (Fase F2
  abierta): reordenar imports y quitar el `noqa` de archivo.
- `vision_tools._quota_retry_delay = quota_retry_delay  # legacy name`
  (`vision_tools.py:36`): solo lo usan 2 tests; migrarlos a `alt_rules.quota_retry_delay`
  y eliminar el alias. **HECHO con P1-1** (también los imports de `fast_api_app.py` y su
  `noqa: E402`; queda `agent.py`).

**Riesgo**: bajo. **Esfuerzo**: S-M. **Verificación**: `ruff check`, `ruff format --check`,
`uv run pytest tests/unit -q`. **Dependencias**: tras P0-3 y P1-1 (mismo archivo).

### P2-5. Plantillas JSX/Vue (E7) y Batch API (B8) (pendiente 7)

Siguen sin empezar y son trabajo de producto, no refactor; ver `docs/improvement-plan.md`
(E7 y B8, esfuerzo L, v2).

- **E7**: el camino de menor costo es auditar el HTML ya renderizado
  (`--build-dir dist/`) en lugar de parsear JSX/Vue; los hallazgos no tienen línea de
  origen (documentar). Prerrequisito: P2-2 (descubrimiento separado).
- **B8**: `LLMProvider` (`core/providers/base.py`) no tiene noción de trabajos
  diferidos. Prerrequisito de diseño: un Protocol `BatchCapable` (enviar / consultar /
  recuperar) y reutilizar `resume.json`. Sin ese diseño, no empezar.

Recomendación: mantener fuera del alcance hasta cerrar P0 y P1.

### P2-6. Código duplicado del modo agente

`bondy/app_utils/vision_tools.py` (305 líneas) reimplementa lo que ya hay en el núcleo:

| Duplicado | En el núcleo |
|---|---|
| `_generate` (reintento por cuota + modelo de respaldo, `:56-86`) | `core/providers/base.py` + `gemini.py` |
| `_load_image` (`:88-115`; búsqueda de archivo por sufijo, ambigua) | `core/images.py::load_image` |
| `fetch_image.py` (skill) | `core/images.py::_load_remote` |
| Heurísticas decorativas y reglas alt | ya compartidas en `core/alt_rules.py` (bien) |

**Cambio propuesto**: hacer que `vision_tools` sea un adaptador fino sobre
`GeminiProvider` + `load_image` (misma firma pública para el agente) y eliminar
`fetch_image.py`. **Riesgo**: medio (cambia la ruta del agente, que solo tiene tests de
heurísticas y humo). **Esfuerzo**: M. **Verificación**:
`uv run pytest tests/unit/test_vision_tools.py tests/unit/test_shared_rules.py -q` y
evaluación manual con `agents-cli eval` solo si hay cuota (no gastar cuota de Gemini
sin pedirlo). **Dependencias**: P0-1, P1-1; si P2-1 degrada el agente, es el momento
de decidir qué se conserva.

### P2-7. Pendientes menores heredados de la Fase F

Abiertos según `docs/improvement-plan.md` ("Abierto en Fase F"): F2 (`# ruff: noqa`,
cubierto en P2-4), F3 (golden de formatos), F4, F6, F7 y un test de instalación en venv
limpio como paso de CI. `mcp_server/github_server.py` sigue sin uso por el pipeline
(CHANGELOG:158 anota el `token` expuesto como argumento de herramienta): decidir si se
retira o se corrige (`token` solo por `GITHUB_TOKEN`).

---

## 5. Orden de ejecución sugerido y agrupación

| Orden | Rama / commit | Ítems | Esfuerzo | Notas |
|---|---|---|---|---|
| 1 | `fix/ssrf-image-fetch` | P0-1 + P1-5 | M | Seguridad primero; un commit por ítem |
| 2 | `ci/hardening` | P0-2 + P1-3 — HECHO (job de P1-4 pendiente, ver P1-4) | S-M | Solo YAML, tipos y tests |
| 3 | `fix/server-attack-surface` | P0-3 | M | Decide el destino del agente ADK |
| 4 | `refactor/settings-only` | P1-1 (y P2-4: alias legacy, imports) — HECHO | M | Tras 1 y 3 (mismos archivos) |
| 5 | `fix/page-watchdog` | P1-2 — HECHO | M-L | Rama propia, sin mezclar con otros refactores |
| 6 | `chore/docker-verify` | P1-4 | S | Requiere Docker Desktop encendido |
| 7 | `refactor/web-cleanup` | P2-3 + P2-4 (resto) | S | |
| 8 | `refactor/core-structure` | P2-2 (un archivo por commit) | L | Después del watchdog |
| 9 | Decisión de producto | P2-1, P2-5, P2-6, P2-7 | — | Tras 1-8 |

Grafo de dependencias: P0-1 -> P1-1 -> P2-6; P0-3 -> P1-1, P1-4, P2-1; P1-2 -> P2-2
(`scan.py`); P2-2 -> P2-5 (E7). Independientes: P0-2, P1-3, P2-3.

Reglas de ejecución para todas las ramas: sin cambios de contrato (JSON, SARIF, exit
codes); tests antes de tocar; `uv run ruff check`, `ruff format --check`, `ty check bondy`
(y `bondy tests` tras P1-3) y `pytest tests/unit` en verde en cada commit; no tocar
`README.md`, `.env.example` ni `docs/architecture.md` mientras tengan cambios sin
commitear (los cambios documentales de P0-2, P1-1 y P1-4 se agrupan en un commit
`docs:` posterior); actualizar `CHANGELOG.md` y `docs/improvement-plan.md` en cada rama.

## 6. Qué sigue funcionando bien (no tocar)

- Aislamiento de red del navegador (`browser.py`: guard de rutas + proxy muerto) con
  tests (`test_network_guard.py`).
- Pipeline por código con `FakeProvider`, topes duros, caché, reanudación: bien cubierto
  (492 tests sin red ni cuota).
- Fuente única de checks (`core/checks.py`) y adaptador web (`core/web_audit.py`).
- `config.py` con precedencia flag > env > archivo y rechazo de la key en `bondy.toml`.
