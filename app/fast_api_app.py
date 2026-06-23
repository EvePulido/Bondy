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
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from google.adk.cli.fast_api import get_fast_api_app
from google.adk.runners import InMemoryRunner
from google.cloud import logging as google_cloud_logging
from google.genai import types
from pydantic import BaseModel

from app.agent import app as adk_app
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
    logger.log_struct(feedback.model_dump(), severity="INFO")
    return {"status": "success"}


# --- Bondy Web UI & API ---
if not os.path.exists("web"):
    os.makedirs("web")

app.mount("/static", StaticFiles(directory="web"), name="static")


class AuditRequest(BaseModel):
    source: str
    raw_html: str | None = None


@app.get("/")
async def root_ui():
    return FileResponse("web/index.html")


@app.post("/api/audit")
async def run_audit(req: AuditRequest):
    try:
        validate_input_before_audit(req.source, req.raw_html)
    except ValueError as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=403)

    max_retries = 3
    for attempt in range(max_retries):
        try:
            runner = InMemoryRunner(app=adk_app)
            session = await runner.session_service.create_session(
                app_name="app", user_id="web_user"
            )

            if req.raw_html:
                prompt = (
                    f"Audit the following raw HTML content for accessibility issues:\n\n"
                    f"{req.raw_html}"
                )
            else:
                prompt = (
                    f"Run a full accessibility audit on the demo site at: {req.source}\n"
                    f"Call read_local_file(file_path='{req.source}') to read the HTML, "
                    f"then audit all WCAG criteria and return a FixesReport with all the fixes."
                )

            import json as _json

            last_text = None
            async for event in runner.run_async(
                user_id="web_user",
                session_id=session.id,
                new_message=types.Content(
                    role="user", parts=[types.Part.from_text(text=prompt)]
                ),
            ):
                # Capture the last text response from the agent
                if hasattr(event, "content") and event.content:
                    for part in event.content.parts:
                        if hasattr(part, "text") and part.text:
                            last_text = part.text

            if last_text:
                # Strip markdown code fences if the model added them
                clean = last_text.strip()
                if clean.startswith("```"):
                    clean = clean.split("```", 2)[-1] if clean.count("```") >= 2 else clean
                    if clean.startswith("json"):
                        clean = clean[4:]
                    clean = clean.rstrip("`").strip()

                try:
                    result = _json.loads(clean)
                    if isinstance(result, dict) and "fixes" in result:
                        result = result["fixes"]
                    return {"status": "success", "data": result}
                except _json.JSONDecodeError:
                    pass

            return JSONResponse(
                {"status": "error", "message": "The workflow did not produce any output."},
                status_code=500,
            )

        except Exception as e:
            err_msg = str(e)
            if "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg:
                if attempt < max_retries - 1:
                    import re

                    wait_sec = 5.0
                    match = re.search(r"retry in (\d+\.?\d*)s", err_msg)
                    if match:
                        wait_sec = float(match.group(1)) + 1.0
                    elif "retryDelay" in err_msg:
                        match_delay = re.search(r"retryDelay': '(\d+)s'", err_msg)
                        if match_delay:
                            wait_sec = float(match_delay.group(1)) + 1.0

                    try:
                        logger.warning(
                            f"Rate limit hit (429). Retrying in {wait_sec} seconds... (Attempt {attempt + 1}/{max_retries})"
                        )
                    except Exception:
                        print(
                            f"Rate limit hit (429). Retrying in {wait_sec} seconds... (Attempt {attempt + 1}/{max_retries})"
                        )

                    await asyncio.sleep(wait_sec)
                    continue

            return JSONResponse(
                {"status": "error", "message": err_msg}, status_code=500
            )


# Main execution
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8080)
