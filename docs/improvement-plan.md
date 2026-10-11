# Plan de mejoras — Bondy (v2: herramienta local, portable y BYOK)

## 0. Visión y principios

Bondy deja de ser "una app web con demos" y pasa a ser **una herramienta que cada desarrollador descarga, configura con su propia API key y ejecuta sobre sus proyectos**. Nada se aloja.

Principios de diseño:

1. **Local primero**: corre en la máquina del usuario; la única salida de red es hacia el proveedor de LLM que él elige.
2. **Determinista primero, LLM al final**: axe, contraste, lang, labels y focus son gratis y reproducibles; el LLM solo juzga lo que ellos no pueden (calidad del alt, decorativa/funcional, redacción del fix).
3. **Funciona sin API key** (modo `--no-llm`) y **con la key del usuario** para el análisis semántico.
4. **Costo predecible**: estimar antes de gastar, topes duros, caché y batch.
5. **Nunca modifica archivos sin que se pida**; todo cambio es un diff reversible.
6. **Falla con gracia**: resultados parciales, errores accionables, nada de cuelgues.

Fuentes de datos externos verificadas (documentación oficial de Gemini API): límites por tier, precios, Batch -50%, caché de contexto implícita, y que el contenido del free tier se usa para mejorar productos de Google (relevante para la privacidad).

---

## 1. Estado actual (revisado)

Hecho antes de la Fase A (33 tests unitarios pasaban, `ruff check` limpio):

| Cambio | Archivo | Estado |
|---|---|---|
| En auditorías solo de WCAG 1.1.1 se omiten axe y `analyze_rendered_page` | `fast_api_app.py::_skip_note`, `agent.py` | Aplicado |
| Reintento de la petición fallida (429/503) en el agente | `agent.py`, `fast_api_app.py` (`retry_options`) | Aplicado |
| Reintento en visión respetando el retraso; no reintentar si la cuota es diaria | `vision_tools.py::_quota_retry_delay` | Aplicado |
| Error claro (429) cuando la cuota diaria se agotó, sin 4 reintentos inútiles | `fast_api_app.py` | Aplicado |
| Tests de lo anterior | `tests/unit/test_latency_controls.py` | Aplicado |

Hallazgos de la medición (site 1, solo alt text): ~12 peticiones por escaneo; cuota gratuita observada de 5/min y 20/día por modelo; un reintento reiniciaba toda la auditoría. Pendiente de re-medir cuando se restablezca la cuota.

**Fase A ejecutada en la rama `refactor/package-bondy`** (sin commitear; 59 tests unitarios pasan, `ruff check` limpio): ver el estado por tarea en la sección 4.

Deuda de portabilidad detectada (nueva), con su estado tras la Fase A:

- ~~El paquete se llama `app`~~ -> renombrado a `bondy` (A1).
- ~~`.agents/skills/` y `web/` fuera del paquete~~ -> ahora en `bondy/resources/` y presentes en el wheel (A1). **Pendiente**: `demo_sites/` sigue fuera del paquete y `security.py`/`render_page.py`/`vision_tools.py` aún resuelven `demo_sites/` desde la raíz del repo (Fase D1).
- ~~Rutas relativas al cwd~~ -> resueltas con `importlib.resources` (`bondy/resources/__init__.py`) (A1).
- ~~Dependencias de nube en el núcleo~~ -> movidas al extra `gcp`; Cloud Logging es opt-in con `BONDY_CLOUD_LOGGING=1` (A2).
- ~~`load_dotenv(override=True)`~~ -> `override=False` (A4).
- Solo acepta rutas dentro de `demo_sites/` en la web/API (la CLI `scan` acepta cualquier ruta local pasando el contenido como HTML crudo). Pendiente: Fase D1.
- ~~Sin CLI ni códigos de salida~~ -> `bondy scan --no-llm` y `bondy doctor` (A3/A5, MVP).

---

## 2. Decisiones (aprobadas por el usuario)

Principio rector confirmado: **lo determinista se resuelve con scripts; el modelo se reserva para lo que requiere razonamiento** (juzgar si un alt es correcto, decorativa vs. funcional, redactar el texto).

| # | Decisión | Resolución |
|---|---|---|
| D1 | Pipeline por código por defecto; el `LlmAgent` queda como `--mode agent`. Al implementarlo hay que **actualizar la regla 3 de `.agents/AGENTS.md`**. | Aprobada |
| D2 | Gemini primero, interfaz `LLMProvider` mínima. | Aprobada |
| D3 | v1: HTML + carpeta de build + URL localhost; plantillas en v2. | Aprobada |
| D4 | Renombrar paquete `app` → `bondy` en un PR aislado. | Aprobada |

---

## 3. Arquitectura objetivo

```
bondy/
  core/            # sin FastAPI ni ADK: discover, scan, findings, fixes, cost
    discover.py    # encuentra archivos/páginas del proyecto
    scanners/      # axe, contrast, focus, lang, labels (deterministas)
    semantic/      # alt text + decorativas (LLM, en lote, con caché)
    fixes.py       # generación y aplicación de parches (diff)
    budget.py      # estimación y topes de costo
    cache.py       # .bondy/cache
    providers/     # gemini.py (+ interfaz)
  cli.py           # `bondy scan|fix|serve|doctor|estimate`
  server.py        # UI web local opcional (127.0.0.1)
  agent_mode.py    # BondyAccessibilityAgent (ADK), opcional
  resources/       # skills, fix_patterns.md, web/ (package data)
examples/          # antes demo_sites/
```

Flujo por defecto (`bondy scan ./mi-proyecto`):

1. **Descubrir** páginas (respeta `.gitignore` + `bondy.toml`).
2. **Escáneres deterministas** en **un solo navegador reutilizado**, páginas en paralelo con límite.
3. **Semántico (solo si hay key y no `--no-llm`)**: imágenes únicas por hash, **varias por petición**, un solo prompt común (aprovecha caché de prefijo), modelo barato primero y escalada solo si `confidence: low`.
4. **Fixes**: plantillas deterministas donde se pueda (`alt=""` decorativa, `lang`, `for`/`id`), LLM solo para redactar alt.
5. **Reporte**: terminal, JSON, Markdown, HTML, SARIF; código de salida según `--fail-on`.

Efecto esperado sobre peticiones: de ~12 por página de 2 imágenes a **1-2** (una por lote de imágenes más, a lo sumo, una de generación).

---

## 4. Fases

### Fase A — Cimientos portables (P0)

Estado en la rama `refactor/package-bondy` (sin commitear).

| # | Tarea | Estado | Notas / desviaciones |
|---|---|---|---|
| A1 | Renombrar `app/` → `bondy/`; recursos a `bondy/resources/` con `importlib.resources`. | **Hecho** | `git mv`; el wheel contiene `resources/` (verificado). Subpaquete `app_utils` se mantiene (renombrado mecánico). Nombre de la `App` ADK y `app_name` pasan de `"app"` a `"bondy"` (rutas `/apps/bondy/...`). `git-commit-formatter` salió del proyecto y quedó como skill global en `~/.claude/skills/` (no forma parte del runtime). `demo_sites/` **no** se renombró a `examples/` (lo referencian `ALLOWED_SOURCES`, tests y `security.py`; se hará con D1). `.gitignore` tenía `Bondy/`, que git (insensible a mayúsculas en Windows/macOS) aplicaba también al paquete `bondy/`: se corrigió para que los archivos nuevos no queden ignorados. `bondy --version` funciona (ver A3); `pip install .` en venv limpio: imports y recursos OK; el escaneo con navegador quedó verificado en A6 (cierre de la Fase A). |
| A2 | Dependencias por extras. | **Hecho** | Núcleo: `playwright`, `google-genai`, `pydantic` (no hizo falta `beautifulsoup4`/`lxml`). Extras `server`, `agent`, `gcp`, `mcp` (+ `eval`, `lint` existentes). El grupo `dev` incluye `bondy[server,agent]`. Telemetría apagada por defecto (documentado en README). `bondy/__init__.py` ya no importa ADK (`__getattr__` perezoso). Regla 3 de AGENTS.md actualizada. Pendiente: el servidor web aún requiere `agent` (usa ADK); desacoplarlo es parte de B2. |
| A3 | CLI: `scan`, `fix`, `serve`, `estimate`, `doctor`. | **Parcial (MVP)** | Hecho: `bondy scan <archivo\|carpeta> [--no-llm] [--format terminal\|json] [--fail-on] [--checks] [--include/--exclude] [--config]` con códigos de salida 0/1/2, y `python -m bondy`. Pendiente: `fix`, `serve`, URLs. `estimate` y `scan` con el LLM llegaron en la Fase B, entrega 1. Sin browser compartido ni paralelismo (cada escáner abre su Chromium; Fase B). |
| A4 | Configuración `bondy.toml` + env + flags. | **Hecho** | `bondy/config.py`; precedencia flag > env > archivo > default, con tests. La API key **no** se acepta en `bondy.toml`. `GEMINI_API_KEY` precede a `GOOGLE_API_KEY`. **Parcial tras la Fase B**: el pipeline nuevo (`bondy/core/providers/gemini.py`) lee `Settings` (modelo, `vision_model`, `fallback_model`) y pasa la key explícita al `Client`. Entrega 2: `vision_tools._generate` (modo agente) también pasa la key explícita desde `Settings`. Pendiente: `vision_tools.py`/`agent.py`/`fast_api_app.py` siguen leyendo `BONDY_VISION_MODEL`/`BONDY_FALLBACK_MODEL` (modelos) directamente. Presupuesto añadido en B6 (`max_*`, `price_*`, `batch_size`, `tokens_per_image`). |
| A5 | `bondy doctor`. | **Parcial** | Hecho (offline): Python, paquete/binario de Chromium, axe-core, `bondy.toml`, key presente (nunca se imprime), permiso de escritura; cada fallo da el comando. **Hecho (entrega 2)**: `bondy doctor --check-key` (opt-in, 1 petición mínima; distingue key rechazada / cuota / red); sin esa flag doctor sigue offline. |
| A6 | Navegador del sistema / modo estático. | **Hecho** | `bondy/app_utils/browser.py::launch_with_label` es el único lanzador: Chromium de Playwright, luego `channel="chrome"`, `channel="msedge"` y por último el ejecutable de Chrome/Edge encontrado en disco (`executable_path`; añadido porque en Linux `channel=chrome` solo mira `/opt/google/chrome`). Si nada arranca lanza `BrowserUnavailableError` con el comando exacto (`python -m playwright install chromium`). Lo usan los 4 escáneres Playwright, `render_page.py` y `doctor` (que ahora lanza el navegador de verdad y dice cuál se usará). **Modo estático**: si no hay navegador, `bondy scan` no falla; omite `axe`, `contrast`, `focus-trap` y `focus-order`, ejecuta `lang`, `labels`, `accessible-name` y un `img-alt` por regex (sustituto parcial de la regla `image-alt` de axe), lo declara en `notes` (`static_mode: true` y `omitted_checks` por archivo en JSON) y sale con 0/1; un error real de un escáner sigue dando 2. Verificado con el wheel en un venv limpio: ver hallazgos. |

**Cierre de la Fase A (hallazgos y verificación)**

- **Red (D6)**: antes solo `axe_scan.py` abortaba peticiones; `contrast.py`, `focus_trap.py` y `focus_order.py` no tenían ninguna protección y además hacían `page.goto()` de cualquier contenido que empezara por `http(s)://` (vía SSRF latente). Ahora los cuatro pasan por `open_page()`: solo `file://` del propio archivo temporal (y, en `render_page`, la carpeta `demo_sites/`), `data:` y `about:`; cualquier otra petición se aborta, incluidos `file://` ajenos (antes `axe_scan` permitía **cualquier** `file:`). `route()` no ve WebSockets y `route_web_socket` se cuelga con la API síncrona, así que el navegador se lanza además con un proxy muerto (`--proxy-server=http://127.0.0.1:1`, `<-loopback>`): lo que el guard no vea no puede conectar. Los tests (`tests/unit/test_network_guard.py`) registran peticiones en un servidor local con `<script>`, `<link>`, `<img>`, `<iframe>`, `fetch` y `WebSocket`: 0 peticiones por escáner, y un test de control demuestra que sin guard sí llegan.
- **`render_page.py`**: por diseño conserva **hosts http(s) públicos** (verificados con `validate_public_url`) para que la captura de visión muestre imágenes remotas; es la única excepción a "solo local" y queda pendiente de decisión del usuario (¿bloquearlos también y renderizar sin imágenes remotas?). La verificación DNS no protege contra DNS rebinding. **Superado (2026-10-11, P0-1 de `docs/refactor-plan.md`)**: `render_page.py` ya no permite hosts http(s) (ver la decisión posterior de "solo local") y toda descarga remota pasa por `bondy/core/netguard.py::fetch_public_bytes`, que fija la IP validada y revalida cada redirección.
- **Importación de los scripts**: los scripts de skills importan `bondy.app_utils.browser`; si se ejecutan sueltos añaden la raíz del paquete (`parents[5]`) a `sys.path`. Verificado con el wheel y con `python -I script.py` desde otro directorio.
- **Wheel**: `uv build --wheel` -> venv limpio fuera del repo (Python 3.12, Playwright 1.63.0 resuelto por pip) -> desde otro directorio: `bondy --version`, `bondy doctor`, `bondy scan demo3.html --no-llm`. En esa máquina el Chromium cacheado era de Playwright 1.60, no el de 1.63, así que el fallback a **Chrome del sistema (`channel=chrome`) funcionó de verdad**; el modo estático solo se probó con el lanzador simulado (no se desinstaló Chrome).
- **Formato**: `scan.py`, `doctor.py` y `cli.py` ya figuraban sin formatear en la línea base; se formateó solo `browser.py`, los dos tests nuevos y los archivos tocados cuando el diff afectaba solo líneas propias.

### Fase B — Costo y eficiencia (P0)

| # | Tarea | Esfuerzo | Criterio |
|---|---|---|---|
| B1 | **Modo `--no-llm`** (axe + skills deterministas). Es el valor base sin key. | S | Salida completa sin red. **Hecho** (fase A). |
| B2 | **Pipeline por código** (ver D1): sin turnos de agente para escáneres; prompts cortos. | L | ≤2 peticiones por página típica. **Hecho (entrega 1)**: `bondy/core/` (ver "Cierre de la Fase B, entrega 1"). `bondy scan` sin `--no-llm` usa el pipeline; sin key cae a `--no-llm` con aviso. La interfaz `LLMProvider` + `GeminiProvider` + `FakeProvider` (D2) también está hecha. |
| B3 | **Lotes de imágenes**: N imágenes por petición con esquema JSON de salida; fusionar `verify` + `classify`. | M | Misma decisión (`keep`/`fix`/`needs_manual_review`) que hoy en los 3 demos (tests golden). **Hecho (entrega 1)**: lotes de `batch_size` (def. 8), una llamada fusionada, dedup por (src, alt), plantillas deterministas, 1 reintento por JSON inválido. El "golden" se hizo como **paridad con `decide_alt_recommendation`** (rejilla alt x match x confianza) y no contra Gemini real (sin cuota): ver hallazgos. |
| B4 | **Caché** `.bondy/cache` por hash(imagen + alt + modelo + versión de prompt). Invalidación al cambiar prompt/modelo. | M | Segundo escaneo = 0 peticiones. **Hecho (entrega 2)**: `bondy/core/store.py`; clave = hash(bytes de la imagen + alt + contexto/lang/señales enviados + modelo + `PROMPT_FINGERPRINT`, que cubre el texto del prompt, su versión y el esquema JSON). Escritura atómica, entradas ilegibles = miss, sin key ni rutas absolutas. `--no-cache`, `--clear-cache`, `--cache-dir`, `bondy cache clear`. |
| B5 | `bondy estimate`: cuenta imágenes/páginas/tokens y muestra **rango de costo** con precios configurables antes de gastar; `--dry-run`. | M | Muestra "N peticiones, ~X tokens, ~$Y". **Hecho (entrega 1)**: `bondy estimate <ruta>` y `bondy scan --dry-run` (`bondy/core/estimate.py`); no llama al modelo ni descarga imágenes remotas. Es una estimación (caracteres/4 + `tokens_per_image`); no hay precios por defecto: sin configurarlos el costo en dólares figura como no disponible. |
| B6 | **Topes duros**: `--max-requests`, `--max-usd`, `--max-pages`, `--max-images`; al llegar al tope, se detiene y entrega parcial. | S | Test que fuerza el tope. **Hecho (entrega 1)**: resultado PARCIAL con motivo y código de salida 3 (ver hallazgos). `--max-requests` cuenta también los reintentos internos (429). |
| B7 | **Escalado de modelo**: barato por defecto, caro solo si baja la confianza; configurable. | S | Métrica de cuántas escalan. |
| B8 | **Batch API opcional** (`--batch`, -50%, hasta 24 h) para repos grandes/CI nocturno; con `bondy fetch <job>`. | L | Job reanudable. |
| B9 | **Escaneo incremental**: solo archivos cambiados (hash o `git diff`). | M | Re-escaneo sin cambios = 0 peticiones. **Hecho (entrega 2)**: `--changed-only` (hash del HTML + hash de las imágenes locales que referencia; invalida al cambiar versión de Bondy, checks, modelo, escáneres, `--static` o el prompt) y `--since <ref>` (git; esas páginas se escanean; las demás reutilizan el resultado guardado si el hash y la configuración coinciden, si no salen `skipped: unchanged since <ref> (no saved result to reuse)`; no cuenta como parcial). |
| B10 | Gestión de cuotas: distinguir 429 por minuto (esperar `retryDelay`) y por día (parar y decirlo), con resultados parciales y reanudación (`--resume`). | M | Sin reinicios completos. **Hecho (entrega 2)**: la distinción 429 minuto/día ya estaba (entrega 1); ahora cuota diaria, topes, `--scan-timeout` y Ctrl+C dejan `resume.json` + páginas completas + veredictos en caché, y `--resume` no repite peticiones. Ctrl+C termina con gracia (exit 3). |

### Cierre de la Fase B, entrega 1 (B2, B3, B5, B6 + `LLMProvider`)

Rama `feat/pipeline-no-llm` (sin commitear). Estado: 183 tests unitarios pasan, `ruff check .` limpio (tras aplicar las decisiones del usuario de abajo). La entrega 2 (caché, incremental, reanudación) está en la sección siguiente. **Nada se verificó contra Gemini real** (cuota diaria agotada): todos los tests usan `FakeProvider`/mocks.

**Qué se construyó** (`bondy/core/`, sin FastAPI ni ADK)

| Módulo | Responsabilidad |
|---|---|
| `checks.py` | Fuente única de qué checks existen y su mapeo WCAG; `scan.py` y `fast_api_app.py` (instrucción "audita todo") leen de aquí. |
| `models.py` | Contratos entre etapas (dataclasses): `ImageOccurrence`, `ImageOutcome`, `ImageFix`, `UsageSummary`, `ScanReport`. |
| `images.py` | Extrae `<img>` (con contexto del enlace/botón que lo contiene), carga imágenes con contención en la raíz del proyecto, tope de 10 MB, detección de formato por bytes (no por extensión) y razones accionables. |
| `providers/` | `LLMProvider` (interfaz), `RetryingProvider` (política única de reintentos), `GeminiProvider` (`google-genai`, key explícita, redactada en errores), `FakeProvider` (429 minuto/día, 503, JSON inválido, timeout). |
| `semantic.py` | Triage determinista, lotes (por cantidad y por bytes), prompt con datos delimitados, validación por esquema, un reintento correctivo, decisión final en código. |
| `fixes.py` | Plantillas: `alt=""` decorativa, prefijo redundante, inserción/sustitución de `alt` en la etiqueta. |
| `budget.py` | `Pricing`, `Limits`, `UsageTracker` (peticiones HTTP reales, tokens reportados o estimados, costo). |
| `estimate.py` | `bondy estimate` / `--dry-run`. |
| `pipeline.py` | `run_scan`: escáneres -> etapa semántica -> fixes -> reporte; `exit_code`. |

**Medición de peticiones por página (proveedor simulado, NO Gemini real)**

| Sitio demo | Páginas | Imágenes | Peticiones antes (*) | Peticiones después (FakeProvider) |
|---|---|---|---|---|
| `site_1_bad_alt` | 1 | 2 | ~12 (medido en la Fase A con Gemini real) | 1 |
| `site_2_focus_trap` | 1 | 0 | 0 de visión | 0 |
| `site_3_mixed_errors` | 1 | 0 | 0 de visión | 0 |
| `retrodiner` | 1 | 7 | >=14 (2 herramientas por imagen; sin contar turnos del agente; **no medido**) | 1 |
| `demo_sites/` completo | 4 | 9 | n/d | 2 (un lote de 8 + uno de 1; el lote cruza páginas) |

(*) "Antes" es el agente ADK: cada `<img>` dispara `verify_image_alt_text` y `classify_image_decorative` (2 peticiones) más los turnos del agente. Solo el dato de `site_1` fue medido (Fase A); el resto es el mínimo teórico del diseño anterior. "Después" cuenta peticiones HTTP del `FakeProvider`; con Gemini real puede haber reintentos por 429/503 o por JSON inválido (hasta 2x por lote).

**Decisiones de diseño tomadas (revisables)**

- **Código de salida 3 = resultado parcial** (**aceptado por el usuario**; tope o cuota alcanzados) cuando no hay hallazgos al umbral; si hay hallazgos al umbral sigue siendo 1; con `--fail-on never` un parcial sale 0; los errores (2) siguen teniendo prioridad. Motivo: 2 ya significa "uso/configuración o escáner falló" y un parcial no es ninguna de las dos cosas.
- **Topes: 0/vacío = sin límite.** Decisión del usuario: `max_requests` vale **50 por defecto** (el resto sin límite); el resumen indica cuándo el tope en vigor es el valor por defecto y el aviso explica cómo subirlo (`--max-requests N` / `0`).
- **`--max-images` cuenta imágenes únicas que irían al modelo**; las resueltas por plantilla no cuentan (son gratis).
- **`--max-requests` cuenta peticiones HTTP**, reintentos por 429 incluidos (el proveedor recibe `max_attempts`); `--max-usd` se evalúa **antes** de cada lote con una estimación (precio configurado) y después con tokens reales si el proveedor los reporta.
- Con la key ausente y sin `--no-llm`: aviso explícito y ejecución determinista (`mode: no-llm`).
- Cuota diaria (`PerDay`) en todos los modelos: se detiene, las imágenes pendientes quedan `skipped` (no "revisión manual") y el resultado es parcial. Dos lotes seguidos fallidos por otra causa (503/timeout) también detienen el escaneo.
- Los hallazgos semánticos son `scanner: "alt-text"`, severidad `critical` si falta/está vacío el alt de una imagen informativa o funcional, o no coincide con la imagen; `warning` para decorativas, prefijos y revisión manual. Los `image-alt` de axe/estático ya cubiertos se retiran por coincidencia de `src` (heurística).

**Hallazgos / pendientes**

- **Imágenes remotas (decisión del usuario)**: `images.py` **descarga imágenes http(s) públicas por defecto** (host validado con `validate_public_url`, cada redirección revalidada; **sin protección contra DNS rebinding en el momento de esta decisión; resuelto el 2026-10-11**: la descarga va por `bondy/core/netguard.py::fetch_public_bytes`, que resuelve una vez, exige IP públicas y conecta a la IP ya validada, con redirecciones revalidadas, máx. 3), como ya hacía `vision_tools._load_image` (que ahora usa el mismo guard). Solo hay opt-out: `--no-remote-images` / `remote_images = false` / `BONDY_REMOTE_IMAGES`; con él esas imágenes van a `needs_manual_review` con motivo accionable y `estimate`/`--dry-run` lo reflejan. La contención de rutas locales no cambia.
- **Sin verificar con Gemini real**: que `response_schema=BatchAnalysis` (modelo anidado con lista) sea aceptado tal cual; `HttpOptions(timeout=60000)` (ms); el tope de ~20 MB por petición con imágenes inline (se usa 15 MB conservador, `MAX_BATCH_BYTES`); que GIF no sea soportado (se trata como no soportado junto con SVG/AVIF); los tokens por imagen (`tokens_per_image=1100` es un marcador).
- **Precios (decisión del usuario, opción B)**: `price_input_per_mtok`/`price_output_per_mtok` no tienen valores por defecto (`None`). Sin ellos `estimate`, `--dry-run` y el resumen muestran peticiones y tokens y declaran el costo no disponible (JSON: `cost_usd: null` + `cost_unavailable_reason`); `--max-usd` sin precios falla con código 2 antes de llamar al modelo. `tokens_per_image=1100` sigue siendo un marcador de estimación.
- **Acoplamiento (resuelto en la entrega 2)**: las reglas de grounding, heurísticas y `quota_retry_delay` viven ahora en `bondy/core/alt_rules.py`; `vision_tools` (modo agente) las importa de ahí y `bondy/core` ya no importa `vision_tools` (test en `test_shared_rules.py`).
- **`web/app.js`** tiene su propio mapeo checks->WCAG: no se unificó (cambios a la UI fuera de alcance).
- **La UI web y `/api/audit` siguen usando el agente ADK**; migrarlos al pipeline queda para una entrega posterior.
- **Calidad del alt "funcional"**: depende de que el modelo siga la regla "describe el destino, no la imagen"; no se puede verificar sin llamadas reales.
- **No empezado (fuera de alcance)**: B4 (caché), B7, B8, B9, B10, validación real de la key, timeouts globales/navegador compartido (siguiente entrega). (B4, B9, B10, validación de la key y timeouts: hechos en la entrega 2.)

### Cierre de la Fase B, entrega 2 (B4, B9, B10, key, D6, deuda)

Rama `feat/cache-and-resume` (sin commitear). 277 tests unitarios pasan, `ruff check .` limpio. Todo con `FakeProvider`/mocks; ninguna llamada a Gemini real. Chromium real solo en los tests de red/axe ya existentes y en una verificación manual local.

**Estructura de la persistencia** (todo bajo `cache_dir`, por defecto `<carpeta escaneada>/.bondy/cache`; ruta relativa = relativa a la carpeta escaneada)

| Archivo | Contenido |
|---|---|
| `verdicts/<sha256>.json` | Un veredicto del modelo por imagen (B4). |
| `pages.json` | Por página (ruta relativa): hash del HTML, hash de sus imágenes locales, hallazgos, resultados de imágenes y fixes (B9). Se invalida entero si cambia la huella de configuración. |
| `resume.json` | Marca de escaneo parcial: motivos y páginas pendientes (B10). Se borra al terminar completo. |

`bondy cache clear` y `--clear-cache` solo borran esos nombres (nunca el directorio entero). `.bondy/` se auto-ignora: Bondy escribe dentro un `.gitignore` con `*` (sin sobrescribir uno existente). Un `scan` determinista simple (`--no-llm`/`--static` sin `--changed-only`/`--since`/`--resume`) no crea nada en la carpeta escaneada.

**Decisiones de diseño tomadas (revisables)**

- **`--no-cache` desactiva toda la persistencia** (veredictos, estado de páginas y marca de reanudación); con `--changed-only`/`--resume` es un error de uso (exit 2).
- **`--resume` = `--changed-only` + marca**: reutiliza páginas completas y veredictos ya guardados; una página interrumpida se vuelve a escanear entera (sus escáneres deterministas se repiten, las peticiones no). Un lote en curso nunca se guarda a medias: se reintenta entero.
- **Una página parcial no se guarda** (imágenes `skipped` o fallo transitorio del proveedor/red); una `needs_manual_review` determinista (404, formato) sí.
- **Reutilización**: hash del HTML (bytes) + hash de los archivos de imagen locales que referencia. Las imágenes remotas se identifican solo por URL (no se descargan para decidir): si una imagen remota cambia con la misma URL, `--changed-only` no lo ve (la caché de veredictos sí, porque hashea los bytes cuando se descarga).
- **Comprobación de la key**: no hay petición extra por escaneo (rompería "re-escaneo = 0 peticiones"). La etapa semántica corre **antes** de los escáneres y el primer lote hace de comprobación: 400 `API_KEY_INVALID`/401/403 abortan con exit 2, sin reintentos ni modelo de respaldo, antes de lanzar ningún navegador. Un escaneo totalmente en caché no necesita la key.
- **Orden del pipeline**: cargar páginas -> reutilizar -> etapa semántica -> escáneres (un navegador) -> fusionar -> persistir. Los hallazgos de imágenes se fusionan después de los escáneres.
- **`--since <ref>`**: git validado (sin guion inicial ni espacios; `--` termina la lista de revisiones); esas páginas más las no rastreadas se escanean; las demás **reutilizan el estado guardado** cuando el hash del contenido y la huella de configuración coinciden (el hash manda sobre lo que diga git); si no hay resultado válido quedan `skipped: unchanged since <ref> (no saved result to reuse)`, sin marcar resultado parcial.
- **Timeouts por defecto**: `timeout = 60` s por página y `scan_timeout = 900` s; `0` = sin límite. Al vencer `scan_timeout` el resultado es parcial (exit 3) y reanudable.
- **Archivo modificado durante el escaneo**: se escanea el contenido leído una sola vez; si el hash en disco difiere al terminar, el resultado se informa pero no se guarda para reutilización.
- **Cuota/red**: `ErrorKind` nuevo `invalid_key` y `network`; mensajes distintos para cuota diaria, red caída, timeout y 503.

**Medición con `FakeProvider` (no Gemini real), copia de `demo_sites/`: 4 páginas, 9 imágenes únicas, lote 8**

| Escaneo | Páginas escaneadas / reutilizadas | Peticiones | Aciertos/fallos de caché |
|---|---|---|---|
| 1.º | 4 / 0 | 2 | 0 / 9 |
| 2.º idéntico (solo caché) | 4 / 0 | 0 | 9 / 0 |
| 2.º `--changed-only` | 0 / 4 | 0 | n/a |
| 1 archivo editado (texto), `--changed-only` | 1 / 3 | 0 | 7 / 0 |
| 1 archivo + 1 imagen nueva, `--changed-only` | 1 / 3 | 1 | 7 / 1 |

**Hallazgos / pendientes**

- **JS que gira tras cargar**: medido con Chromium real y `page_timeout=3`: `while(true){}` dentro del script de carga falla a los 3 s (`Page.goto: Timeout`); en cambio un bucle que arranca tras `load` dejó `page.evaluate` colgado ~85 s hasta que Chromium cerró la pestaña (`TargetClosedError`), sin que lo corte el timeout de Playwright. Un watchdog real exigiría matar el proceso del navegador (la API síncrona no es thread-safe) o ejecutar cada página en un subproceso; no se hizo entonces. **Hecho el 2026-10-11 (P1-2 de `docs/refactor-plan.md`)**: un `threading.Timer` por página mata el árbol de procesos del driver de Playwright. El `scan_timeout` se comprueba entre páginas, escáneres y lotes, no dentro de una evaluación bloqueada.
- Dos procesos `bondy scan` sobre la misma caché son seguros (escritura atómica con `os.replace`); `pages.json` es "el último gana" (puede perder el trabajo de página del otro, no se corrompe).
- Escribir `.bondy/` en el proyecto escaneado es un cambio de comportamiento: documentado en el README, solo ocurre cuando hace falta (LLM, `--changed-only`, `--since`, `--resume`), se auto-ignora con su propio `.gitignore` y es desactivable con `--no-cache`/`cache = false`.
- **Limitación conocida (decisión original: no implementar watchdog duro; revertida el 2026-10-11, ver "Cierre del plan de refactor")**: un bucle JS que arranca tras `load` bloquea `page.evaluate` hasta que Chromium cierra la pestaña (~85 s medidos); `--scan-timeout` solo se comprueba entre páginas/escáneres/lotes. Mitigación: `--scan-timeout` + `--resume`. Un subproceso por página o matar el navegador desde un hilo añade complejidad y costo de rendimiento para un caso raro.
- El `PROMPT_FINGERPRINT` no cubre `decide()`/plantillas (cambian la decisión, no el veredicto del modelo), por eso la reutilización de páginas se invalida con la versión de Bondy.
- Sin verificar con Gemini real: el texto exacto de los errores 400/401/403 (la clasificación se basó en los formatos documentados de `google-genai`, `API_KEY_INVALID`, `PERMISSION_DENIED`, `UNAUTHENTICATED`), `max_output_tokens=4` en la comprobación de la key y que `models.generate_content` rechace con 400 una key inválida sin cobrar.

### Cierre de la Fase E (entrega 3: E1-E5 y D3)

Rama `feat/cache-and-resume` (sin commitear; se apila sobre la entrega 2). 410 tests unitarios pasan (1 omitido a propósito: validación contra el esquema SARIF oficial, ver abajo) y `ruff check .` limpio. Todo determinista: ninguna llamada nueva al modelo; los tests usan `FakeProvider`/escáneres simulados.

**Qué se construyó** (`bondy/core/`)

| Módulo | Responsabilidad |
|---|---|
| `report.py` | Modelo único (`Report`, `Item`, `Suppression`, `BaselineInfo`): un `Item` por elemento afectado, rutas relativas con `/`, huella estable (regla + ruta + selector/fragmento normalizado, sin línea; duplicados con sufijo `~n`), línea asignada por el índice del HTML cuando el elemento es único, `exit_code`, `summary` y `next_step`. |
| `formats.py` | Renderizadores terminal / JSON / Markdown / HTML / SARIF; solo presentan el modelo y escapan por formato. |
| `source.py` | Índice de elementos del HTML (etiqueta+atributos normalizados, línea) para localizar hallazgos y objetivos de `bondy-ignore`. |
| `dedupe.py` | Fusiona hallazgos del mismo problema sobre el mismo elemento (axe / axe-tree / accessible-name / labels; axe color-contrast / contrast) antes de supresiones y baseline; conserva `merged_from` y las huellas originales. |
| `baseline.py` | Crear/cargar/aplicar baseline (versión 1, determinista, sin fecha), resueltos y "no reevaluados". |
| `suppress.py` | Comentarios `bondy-ignore` y `[[ignore]]`: validación, aplicación, obsoletas. |
| `redact.py` | `redact_secrets`, `contains_secret`. |

**Decisiones de diseño tomadas (revisables)**

- **Granularidad**: un `Item` por nodo de axe (antes un hallazgo con `nodes`). Cambia la forma del JSON (documentado en CHANGELOG). Las huellas y el baseline operan por elemento.
- **Huella**: `sha256(regla, ruta relativa, selector || fragmento || mensaje normalizado)[:32]`. Dos elementos idénticos en la misma página comparten clave y se distinguen por orden (`~2`); si se inserta uno idéntico antes, el "nuevo" puede ser cualquiera de los dos (inherente).
- **`regla`** = id de regla de axe, o el nombre del escáner de Bondy (`contrast`, `lang`, `labels`, `alt-text`...). Las supresiones aceptan ese id o un criterio WCAG (`1.4.3` / `WCAG 1.4.3`).
- **SARIF**: solo contiene los hallazgos nuevos. Los baselined/suprimidos no se emiten porque la documentación de GitHub (verificada) no menciona `suppressions` ni `baselineState`; los conteos van en `runs[0].properties.bondy`. `uri` es relativa a la carpeta escaneada con `uriBaseId: %SRCROOT%`; GitHub resuelve desde la raíz del repositorio, así que se añadió `--sarif-prefix` (la action lo calcula).
- **`--output`**: el archivo recibe el formato elegido y stdout el resumen de terminal (o solo "Report written to" si el formato ya es terminal). El código de salida no cambia.
- **Baseline create** rechaza escribir si el escaneo tuvo errores (exit 2) o es parcial (exit 3). El archivo por defecto es `bondy-baseline.json`. Un baseline de `bondy.toml` se resuelve relativo a ese archivo; por flag/env, relativo al cwd.
- **"Resueltos"**: solo cuentan entradas cuyo archivo se escaneó completo, cuyo escáner corrió (modo con/sin navegador, con/sin modelo) y sin `--checks` que lo excluya; el resto va a `not_evaluated`. Un archivo borrado no se declara resuelto.
- **Supresión**: se aplica antes que el baseline; un hallazgo suprimido nunca entra en `baseline create`. Un comentario se ata al elemento por firma de etiqueta (tag + atributos) o por selector simple y único; elementos idénticos se suprimen juntos; hallazgos sin elemento (p. ej. `focus-trap`) solo se suprimen por `[[ignore]]`, salvo los de nivel de página con un comentario antes de `<html>`.
- **Obsoletas**: solo se declaran cuando el escaneo fue completo, sin `--checks`, y el archivo se evaluó entero (sin errores/omitidos); si no, quedan `unverified` y no se listan como obsoletas. Una regla bien formada pero inexistente aparece como obsoleta ("no finding matched"): no se enumeran las reglas de axe offline (se intentó extraerlas de `axe.min.js` y la lista salió incompleta), así que no se rechaza por nombre.
- **Glob de `[[ignore]]`**: se rechaza lo absoluto, `~`, unidades de disco y cualquier segmento `..`; `\` se normaliza a `/`.
- **Redacción**: antes de truncar, sobre alt y contexto enviados (esto también alimenta la clave de la caché), sobre los textos de los reportes (después de calcular la huella) y como comprobación al guardar `pages.json`: si el resultado de una página contiene texto con aspecto de secreto **no se guarda** (se reescanea; sus veredictos siguen en caché, así que no cuesta peticiones). No se añadió `--no-redact`: un falso positivo solo recorta algo de contexto, y un interruptor que envía secretos no aporta nada que el usuario necesite.
- **Terminal**: los caracteres de control de datos del proyecto se sustituyen por `?` (inyección de secuencias ANSI).
- **HTML del reporte**: CSS inline, sin JS, `<meta CSP default-src 'none'>`, landmarks (`header`/`main`/`footer`), `lang="en"`, tablas con `caption`/`scope`, colores AA comprobados por test (claro y oscuro).

**CI (E3)**: `action.yml` (composite), `.pre-commit-hooks.yaml`, `docs/ci-example.yml` (no activo). Verificado con `git ls-remote` contra los repos oficiales: `github/codeql-action` v4.38.3 -> `24c54180a607b1449ed407dd24f251e4e9147c8d`; `actions/setup-python` v7.0.0 -> `5fda3b95a4ea91299a34e894583c3862153e4b97`; `actions/checkout` v7.0.1 -> `3d3c42e5aac5ba805825da76410c181273ba90b1`. **No se ejecutó en GitHub**: la action y el hook solo se validaron como YAML y por tests de estructura/semántica (el hook se probó con `--since HEAD` en un repo temporal). TODO explícito: la coordenada `owner/repo@ref` con la que se consumirá la action (`docs/ci-example.yml` usa `uses: ./`) y la URL del repositorio en `.pre-commit-hooks.yaml` no existen todavía.

**Hallazgos / pendientes**

- SARIF validado contra el esquema oficial de OASIS (`sarif-schema-2.1.0.json`, descargado de docs.oasis-open.org; 0 errores con `jsonschema` Draft 4) sobre la salida real de `demo_sites/site_3_mixed_errors`. El esquema **no** está vendorizado ni la prueba corre por defecto (`BONDY_SARIF_SCHEMA=<ruta>` la activa); el test por defecto es estructural estricto.
- Sin verificar con GitHub real: que las rutas con `--sarif-prefix` se asocien a archivos del repositorio, que `partialFingerprints` desduplique entre ejecuciones, y el comportamiento de la action (instalación con `pip install $GITHUB_ACTION_PATH`, Chromium con `--with-deps`).
- El pre-commit hook usa `entry: bondy scan . --since HEAD`: escanea la raíz del repositorio y necesita al menos un commit; para subcarpetas hay que copiar el hook. `scan` acepta una sola ruta (no los nombres de archivo que pre-commit pasaría).
- Redacción por patrones: no cubre formatos inusuales, secretos dentro de píxeles de imagen ni los cortados por la ventana de contexto (2000 caracteres al extraer). La respuesta del modelo (veredicto) no se redacta: si una imagen muestra un secreto el modelo podría reproducirlo en `visible_content`/`suggested_alt`.
- `render_usage`/resumen de terminal pasaron de `cli.py` a `formats.py`; el progreso en vivo por página/imagen (E5) sigue sin implementar.
- `estimate` acepta los nuevos `--format` pero solo distingue `json`; otros formatos imprimen texto.
- Los hallazgos de una página reutilizada (`--changed-only`) se tratan igual que los recién escaneados para baseline/supresión (se aplican al construir el reporte, no se guardan).

### Fase C — Casos extremos y robustez (P0/P1)

Cada fila debe tener un test con fixture en `tests/fixtures/edge/`.

**Entrada y proyecto**

| Caso | Comportamiento esperado |
|---|---|
| Proyecto vacío / sin HTML | Mensaje claro, código de salida 0 con "nada que escanear". |
| Miles de archivos | Tope configurable, muestreo y aviso; concurrencia limitada. |
| `node_modules`, `.git`, `dist` ignorados por defecto; `.gitignore` respetado | Configurable en `bondy.toml`. |
| Archivos binarios, enormes (>2 MB) o minificados en una línea | Saltar o fragmentar con aviso; anclar por posición, no por texto. |
| Codificaciones (UTF-8 con BOM, Latin-1) y saltos CRLF/LF | Detectar, conservar al escribir. |
| Fragmentos/parciales sin `<html>`, plantillas con `{{ }}`, `<% %>` | No reportar `lang`/título faltantes; marcar como fragmento. |
| Rutas con espacios, OneDrive, rutas largas de Windows, symlinks | Normalizar; no seguir symlinks fuera del proyecto. |
| Archivos de solo lectura, bloqueados o modificados durante el escaneo | Detectar por hash antes de escribir; error legible. |

**Contenido de la página**

| Caso | Comportamiento esperado |
|---|---|
| Miles de imágenes / duplicadas | Deduplicar por `src`+hash, tope, informar cuántas se omitieron. |
| `srcset`, `<picture>`, `data-src` (lazy), fondos CSS, SVG inline, `data:` URIs | Resolver o marcar "no verificable" sin inventar. |
| Imágenes 404, protegidas, enormes, tipo MIME no imagen, AVIF/SVG no soportado por visión | `needs_manual_review` con motivo, sin reventar el lote. |
| Rutas raíz `/img/x.png` y relativas | Resolver contra la raíz del proyecto/servidor. |
| Contenido dinámico (SPA), modales, banners, carga tardía | Espera configurable; soporte de URL de dev-server; documentar límites. |
| Páginas con login | Fuera de alcance v1; permitir `--storage-state` de Playwright. |
| iframes y shadow DOM | axe los cubre; documentar lo que no. |
| Idiomas/RTL | El alt sugerido en el idioma del `lang` de la página. |

**LLM y red**

| Caso | Comportamiento esperado |
|---|---|
| Sin key / key inválida / sin red | `doctor` y mensaje accionable; cae a `--no-llm` con aviso explícito. |
| JSON inválido o truncado del modelo | Validar con esquema, **un** reintento con el error; si falla, `needs_manual_review`. |
| El modelo "inventa" un `before` que no existe | Verificar contra el archivo; si no aparece, localizar por selector/posición o descartar el fix. |
| Alucinaciones en alt | Mantener reglas de grounding y confianza; nunca autoaplicar con `confidence: low`. |
| Prompt injection en el HTML/alt/comentarios | Contenido delimitado como dato; sin herramientas que escriban o naveguen; salida validada. |
| Ctrl+C / corte a mitad | Guardar parcial en `.bondy/`; `--resume`. |
| Offline o proveedor caído | Reintentos acotados y reporte parcial. |

**Aplicación de fixes (`bondy fix`)**

| Caso | Comportamiento esperado |
|---|---|
| Fragmento ambiguo (aparece N veces) | Anclar por línea/columna u ofrecer parche manual; nunca "reemplazar el primero". |
| Árbol de git sucio | Negarse salvo `--force`; sugerir commit/stash. |
| Escritura | Atómica (archivo temporal + rename), `.bak` opcional, modo `--diff` por defecto y `--write` explícito. |
| Fix que rompe el HTML | Re-parsear tras aplicar; revertir si el resultado no es válido o introduce nuevas violaciones. |

### Fase D — Seguridad adaptada al modelo local (P0)

El modelo de amenaza cambia: ya no es "un tercero ataca mi servidor", sino "un proyecto/HTML hostil o mis datos salen a un proveedor".

| # | Tarea | Esfuerzo | Criterio |
|---|---|---|---|
| D1 | Escritura solo dentro de la raíz del proyecto (resolve + `is_relative_to`, sin symlinks fuera). Sustituye a la lista `ALLOWED_SOURCES`. | M | Tests de traversal y symlink. |
| D2 | SSRF: por defecto bloquear IPs privadas/metadatos; **permitir `localhost`/dev-server solo con `--allow-localhost`** (necesario para escanear su propio servidor). | S | Test de metadata `169.254.169.254` bloqueada. |
| D3 | Privacidad: aviso explícito de qué se envía al proveedor (HTML/imágenes), `--exclude` por patrón, **redactor de secretos** (tokens/keys en scripts y atributos) antes de enviar, no enviar `.env`. | M | Test de redacción. **Parcial (entrega 3)**: hecho el redactor (`bondy/core/redact.py`), su uso antes de enviar/hashear/guardar/reportar y el bloqueo de `.env`/`*.pem`/`id_rsa` como imagen; el aviso explícito de qué se envía está en el README (sección 2c y Seguridad), no como mensaje en tiempo de ejecución; `--exclude` ya existía. Sin `--no-redact` (ver decisiones). |
| D4 | La API key: solo desde env/archivo del usuario; nunca en logs, reportes ni caché; enmascarada en `doctor`. | S | Test que busca la key en toda la salida. |
| D5 | UI `serve`: enlazar a `127.0.0.1`, token de sesión aleatorio, sin CORS abierto, límite de tamaño de petición. | M | No accesible desde otra máquina. |
| D6 | Navegador: contexto aislado, sin descargas, red limitada a lo necesario, timeouts globales. | S | **Parcial**: hecho contexto aislado (`new_context`, `accept_downloads=False`, service workers bloqueados) y red limitada en los 4 escáneres y `render_page` (ver hallazgos de la Fase A); test de 0 peticiones a un servidor local. **Hecho (entrega 2)**: un solo navegador compartido por escaneo (`browser_session`), `--timeout` por página (def. 60 s) y `--scan-timeout` (def. 900 s), cierre garantizado (error y Ctrl+C), guard de red intacto (tests de 0 peticiones corren también dentro de la sesión). Limitación medida: un JS que gira *después* de cargar no es interrumpible por el timeout de página (ver hallazgos). |
| D7 | Advertir de que el free tier de Google usa el contenido para mejorar productos; recomendar key de pago para código privado. | S | Mensaje en `doctor`/README. |

### Fase E — Salidas y experiencia de desarrollador (P1)

| # | Tarea | Esfuerzo |
|---|---|---|
| E1 | Formatos: terminal legible, JSON, Markdown, HTML autocontenido, **SARIF** (GitHub code scanning). | M | **Hecho (entrega 3)** |
| E2 | Códigos de salida y `--fail-on critical\|warning`; `bondy scan --baseline` para ignorar deuda existente. | S | **Hecho (entrega 3)** |
| E3 | GitHub Action y hook de pre-commit oficiales (solo archivos cambiados). | M | **Hecho como archivos (entrega 3)**; no ejecutado en la nube |
| E4 | `# bondy-ignore` / lista de supresiones con motivo, versionable. | S | **Hecho (entrega 3)** |
| E5 | Progreso real (por página/imagen) y resumen de costo al final: peticiones, tokens, caché, $ estimado. | S | **Resumen hecho (entrega 3)**; el progreso por página/imagen en vivo sigue pendiente |
| E6 | UI web local (`bondy serve`): reutilizar `web/`, con selección de carpeta, progreso por SSE y botón "aplicar" solo con diff visible. | L |
| E7 | Plantillas (JSX/TSX, Vue, Svelte, Jinja/ERB): extraer el HTML o auditar el build/render. | L (v2) |

### Fase F — Calidad, pruebas y CI (P1)

| # | Tarea | Esfuerzo |
|---|---|---|
| F1 | ~~Formatear los 10 archivos pendientes (`ruff format`) y añadir `format --check` + `ty` al CI.~~ | S | **Hecho (2026-10-10)**: política LF (`.gitattributes` + `line-ending = "lf"`); 7 archivos con cambios de estilo reales (los otros 9 solo diferían en finales de línea); `ruff format --check`, `ty check bondy` y `ruff check` en `ci.yml`. |
| F2 | Quitar `# ruff: noqa` y el prompt gigante de `agent.py` (a archivo de recurso). | S |
| F3 | Tests golden con los 4 demos (ahora `examples/`) + fixtures de casos extremos de la Fase C. | M |
| F4 | Tests con proveedor simulado (429 minuto/día, 503, JSON roto, timeout). | M |
| F5 | CI en matriz **Windows/macOS/Linux × Python 3.11-3.13**; test de instalación en venv limpio. | M | **Parcial (2026-10-10)**: `.github/workflows/ci.yml` (3 SO × Python 3.11/3.13, pins por SHA, `permissions: contents: read`, `concurrency`). La matriz usa 3.11 y 3.13 (no 3.12). **Sin ejecutar en GitHub**; ver "Cierre de la Fase F". Venv limpio probado en local con `uv sync --frozen --extra server --extra agent --extra lint` (488 passed, 1 skipped). |
| F6 | Tests de integración reales marcados `skipif` sin key (nunca en CI por defecto). | S |
| F7 | Limpiar metadatos (`pyproject`), alinear README/arquitectura (conteo de skills), idioma documentado. | S |

---

## 5. Orden recomendado

1. **Decidir D1-D4** (sección 2).
2. **A1-A2** (paquete y dependencias) + **F1**: base portable y estable.
3. **B1, B2, B3, B6** : modo sin key + pipeline + lotes + topes. Esto resuelve cuota y costo.
4. **A3-A5**, **D1-D4**: CLI usable y seguro.
5. **C** en paralelo con cada paso (cada tarea trae sus casos).
6. **B4, B5, B9, B10**: caché, estimación, incremental, reanudación.
7. **E1-E5**, luego **E6** y **B8**.
8. **E7** y proveedores adicionales en v2.

## 6. Ramas / PRs sugeridos

- `refactor/package-bondy` (A1, A2, F1, F2)
- `feat/cli-and-config` (A3-A6)
- `feat/pipeline-no-llm` (B1-B3, B6)
- `feat/cost-controls` (B4, B5, B7-B10)
- `fix/security-local-model` (D1-D7)
- `test/edge-cases` (C + F3-F6)
- `feat/reports-and-ci` (E1-E5, F5)

## 7. Costo estimado por escaneo (referencia)

Cálculo propio, no medido: ~50k tokens de entrada y ~4k de salida con el flujo actual → ≈ $0.04-0.05 con Gemini 3.8 Flash, ≈ $0.02-0.03 con 3.5 Flash-Lite (precios oficiales, paga). El pipeline (B2-B4) apunta a un orden de magnitud menos y a **$0 en re-escaneos** (caché). La documentación de Google indica además que los precios de 3.8/3.6 Flash suben tras el 1 de enero de 2027, otro motivo para el caché y para `estimate`.

## 8. Riesgos

- **Regla D1**: cambiar de agente a pipeline cambia el comportamiento; mitigar con tests golden y `--mode agent`.
- **Renombrar el paquete** rompe imports, Dockerfile y CI; hacerlo en un PR aislado y mecánico.
- **Dependencia de Chromium**: es la mayor fricción de instalación; mitigada por A6 y `doctor`.
- **Calidad del alt** con modelos baratos: validar con el conjunto de demos antes de fijar el modelo por defecto.
- **Cuota/precios cambian**: no codificar valores; configurables y mostrados por `estimate`.

### Decisiones tras el cierre de la Fase A

| Decisión | Resolución |
|---|---|
| `render_page.py` y hosts públicos | **Solo local**: se eliminó `allow_remote`; las imágenes remotas no aparecen en la captura (las verifican `verify_image_alt_text`/`classify` con su propia validación). |
| Timeouts globales por escaneo (resto de D6) | Se hacen en la **Fase B**, junto con el navegador compartido. |
| Flag `--static` | **Hecho**: `--static`, `BONDY_STATIC` o `static` en `bondy.toml`; la nota indica que fue forzado y no sugiere instalar un navegador. |

## Pendientes tras la Fase E (2026-10-10)

Dejados para después por decisión del usuario:

| # | Pendiente | Nota |
|---|---|---|
| P1 | ~~**UI web y `/api/audit` sobre `bondy/core`**~~ | **Hecho (2026-10-10)**: `bondy/core/web_audit.py` (adaptador + `run_web_audit`), `GET /api/checks`, mapeo solo en `checks.py`, `app.js` sin mapeo propio. Sin verificar: UI en un navegador real y Gemini real (P2). |
| P2 | **Parcialmente verificado el 2026-10-10 con key nueva** (`doctor --check-key` OK; `scan demo_sites/site_1_bad_alt`: 1 lote, esquema anidado aceptado, imágenes remotas descargadas, 3197 tokens de entrada vs ~3104-6208 estimados, 2 peticiones). **Cerrado el mismo día**: textos de key inválida (`doctor --check-key` FAIL con fix y exit 2 en `scan`, sin más peticiones ni filtrar la key); calidad del alt funcional (enlace con icono de lupa -> `Search`, botón con icono X y alt `icon` -> `Close`, divisor decorativo; 1 lote, 4191 tokens de entrada); timeout (`HttpOptions.timeout` del SDK está en ms y Bondy usa 60 000 = 60 s); topes (10 MB por imagen y 15 MB por lote, por debajo de los ~20 MB de Gemini). Observación: con esta key `gemini-flash-latest` devuelve 429 y cada lote gasta 1 petición extra hasta caer a `gemini-3.5-flash-lite`; configurar `BONDY_MODEL`/`BONDY_VISION_MODEL=gemini-3.5-flash-lite` lo evita. El veredicto del divisor decorativo varió entre dos ejecuciones (el modelo no es determinista). Original: Verificar con **Gemini real** (esquema anidado, timeout en ms, tope ~20 MB, textos de error de key, calidad del alt funcional) | Necesita key de pago o cuota nueva. |
| P3 | ~~Verificar **Docker** y **CI de GitHub**~~ | **Parcial (2026-10-10)**: validado sin nube: YAML de `action.yml`, `bondy-audit.yml`, hook y ejemplo; SHAs de las acciones comprobados con `git ls-remote` (los `^{}` son los commits); la parte `bash -e` de la action tenia un bug (corregido); `bondy scan demo_sites --format sarif/markdown --no-llm` y `uvicorn` con `BONDY_NO_LLM=1` (`GET /`, `POST /api/audit`) funcionan en local. **Sin verificar entonces**: `docker build`/`run` (el daemon de Docker Desktop estaba apagado), la action y el hook en un repo/runner real. **Docker verificado el 2026-10-11** (ver "Cierre del plan de refactor"); la action, el hook y el job `docker` de `ci.yml` siguen sin ejecutarse en GitHub. Pendiente fijar `owner/repo@tag` de la action y la URL `repo:` del hook (siguen como TODO; no existen aun). |
| P4 | ~~`bondy scan` con varias rutas, progreso en vivo, aviso en ejecucion~~ / **`--mode agent` en la CLI** | **Hecho (2026-10-10)**: varias rutas, progreso por pagina/imagen/lote en stderr (`--quiet`, `--progress`) y aviso de lo que se envia (solo LLM). **Pendiente**: `--mode agent` en la CLI (el agente ADK solo corre desde la app web). |
| P5 | Fase C restante, ~~Fase F (formato de archivos viejos, `ty` en CI, matriz Windows/macOS/Linux)~~ (**hecha como archivos el 2026-10-10, sin ejecutar en runners**; F2-F4/F6/F7 siguen abiertas), E7 plantillas, B8 Batch API, `demo_sites` -> `examples/` (**hecho**) | Ver secciones 4 y 5. |
| P6 | ~~Watchdog duro por página~~ | **Hecho (2026-10-11)**: antes descartado (mitigación `--scan-timeout` + `--resume`). Ver "Cierre del plan de refactor". |
| P7 | ~~**Duplicados entre escáneres** (un enlace sin nombre daba `axe` link-name + `axe-tree` + `accessible-name`; demo_sites 59 hallazgos)~~ | **Hecho (2026-10-10)**: `bondy/core/dedupe.py`, llamado desde `build_report` antes de supresiones y baseline. Demo_sites 59 -> 36; caso minimo 19 -> 9. Familias: nombre accesible (axe `link-name`/`button-name`/`input-button-name`/`label`/`select-name`/`aria-*-name` + `axe-tree` + `accessible-name` + `labels`) y contraste (axe `color-contrast` + `contrast`). El hallazgo ganador conserva su huella y lleva `merged_from` (JSON, SARIF `mergedFrom`, markdown/HTML). Un `bondy-ignore`/`[[ignore]]` por la regla de cualquiera de los fusionados suprime el item; el baseline casa por cualquiera de las huellas. La cache guarda hallazgos crudos; `FINDINGS_SCHEMA = 2` invalida paginas guardadas por versiones anteriores. Sin verificar: otros navegadores/paginas grandes. Tests `test_dedupe.py`. |

### Hallazgos y cierres (2026-10-10, tras P1)

| Hallazgo | Resolucion |
|---|---|
| `focus-order`: un `<a>` vacio daba N hallazgos identicos "(whole page)" | **Corregido**: el validador recorria 20 Tab sin detectar la vuelta y deduplicaba por selector. Ahora identifica cada elemento por identidad, se detiene al cerrar el ciclo y el hallazgo trae el HTML del elemento. Test `test_focus_order.py`. |
| `AXE_SCAN_SCRIPT` y `audit_schema.parse_audit_response` sin uso | **Eliminados** (grep: nada del agente, MCP, skills ni tests, salvo su propio test, los usaba). |
| Cuota diaria agotada con hallazgos deterministas | **Decidido**: `/api/audit` responde 200 `partial: true` con una nota; 429 solo si no hay nada que mostrar. |
| Imagen Docker sin Chromium por defecto | **Decidido**: `INSTALL_CHROMIUM=false` (modo estático, documentado); activable con `--build-arg`. |
| `ruff format --check`: 14 archivos del repo no pasan `ruff format --check` | **Corregido (Fase F)**: eran 16; 9 solo por finales de linea (`line-ending = "native"` + `.gitattributes` ausente) y 7 por estilo. Ver "Cierre de la Fase F". |
| Reporte con varias rutas usa la carpeta comun como raiz | Documentado: para baselines/SARIF estables escanear una carpeta. |
| `upload-sarif` falla en PRs desde forks (token sin `security-events: write`) | **Hecho (2026-10-11, P0-2)**: la action omite la subida en forks y Dependabot, avisa con `::notice::` y conserva el SARIF como artefacto `bondy-sarif`; el paso lleva `continue-on-error: true`. Documentado en README y `docs/ci-example.yml`. Sin ejecutar en un PR de fork real. |

### Cierre de la Fase F (2026-10-10: F1, F5 parcial, `ty`)

| Tema | Resolucion |
|---|---|
| Finales de linea | `.gitattributes`: `* text=auto eol=lf` + binarios explicitos (`*.png`, fuentes...). `ruff`: `line-ending = "lf"`. El indice de git ya era LF en todos los archivos de texto, asi que **no hay diff masivo de finales de linea**: `git diff --stat` solo muestra los 7 archivos con estilo real y los de `ty`. En Windows con `core.autocrlf=true` el arbol de trabajo pasa a LF en los `.py` formateados; `git status` puede listar muchos archivos como `M` hasta un `git add` (sin cambios reales; comprobado con un indice temporal). Los fixtures con CRLF/BOM de los tests se crean en tiempo de ejecucion (`write_bytes`), no dependen del archivo fuente. |
| `.git-blame-ignore-revs` | Opcional: el commit de formato es pequeno (7 archivos); si se quiere, anadir su SHA y `git config blame.ignoreRevsFile .git-blame-ignore-revs`. |
| `ty` | `python-version = "3.11"`; `ty check bondy` en 0 errores con 3 reglas reactivadas (ver CHANGELOG). `ty check bondy tests` daba 9 diagnosticos (todos `unsupported-operator` por `str | None` en tests) y no estaba en CI. **Resuelto el 2026-10-11 (P1-3)**: 0 diagnosticos y `ty check bondy tests` corre en `ci.yml`. |
| `ci.yml` | Matriz 3 SO x {3.11, 3.13}; acciones por SHA verificado; `uv` por pip (no se uso `astral-sh/setup-uv` para no fijar un SHA nuevo sin necesidad). `UV_PYTHON` fija el interprete de setup-python. Chromium se instala en los 3 SO para que corran los tests de navegador. |
| Tests sin navegador | Simulando que no hay Chromium/Chrome/Edge (parche de `BrowserType.launch`): 474 passed, 15 skipped, 0 failed. Se omiten: `test_axe_scanner::test_scan_detects_known_violations`, `test_dedupe` (linea ~577, `omitted`), 3 de `test_focus_order`, 8 de `test_network_guard` (fixture `need_browser`), `test_report_in_project` (linea ~53) y `test_reports` (esquema SARIF, `BONDY_SARIF_SCHEMA`, se omite siempre en CI). Misma lista en los 3 SO. |
| Portabilidad Linux/macOS | **Razonado leyendo el codigo, no ejecutado en Linux/macOS**: separadores (los tests normalizan `\`/`/`), mayusculas/minusculas (nombres de `demo_sites` coinciden con el disco), rutas tipo `C:\...` rechazadas por `validate_input_before_audit` y `_ignore_path` tambien en POSIX, `git` con identidad `-c user.name`. Comprobado en local: arbol con LF puro (como un checkout de Linux) -> 488 passed, 1 skipped. |
| **No verificado** | Ejecucion real de `ci.yml` en runners de GitHub (los tres SO, `--with-deps` en Linux, instalacion de `uv` por pip, tiempos y `timeout-minutes`), comportamiento de Chromium en macOS/Linux, y el `uv.lock` en 3.11 (solo se probo con el interprete local 3.13). |
| Abierto en Fase F | F2 (`# ruff: noqa`/prompt de `agent.py`), F3 (golden), F4, F6, F7 y un test de instalacion en venv limpio como paso de CI. |

## Cierre del plan de refactor (2026-10-11)

Resultado de ejecutar los ítems P0-1 a P1-4 de [refactor-plan.md](refactor-plan.md) (la numeración P0/P1 de ese documento no es la de la tabla "Pendientes tras la Fase E"). El detalle técnico y los resultados medidos están allí y en [CHANGELOG.md](../CHANGELOG.md); aquí solo el estado.

| Ítem (refactor-plan) | Estado | Notas |
|---|---|---|
| P0-1 SSRF / DNS rebinding en descargas remotas | **Hecho** | `bondy/core/netguard.py::fetch_public_bytes` es el único descargador (IP validada fijada, redirecciones revalidadas, máx. 3, sin credenciales en la URL, tope de bytes). `images.py`, `vision_tools._load_image` y `fetch_image.py` delegan en él; `urlopen` ya no aparece en `bondy/`. Tests: `tests/unit/test_netguard.py`. |
| P0-2 `upload-sarif` en forks | **Hecho (solo local)** | Ver fila de "Hallazgos y cierres". YAML válido y test estructural; no se ejecutó en un PR de fork real. |
| P0-3 API de ADK expuesta | **Hecho** | Riesgo confirmado con TestClient. Las rutas de ADK solo se montan con `BONDY_ENABLE_AGENT_API=1` y entonces las protege `_AgentApiGuard`. Sin la bandera la app es un `FastAPI()` propio. `/api/audit` y `/feedback` siguen sin autenticación (decisión: herramienta local). |
| P1-1 Configuración solo en `Settings` | **Hecho** | `ServerSettings`/`load_server_settings()`, `BONDY_APPLY_TOKEN` (alias heredado `BONDY_API_KEY`), `.env` del servidor con lista blanca, `vision_tools` y `agent.py` leen el modelo de `Settings`. Test de arquitectura en `tests/unit/test_settings_only.py`. Pendiente: `python-dotenv` sigue declarado en el extra `server` (sin uso; quitarlo exige regenerar `uv.lock`). |
| P1-2 Watchdog duro por página | **Hecho (solo probado en Windows)** | `page_watchdog` en `bondy/app_utils/browser.py`: `--timeout` es un límite duro por página; la página colgada queda `skipped`, resultado parcial (exit 3) y pendiente en `resume.json`. **Sin verificar**: la rama POSIX (`pkill -P` + `SIGKILL`) en macOS/Linux; cada kill deja un directorio `playwright_chromiumdev_profile-*` en el temporal; una página colgada vuelve a colgar en cada `--resume` hasta excluirla. |
| P1-3 `ty check bondy tests` | **Hecho** | 0 diagnósticos; el paso corre en `ci.yml`. |
| P1-4 Docker con `INSTALL_CHROMIUM=true` | **Hecho (verificado en local el 2026-10-11)** | Docker Desktop 28.3.3. Build con Chromium OK (3 min 10 s, imagen 2.48 GB; sin Chromium 1.02 GB). `bondy doctor` -> `[OK] browser: Playwright Chromium` (exit 0). `bondy scan examples --no-llm` -> exit 1, 36 hallazgos, sin nota `STATIC MODE`. `POST /api/audit` sobre un ejemplo -> `mode: no-llm`, 3 hallazgos, sin `STATIC MODE`. `ARG UV_VERSION=0.11.21` alinea `uv` con `ci.yml` (hay que mantener ambos a mano). Imagen sin Chromium: modo estático como antes. |

**Sin verificar / abierto**

- El job `docker` de `.github/workflows/ci.yml` (push a `main` y `workflow_dispatch`, no en PRs) **no se ha ejecutado en GitHub**; solo sus pasos, en local.
- Usuario no root: no soportado (la imagen corre como `root`; con `--user 1000:1000` el navegador no se encuentra y `/code` no es escribible). Haría falta `PLAYWRIGHT_BROWSERS_PATH`, `chown` de `/code` y un HOME escribible.
- La imagen no tiene `HEALTHCHECK`; no hay test que compare las versiones de `uv` de `Dockerfile` y `ci.yml`.
- Extras: `server` sin `agent` no se ha probado en un entorno limpio (ADK ya solo se importa con la bandera), y `pyproject.toml` aún declara que `server` requiere `agent` (P2-2).
- P2 (`--mode agent`, `app.js` heurístico, módulos grandes, plantillas JSX/Vue, Batch API, duplicados de `vision_tools`) no se ha tocado, salvo la parte de P2-4 agrupada con P1-1 (alias `_quota_retry_delay` e imports de `fast_api_app.py`); ver `refactor-plan.md`, sección 4.
