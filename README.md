<div align="center">
  <img src="bondy/resources/web/assets/logo-bondy.png" alt="Bondy Logo" width="250"/>
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
- [Testing & Linting](#testing--linting)
- [Security](#security)
- [Contributors](#contributors)
- [References](#references)

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
- **Single-Pass Modal Auditing**: Audits and generates complete, generic, and reusable modal accessibility fixes (logical DOM order, role/aria attributes, close buttons, robust focus traps, Escape handlers, background inertness, and focus restoration) in the very first scan.
- **Playwright Computed Contrast**: Uses a Playwright Chromium headless instance to render the page and extract exact Computed Styles for foreground/background colors, ensuring deterministic and flawless WCAG 1.4.3 contrast ratio calculations without relying on AI mathematical estimations.
- **Robust JSON Parsing Engine**: Features a fault-tolerant JSON extraction system capable of parsing clean payloads out of arbitrary markdown code blocks and conversational commentary returned by the model.
- **Deterministic Skills**: 6 highly specialized, deterministic accessibility skills that execute locally via Playwright (e.g., focus trap detection, HTML lang validation).
- **Deterministic axe-core Baseline**: Every audit starts with axe-core (WCAG 2.0/2.1/2.2 A/AA) plus Chromium's accessibility tree, and the score shown in the UI is computed from real rule counts.
- **Grounded Vision Checks**: Alt text is verified against the real image with structured, temperature-0 output and explicit anti-hallucination rules; images are classified as decorative, informative or functional; and a screenshot of the rendered page is analyzed for visual issues.
- **Safe Auto-Fix**: "Apply to File" is offered only when the original snippet appears exactly once in the file.
- **Security Guardrails**: Strict input validation to ensure only authorized local environments or raw HTML snippets are scanned.
- **Enterprise-Ready AI**: Runs robustly using Google Cloud Vertex AI, ensuring high availability and bypassing the limitations of free-tier API keys.

## Architecture & Workflow

To circumvent rate limits while maintaining high performance, Bondy uses a single, monolithic `BondyAccessibilityAgent` equipped with 9 specialized skills (`SkillToolset`). This single agent handles the full lifecycle of reading files, validating criteria, and returning a JSON payload of fixes.

```mermaid
flowchart TD
    UI["FastAPI Web Interface"] -->|"URL or HTML Snippet"| SEC{"Security Validator"}
    SEC -->|"Allowed"| AGENT["BondyAccessibilityAgent"]
    SEC -->|"Blocked"| ERR["HTTP 403 Forbidden"]
    
    subgraph Agent_Runtime ["Agent Runtime"]
        AGENT -->|"Calls"| PLAY["Playwright Simulator"]
        AGENT -->|"Calls"| DOM["DOM Parsers"]
        AGENT -->|"Calls"| VISION["Gemini Vision Model"]
        
        PLAY -.->|"Focus Traps, Tab Order and Contrast"| AGENT
        DOM -.->|"Labels and Lang Attributes"| AGENT
        VISION -.->|"Contextual Alt Text"| AGENT
    end
    
    AGENT -->|"Synthesizes Findings and Refactors HTML"| JSON_REPORT["JSON Fixes Payload"]
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
| | `text-contrast-calculator` | Playwright Simulation (Computed Styles) | Calculates text contrast mathematically against rendered backgrounds | 1.4.3 (Contrast) |
| | `interactive-elements-validator`| Deterministic (DOM Parsing) | Identifies empty links or button tags | 2.4.4 / 4.1.2 (Name/Role) |
| **Baseline** | `axe-accessibility-scanner` | Playwright + axe-core (Accessibility Tree) | Deterministic WCAG 2.x A/AA scan and unnamed-control detection | Multiple (2.0 / 2.1 / 2.2) |
| **Vision tools** | `verify_image_alt_text`, `classify_image_decorative`, `analyze_rendered_page` | Gemini Multimodal Vision + heuristics | Grounded alt verification, decorative/functional classification, rendered-page screenshot analysis | 1.1.1 / 1.4.x |
| **Refactoring** | `suggestion-fix-generator` | Gemini Text Refactoring | Generates clean HTML replacement code | N/A |

## Quick Start

### 1. Prerequisites
- Python 3.12+
- `uv` (Python Package Manager)
- A Gemini API key from [Google AI Studio](https://aistudio.google.com/apikey) (free, no billing needed) **or** a Google Cloud Project with Vertex AI enabled.

### 2. Installation & Credentials Setup
1. Clone the repository and sync dependencies. The base install is minimal (Playwright + `google-genai` + Pydantic); the web UI and the ADK agent are opt-in extras:
   * **Windows / macOS / Linux**:
     ```bash
     uv sync                                  # dev checkout: core + dev group (includes server + agent)
     uv sync --no-dev --extra server --extra agent   # run the web UI + agent only
     uv pip install "bondy[server,agent]"     # from a built wheel / index
     ```

   | Extra | Adds | Needed for |
   | :--- | :--- | :--- |
   | _(none)_ | `playwright`, `google-genai`, `pydantic` | Deterministic scanners and vision tools |
   | `server` | `fastapi`, `uvicorn`, `python-dotenv` | Local web UI / HTTP API (`bondy.fast_api_app`) |
   | `agent` | `google-adk` | ADK `BondyAccessibilityAgent` (the web UI uses it today, so install `server` + `agent` together) |
   | `gcp` | `google-adk[gcp]`, Cloud Logging, GCS, OpenTelemetry GenAI | Cloud Run / Vertex AI deployments only |
   | `mcp` | `mcp`, `PyGithub` | `mcp_server/github_server.py` |
   | `eval`, `lint` | evaluation / ruff, ty, codespell | Evaluations and linting |

   **Telemetry is off by default.** Nothing is sent to Google Cloud unless you install the `gcp` extra *and* opt in with `BONDY_CLOUD_LOGGING=1` (Cloud Logging) and/or `LOGS_BUCKET_NAME` + `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` (GenAI telemetry).
2. Install Playwright browsers (required for deterministic visual/focus skills):
   * **Windows / macOS / Linux**:
     ```bash
     uv run playwright install --with-deps chromium
     ```
3. **Fastest option — Google AI Studio (no Google Cloud needed):** create an API key at <https://aistudio.google.com/apikey>, copy `.env.example` to `.env` and set:
   ```env
   GOOGLE_GENAI_USE_VERTEXAI=False
   GOOGLE_API_KEY=your-ai-studio-api-key
   ```
   Then skip to step 5's "Run" section. The free tier has low quotas: Bondy retries automatically on 429/503 and falls back to a secondary model.

   **Vertex AI option** — follow the next steps if you prefer Google Cloud:

   Create a Google Cloud Project (if you don't have one):
   - Go to the [Google Cloud Console (console.cloud.google.com)](https://console.cloud.google.com/).
   - Create a new project and copy its **Project ID**.
   - Make sure to enable the **Vertex AI API** in the APIs & Services section for that project.
4. Authenticate with Google Cloud locally since this project routes traffic globally to handle rate limits:
   * **Windows / macOS / Linux**:
     ```bash
     gcloud auth application-default login
     gcloud auth application-default set-quota-project your-google-cloud-project-id
     ```
5. Configure your local environment variables. You can create a `.env` file in the root directory (copy `.env.example`):
   ```env
   # Force ADK to use Vertex AI instead of standard Gemini API
   GOOGLE_GENAI_USE_VERTEXAI=True
   
   # Replace with your own Google Cloud Project ID that has the Vertex AI API enabled
   GOOGLE_CLOUD_PROJECT=your-google-cloud-project-id
   GOOGLE_CLOUD_LOCATION=global
   ```
   *Alternatively, if you prefer running temporary exports in your terminal:*
   * **Windows (PowerShell)**:
     ```powershell
     $env:GOOGLE_GENAI_USE_VERTEXAI="True"
     $env:GOOGLE_CLOUD_PROJECT="your-google-cloud-project-id"
     ```
   * **macOS / Linux (Bash/Zsh)**:
     ```bash
     export GOOGLE_GENAI_USE_VERTEXAI="True"
     export GOOGLE_CLOUD_PROJECT="your-google-cloud-project-id"
     ```

#### Optional environment variables

| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `BONDY_FALLBACK_MODEL` | `gemini-3.5-flash-lite` | Model used automatically after a 503 from the primary model. Empty disables it. |
| `BONDY_VISION_MODEL` | `gemini-flash-latest` | Model for the vision tools (alt text, decorative images, page screenshot). |
| `BONDY_API_KEY` | _unset_ | If set, `POST /api/apply-fix` requires an `X-API-Key` header. If unset, only localhost can write files. |

### 2b. Command line (no API key needed)

```bash
bondy --version
bondy doctor                              # checks Python, Chromium, axe-core, config, API key (offline)
bondy doctor --check-key                  # + validates the key with 1 minimal request
bondy scan ./my-site --no-llm             # deterministic scanners on a file or folder
bondy scan page.html --format json --fail-on warning
```

`bondy scan` runs axe-core, contrast, keyboard focus (trap/order), `lang`, form labels and accessible-name checks. Without `--no-llm` and **with an API key** (`GEMINI_API_KEY` or `GOOGLE_API_KEY`) it also runs a semantic stage on `<img>` elements: code triages first (decorative signals, redundant "image of" prefixes, images that cannot be loaded) and only the rest goes to Gemini, **several images per request** (`--batch-size`, default 8), with one fused call that judges the alt text and the decorative/informative/functional class. The final keep/fix/manual-review decision is made in code. Without a key it falls back to `--no-llm` and says so.

Exit code: `0` nothing at/above `--fail-on` (default `critical`), `1` findings at/above it, `2` usage/config error or a scanner failed (incomplete result), `3` **partial** result (a limit or the API quota stopped the scan and nothing at/above the threshold was found).

```bash
bondy estimate ./my-site                  # requests / tokens / cost estimate; calls no model
bondy scan ./my-site --dry-run            # same estimate, runs nothing
bondy scan ./my-site --max-requests 20 --max-usd 0.50 --max-pages 50 --max-images 100
```

Hard limits (`--max-requests`, `--max-usd`, `--max-pages`, `--max-images`; also `bondy.toml`/`BONDY_MAX_*`) stop the scan and print a PARTIAL RESULT with the reason. `--max-requests` counts HTTP requests to the model, retries included, and has a **default of 50**; `0` means no limit (the summary says when the cap in force is the default and how to change it). The other limits are unlimited unless set. At the end of every LLM scan Bondy prints what it used: requests, batches, images verified/skipped, tokens (when the provider reports them) and an **estimated** cost.

**Prices are never assumed.** Bondy ships no price values: set `price_input_per_mtok` and `price_output_per_mtok` (USD per million tokens, from your provider's price list) in `bondy.toml` or `BONDY_PRICE_INPUT_PER_MTOK` / `BONDY_PRICE_OUTPUT_PER_MTOK`. Without them `estimate`, `--dry-run` and the usage summary show requests and tokens and say the dollar cost is not available (JSON: `cost_usd: null` plus `cost_unavailable_reason`). `--max-usd` needs prices: without them the command fails with exit code 2 before calling the model. `estimate` is an approximation (characters/4 plus `tokens_per_image`), not a quote.

Images in the HTML are sent to the provider: local files inside the project root, and public http(s) images, which Bondy downloads (public hosts only, redirects re-checked). Use `--no-remote-images` (`remote_images = false`, `BONDY_REMOTE_IMAGES=0`) to skip downloading remote images; they then go to manual review. The free tier of the Gemini API may use content to improve Google products.

**Cache, incremental scans and resuming.** When something needs it (a scan that uses the model, `--changed-only`, `--since` or `--resume`), Bondy keeps a small cache under `<scanned folder>/.bondy/cache` and puts a `.gitignore` containing `*` inside `.bondy/` so it never shows up in your `git status`. A plain deterministic scan (`bondy scan --no-llm`) writes nothing into the scanned folder. The cache holds: one model verdict per image (key = image bytes + alt + the context sent + model + prompt/schema version), the result of each finished page and a marker when a scan was cut short. Consequences: re-scanning an unchanged project makes **0 requests**; `bondy scan --changed-only` also skips unchanged pages entirely (HTML and local images hashed) and marks them `reused`; `--since <git-ref>` scans only files changed vs a ref and reuses the saved result (same content hash and configuration) for the untouched ones; those without a valid saved result are listed as `skipped`, not as a partial result. If the scan stops (daily quota, `--max-*`, `--scan-timeout`, Ctrl+C: it exits with code 3 and saves what is done) run it again with `--resume` and finished work is not repeated. `--no-cache` disables all of it (`cache = false`), `--cache-dir` moves it, `--clear-cache` / `bondy cache clear` empties it (only Bondy's own files). Entries contain no API key or absolute paths. Remote images are identified by URL for page reuse, so a remote image that changes under the same URL is not detected by `--changed-only`.

`bondy doctor --check-key` validates your API key with one minimal request (opt-in; plain `doctor` stays offline) and tells a rejected key from an exhausted quota or no network. `scan` stops immediately (exit 2, no retries) if the first batch shows the key is invalid; a fully cached scan needs no key. Scanners share one browser per scan; `--timeout` (seconds per page, default 60) and `--scan-timeout` (default 900) bound the work, `0` = no limit. Known limit: a page whose JavaScript starts spinning *after* load can block `--timeout` until the browser closes the tab (about 85 s measured), because `--scan-timeout` is checked between pages, scanners and batches, not inside a blocked evaluation. If that happens, use `--scan-timeout` and `--resume` to continue without repeating finished work.

**Configuration precedence: flag > environment variable > `bondy.toml` > default.** `bondy.toml` is searched upward from the current directory (or pass `--config`). Keys: `model`, `vision_model`, `fallback_model`, `no_llm`, `static`, `format` (`terminal`|`json`|`markdown`|`html`|`sarif`), `fail_on` (`critical`|`warning`|`never`), `checks`, `include`, `exclude`, `batch_size`, `max_requests`, `max_usd`, `max_pages`, `max_images`, `price_input_per_mtok`, `price_output_per_mtok`, `tokens_per_image`, `remote_images`, `cache`, `cache_dir`, `timeout`, `scan_timeout`, `baseline`, and `[[ignore]]` tables (file only). Each key has an environment variable (`BONDY_MODEL`, `BONDY_VISION_MODEL`, `BONDY_FALLBACK_MODEL`, `BONDY_NO_LLM`, `BONDY_FORMAT`, `BONDY_FAIL_ON`, `BONDY_CHECKS`, `BONDY_INCLUDE`, `BONDY_EXCLUDE`, `BONDY_BATCH_SIZE`, `BONDY_MAX_REQUESTS`, `BONDY_MAX_USD`, `BONDY_MAX_PAGES`, `BONDY_MAX_IMAGES`, `BONDY_PRICE_INPUT_PER_MTOK`, `BONDY_PRICE_OUTPUT_PER_MTOK`, `BONDY_TOKENS_PER_IMAGE`, `BONDY_REMOTE_IMAGES`, `BONDY_CACHE`, `BONDY_CACHE_DIR`, `BONDY_TIMEOUT`, `BONDY_SCAN_TIMEOUT`, `BONDY_BASELINE`; lists are comma-separated).

```toml
# bondy.toml
fail_on = "warning"
checks = ["WCAG 1.1.1", "WCAG 3.1.1"]
exclude = ["node_modules/**", "dist/**"]
```

The API key is read from `GEMINI_API_KEY` (first) or `GOOGLE_API_KEY`; it is intentionally **not** accepted in `bondy.toml` because that file is meant to be committed. Variables already set in your shell are never overwritten by `.env`.

### 2c. Reports, baselines, suppressions and CI

```bash
bondy scan ./site --format markdown --output report.md   # terminal | json | markdown | html | sarif
bondy scan ./site --format sarif --output bondy.sarif    # SARIF 2.1.0 for GitHub code scanning
bondy baseline create ./site -o bondy-baseline.json      # accept today's findings
bondy scan ./site --baseline bondy-baseline.json         # only NEW findings fail
```

**Formats.** All of them are rendered from one internal report. Paths are always relative to the scanned folder with `/` separators (never your absolute paths). `html` is a single self-contained file (inline CSS, no JavaScript, no remote resources, landmarks, `lang`, AA contrast, a restrictive CSP). Everything that comes from the scanned project (HTML, alt text, selectors, paths) is treated as untrusted data and escaped for the target format. `--output FILE` writes the report there and still prints the terminal summary. The exit code does not depend on the format. In SARIF each result carries a stable `partialFingerprints` value; GitHub resolves paths from the repository root, so when you scan a sub-folder pass `--sarif-prefix <folder relative to the repo root>` (the bundled action does it for you). Baselined and suppressed findings are not emitted as SARIF results (GitHub code scanning does not document support for `suppressions`/`baselineState`); their counts are in `runs[].properties.bondy`.

**Baseline.** A finding's fingerprint is rule + path relative to the scanned folder + normalized selector or HTML fragment, never a line number, so moving code around does not resurrect old findings. `--baseline FILE` (also `baseline` in `bondy.toml`, relative to that file, or `BONDY_BASELINE`) hides known findings, reports how many were hidden and how many were **resolved** (so you can regenerate a smaller baseline) and only new findings count for the exit code. A corrupt, unknown-version or missing baseline is a usage error (exit 2) detected before anything is scanned or spent. `baseline create` refuses to write when the scan had errors or is partial. Create the baseline in the same mode you run in CI (browser vs static, with or without the model): findings of checks that did not run are reported as "not re-evaluated", not as resolved.

**Suppressions (always with a reason).**

```html
<!-- bondy-ignore: image-alt, 1.4.3 -- decorative logo, the text is adjacent -->
<img src="logo.png">
```

```toml
# bondy.toml
[[ignore]]
path = "legacy/**"          # glob relative to the scanned folder; no absolute paths, no ".."
rule = "color-contrast"     # a rule id (axe rule or Bondy check) or a WCAG criterion such as "1.4.3"
reason = "legacy pages are retired in Q3"
```

The comment applies to the next element (a comment before `<html>` applies to page-level findings such as a missing `lang`). Identical elements are indistinguishable and are suppressed together; findings that Bondy cannot tie to one element are never suppressed by a comment (use `[[ignore]]`). A missing reason, an unparsable rule or a path that leaves the folder is a usage error (exit 2). Every report lists the applied suppressions with their reason and warns about **obsolete** ones (matching nothing); an unknown-but-well-formed rule name shows up as obsolete, because the axe rule list is not enumerable offline.

**Secret redaction.** Before the HTML context and alt text are sent to the model (and before they are hashed into the verdict cache, so secrets never reach `.bondy/`), Bondy replaces secret-looking values with `[REDACTED]`: `AIza...`, `sk-...`, `ghp_...`, `AKIA...`, `Bearer`/JWT tokens, PEM private keys, `api_key=`/`token=`/`password=`-style assignments and URLs with credentials or `?token=`/`?key=`. Report snippets are redacted the same way, and a page whose findings quote secret-like text is not saved for `--changed-only` reuse. Files such as `.env`, `*.pem` or `id_rsa` are never loaded as images. This is **pattern matching, not a guarantee**: unusual formats, secrets inside image pixels or split by the context window are not caught; do not scan code you may not share with your provider.

**Summary and next step.** Every run ends with new findings by severity, how many were hidden by the baseline or suppressed, pages scanned/reused/skipped, the model usage and a concrete next step; the JSON has the same numbers under `summary`.

**CI.** `action.yml` is a composite GitHub Action (inputs `path`, `fail-on`, `format`, `baseline`, `changed-only`, `since`, `gemini-api-key`, ...) that installs Bondy, scans and uploads the SARIF with `github/codeql-action/upload-sarif` pinned to a commit. `.pre-commit-hooks.yaml` defines a `bondy` hook that scans only the HTML changed against `HEAD`, offline and without writing a cache. A ready-to-copy, inactive workflow is in `docs/ci-example.yml`.

### 3. Run the API and Web UI Locally
Launch the built-in FastAPI server to access the Bondy Web UI:
* **Windows / macOS / Linux**:
  ```bash
  uv run python -m uvicorn bondy.fast_api_app:app --reload --port 8080
  ```
  Go to `http://localhost:8080` to interact with the agent.

### 4. Deployment to Google Cloud (Optional)
Bondy can be fully deployed to your own Google Cloud environment (Cloud Run) using the ADK `agents-cli`:

1. Provision the base infrastructure (Terraform):
   * **Windows / macOS / Linux**:
     ```bash
     agents-cli infra single-project
     ```
2. Build and deploy the Dockerized application to Cloud Run:
   * **Windows / macOS / Linux**:
     ```bash
     agents-cli deploy
     ```

### 5. Auditing Local Files (Usage)
Bondy supports auditing local files seamlessly. To scan a local project:
1. Drop your HTML files or folders into the local `demo_sites/` directory within this repository.
2. Open the Bondy Web UI (`http://localhost:8080`).
3. In the URL bar of the UI, simply type the path to your file relative to the demo folder (e.g., `demo_sites/my_folder/index.html` or just `demo_sites/my_folder`).
4. Bondy will read your local HTML, launch a headless browser to evaluate computed styles and interactions, and autonomously generate a JSON fix.

## Testing & Linting

### Running Tests
We use `pytest` for all unit and integration testing.
* **Windows / macOS / Linux**:
  ```bash
  uv run pytest
  ```

### Code Formatting & Pre-Commit
Verify code compliance with formatters and linters:
* **Windows / macOS / Linux**:
  ```bash
  uv run pre-commit run --all-files
  ```

### Metadata and Manifest Validation
Validate agent configurations, types, and manifests:
* **Windows / macOS / Linux**:
  ```bash
  agents-cli lint
  ```

## Security

All tools follow the project's security rules (`.agents/AGENTS.md`):

- **Path guardrail:** only files inside `demo_sites/` or raw HTML are audited; traversal and absolute paths are rejected (`bondy/app_utils/security.py`).
- **SSRF guard:** remote image/page URLs must resolve to public IPs; loopback, private and metadata addresses are blocked (`validate_public_url`). The axe scanner aborts every non-local network request made by the audited page.
- **Secret redaction:** secret-looking values are replaced with `[REDACTED]` before text reaches the model, the cache or a report (best effort, not a guarantee).
- **Untrusted output:** scanned HTML, alt text and paths are escaped in every report format (HTML, Markdown, SARIF, terminal).
- **Write protection:** `POST /api/apply-fix` accepts only localhost, or a valid `X-API-Key` when `BONDY_API_KEY` is set, and refuses ambiguous replacements.

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

Demo site templates provided by [freewebsitetemplates.com](https://freewebsitetemplates.com) (used for accessibility auditing test environments).

---
*Built using the Google Agent Development Kit.*
