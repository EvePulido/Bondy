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
| A3 | CLI: `scan`, `fix`, `serve`, `estimate`, `doctor`. | **Parcial (MVP)** | Hecho: `bondy scan <archivo\|carpeta> [--no-llm] [--format terminal\|json] [--fail-on] [--checks] [--include/--exclude] [--config]` con códigos de salida 0/1/2, y `python -m bondy`. Pendiente: `fix`, `serve`, `estimate`, URLs, y que `scan` sin `--no-llm` use el LLM (hoy avisa y corre solo lo determinista). Sin browser compartido ni paralelismo (cada escáner abre su Chromium; Fase B). |
| A4 | Configuración `bondy.toml` + env + flags. | **Hecho** | `bondy/config.py`; precedencia flag > env > archivo > default, con tests. La API key **no** se acepta en `bondy.toml`. `GEMINI_API_KEY` precede a `GOOGLE_API_KEY`. Pendiente: que `vision_tools.py`/`agent.py`/`fast_api_app.py` lean de `Settings` (hoy siguen leyendo `BONDY_VISION_MODEL`/`BONDY_FALLBACK_MODEL` directamente, con los mismos defaults) y pasar la key explícita al `Client` (el SDK da prioridad a `GOOGLE_API_KEY`). Presupuesto (`budget`) llega con B6. |
| A5 | `bondy doctor`. | **Parcial** | Hecho (offline): Python, paquete/binario de Chromium, axe-core, `bondy.toml`, key presente (nunca se imprime), permiso de escritura; cada fallo da el comando. Pendiente: validar la key con 1 petición real (consume cuota; no se implementó a propósito). |
| A6 | Navegador del sistema / modo estático. | **Hecho** | `bondy/app_utils/browser.py::launch_with_label` es el único lanzador: Chromium de Playwright, luego `channel="chrome"`, `channel="msedge"` y por último el ejecutable de Chrome/Edge encontrado en disco (`executable_path`; añadido porque en Linux `channel=chrome` solo mira `/opt/google/chrome`). Si nada arranca lanza `BrowserUnavailableError` con el comando exacto (`python -m playwright install chromium`). Lo usan los 4 escáneres Playwright, `render_page.py` y `doctor` (que ahora lanza el navegador de verdad y dice cuál se usará). **Modo estático**: si no hay navegador, `bondy scan` no falla; omite `axe`, `contrast`, `focus-trap` y `focus-order`, ejecuta `lang`, `labels`, `accessible-name` y un `img-alt` por regex (sustituto parcial de la regla `image-alt` de axe), lo declara en `notes` (`static_mode: true` y `omitted_checks` por archivo en JSON) y sale con 0/1; un error real de un escáner sigue dando 2. Verificado con el wheel en un venv limpio: ver hallazgos. |

**Cierre de la Fase A (hallazgos y verificación)**

- **Red (D6)**: antes solo `axe_scan.py` abortaba peticiones; `contrast.py`, `focus_trap.py` y `focus_order.py` no tenían ninguna protección y además hacían `page.goto()` de cualquier contenido que empezara por `http(s)://` (vía SSRF latente). Ahora los cuatro pasan por `open_page()`: solo `file://` del propio archivo temporal (y, en `render_page`, la carpeta `demo_sites/`), `data:` y `about:`; cualquier otra petición se aborta, incluidos `file://` ajenos (antes `axe_scan` permitía **cualquier** `file:`). `route()` no ve WebSockets y `route_web_socket` se cuelga con la API síncrona, así que el navegador se lanza además con un proxy muerto (`--proxy-server=http://127.0.0.1:1`, `<-loopback>`): lo que el guard no vea no puede conectar. Los tests (`tests/unit/test_network_guard.py`) registran peticiones en un servidor local con `<script>`, `<link>`, `<img>`, `<iframe>`, `fetch` y `WebSocket`: 0 peticiones por escáner, y un test de control demuestra que sin guard sí llegan.
- **`render_page.py`**: por diseño conserva **hosts http(s) públicos** (verificados con `validate_public_url`) para que la captura de visión muestre imágenes remotas; es la única excepción a "solo local" y queda pendiente de decisión del usuario (¿bloquearlos también y renderizar sin imágenes remotas?). La verificación DNS no protege contra DNS rebinding.
- **Importación de los scripts**: los scripts de skills importan `bondy.app_utils.browser`; si se ejecutan sueltos añaden la raíz del paquete (`parents[5]`) a `sys.path`. Verificado con el wheel y con `python -I script.py` desde otro directorio.
- **Wheel**: `uv build --wheel` -> venv limpio fuera del repo (Python 3.12, Playwright 1.63.0 resuelto por pip) -> desde otro directorio: `bondy --version`, `bondy doctor`, `bondy scan demo3.html --no-llm`. En esa máquina el Chromium cacheado era de Playwright 1.60, no el de 1.63, así que el fallback a **Chrome del sistema (`channel=chrome`) funcionó de verdad**; el modo estático solo se probó con el lanzador simulado (no se desinstaló Chrome).
- **Formato**: `scan.py`, `doctor.py` y `cli.py` ya figuraban sin formatear en la línea base; se formateó solo `browser.py`, los dos tests nuevos y los archivos tocados cuando el diff afectaba solo líneas propias.

### Fase B — Costo y eficiencia (P0)

| # | Tarea | Esfuerzo | Criterio |
|---|---|---|---|
| B1 | **Modo `--no-llm`** (axe + skills deterministas). Es el valor base sin key. | S | Salida completa sin red. |
| B2 | **Pipeline por código** (ver D1): sin turnos de agente para escáneres; prompts cortos. | L | ≤2 peticiones por página típica. |
| B3 | **Lotes de imágenes**: N imágenes por petición con esquema JSON de salida; fusionar `verify` + `classify`. | M | Misma decisión (`keep`/`fix`/`needs_manual_review`) que hoy en los 3 demos (tests golden). |
| B4 | **Caché** `.bondy/cache` por hash(imagen + alt + modelo + versión de prompt). Invalidación al cambiar prompt/modelo. | M | Segundo escaneo = 0 peticiones. |
| B5 | `bondy estimate`: cuenta imágenes/páginas/tokens y muestra **rango de costo** con precios configurables antes de gastar; `--dry-run`. | M | Muestra "N peticiones, ~X tokens, ~$Y". |
| B6 | **Topes duros**: `--max-requests`, `--max-usd`, `--max-pages`, `--max-images`; al llegar al tope, se detiene y entrega parcial. | S | Test que fuerza el tope. |
| B7 | **Escalado de modelo**: barato por defecto, caro solo si baja la confianza; configurable. | S | Métrica de cuántas escalan. |
| B8 | **Batch API opcional** (`--batch`, -50%, hasta 24 h) para repos grandes/CI nocturno; con `bondy fetch <job>`. | L | Job reanudable. |
| B9 | **Escaneo incremental**: solo archivos cambiados (hash o `git diff`). | M | Re-escaneo sin cambios = 0 peticiones. |
| B10 | Gestión de cuotas: distinguir 429 por minuto (esperar `retryDelay`) y por día (parar y decirlo), con resultados parciales y reanudación (`--resume`). | M | Sin reinicios completos. |

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
| D3 | Privacidad: aviso explícito de qué se envía al proveedor (HTML/imágenes), `--exclude` por patrón, **redactor de secretos** (tokens/keys en scripts y atributos) antes de enviar, no enviar `.env`. | M | Test de redacción. |
| D4 | La API key: solo desde env/archivo del usuario; nunca en logs, reportes ni caché; enmascarada en `doctor`. | S | Test que busca la key en toda la salida. |
| D5 | UI `serve`: enlazar a `127.0.0.1`, token de sesión aleatorio, sin CORS abierto, límite de tamaño de petición. | M | No accesible desde otra máquina. |
| D6 | Navegador: contexto aislado, sin descargas, red limitada a lo necesario, timeouts globales. | S | **Parcial**: hecho contexto aislado (`new_context`, `accept_downloads=False`, service workers bloqueados) y red limitada en los 4 escáneres y `render_page` (ver hallazgos de la Fase A); test de 0 peticiones a un servidor local. **Pendiente**: timeouts globales por escaneo (hoy solo el `goto` de `render_page` tiene 20 s) y su test. |
| D7 | Advertir de que el free tier de Google usa el contenido para mejorar productos; recomendar key de pago para código privado. | S | Mensaje en `doctor`/README. |

### Fase E — Salidas y experiencia de desarrollador (P1)

| # | Tarea | Esfuerzo |
|---|---|---|
| E1 | Formatos: terminal legible, JSON, Markdown, HTML autocontenido, **SARIF** (GitHub code scanning). | M |
| E2 | Códigos de salida y `--fail-on critical\|warning`; `bondy scan --baseline` para ignorar deuda existente. | S |
| E3 | GitHub Action y hook de pre-commit oficiales (solo archivos cambiados). | M |
| E4 | `# bondy-ignore` / lista de supresiones con motivo, versionable. | S |
| E5 | Progreso real (por página/imagen) y resumen de costo al final: peticiones, tokens, caché, $ estimado. | S |
| E6 | UI web local (`bondy serve`): reutilizar `web/`, con selección de carpeta, progreso por SSE y botón "aplicar" solo con diff visible. | L |
| E7 | Plantillas (JSX/TSX, Vue, Svelte, Jinja/ERB): extraer el HTML o auditar el build/render. | L (v2) |

### Fase F — Calidad, pruebas y CI (P1)

| # | Tarea | Esfuerzo |
|---|---|---|
| F1 | Formatear los 10 archivos pendientes (`ruff format`) y añadir `format --check` + `ty` al CI. | S |
| F2 | Quitar `# ruff: noqa` y el prompt gigante de `agent.py` (a archivo de recurso). | S |
| F3 | Tests golden con los 4 demos (ahora `examples/`) + fixtures de casos extremos de la Fase C. | M |
| F4 | Tests con proveedor simulado (429 minuto/día, 503, JSON roto, timeout). | M |
| F5 | CI en matriz **Windows/macOS/Linux × Python 3.11-3.13**; test de instalación en venv limpio. | M |
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
