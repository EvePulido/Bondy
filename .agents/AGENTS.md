# Local Project Context & Secure Coding Standards — Bondy

This file defines the project context and persistent security standards that all development agents in this workspace must strictly follow.

---

## 1. Mandatory Input Validation (Security First)
* **Rule:** Before invoking any web navigation or automation tool via Playwright (e.g., in focus validators or focus trap detectors), you must validate the input parameters against the deterministic security module in `app/app_utils/security.py` using the `validate_input_before_audit` function.
* **Allowed Sources:** Only allow local demo directories statically registered in `ALLOWED_SOURCES` (`demo_sites/...`) or raw HTML content pasted directly. Arbitrary external HTTP requests to untrusted internet URLs are strictly prohibited.

## 2. Code Quality and Pre-Commit Remediation Loop
* **Rule:** If a `git commit` or test execution fails due to a `pre-commit` hook check (e.g., Ruff linting, Ruff formatting, or type checking errors), you must:
  1. Halt execution immediately and treat the violation as a high-priority refactoring task.
  2. Apply the necessary style, syntax, or logic fixes to the affected files.
  3. Run `uv run pre-commit run --all-files` manually to verify that 100% of the checks pass cleanly before attempting to commit again.

## 3. System Architecture (ADK 2.0)
* **Rule:** The main agent orchestration logic of the project must be implemented using a single `LlmAgent` (the `BondyAccessibilityAgent`) equipped with a `SkillToolset` in `app/agent.py`. Avoid parallel graph workflows to prevent Google Cloud Vertex AI rate limit (429) exhaustion.

## 4. Code Preservation
* **Rule:** Only modify modules or files that are directly related to the user's request. Preserve all surrounding code, comments, AI model configurations, and standard project formatting intact.
