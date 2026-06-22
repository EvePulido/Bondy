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
- [ ] Set up the GitHub Actions CI/CD workflow in `.github/workflows/bondy-audit.yml`.
- [x] Write the comprehensive repository `README.md` containing architecture overview, installation, and usage instructions.
- [ ] Record the 5-minute project demonstration video.
- [ ] Write the final Kaggle essay/writeup.

### Phase 8: Token Optimization & Web UI Enhancements
- [x] Analyze and mitigate Google AI Studio Free Tier rate limits by migrating to `gemini-3.1-flash-lite` (15 RPM / 500 RPD) and adding explicit `read_local_file` tool to the agent.
- [x] Implement backend retry loops with automatic sleep in `run_audit` when `429 RESOURCE_EXHAUSTED` occurs.
- [x] Fix LLM resource load failures by explicitly documenting files and adding no-script notes in LLM-based skills.
- [x] Restructure Auditor into four specialized concurrent subagents (Image, Form, Keyboard, Doc) using ADK 2.0 `JoinNode` and `merge_findings` node to optimize token overhead and speed.
- [x] Configure ruff `line-ending = 'native'` and codespell ignore patterns in `pyproject.toml` to ensure 100% clean local and CI linting.
- [ ] Overhaul and redesign the localhost:8000 web interface to be modern, intuitive, and highly accessible:
  - [ ] Rebuild the UI visual style following WCAG 2.2 AA contrast and typography guidelines to guarantee high readability.
  - [ ] Integrate three visualization themes/modes: Light Mode (default), Dark Mode, and High Contrast Mode.
  - [ ] Handle loading (with interactive steps indicating active subagents), success, and error feedback states gracefully.
  - [ ] Implement accessible checkboxes to dynamically parameterize the audit, allowing the user to select and run only specific subagents.

### Phase 9: Google Cloud Migration & API Logger Fixes
- [ ] Correct the `/feedback` logging fallback in `app/fast_api_app.py` to prevent `AttributeError` when Google Cloud credentials are not initialized locally.
- [ ] Create a Google Cloud billing account and project (`bondy-accessibility-auditor`).
- [ ] Enable the Vertex AI API in GCP.
- [ ] Authenticate developer machine using `gcloud auth application-default login`.
- [ ] Configure `.env` with `GOOGLE_CLOUD_PROJECT` and `GOOGLE_CLOUD_LOCATION` to route traffic through Vertex AI, unlocking `agents-cli eval run`.
