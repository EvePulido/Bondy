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

Hecho en esta rama (33 tests unitarios pasan, `ruff check` limpio):

| Cambio | Archivo | Estado |
|---|---|---|
| En auditorías solo de WCAG 1.1.1 se omiten axe y `analyze_rendered_page` | `fast_api_app.py::_skip_note`, `agent.py` | Aplicado |
| Reintento de la petición fallida (429/503) en el agente | `agent.py`, `fast_api_app.py` (`retry_options`) | Aplicado |
| Reintento en visión respetando el retraso; no reintentar si la cuota es diaria | `vision_tools.py::_quota_retry_delay` | Aplicado |
| Error claro (429) cuando la cuota diaria se agotó, sin 4 reintentos inútiles | `fast_api_app.py` | Aplicado |
| Tests de lo anterior | `tests/unit/test_latency_controls.py` | Aplicado |

Hallazgos de la medición (site 1, solo alt text): ~12 peticiones por escaneo; cuota gratuita observada de 5/min y 20/día por modelo; un reintento reiniciaba toda la auditoría. Pendiente de re-medir cuando se restablezca la cuota.

Deuda de portabilidad detectada (nueva):

- El paquete se llama `app` (nombre genérico; se instalaría como `import app` en site-packages).
- `.agents/skills/`, `web/` y `demo_sites/` están fuera del paquete: **no viajarían en un wheel**.
- Rutas relativas al cwd (`.agents/skills`, `web/index.html`, `os.makedirs("web")`).
- Dependencias de nube innecesarias en local: `google-adk[gcp]`, `gcsfs`, `google-cloud-logging`, OpenTelemetry.
- `load_dotenv(override=True)` pisa variables de entorno del usuario.
- Solo acepta rutas dentro de `demo_sites/`.
- Salida solo vía UI web; sin CLI ni códigos de salida.

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

| # | Tarea | Esfuerzo | Criterio de aceptación |
|---|---|---|---|
| A1 | Renombrar `app/` → `bondy/`; mover skills/web/fix_patterns a `bondy/resources/` como package data; localizar recursos con `importlib.resources`. | M | `pip install .` en un venv limpio y `bondy --version` funciona desde cualquier directorio. |
| A2 | Dependencias por extras: núcleo (`playwright`, `google-genai`, `pydantic`, `beautifulsoup4`/`lxml`), `bondy[server]` (FastAPI/uvicorn), `bondy[agent]` (ADK). Quitar `gcsfs`, `google-cloud-logging`, OpenTelemetry del núcleo. Telemetría **apagada** y documentada. | M | Instalación base sin ADK ni GCP; `bondy scan --no-llm` corre. |
| A3 | CLI: `bondy scan <ruta\|url>`, `bondy fix`, `bondy serve`, `bondy estimate`, `bondy doctor`. Soportar `uvx bondy`/`pipx run`. | L | Comandos documentados con `--help`. |
| A4 | Configuración: `bondy.toml` (include/exclude, checks, modelo, presupuesto, formato) + flags + variables de entorno (`GEMINI_API_KEY`/`GOOGLE_API_KEY`). Precedencia: flag > env > archivo. **No** usar `override=True` sobre el entorno del usuario. | M | Tests de precedencia. |
| A5 | `bondy doctor`: verifica Python, Chromium/Chrome instalado, key presente y válida (1 petición mínima), versión de axe, permisos de escritura. Mensajes con la acción exacta. | M | Cada fallo da un comando para corregirlo. |
| A6 | Navegador: usar Chromium de Playwright o **Chrome/Edge del sistema** (`channel=`) si no hay descarga; si no hay navegador, modo estático (HTML parseado) con aviso de qué checks se pierden. | M | Funciona en una máquina sin `playwright install`. |

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
| D6 | Navegador: contexto aislado, sin descargas, red limitada a lo necesario, timeouts globales. | S | Test de timeout. |
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
