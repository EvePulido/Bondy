# A11y-Forge — Especificación Técnica de Construcción (Build Spec)

> **Este documento está diseñado para ser leído directamente por Antigravity.** Sigue las prácticas de Behavior-Driven Development (BDD) del curso: Markdown para narrativa, YAML para configuración con anidación profunda, y escenarios `Scenario / Given / When / Then` para forzar pensamiento Estado → Acción → Resultado y eliminar el espacio de ambigüedad donde un agente podría "alucinar" un detalle.

---

## 0. Cómo usar este documento con Antigravity

1. **No le pegues el documento completo y le digas "constrúyelo todo".** Trabaja módulo por módulo (sección por sección de este doc), en el orden del Checklist (Sección 10). Esto es justo lo que el Día 3 del curso llama "skills como unidad de mejora" — construir y validar en piezas pequeñas, no de un jalón.
2. **Activa el sandbox de terminal antes de empezar:** User Settings → habilita "Terminal Sandboxing" en Antigravity. Así cualquier comando que ejecute el agente (instalar dependencias, correr scripts) queda contenido.
3. **Pídele que verifique versiones antes de asumir.** En cualquier punto donde este documento diga "última versión estable", pídele explícitamente que corra `pip show <paquete>` o consulte la documentación oficial antes de fijar una versión — no debe inventar un número de versión.
4. **Usa el navegador integrado de Antigravity** para probar en vivo los `demo_sites/` (Sección 9) contra tu Auditor — es la forma más directa de validar que cada skill funciona antes de pasar a la siguiente.
5. Si Antigravity te sugiere una librería o modelo que no aparece en la Sección 2, trátalo como sospechoso — puede ser una alucinación por desactualización de su entrenamiento (esto es exactamente lo que el Día 5 del curso advierte: el agente cae a su conocimiento de entrenamiento si no le das contexto explícito).

---

## 1. Contexto (Background — el "por qué")

A11y-Forge es un agente auditor de accesibilidad web. A diferencia de linters estáticos (axe-core, Lighthouse), no solo detecta SI existen atributos de accesibilidad, sino SI son correctos (ej. alt text presente pero que describe algo distinto a la imagen real). Según el WebAIM Million 2026, el 96% de los errores de accesibilidad reales caen en 6 categorías — este proyecto cubre esas 6 mediante 9 "agent skills" especializadas. Equipo: 2 personas. Track: Agents for Business. Plazo: 17 días.

---

## 2. Stack Tecnológico

```yaml
stack:
  lenguaje: Python 3.12
  framework_agentes: google-adk
    instalacion: "pip install google-adk"
    nota: "No fijar número de versión en este doc — instalar la última estable y confirmar la API contra https://google.github.io/adk-docs/ al momento de codear."
  modelo_vision_y_razonamiento: gemini-3.5-flash
    razon: "GA desde mayo 2026, nativamente multimodal, optimizado para tareas agénticas (tool calls, navegación), buena relación costo/latencia."
  modelo_alterno_economico: gemini-2.5-flash-lite
    uso: "si el volumen de llamadas de visión sube y se necesita bajar costo"
  automatizacion_navegador: playwright (Python)
    instalacion: "pip install playwright && playwright install --with-deps chromium"
  protocolo_mcp: mcp  # SDK oficial de Python
    instalacion: "pip install mcp"
  backend_web: FastAPI
    razon: "Mismo lenguaje que el resto del stack (Python) — reduce la complejidad de contexto para un equipo de 2 personas en 17 días. Decisión cerrada, no hay que evaluar alternativas en JS."
  plantillas_ui: Jinja2 (incluido con FastAPI)
  ci: GitHub Actions
  hosting_repo: GitHub
  variables_de_entorno: ".env (NUNCA committeado — ver .gitignore en Sección 3)"
```

**Nota anti-alucinación:** si en algún momento Antigravity sugiere usar Node.js, Express, o cualquier librería de JS para el backend, recházalo — el stack está fijado en Python por la razón de arriba. Esto no es una preferencia ambigua, es una decisión de arquitectura ya tomada.

---

## 3. Estructura de Carpetas del Repositorio (exacta)

```
a11y-forge/
├── README.md
├── pyproject.toml
├── .env.example
├── .gitignore
├── .github/
│   └── workflows/
│       └── a11y-audit.yml              # CI: corre el audit en cada PR (Sección 8)
├── .agents/
│   └── skills/                          # Carpeta estándar de Agent Skills (Día 3 del curso)
│       ├── validar-contraste-texto/
│       │   ├── SKILL.md
│       │   └── scripts/contrast.py
│       ├── validar-idioma-documento/
│       │   ├── SKILL.md
│       │   └── scripts/check_lang.py
│       ├── validar-nombre-accesible-interactivo/
│       │   ├── SKILL.md
│       │   └── scripts/accessible_name.py
│       ├── validar-labels-formularios/
│       │   ├── SKILL.md
│       │   └── scripts/form_labels.py
│       ├── evaluar-orden-foco/
│       │   ├── SKILL.md
│       │   └── scripts/focus_order.py
│       ├── detectar-trampa-de-foco/
│       │   ├── SKILL.md
│       │   └── scripts/focus_trap.py
│       ├── validar-calidad-alt-text/
│       │   ├── SKILL.md
│       │   └── references/wcag_1_1_1.md
│       ├── clasificar-imagen-decorativa/
│       │   ├── SKILL.md
│       │   └── references/decorativa_vs_informativa.md
│       └── generar-fix-sugerido/
│           ├── SKILL.md
│           └── references/patrones_de_fix.md
├── agents/
│   ├── orchestrator.py                  # Agente Orquestador (ADK)
│   ├── auditor.py                       # Agente Auditor (ADK) — carga skills vía SkillToolset
│   └── refactorizador.py                # Agente Refactorizador (ADK)
├── mcp_server/
│   └── github_server.py                 # MCP server → GitHub (Sección 6)
├── browser/
│   └── runner.py                        # Wrapper sandboxed de Playwright, usado por las skills DOM
├── web/
│   ├── app.py                           # FastAPI
│   ├── templates/index.html
│   └── static/
├── demo_sites/                          # Sección 9
│   ├── site_1_bad_alt/index.html
│   ├── site_2_focus_trap/index.html
│   └── site_3_mixed_errors/index.html
├── tests/
│   └── skills_eval/
│       └── test_trigger_accuracy.py     # Eval de skills (Día 3 del curso)
└── docs/
    └── architecture.md
```

**Regla:** cada skill vive en su propia carpeta bajo `.agents/skills/`, nunca como función suelta dentro de `agents/auditor.py`. El Auditor solo orquesta — la lógica de detección vive en las skills.

---

## 4. Las 9 Agent Skills — Especificación Completa

Cada skill sigue el mismo molde: frontmatter YAML (lo único obligatorio para que el agente la cargue), contrato de entrada/salida, y al menos un escenario Given/When/Then concreto con valores reales — no descripciones vagas.

### 4.1 `validar-contraste-texto`

```yaml
skill:
  name: validar-contraste-texto
  needs_llm: false
  wcag: "1.4.3"
  description: >
    Calcula el ratio de contraste entre texto y fondo para cada elemento de texto visible.
    Umbral: 4.5:1 para texto normal, 3:1 para texto grande (>=18pt o >=14pt bold).
    Usar para verificar legibilidad de texto contra su fondo.
    NO usar para contraste de elementos no textuales (iconos, gráficos).
contrato:
  entrada: { dom_snapshot: "árbol DOM serializado (de Playwright)" }
  salida: { issues: "lista de {selector, fg_color, bg_color, ratio, ratio_requerido, passes}" }
```
**Scenario:** Texto con contraste insuficiente
`Given` un párrafo con color `#AAAAAA` sobre fondo `#FFFFFF`
`When` se ejecuta `validar-contraste-texto`
`Then` reporta un issue con `ratio≈2.32`, `passes:false`, criterio `1.4.3`

### 4.2 `validar-idioma-documento`

```yaml
skill:
  name: validar-idioma-documento
  needs_llm: false
  wcag: "3.1.1"
  description: >
    Verifica que la etiqueta <html> tenga el atributo lang con un código de idioma
    válido (formato BCP 47, ej. "es", "en-US"). Es el check más simple del proyecto.
    Usar siempre como parte de la auditoría base.
contrato:
  entrada: { html_root_tag: "string del nodo <html> completo" }
  salida: { issue: "{ presente: bool, valor: string|null, valido: bool }" }
```
**Scenario:** Falta el atributo lang
`Given` `<html><head>...` sin atributo `lang`
`When` se ejecuta `validar-idioma-documento`
`Then` reporta `presente:false`, criterio `3.1.1`, fix sugerido `<html lang="es">`

### 4.3 `validar-nombre-accesible-interactivo`

```yaml
skill:
  name: validar-nombre-accesible-interactivo
  needs_llm: false
  wcag: "2.4.4 / 4.1.2"
  description: >
    Verifica que cada <a> y <button> tenga un nombre accesible: texto visible,
    aria-label, aria-labelledby, o alt de una imagen contenida. Cubre las
    categorías "Empty Links" y "Empty Buttons" del WebAIM Million en un solo skill.
    Usar para auditar todos los elementos interactivos de navegación/acción.
contrato:
  entrada: { elementos: "lista de nodos <a>/<button> con su contenido HTML interno" }
  salida: { issues: "lista de {selector, tipo: link|button, tiene_nombre_accesible: bool}" }
```
**Scenario:** Botón vacío con solo un ícono SVG sin etiqueta
`Given` `<button><svg>...</svg></button>` sin `aria-label`
`When` se ejecuta el skill
`Then` reporta `tiene_nombre_accesible:false`, sugiere agregar `aria-label="Cerrar"` (o el texto que aplique según contexto)

### 4.4 `validar-labels-formularios`

```yaml
skill:
  name: validar-labels-formularios
  needs_llm: false
  wcag: "1.3.1 / 4.1.2"
  description: >
    Verifica que TODO input de formulario (text, checkbox, radio, select, textarea)
    tenga un label asociado vía <label for="">, envoltura <label>, o
    aria-label/aria-labelledby. Reemplaza y amplía el alcance original de
    "solo radio buttons" a todos los campos de formulario.
    Usar para auditar formularios completos, no elementos individuales sueltos.
contrato:
  entrada: { inputs: "lista de nodos de formulario con su id, type, y contexto DOM circundante" }
  salida: { issues: "lista de {selector, tipo_input, tiene_label: bool, metodo_detectado}" }
```
**Scenario:** Checkbox sin label
`Given` `<input type="checkbox" id="terminos">` sin ningún `<label for="terminos">` en la página
`When` se ejecuta el skill
`Then` reporta `tiene_label:false`, criterio `1.3.1/4.1.2`

### 4.5 `evaluar-orden-foco`

```yaml
skill:
  name: evaluar-orden-foco
  needs_llm: false
  wcag: "2.4.3"
  description: >
    Simula pulsaciones de Tab con Playwright y registra la secuencia real de
    elementos enfocados. Compara contra el orden visual/DOM esperado.
    Usar para detectar saltos de foco ilógicos (ej. que tabular salte del header
    directo al footer sin pasar por el contenido principal).
contrato:
  entrada: { url_o_html: "página cargada en el navegador sandboxed de Playwright" }
  salida: { secuencia_foco: "lista ordenada de selectores", anomalias: "lista de saltos detectados" }
```
**Scenario:** Orden de foco ilógico
`Given` una página donde el DOM tiene un modal oculto con `tabindex="0"` antes del contenido principal
`When` se simulan 5 pulsaciones de Tab
`Then` el agente detecta que el foco entra al modal oculto antes que al contenido visible y lo reporta como anomalía

### 4.6 `detectar-trampa-de-foco`

```yaml
skill:
  name: detectar-trampa-de-foco
  needs_llm: false
  wcag: "2.1.2"
  description: >
    Simula Tab repetidamente (mínimo 30 pulsaciones) y detecta si el foco entra
    en un ciclo del que no puede salir (ej. un modal sin botón de cierre
    accesible por teclado). Usar en cualquier componente tipo modal/dropdown/popup.
contrato:
  entrada: { url_o_html: "página cargada en Playwright" }
  salida: { trampa_detectada: bool, selectores_involucrados: "lista", num_pulsaciones_sin_salida: int }
```
**Scenario:** Modal sin escape por teclado
`Given` un modal abierto con 2 elementos enfocables internos y sin manejo de `Escape` ni botón de cierre alcanzable por Tab
`When` se simulan 30 pulsaciones de Tab
`Then` se detecta que el foco cicla solo entre esos 2 elementos, se reporta `trampa_detectada:true`

### 4.7 `validar-calidad-alt-text`

```yaml
skill:
  name: validar-calidad-alt-text
  needs_llm: true
  modelo: gemini-3.5-flash
  wcag: "1.1.1"
  description: >
    Compara cada imagen real contra su atributo alt usando un modelo con visión.
    Determina si el alt describe fielmente el contenido/función de la imagen en su
    contexto (¿está dentro de un link/botón? ¿hay un figcaption adyacente?).
    NO asume automáticamente que un caption adyacente hace innecesario el alt —
    solo lo marca como "posible redundancia, revisar".
contrato:
  entrada: { imagen_url_o_bytes: "binario", alt_actual: "string", contexto_dom: "¿dentro de link/botón? ¿figcaption cercano?" }
  salida: { veredicto: "buena | deficiente | ausente | posible_redundancia", explicacion: "string", sugerencia: "string" }
```
**Scenario:** Alt text presente pero incorrecto
`Given` una foto real de un perro con `alt="gráfica de ventas Q3"`
`When` se ejecuta el skill con visión
`Then` el modelo detecta la discrepancia, reporta `veredicto: deficiente`, y sugiere un alt que describa al perro real

### 4.8 `clasificar-imagen-decorativa`

```yaml
skill:
  name: clasificar-imagen-decorativa
  needs_llm: true
  modelo: gemini-3.5-flash
  wcag: "1.1.1"
  description: >
    Determina si una imagen es puramente decorativa (no aporta información
    única más allá de lo estético) y por lo tanto debería llevar alt="" en vez
    de una descripción innecesaria. Usa el contexto del DOM circundante.
contrato:
  entrada: { imagen_url_o_bytes: "binario", contexto_dom: "texto/headings circundantes" }
  salida: { es_decorativa: bool, justificacion: "string" }
```
**Scenario:** Ícono decorativo con alt verboso
`Given` un ícono de flecha puramente visual junto a un texto de enlace "Ver más" que ya transmite el significado completo
`When` se ejecuta el skill
`Then` reporta `es_decorativa:true`, sugiere cambiar el alt actual por `alt=""`

### 4.9 `generar-fix-sugerido`

```yaml
skill:
  name: generar-fix-sugerido
  needs_llm: true
  modelo: gemini-3.5-flash
  description: >
    Toma un hallazgo (de cualquiera de las 8 skills anteriores) junto con el nodo
    DOM afectado, y genera el snippet de código corregido en formato antes/después.
    Usar como último paso, después de que el Auditor haya generado todos los hallazgos.
    NO debe inventar selectores o nodos que no estén en el hallazgo recibido.
contrato:
  entrada: { finding: "objeto Finding (ver Sección 5)", nodo_dom_original: "HTML del nodo" }
  salida: { before: "string", after: "string", explicacion: "string" }
```
**Scenario:** Generar fix para botón vacío
`Given` un Finding del skill `validar-nombre-accesible-interactivo` con `selector: "button.close-modal"`, `tipo: button`
`When` se ejecuta `generar-fix-sugerido`
`Then` retorna `before` con el HTML original y `after` con `aria-label="Cerrar"` agregado, sin modificar nada más del nodo

---

## 5. Plantilla Real de `SKILL.md` (úsala tal cual para las 9 carpetas)

Esta es la plantilla exacta que va dentro de cada carpeta `.agents/skills/<nombre>/SKILL.md`, siguiendo el formato canónico del Día 3 (frontmatter YAML + cuerpo en Markdown):

```markdown
---
name: validar-contraste-texto
description: |
  Calcula el ratio de contraste entre texto y fondo para cada elemento de texto
  visible en una página web. Determina si cumple el mínimo WCAG 2 AA (4.5:1 texto
  normal, 3:1 texto grande).
  Usar cuando se necesite verificar legibilidad de texto contra su fondo.
  Do NOT use para contraste de elementos no textuales (iconos, gráficos, bordes).
---

## Instrucciones

1. Recibe el `dom_snapshot` serializado por Playwright.
2. Para cada nodo de texto visible, extrae color de texto (`fg`) y color de fondo
   efectivo (`bg`), resolviendo transparencias si las hay.
3. Ejecuta `scripts/contrast.py` con `fg` y `bg` para obtener el ratio.
4. Determina el umbral requerido según tamaño/peso de fuente (ver `references/` si existe).
5. Devuelve la lista de `issues` según el contrato de la Sección 4.1 de la spec técnica.

## Cuándo NO activar este skill

- Si el nodo no contiene texto visible (solo íconos, imágenes, bordes).
- Si el texto está oculto (`display:none`, `visibility:hidden`, `aria-hidden="true"`).
```

**Regla para las 9 skills:** cambia `name`, `description` e `Instrucciones` según la Sección 4 correspondiente — la estructura del frontmatter y el cuerpo se mantiene idéntica. Para las skills que usan LLM (4.7, 4.8, 4.9), agrega una línea adicional en el cuerpo: `Modelo: gemini-3.5-flash (confirmar disponibilidad vigente antes de implementar)`.

---

## 6. Contrato de Datos Entre Agentes

```yaml
Finding:
  id: string (uuid)
  skill: string                    # nombre del skill que lo generó, ej. "validar-contraste-texto"
  wcag_criterion: string           # ej. "1.4.3"
  severity: enum[critical, warning, info]
  selector: string                 # selector CSS del nodo DOM afectado
  description: string
  evidence:
    current_value: string
    expected_value: string | null

FixSuggestion:
  finding_id: string                # referencia al Finding.id correspondiente
  before: string
  after: string
  explanation: string

AuditReport:
  site_id: string
  timestamp: string (ISO 8601)
  findings: list[Finding]
  fixes: list[FixSuggestion]
  summary:
    total_issues: int
    by_severity: { critical: int, warning: int, info: int }
```

**Regla:** el Orquestador es el único componente que ensambla `AuditReport`. El Auditor solo produce `Finding[]`. El Refactorizador solo produce `FixSuggestion[]` a partir de los `Finding` recibidos — nunca debe generar un finding nuevo por su cuenta.

---

## 7. Servidor MCP — Código Base (adaptado de la plantilla del Día 5)

```python
# mcp_server/github_server.py — Expone un repo de GitHub vía MCP
import os
from github import Github  # pip install PyGithub
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

server = Server("a11y-forge-github")
gh = Github(os.environ["GITHUB_TOKEN"])  # token de solo lectura, fine-grained (Sección 8)
REPO_NAME = os.environ["GITHUB_REPO"]    # ej. "usuario/a11y-forge-demo-target"

@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="list_html_files",
            description="Lista los archivos HTML/JSX/Vue del repositorio configurado",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="read_file",
            description="Lee el contenido de un archivo específico del repo (solo lectura)",
            inputSchema={
                "type": "object",
                "properties": {"path": {"type": "string", "description": "ruta del archivo en el repo"}},
                "required": ["path"],
            },
        ),
    ]

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    repo = gh.get_repo(REPO_NAME)
    if name == "list_html_files":
        contents = repo.get_contents("")
        files = [f.path for f in contents if f.path.endswith((".html", ".jsx", ".vue"))]
        return [TextContent(type="text", text=str(files))]
    elif name == "read_file":
        file = repo.get_contents(arguments["path"])
        return [TextContent(type="text", text=file.decoded_content.decode("utf-8"))]
    return [TextContent(type="text", text=f"Tool desconocida: {name}")]

async def main():
    async with stdio_server() as (read, write):
        init_options = server.create_initialization_options()
        await server.run(read, write, init_options)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
```

**Nota anti-alucinación:** este servidor expone SOLO `list_html_files` y `read_file` — ambas de solo lectura. Si Antigravity propone agregar una tool de escritura (`write_file`, `create_pr`, etc.) sin que lo hayas pedido explícitamente, recházalo — está fuera del alcance de los 17 días (ver "Fase 2" en el documento estratégico original).

---

## 8. Seguridad — Implementación Concreta (Pilares 4 y 5 del curso)

### Pilar 4 (Application & Runtime) — Hook antes de ejecutar el navegador

```python
# browser/runner.py — hook determinístico ANTES de cualquier llamada a Playwright
ALLOWED_SOURCES = {"demo_sites/site_1_bad_alt", "demo_sites/site_2_focus_trap", "demo_sites/site_3_mixed_errors"}

def validar_input_antes_de_auditar(source: str, raw_html: str | None) -> None:
    """Hook de Pilar 4: corre SIEMPRE antes de que Playwright cargue cualquier página.
    Rechaza cualquier cosa que no sea un sitio demo curado o HTML pegado directamente.
    NUNCA acepta una URL arbitraria — ver justificación en doc estratégico, Sección 6."""
    if raw_html is not None:
        return  # HTML pegado directamente: permitido
    if source not in ALLOWED_SOURCES:
        raise ValueError(f"Fuente no permitida: {source}. Usa un sitio demo o pega HTML.")
```

Este hook se invoca al inicio de `agents/auditor.py`, antes de instanciar el navegador. Es exactamente el patrón que el Día 4 del curso llama "deterministic hooks that run at specific lifecycle points, such as before a tool call".

### Pilar 5 (IAM) — Token de mínimo privilegio para GitHub

Pasos exactos para crear el token (no usar un Personal Access Token clásico con todos los permisos):

```yaml
github_token_setup:
  tipo: "Fine-grained personal access token"
  ruta: "GitHub → Settings → Developer settings → Fine-grained tokens → Generate new token"
  repository_access: "Only select repositories → elegir SOLO el repo demo objetivo"
  permisos:
    contents: "Read-only"
    metadata: "Read-only (obligatorio, se activa automático)"
  expiracion: "30 días máximo (vence solo, no requiere revocación manual después del hackathon)"
  almacenamiento: ".env (variable GITHUB_TOKEN), agregado a .gitignore — NUNCA en el código ni en commits"
```

### Sandbox de ejecución (Antigravity)

```yaml
sandbox:
  desarrollo_local: "User Settings → Terminal Sandboxing (toggle en Antigravity)"
  alternativa_dockerizada:
    archivo: ".gemini/sandbox.Dockerfile"
    base_image: "imagen oficial de sandbox de Gemini CLI"
    activacion: "export GEMINI_SANDBOX=docker"
  proposito: "Aislar la ejecución del navegador Playwright en un contenedor efímero y de bajo privilegio, separado de la red principal y del sistema de archivos sensible."
```

---

## 9. Sitios Demo — Especificación de Bugs Intencionales

```yaml
demo_sites:
  site_1_bad_alt:
    bugs:
      - "1 imagen con alt incorrecto (foto de perro, alt describe una gráfica)"
      - "1 imagen decorativa con alt verboso innecesario"
      - "1 imagen sin alt en absoluto"
  site_2_focus_trap:
    bugs:
      - "1 modal sin manejo de Escape ni botón de cierre alcanzable por Tab"
      - "Orden de foco ilógico: el modal oculto es focuseable antes que el contenido principal"
  site_3_mixed_errors:
    bugs:
      - "Texto con contraste insuficiente (#AAAAAA sobre #FFFFFF) en el título principal"
      - "1 botón con solo ícono SVG, sin aria-label"
      - "1 checkbox sin label asociado"
      - "Falta el atributo lang en <html>"
```

## 10. Escenario de Aceptación End-to-End (nivel sistema completo)

**Scenario:** Auditoría completa contra `site_3_mixed_errors`
`Given` el sitio `demo_sites/site_3_mixed_errors/index.html` con los 4 bugs listados arriba
`When` el usuario lo selecciona en la UI y presiona "Auditar"
`Then` el `AuditReport` final debe contener exactamente 4 `Finding`, uno por cada bug, cada uno con su `wcag_criterion` correcto y su `FixSuggestion` correspondiente — ni más, ni menos hallazgos que los 4 bugs intencionales

---

## 11. Checklist de Implementación (orden sugerido, no paralelo)

- [ ] 1. Estructura de carpetas completa (Sección 3) + `pyproject.toml` con dependencias de la Sección 2
- [ ] 2. Los 3 `demo_sites/` con los bugs exactos de la Sección 9
- [ ] 3. Las 5 skills sin LLM primero (4.1, 4.2, 4.3, 4.4, y el cálculo base de 4.5/4.6) — son las más rápidas y no dependen de la API de Gemini
- [ ] 4. `browser/runner.py` con el hook de seguridad de la Sección 8 ya integrado desde el inicio, no al final
- [ ] 5. Las 3 skills con LLM (4.7, 4.8, 4.9) usando `gemini-3.5-flash`
- [ ] 6. `agents/auditor.py` — Orquesta las 9 skills vía `SkillToolset` (ADK)
- [ ] 7. `agents/refactorizador.py` — consume `Finding[]`, produce `FixSuggestion[]`
- [ ] 8. `agents/orchestrator.py` — ensambla el `AuditReport`
- [ ] 9. `mcp_server/github_server.py` (Sección 7) + token configurado (Sección 8)
- [ ] 10. `web/app.py` (FastAPI) — UI mínima para correr el demo
- [ ] 11. `tests/skills_eval/` — al menos 1 test por skill validando el Scenario Given/When/Then correspondiente
- [ ] 12. `.github/workflows/a11y-audit.yml` — CI que corre el audit en PR (versión B, contra el propio repo demo)
- [ ] 13. `README.md` con arquitectura, setup, y diagramas
- [ ] 14. Grabar video (abrir con el dato del 96% del WebAIM Million, mostrar uso de Antigravity en el desarrollo)
- [ ] 15. Writeup en Kaggle
