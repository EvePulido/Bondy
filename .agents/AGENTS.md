# Local Project Context & Secure Coding Standards — Bondy

This file defines the project context and persistent security standards that all development agents in this workspace must strictly follow.

---

## 1. Mandatory Input Validation (Security First)
* **Rule:** Before invoking any web navigation or automation tool via Playwright (e.g., in focus validators or focus trap detectors), you must validate the input parameters against the deterministic security module in `bondy/app_utils/security.py` using the `validate_input_before_audit` function.
* **Allowed Sources:** Only allow local demo directories statically registered in `ALLOWED_SOURCES` (`demo_sites/...`) or raw HTML content pasted directly. Arbitrary external HTTP requests to untrusted internet URLs are strictly prohibited.

## 2. Code Quality and Pre-Commit Remediation Loop
* **Rule:** If a `git commit` or test execution fails due to a `pre-commit` hook check (e.g., Ruff linting, Ruff formatting, or type checking errors), you must:
  1. Halt execution immediately and treat the violation as a high-priority refactoring task.
  2. Apply the necessary style, syntax, or logic fixes to the affected files.
  3. Run `uv run pre-commit run --all-files` manually to verify that 100% of the checks pass cleanly before attempting to commit again.

## 3. System Architecture (ADK 2.0)
* **Rule:** Per decision D1 of `docs/improvement-plan.md`, the **default pipeline is code-driven** (`bondy/core/`): code discovers pages, runs the deterministic scanners, decides everything it can (heuristics, templates, the final keep/fix/manual-review decision) and only calls the model, through the `LLMProvider` interface (`bondy/core/providers/`), for what needs reasoning (does the alt describe the image, decorative vs. informative vs. functional, drafting the alt). `bondy/core/` must not import FastAPI or ADK. The ADK agent in `bondy/agent.py` (a single `LlmAgent`, `BondyAccessibilityAgent`, with a `SkillToolset`) is an **optional mode** installed with the `agent` extra and is still what the web UI runs until the UI moves to the pipeline. Avoid parallel graph workflows to prevent rate limit (429) exhaustion. Tests never call a real provider: use `FakeProvider`.

## 4. Code Preservation
* **Rule:** Only modify modules or files that are directly related to the user's request. Preserve all surrounding code, comments, AI model configurations, and standard project formatting intact.
