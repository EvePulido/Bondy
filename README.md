# Bondy ♿🛡️

**Bondy** is an autonomous, agentic Web Accessibility Auditor built on **Google ADK 2.0**. It leverages large language models and deterministic Playwright routines to scan web applications, identify accessibility violations (WCAG 2.2 AA), and autonomously suggest exact code fixes.

## 🚀 Features

- **Autonomous Agent Workflow**: A dual-agent architecture (Auditor + Refactorizador) connected via ADK Workflows.
- **Deterministic Skills**: 6 highly specialized, deterministic accessibility skills that execute locally via Playwright (e.g., Focus Trap Detection, Contrast Calculation).
- **Security Guardrails**: Input validation to ensure only authorized local environments or raw HTML are scanned.
- **Local-First AI**: Runs flawlessly using Google AI Studio API Keys (`gemini-flash-latest`), perfect for local deployments without complex GCP architectures.

## 📁 Architecture & Workflow

1. **Auditor Agent**: Uses Playwright and multimodal vision tools to scan a target directory or raw HTML and generates `Finding` reports.
2. **Refactorizador Agent**: Consumes the findings and generates precise code modifications (`FixSuggestion`) based on WCAG patterns.

## 🛠️ Quick Start

### 1. Prerequisites
- Python 3.12+
- `uv` (Python Package Manager)
- A Google AI Studio API Key.

### 2. Installation
```bash
# Sync dependencies
uv sync

# Install Playwright browsers (Required)
uv run playwright install --with-deps chromium

# Set your API Key
$env:GEMINI_API_KEY="AQ.YourApiKeyHere..."
```

### 3. Run the API and Web UI
Launch the built-in FastAPI server to access the Bondy Web UI:
```bash
uv run python -m uvicorn app.fast_api_app:app --reload
```
Go to `http://localhost:8000/bondy` to interact with the agent.

## 🧪 Testing

We use `pytest` for all unit and integration testing. Due to quota limitations on free API keys, integration tests use a simulated (Mock) LLM response.

```bash
uv run pytest tests/unit tests/integration
```

## 🔒 Security

All tools strictly adhere to the project's security rules (`AGENTS.md`), preventing unauthorized web navigation and blocking directory traversal outside of the `ALLOWED_SOURCES`.

---
*Built with ❤️ using the Google Agent Development Kit.*
