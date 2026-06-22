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
    web=True,
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


@app.get("/bondy")
async def bondy_ui():
    return FileResponse("web/index.html")


@app.post("/api/audit")
async def run_audit(req: AuditRequest):
    try:
        validate_input_before_audit(req.source, req.raw_html)
    except ValueError as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=403)

    try:
        runner = InMemoryRunner(app=adk_app)
        session = await runner.session_service.create_session(
            app_name="app", user_id="web_user"
        )

        prompt = f"Ejecuta una auditoría de accesibilidad para la ruta/source: {req.source}\n"
        if req.raw_html:
            prompt += f"Contenido HTML:\n{req.raw_html}"

        final_output = None

        async for event in runner.run_async(
            user_id="web_user",
            session_id=session.id,
            new_message=types.Content(
                role="user", parts=[types.Part.from_text(text=prompt)]
            ),
        ):
            if event.output is not None:
                final_output = event.output

        if final_output:
            if isinstance(final_output, list):
                try:
                    result = [f.model_dump() for f in final_output]
                except AttributeError:
                    result = final_output
            else:
                try:
                    result = final_output.model_dump()
                except AttributeError:
                    result = final_output

            return {"status": "success", "data": result}
        else:
            return JSONResponse(
                {
                    "status": "error",
                    "message": "The workflow did not produce any output.",
                },
                status_code=500,
            )

    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


# Main execution
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
