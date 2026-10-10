# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ruff: noqa: E402
import asyncio
import os

from dotenv import load_dotenv

AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(dotenv_path=os.path.join(AGENT_DIR, ".env"), override=True)

import google.auth
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from google.adk.apps import App
from google.adk.cli.fast_api import get_fast_api_app
from google.adk.models import Gemini
from google.adk.runners import InMemoryRunner
from google.cloud import logging as google_cloud_logging
from google.genai import types
from pydantic import BaseModel

from app.agent import app as adk_app
from app.app_utils.audit_schema import parse_audit_response
from app.app_utils.security import validate_input_before_audit
from app.app_utils.telemetry import setup_telemetry
from app.app_utils.typing import Feedback

setup_telemetry()
try:
    _, project_id = google.auth.default()
    logging_client = google_cloud_logging.Client()
    logger = logging_client.logger(__name__)
except Exception:
    import logging

    logger = logging.getLogger(__name__)
    logging.basicConfig(level=logging.INFO)
allow_origins = (
    os.getenv("ALLOW_ORIGINS", "").split(",") if os.getenv("ALLOW_ORIGINS") else None
)

# Artifact bucket for ADK (created by Terraform, passed via env var)
logs_bucket_name = os.environ.get("LOGS_BUCKET_NAME")

# In-memory session configuration - no persistent storage
session_service_uri = None

artifact_service_uri = f"gs://{logs_bucket_name}" if logs_bucket_name else None

app: FastAPI = get_fast_api_app(
    agents_dir=AGENT_DIR,
    web=False,
    artifact_service_uri=artifact_service_uri,
    allow_origins=allow_origins,
    session_service_uri=session_service_uri,
    otel_to_cloud=False,
)
app.title = "bondy"
app.description = "API for interacting with the Agent bondy"


@app.post("/feedback")
def collect_feedback(feedback: Feedback) -> dict[str, str]:
    """Collect and log feedback.

    Args:
        feedback: The feedback data to log

    Returns:
        Success message
    """
    if hasattr(logger, "log_struct"):
        try:
            import typing

            typing.cast(typing.Any, logger).log_struct(
                feedback.model_dump(), severity="INFO"
            )
        except Exception as e:
            import logging

            logging.getLogger(__name__).info(
                f"Feedback received (GCP logging failed: {e}): {feedback.model_dump()}"
            )
    else:
        logger.info(f"Feedback received: {feedback.model_dump()}")
    return {"status": "success"}


# --- Bondy Web UI & API ---
if not os.path.exists("web"):
    os.makedirs("web")

app.mount("/static", StaticFiles(directory="web"), name="static")


class AuditRequest(BaseModel):
    source: str
    raw_html: str | None = None
    enabled_checks: list[str] | None = None


class ApplyFixRequest(BaseModel):
    file_path: str
    before: str
    after: str


_AXE_SCRIPT = (
    os.path.join(AGENT_DIR, ".agents", "skills", "axe-accessibility-scanner")
    + os.sep
    + "scripts"
    + os.sep
    + "axe_scan.py"
)


def _compute_axe_stats(raw_html: str | None, source: str) -> dict | None:
    """Runs the deterministic axe baseline and returns real rule counts.

    Returns None if the scan cannot run (e.g. Chromium missing), so the UI can
    fall back gracefully instead of failing the whole audit.
    """
    import importlib.util

    try:
        if raw_html is None:
            from app.app_utils.security import get_safe_demo_path

            with open(get_safe_demo_path(source), encoding="utf-8") as f:
                raw_html = f.read()

        spec = importlib.util.spec_from_file_location("bondy_axe_scan", _AXE_SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        report = module.scan(raw_html)
        summary = report["summary"]
        return {
            "passes": summary["passes"],
            "violations": summary["violations"],
            "needs_review": summary["needs_review"],
        }
    except Exception as e:
        logger.warning(f"axe baseline unavailable: {e}")
        return None


# Backup model used when the primary one is overloaded (503). Empty string disables it.
FALLBACK_MODEL = os.getenv("BONDY_FALLBACK_MODEL", "gemini-3.5-flash-lite")


def _build_fallback_app() -> App:
    """Same agent and tools, running on the backup model."""
    agent = adk_app.root_agent.model_copy(
        update={"model": Gemini(model=FALLBACK_MODEL)}
    )
    return App(root_agent=agent, name="app")


@app.get("/")
async def root_ui():
    return FileResponse("web/index.html")


@app.post("/api/audit")
async def run_audit(req: AuditRequest):
    try:
        validate_input_before_audit(req.source, req.raw_html)
    except ValueError as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=403)

    # Real, deterministic rule counts (computed once, outside the LLM retry loop)
    axe_stats = await asyncio.to_thread(_compute_axe_stats, req.raw_html, req.source)

    max_retries = 4
    use_fallback = False
    for attempt in range(max_retries):
        try:
            runner = InMemoryRunner(
                app=_build_fallback_app() if use_fallback else adk_app
            )
            session = await runner.session_service.create_session(
                app_name="app", user_id="web_user"
            )

            if req.enabled_checks:
                checks_str = ", ".join(req.enabled_checks)
                extra_instruction = f"Only audit the following criteria: {checks_str}. Ignore all other criteria."
            else:
                extra_instruction = "Audit all criteria (WCAG 1.1.1, WCAG 1.3.1, WCAG 1.4.3, WCAG 2.4.4, WCAG 3.1.1, WCAG 2.1.2, WCAG 2.4.3)."

            if req.raw_html:
                prompt = (
                    f"Audit the following raw HTML content for accessibility issues:\n\n"
                    f"{req.raw_html}\n\n"
                    f"{extra_instruction}"
                )
            else:
                prompt = (
                    f"Run a full accessibility audit on the demo site at: {req.source}\n"
                    f"Call read_local_file(file_path='{req.source}') to read the HTML, "
                    f"then audit the following criteria: {extra_instruction} and return the JSON array of fixes."
                )

            last_text = None
            async for event in runner.run_async(
                user_id="web_user",
                session_id=session.id,
                new_message=types.Content(
                    role="user", parts=[types.Part.from_text(text=prompt)]
                ),
            ):
                # Capture the last text response from the agent
                if hasattr(event, "content") and event.content and event.content.parts:
                    for part in event.content.parts:
                        if hasattr(part, "text") and part.text:
                            last_text = part.text

            if last_text:
                try:
                    fixes = parse_audit_response(last_text)
                except ValueError as parse_err:
                    return JSONResponse(
                        {"status": "error", "message": str(parse_err)},
                        status_code=500,
                    )

                source_type = "raw_html" if req.raw_html else "local_file"
                return {
                    "status": "success",
                    "data": [fix.model_dump() for fix in fixes],
                    "stats": axe_stats,
                    "source_type": source_type,
                    "file_path": req.source if not req.raw_html else None,
                }

            return JSONResponse(
                {
                    "status": "error",
                    "message": "The AI workflow timed out or did not produce any output. Recovery: Please click 'Run' to try again, or reduce the number of checks if the page is too large.",
                },
                status_code=500,
            )

        except Exception as e:
            err_msg = str(e)
            is_rate_limit = "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg
            is_overloaded = "503" in err_msg or "UNAVAILABLE" in err_msg
            if is_rate_limit or is_overloaded:
                if attempt < max_retries - 1:
                    import re

                    # Exponential backoff for transient overload: 5s, 10s, 20s
                    wait_sec = 5.0 * (2**attempt)
                    match = re.search(r"retry in (\d+\.?\d*)s", err_msg)
                    if match:
                        wait_sec = float(match.group(1)) + 1.0
                    elif "retryDelay" in err_msg:
                        match_delay = re.search(r"retryDelay': '(\d+)s'", err_msg)
                        if match_delay:
                            wait_sec = float(match_delay.group(1)) + 1.0

                    reason = "Rate limit (429)" if is_rate_limit else "Model overloaded (503)"
                    if is_overloaded and FALLBACK_MODEL and not use_fallback:
                        # Same model keeps failing: switch to the backup model
                        use_fallback = True
                        wait_sec = min(wait_sec, 3.0)
                        reason += f" - switching to fallback model '{FALLBACK_MODEL}'"
                    logger.warning(
                        f"{reason}. Retrying in {wait_sec} seconds... (Attempt {attempt + 1}/{max_retries})"
                    )

                    await asyncio.sleep(wait_sec)
                    continue

            return JSONResponse(
                {"status": "error", "message": err_msg}, status_code=500
            )


from collections import defaultdict

file_locks = defaultdict(asyncio.Lock)


@app.post("/api/apply-fix")
async def apply_fix(req: ApplyFixRequest, request: Request):
    from app.app_utils.security import get_safe_demo_path

    # This endpoint writes to disk: require an API key if configured,
    # otherwise only accept requests coming from the local machine.
    api_key = os.getenv("BONDY_API_KEY")
    if api_key:
        authorized = request.headers.get("x-api-key") == api_key
    else:
        authorized = request.client is not None and request.client.host in (
            "127.0.0.1",
            "::1",
            "localhost",
        )
    if not authorized:
        return JSONResponse(
            {"status": "error", "message": "Unauthorized."}, status_code=403
        )

    try:
        safe_path = get_safe_demo_path(req.file_path)

        async with file_locks[safe_path]:
            with open(safe_path, encoding="utf-8") as f:
                content = f.read()

            if req.before not in content:
                return JSONResponse(
                    {
                        "status": "error",
                        "message": "Original code not found in file. Ensure the file hasn't been modified externally.",
                    },
                    status_code=400,
                )

            content = content.replace(req.before, req.after, 1)

            with open(safe_path, "w", encoding="utf-8") as f:
                f.write(content)

        return {"status": "success", "message": "Fix applied successfully"}
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


# Main execution
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8080)
