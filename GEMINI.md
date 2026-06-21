# Coding Agent Guide — A11y-Forge (Bondy)

## Prerequisites & Local Setup

### 1. Instalar CLI global (Solo una vez)
```bash
uv tool install google-agents-cli
```

### 2. Sincronizar Dependencias del Proyecto
Este comando sincroniza el entorno virtual `.venv` con el archivo lock del repositorio:
```bash
uv sync
```

### 3. Instalar Navegadores de Playwright (Requerido localmente por cada desarrollador)
```bash
uv run playwright install --with-deps chromium
```

### 4. Configurar Hooks de Pre-Commit (Requerido localmente por cada desarrollador)
Para asegurar la calidad de código y formateo automático antes de realizar commits:
```bash
uv run pre-commit install
```

---

## Development Phases

### Phase 1: Understand Requirements
Before writing any code, understand the project's requirements, constraints, and success criteria. Read the technical design in docs/ARCHITECTURE.md and the implementation checklist in IMPLEMENTATION_PLAN.md if necessary.

### Phase 2: Build and Implement
Implement agent logic in `app/`. Use `agents-cli playground` for interactive testing. Iterate based on user feedback.
All skills must be stored under `.agents/skills/<name>/SKILL.md` (ADK Autodiscovery).

### Phase 3: The Evaluation Loop (Main Iteration Phase)
Start with 1-2 eval cases, run `agents-cli eval generate`, then `agents-cli eval grade`, iterate by making changes and rerunning both commands until satisfied. Expect 5-10+ iterations. Once you have a baseline, reach for `agents-cli eval compare` (regression diffs), `agents-cli eval analyze` (cluster failure modes), and `agents-cli eval optimize` (auto-tune prompts). See the **Evaluation Guide** for metrics, dataset schema, LLM-as-judge config, and common gotchas.

### Phase 4: Pre-Deployment Tests
Run `uv run pytest tests/unit tests/integration`. Fix issues until all tests pass.

### Phase 5: Deploy to Dev
**Requires explicit human approval.** Run `agents-cli deploy` only after user confirms. See the **Deployment Guide** for details.

### Phase 6: Production Deployment
Ask the user: Option A (simple single-project) or Option B (full CI/CD pipeline with `agents-cli infra cicd`).

## Development Commands

| Command | Purpose |
|---------|---------|
| `agents-cli playground` | Interactive local testing |
| `uv run pytest tests/unit tests/integration` | Run unit and integration tests |
| `agents-cli eval dataset synthesize` | Synthesize multi-turn eval scenarios for your agent |
| `agents-cli eval generate` | Run agent on eval dataset, produce traces |
| `agents-cli eval grade` | Run agent evaluations on the traces |
| `agents-cli eval compare` | Compare two grade-results files (regression check) |
| `agents-cli eval analyze` | Cluster failure modes from grade results |
| `agents-cli eval metric list` | List built-in metrics available in the SDK |
| `agents-cli eval optimize` | Auto-tune agent prompts using eval data |
| `agents-cli lint` | Check code quality |
| `agents-cli infra single-project` | Set up project infrastructure (Terraform) |
| `agents-cli deploy` | Deploy to dev |
| `agents-cli scaffold enhance` | Add deployment target or CI/CD to project |
| `agents-cli scaffold upgrade` | Upgrade project to latest version |

---

## Operational Guidelines for Coding Agents

- **Code preservation**: Only modify code directly targeted by the user's request. Preserve all surrounding code, config values (e.g., `model`), comments, and formatting.
- **Project Structure**: Maintain `google-adk` standard workspace format. Keep agent and app files inside the `app/` folder.
- **Workflow & Graphs**: Implement stateful logic using the Workflow API of ADK 2.0. Avoid manual Python orchestrations.
- **Security Guardrails**:
  - Always validate input path/URL parameters against `ALLOWED_SOURCES` in `app/app_utils/security.py` before allowing Playwright navigation.
  - Never expose credentials or local paths in agent outputs or system prompts.
- **NEVER change the model** unless explicitly asked. The default model is `gemini-flash-latest` (alias, do not hardcode numbered versions).
- **Model 404 errors**: Fix `GOOGLE_CLOUD_LOCATION` (e.g., `global` instead of `us-east1`), not the model name.
- **ADK tool imports**: Import the tool instance, not the module: `from google.adk.tools.load_web_page import load_web_page`
- **Run Python with `uv`**: `uv run python script.py`. Run `agents-cli install` first.
- **Stop on repeated errors**: If the same error appears 3+ times, fix the root cause instead of retrying.
- **Terraform conflicts** (Error 409): Use `terraform import` instead of retrying creation.

