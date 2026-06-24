# Bondy: Development & Migration Plan

This checklist outlines the sequential migration and development steps to consolidate the final **Bondy** project into the root workspace using the **Google ADK 2.0** architecture.

---

## Migration and Implementation Checklist (Strict Order)

### Phase 1: Folder Mapping and Base Structure
- [x] Copy the 9 skills from the previous prototype to the root `.agents/skills/` directory.
- [x] Copy the demo sites from the previous prototype to the root `demo_sites/` directory.
- [x] Retain the standard ADK scaffold structure under `app/`.

### Phase 2: Secure Environment Configuration
- [x] Synchronize dependencies using `uv sync`.
- [x] Install Playwright web browsers: `uv run playwright install --with-deps chromium`.
- [x] Configure git pre-commit hooks to run `ruff` format and lint quality checks automatically.

### Phase 3: Security Module Implementation
- [x] Create the security configuration module in `app/app_utils/security.py`.
- [x] Migrate the deterministic guardrail that validates and blocks any navigation to sources not registered in `ALLOWED_SOURCES` (authorized demo sites or raw HTML content).

### Phase 4: Workflow Graph in `app/agent.py`
- [x] Define the `Auditor` and `Refactorizador` agents in `app/agent.py`.
- [x] Implement the orchestration workflow using the ADK 2.0 Workflow API (connecting the Auditor's findings output to the Refactorizador's input).

### Phase 5: MCP Server and FastAPI Interface
- [x] Set up the GitHub reader MCP server in `mcp_server/github_server.py`.
- [x] Develop the FastAPI application in `app/fast_api_app.py` to serve the premium web UI, allowing users to run audits on demo sites or raw HTML, and view the final `AuditReport` with suggested fixes.
uv run python -m uvicorn app.fast_api_app:app --reload

### Phase 6: Evaluations and Unit Testing
- [x] Add pytest test cases under `tests/` to validate the security runner and the 6 deterministic skills.
- [x] Set up `eval_config.yaml` and run `agents-cli eval run` (SKIPPED: `agents-cli eval` requires a Vertex AI GCP Project, incompatible with local AI Studio keys).

### Phase 7: Delivery and Release Closure
- [x] Set up the GitHub Actions CI/CD workflow in `.github/workflows/bondy-audit.yml`.
- [x] Write the comprehensive repository `README.md` containing architecture overview, installation, and usage instructions.
- [ ] Record the 5-minute project demonstration video.
- [ ] Write the final Kaggle essay/writeup.

### Phase 8: Token Optimization & Web UI Enhancements
- [x] Analyze and mitigate Google AI Studio Free Tier rate limits by migrating to `gemini-3.1-flash-lite` (15 RPM / 500 RPD) and adding explicit `read_local_file` tool to the agent.
- [x] Implement backend retry loops with automatic sleep in `run_audit` when `429 RESOURCE_EXHAUSTED` occurs.
- [x] Fix LLM resource load failures by explicitly documenting files and adding no-script notes in LLM-based skills.
- [x] Restructure Auditor into four specialized concurrent subagents (Image, Form, Keyboard, Doc) using ADK 2.0 `JoinNode` and `merge_findings` node to optimize token overhead and speed.
- [x] Configure ruff `line-ending = 'native'` and codespell ignore patterns in `pyproject.toml` to ensure 100% clean local and CI linting.
- [x] Overhaul and redesign the localhost:8080 web interface to be modern, intuitive, and highly accessible:
  - [x] Rebuild the UI visual style following WCAG 2.2 AA contrast and typography guidelines to guarantee high readability.
  - [x] Integrate three visualization themes/modes: Light Mode (default), Dark Mode, and High Contrast Mode.
  - [x] Handle loading (with interactive steps indicating active subagents), success, and error feedback states gracefully.
  - [x] Implement accessible checkboxes to dynamically parameterize the audit, allowing the user to select and run only specific subagents.

### Phase 9: Google Cloud Migration & API Logger Fixes
- [x] Correct the `/feedback` logging fallback in `app/fast_api_app.py` to prevent `AttributeError` when Google Cloud credentials are not initialized locally.
- [x] Create a Google Cloud billing account and project (`bondy-dev-500300`).
- [x] Enable the Vertex AI API in GCP.
- [x] Authenticate developer machine using `gcloud auth application-default login` with quota project `bondy-dev-500300`.
- [x] Configure `.env` with `GOOGLE_CLOUD_PROJECT=bondy-dev-500300` and `GOOGLE_CLOUD_LOCATION=global` to route traffic through Vertex AI.

### Phase 10: Architecture Simplification & End-to-End Fix ✅ (Session: 2026-06-22)

> **Context for teammates:** This session resolved a series of cascading errors that prevented the audit pipeline from working end-to-end. Below is a full account of what was fixed and how.

#### Problems Encountered & Resolutions

| # | Error | Root Cause | Fix |
|---|-------|-----------|-----|
| 1 | `404 NOT_FOUND` (publisher model) | Region `us-central1` does not serve `gemini-3.1-flash-lite` | Set `GOOGLE_CLOUD_LOCATION=global` in `.env` |
| 2 | `FileNotFoundError` (duplicated path) | `get_safe_demo_path()` was appending `index.html` to a path that already ended with it | Added check in `security.py` to skip appending when path already ends in `index.html` |
| 3 | `400 INVALID_ARGUMENT` (Context Cache) | Demo HTML files are ~891 tokens; Vertex AI requires ≥4096 to cache | Removed `ContextCacheConfig` from `agent.py` |
| 4 | `LlmCallsLimitExceededError: 500` | Agents had `output_schema=list[Finding]`. Model returned `{"findings":[...]}` (an object), ADK rejected it, model retried — infinite loop | Wrapped in `FindingsReport` / `FixesReport` BaseModels |
| 5 | `TypeError: Object of type Finding is not JSON serializable` | `merge_findings` node returned a raw Python list of Pydantic objects; ADK could not serialize it to pass to the next node | Changed return type to `FindingsReport` (a full BaseModel) |
| 6 | `429 RESOURCE_EXHAUSTED` | 4 parallel agents saturated the Vertex AI rate limit instantly | Added `max_concurrency=1` to the Workflow |
| 7 | Agent returns "No issues found" (false negative) | In the parallel Workflow, each sub-agent received the user message as free text but had **no explicit context** about which file to read. Model skipped tool calls | Full redesign: replaced the 4-agent Workflow with a **single `LlmAgent`** with step-by-step instructions |
| 8 | `set_model_response_tool` ValidationError | ADK's internal `output_schema` mechanism (`set_model_response_tool`) failed silently when validating nested Pydantic lists | **Removed `output_schema` and `output_key` entirely.** Agent now returns plain JSON text; backend parses it with `json.loads()` |

#### Final Architecture

The agent is now a single `LlmAgent` named `BondyAccessibilityAgent` with:
- All 9 skills available as tools (`SkillToolset`)
- `read_local_file` tool for secure HTML access (validated via `security.py`)
- Explicit step-by-step instruction to call `read_local_file` first, audit WCAG 1.1.1 / 1.3.1 / 1.4.3 / 2.4.4 / 3.1.1, then return a raw JSON array
- No `output_schema` — the FastAPI endpoint captures `event.content.parts[].text` and parses JSON manually

#### Files Modified

- `app/agent.py` — complete rewrite: single `LlmAgent`, no Workflow, no `output_schema`
- `app/fast_api_app.py` — `/api/audit` endpoint: captures last text event, strips markdown fences, parses JSON
- `app/app_utils/security.py` — fixed `index.html` path duplication bug
- `web/index.html`, `web/index.css`, `web/app.js` — premium dark-mode UI with Before/After fix cards
- `.env` — `GOOGLE_CLOUD_LOCATION=global`

#### How to Run Locally

```bash
uv sync
uv run python -m uvicorn app.fast_api_app:app --reload --port 8080
# Open http://localhost:8080, select a demo site, click Run Audit
```

#### Key Lesson

> ADK 2.0's `output_schema` with nested Pydantic models is experimental and unreliable. For production, instruct the model to return **plain JSON text** and parse it manually in the backend.

