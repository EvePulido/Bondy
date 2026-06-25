# Title: Bondy - The Autonomous AI Web Accessibility Auditor
## Subtitle: Eradicating 96% of WCAG failures through Playwright-driven agents and Multimodal Vision.

### 1. The Problem: A Digital World Built with Barriers
According to the WebAIM Million 2026 report, a staggering **95.9% of home pages fail to meet basic WCAG 2 accessibility standards**. Even more alarming is that this metric has worsened recently, reversing a 6-year trend of minor improvements. We hypothesize that this regression is directly tied to the rapid proliferation of AI-assisted coding tools. As developers increasingly rely on LLMs to generate frontend code rapidly, the output often consists of boilerplate HTML lacking semantic structure and proper accessibility tags.

Traditional solutions fall fundamentally short. Manual accessibility auditing is prohibitively expensive, slow, and subjective, often pricing out small businesses and non-profits. Conversely, static code analyzers (like Google Lighthouse) are blind to context. A static linter can verify if an `alt` attribute exists on an image, but it cannot determine if the image is purely decorative or if the alt text actually describes the visual content accurately. Furthermore, static linters cannot detect dynamic interaction bugs, such as keyboard focus traps in modal dialogs. 

Strikingly, **96% of all detected web accessibility errors fall into just six categories** (low contrast, missing alt text, missing labels, empty links, empty buttons, and missing document language). The internet desperately needs a solution that can intelligently target these exact failures at scale.

### 2. The Solution & The Value of Agents
Enter **Bondy**. Bondy bridges the critical gap between passive static linters and expensive human auditors, introducing a much-needed paradigm shift in web auditing. 

While traditional industry-standard tools like Google Lighthouse or axe-core excel at basic syntax checking, they fundamentally fail to understand visual semantics or dynamic application states. A static linter simply checks if an `alt` attribute exists; Bondy actually looks at the image to see if the text makes sense. A static linter parses a `<dialog>` tag; Bondy attempts to navigate it via the keyboard to ensure users with motor disabilities won't get trapped. 

**Why Agents?** Web accessibility is inherently experiential—it requires *interacting* with and *seeing* a webpage exactly as a human user (or assistive technology) would. An LLM acting merely as a text-completion engine cannot accomplish this. However, by leveraging the **Google Agent Development Kit (ADK 2.0)**, we empowered our Gemini models with a specialized `SkillToolset`. 

Agents uniquely solve this problem because they can:
1. **Navigate like a human**: Bondy uses Playwright to physically tab through the DOM, keeping track of focus states to detect invisible keyboard traps.
2. **See like a human**: Bondy passes screenshots and DOM context to Gemini Multimodal Vision, allowing the agent to evaluate if an image is merely decorative (requiring `alt=""`) or if its text description is contextually accurate.
3. **Act like an engineer**: Once a violation is confirmed, Bondy doesn't just return a warning—it acts as an autonomous refactoring agent, generating the exact HTML drop-in replacement needed to resolve the issue.

By attacking the core 96% of errors, Bondy democratizes web access for millions of people with disabilities (Agents for Good), while simultaneously saving enterprises millions of dollars in manual auditing costs and ADA compliance lawsuits (Agents for Business).

### 3. Architecture & Technical Implementation

Our system architecture was meticulously designed to balance deterministic reliability with the cognitive flexibility of generative AI, all while adhering strictly to Google Cloud's infrastructure constraints. The resulting application is a highly scalable, monolithic agentic system built on top of the **Google Agent Development Kit (ADK 2.0)**.

**3.1. The Request Lifecycle & Deterministic Security Guardrails**
The auditing process begins when a user submits a target URL or raw HTML payload via our FastAPI-driven web interface. Before any LLM inference occurs, the payload is intercepted by our custom Security Guardrail module. In the era of autonomous agents, Server-Side Request Forgery (SSRF) and prompt injection are critical vulnerabilities. Our guardrail acts as a deterministic firewall: it strictly sanitizes inputs and cross-references URLs against an `ALLOWED_SOURCES` registry. If a user attempts to force the agent to navigate to a malicious or unauthorized external domain, the request is immediately blocked (HTTP 403 Forbidden). Only sanitized local environments or statically vetted HTML are passed downstream to the agent.

**3.2. The Monolithic Orchestrator: `BondyAccessibilityAgent`**
At the core of our architecture is the `BondyAccessibilityAgent`. We intentionally moved away from hardcoded, sequential Python scripts in favor of an autonomous reasoning engine. Powered by Gemini, this orchestrator is responsible for understanding the context of the HTML, selecting the appropriate auditing tools, and synthesizing the final output. By utilizing a monolithic single-agent design, we effectively bypassed the strict rate limits (Vertex AI `429 RESOURCE_EXHAUSTED` errors) that typically plague multi-agent parallel workflows. This architectural decision ensures high availability and seamless scalability on Google Cloud Run.

**3.3. The Hybrid `SkillToolset`: Combining Determinism with AI**
An LLM alone cannot reliably audit dynamic web accessibility. Therefore, we equipped our agent with a comprehensive `SkillToolset` containing 9 specialized skills. We adopted a "Hybrid Execution Strategy" to maximize accuracy and minimize token overhead:
*   **Deterministic DOM Parsing:** For binary accessibility rules (e.g., verifying if the root `<html>` tag contains a valid BCP-47 `lang` attribute, or calculating exact hex-color contrast ratios to meet the WCAG 4.5:1 minimum threshold), the agent invokes localized Python parsers. This guarantees 100% accuracy without wasting expensive LLM reasoning cycles on simple math or regex tasks.
*   **Playwright Browser Simulation:** To audit complex keyboard interactions (WCAG 2.1.2 No Focus Trap and 2.4.3 Focus Order), the agent delegates execution to a headless Chromium instance via Playwright. A deterministic script physically injects 'Tab' keystrokes into the DOM, mapping the sequence of focused elements. If the focus loop gets trapped inside a modal dialog without an escape route, Playwright captures the exact offending HTML node and feeds it directly back into the agent's context window.
*   **Multimodal Vision Integration:** For subjective accessibility requirements, such as WCAG 1.1.1 (Non-text Content), the agent leverages Gemini's Multimodal Vision. The agent cross-references a rendered screenshot of the webpage against the raw HTML `alt` tags. It can intelligently deduce whether an image is purely decorative (and thus requires an empty `alt=""` attribute to be ignored by screen readers) or if the current description accurately reflects the visual context.

**3.4. Code Refactoring & MCP Ecosystem**
Bondy goes beyond mere detection. Once the auditing phase concludes, the agent transitions into a refactoring state. It synthesizes the raw findings from Playwright, DOM parsers, and Vision models, and autonomously generates drop-in HTML replacement code to fix the violations. 
Furthermore, to ensure Bondy integrates seamlessly into enterprise workflows, we implemented a **Model Context Protocol (MCP) Server**. This allows Bondy to securely connect to private GitHub repositories using fine-grained access tokens, effectively auditing codebases before they even reach production.

### 4. The Project Journey (The Build)
Building Bondy was an incredible journey of iteration and intense debugging, executed across three rigorous phases using the **Antigravity CLI** as our core development engine from start to finish.

**Phase 1: Accessible Web Interface & Figma MCP Integration**
We knew a tool auditing accessibility had to be a beacon of accessibility itself. We began by designing sleek, intuitive Web UI mockups in **Figma**. To accelerate development, we connected Figma directly to VS Code via an **MCP (Model Context Protocol) Server**, allowing the AI to seamlessly translate our visual mockups into production-ready code (`web/index.html` and `app.js`). We utilized Glassmorphism aesthetics while engineering three dedicated visualization themes (Light, Dark, and a strict High Contrast mode). We also engineered a two-column responsive grid loader that displays real-time execution steps to provide clear feedback for cognitive accessibility.

**Phase 2: FastAPI Backend & Security Guardrails**
We built a robust FastAPI backend and implemented strict deterministic security guardrails to sanitize inputs. We wrote a custom Python module to block Server-Side Request Forgery risks, ensuring the agent only audits authorized demo sites or statically provided HTML.

**Phase 3: Agent Optimization & Technical Hurdles**
Initially, we designed a complex multi-agent graph workflow where four separate auditor subagents (Image, Form, Keyboard, Doc) ran in parallel. This approach failed dramatically in early testing: it flooded the Google Cloud Vertex AI API (causing `429 RESOURCE_EXHAUSTED` errors) and triggered infinite loops (`LlmCallsLimitExceededError: 500`) due to nested Pydantic output schemas failing silently during serialization. We also hit `400 INVALID_ARGUMENT` errors when attempting to use Vertex Context Caching because our demo HTML files were smaller than the 4,096 token minimum requirement.

Leveraging the **Antigravity IDE and CLI**, we rapidly debugged our evaluation traces and completely pivoted our architecture. We consolidated everything into a single, highly optimized `BondyAccessibilityAgent`. We bypassed the native output schema parser by instructing the LLM to return raw JSON arrays and parsed them manually in the backend. 

**Phase 4: Final Integration & The "Eureka" Moment**
The final phase involved connecting the frontend to the optimized monolithic agent. Watching Bondy successfully launch a headless browser in the background, navigate a hidden focus trap, and dynamically output the exact HTML refactoring code to our Glassmorphism UI was our "Eureka" moment. We rigorously tested the system using a suite of purposely broken demo sites (`demo_sites/`). Ultimately, this pivot not only solved our rate limits and serialization errors but dramatically improved audit speed. 

Bondy is now fully containerized and deployable to Google Cloud Run via a single `agents-cli deploy` command, making this powerful accessibility engine instantly available to the world.
