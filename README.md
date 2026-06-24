<div align="center">
  <img src="web/assets/logo-bondy.png" alt="Bondy Logo" width="250"/>
  <h1>Bondy</h1>
  <p><strong>An autonomous, agentic Web Accessibility Auditor built on Google ADK 2.0.</strong></p>
</div>

Bondy leverages large language models and deterministic Playwright routines to scan web applications, identify accessibility violations (WCAG 2.2 AA), and autonomously suggest exact code fixes.

---

## Table of Contents
- [The Problem](#the-problem)
- [The Solution](#the-solution)
- [Features](#features)
- [Architecture & Workflow](#architecture--workflow)
- [Quick Start](#quick-start)
- [Testing](#testing)
- [Security](#security)

---

## The Problem

According to the WebAIM Million report, **95.9% of home pages presented detectable WCAG 2 failures**, reversing the trend of small improvements observed over the previous six years (WebAIM, 2026). This reversal and stagnation in web accessibility may be heavily exacerbated by the rapid proliferation of AI-assisted coding tools. While developers increasingly rely on Large Language Models (LLMs) to generate web applications, these models often produce boilerplate HTML that lacks proper semantic structure and fails to adhere to modern accessibility standards.

Manual web accessibility audits are resource-intensive, slow, and expensive. Static code analyzers (like Lighthouse) only check for the presence of HTML attributes but cannot evaluate their semantic quality or catch dynamic interaction bugs. 

Strikingly, **96% of all detected errors fall into just six categories**:
1. Low contrast text (83.9%)
2. Missing alternative text for images (53.1%)
3. Missing form input labels (51%)
4. Empty links (46.3%)
5. Empty buttons (30.6%)
6. Missing document language (13.5%)

Fixing just these issues would significantly improve web accessibility globally.

## The Solution

**Bondy** bridges the critical gap between passive static linters and expensive human auditors. While tools like Google Lighthouse simply parse source code to check if an `alt` attribute exists, they fail to understand if the image is merely decorative or if the provided text actually makes sense. 

Bondy introduces a paradigm shift by combining **deterministic browser automation (Playwright)** with the **cognitive reasoning of Large Language Models (Gemini Multimodal)**. 

Unlike traditional tools, Bondy:
1. **Navigates like a human**: It physically tabs through the DOM using Playwright to detect invisible focus traps and illogical tab sequences.
2. **Sees like a human**: It uses Gemini's Multimodal Vision to look at the rendered web page, deciding if an image is purely decorative (requiring an empty `alt=""`) or analyzing if the current description matches the visual context.
3. **Acts like an engineer**: Once it finds the errors that plague 96% of the web, it doesn't just output a warning, it acts as an autonomous refactoring agent, generating the exact, drop-in HTML patch needed to resolve the WCAG violation.

## Features

- **Autonomous Agent Workflow**: A monolithic AI Agent orchestrator (`BondyAccessibilityAgent`) equipped with a rich `SkillToolset` to sequentially evaluate inputs and bypass strict API rate limits.
- **Deterministic Skills**: 6 highly specialized, deterministic accessibility skills that execute locally via Playwright (e.g., focus trap detection, contrast calculation).
- **Security Guardrails**: Strict input validation to ensure only authorized local environments or raw HTML snippets are scanned.
- **Enterprise-Ready AI**: Runs robustly using Google Cloud Vertex AI, ensuring high availability and bypassing the limitations of free-tier API keys.

## Architecture & Workflow

To circumvent rate limits while maintaining high performance, Bondy uses a single, monolithic `BondyAccessibilityAgent` equipped with 9 specialized skills (`SkillToolset`). This single agent handles the full lifecycle of reading files, validating criteria, and returning a JSON payload of fixes.

```mermaid
flowchart TD
    UI[FastAPI Web Interface] -->|URL or HTML Snippet| SEC{Security Validator}
    SEC -->|Allowed| AGENT[BondyAccessibilityAgent]
    SEC -->|Blocked| ERR[HTTP 403 Forbidden]
    
    subgraph Agent Runtime
        AGENT -->|Calls| PLAY[Playwright Simulator]
        AGENT -->|Calls| DOM[DOM Parsers]
        AGENT -->|Calls| VISION[Gemini Vision Model]
        
        PLAY -.->|Focus Traps & Tab Order| AGENT
        DOM -.->|Labels & Lang Attributes| AGENT
        VISION -.->|Contextual Alt Text & Contrast| AGENT
    end
    
    AGENT -->|Synthesizes Findings & Refactors HTML| JSON_REPORT[JSON Fixes Payload]
    JSON_REPORT --> UI
```

### Skill Mapping

| Category | Associated Skill | Skill Type | Responsibility | WCAG Criterion |
| :--- | :--- | :--- | :--- | :--- |
| **Image Auditing** | `alt-text-quality-analyzer` | Gemini Multimodal Vision | Analyzes image context against alt text | 1.1.1 (Non-text Content) |
| | `image-decorator-classifier` | Gemini Multimodal Vision | Classifies if an image is purely decorative | 1.1.1 (Non-text Content) |
| **Form Auditing** | `form-labels-validator` | Deterministic (DOM Parsing) | Audits missing associations in input tags | 1.3.1 / 4.1.2 (Labels) |
| **Keyboard Auditing**| `focus-order-validator` | Playwright Simulation | Detects illogical focus orders and jumps | 2.4.3 (Focus Order) |
| | `focus-trap-detector` | Playwright Simulation | Detects keyboard focus traps in components | 2.1.2 (No Focus Trap) |
| **Document Auditing** | `document-language-validator`| Deterministic (DOM Parsing) | Validates root `<html>` lang attribute | 3.1.1 (Language of Page) |
| | `text-contrast-calculator` | Mathematical Formula | Calculates text contrast against backgrounds | 1.4.3 (Contrast) |
| | `interactive-elements-validator`| Deterministic (DOM Parsing) | Identifies empty links or button tags | 2.4.4 / 4.1.2 (Name/Role) |
| **Refactoring** | `suggestion-fix-generator` | Gemini Text Refactoring | Generates clean HTML replacement code | N/A |

## Quick Start

### 1. Prerequisites
- Python 3.12+
- `uv` (Python Package Manager)
- A Google Cloud Project with Vertex AI enabled.

### 2. Installation & Credentials Setup
1. Clone the repository and sync dependencies:
   ```bash
   uv sync
   ```
2. Install Playwright browsers (required for deterministic visual/focus skills):
   ```bash
   uv run playwright install --with-deps chromium
   ```
3. Authenticate with Google Cloud (Vertex AI) since this project routes traffic globally to handle rate limits:
   ```bash
   gcloud auth application-default login
   ```
4. Create a `.env` file in the root directory and configure it with your own Google Cloud Project ID:
   ```env
   # Replace with your own Google Cloud Project ID that has the Vertex AI API enabled
   GOOGLE_CLOUD_PROJECT=your-google-cloud-project-id
   GOOGLE_CLOUD_LOCATION=global
   ```

### 3. Run the API and Web UI Locally
Launch the built-in FastAPI server to access the Bondy Web UI:
   ```bash
   uv run python -m uvicorn app.fast_api_app:app --reload --port 8080
   ```
   Go to `http://localhost:8080` to interact with the agent.

### 4. Deployment to Google Cloud (Optional)
Bondy can be fully deployed to your own Google Cloud environment (Cloud Run) using the ADK `agents-cli`:

1. Provision the base infrastructure (Terraform):
   ```bash
   agents-cli infra single-project
   ```
2. Build and deploy the Dockerized application to Cloud Run:
   ```bash
   agents-cli deploy
   ```

## Testing

We use `pytest` for all unit and integration testing. 

```bash
uv run pytest tests/unit tests/integration
```

## Security

All tools strictly adhere to the project's security rules (`AGENTS.md`), preventing unauthorized web navigation and blocking directory traversal outside of the `ALLOWED_SOURCES`.

## Contributors

<table>
  <tr>
    <td align="center">
      <a href="https://github.com/EvePulido">
        <img src="https://github.com/EvePulido.png" width="100px;" alt="EvePulido" style="border-radius:50%"/><br />
        <sub><b>EvePulido</b></sub>
      </a>
    </td>
    <td align="center">
      <a href="https://github.com/1mano1">
        <img src="https://github.com/1mano1.png" width="100px;" alt="1mano1" style="border-radius:50%"/><br />
        <sub><b>1mano1</b></sub>
      </a>
    </td>
  </tr>
</table>

## References

WebAIM. (2026). *The WebAIM million: An annual accessibility analysis of the top 1,000,000 home pages*. Center for Persons with Disabilities, Utah State University. https://webaim.org/projects/million/

---
*Built using the Google Agent Development Kit.*
