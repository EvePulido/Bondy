# Bondy ♿🛡️

**Bondy** is an autonomous, agentic Web Accessibility Auditor built on **Google ADK 2.0**. It leverages large language models and deterministic Playwright routines to scan web applications, identify accessibility violations (WCAG 2.2 AA), and autonomously suggest exact code fixes.

## 🚀 Features

- **Autonomous Agent Workflow**: A multi-agent concurrent architecture featuring specialized subagents (Image, Form, Keyboard, and Document Structure) synchronized via ADK 2.0 Workflows.
- **Deterministic Skills**: 6 highly specialized, deterministic accessibility skills that execute locally via Playwright (e.g., Focus Trap Detection, Contrast Calculation).
- **Security Guardrails**: Input validation to ensure only authorized local environments or raw HTML are scanned.
- **Local-First AI**: Runs flawlessly using Google AI Studio API Keys (`gemini-flash-latest`), perfect for local deployments without complex GCP architectures.

## 📁 Architecture & Workflow

1. **Specialized Auditor Agents**: Four concurrent subagents (`ImageAuditor`, `FormAuditor`, `KeyboardAuditor`, and `DocAuditor`) use Playwright and multimodal vision tools to scan a target directory or raw HTML, generating findings. These outputs are synchronized via a `JoinNode` and aggregated.
2. **Refactorizador Agent**: Consumes the aggregated findings and generates precise code modifications (`FixSuggestion`) based on WCAG patterns.

## 🛠️ Quick Start

### 1. Prerequisites
- Python 3.12+
- `uv` (Python Package Manager)
- A Google AI Studio API Key.

### 2. Installation & Credentials Setup
1. Clone the repository and sync dependencies:
   ```bash
   uv sync
   ```
2. Install Playwright browsers (required for deterministic visual/focus skills):
   ```bash
   uv run playwright install --with-deps chromium
   ```
3. Create a `.env` file in the root directory of the project and paste your Gemini API Key. To prevent conflicts with any expired or invalid environment variables configured globally on your local machine, **set both variables to the same key**:
   ```env
   GEMINI_API_KEY=tu_api_key_de_ai_studio
   GOOGLE_API_KEY=tu_api_key_de_ai_studio
   ```

### 3. Run the API and Web UI
Launch the built-in FastAPI server to access the Bondy Web UI:
   ```bash
   uv run python -m uvicorn app.fast_api_app:app --reload
   ```
   Go to `http://localhost:8000/bondy` to interact with the agent.

---

## ⚙️ Quota & Token Optimization

Since the Gemini Free Tier has strict rate limits (especially for requests per minute and per day), please review the [Optimization Guide](file:///C:/Users/evely/OneDrive/Desktop/Bondy/bondy/docs/OPTIMIZATION_GUIDE.md) to learn how to:
- Dynamically limit active skills to reduce token overhead.
- Design targeted local demo pages.
- Handle contrast validation without compromising production CSS practices.

## 🧪 Testing

We use `pytest` for all unit and integration testing. Due to quota limitations on free API keys, integration tests use a simulated (Mock) LLM response.

```bash
uv run pytest tests/unit tests/integration
```

## 🔒 Security

All tools strictly adhere to the project's security rules (`AGENTS.md`), preventing unauthorized web navigation and blocking directory traversal outside of the `ALLOWED_SOURCES`.

---
*Built with ❤️ using the Google Agent Development Kit.*
