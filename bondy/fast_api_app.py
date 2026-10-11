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
from pathlib import Path

from dotenv import load_dotenv

AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# override=False: variables already set in the environment win over .env
load_dotenv(dotenv_path=os.path.join(AGENT_DIR, ".env"), override=False)

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from google.adk.cli.fast_api import get_fast_api_app
from pydantic import BaseModel

from bondy.app_utils.security import validate_input_before_audit
from bondy.app_utils.telemetry import setup_telemetry
from bondy.app_utils.typing import Feedback
from bondy.core.checks import describe_checks
from bondy.core.providers.base import LLMProvider
from bondy.core.web_audit import WebAuditError, run_web_audit
from bondy.resources import WEB_DIR

setup_telemetry()
# Cloud Logging is opt-in (BONDY_CLOUD_LOGGING=1, needs the `gcp` extra); by
# default feedback and warnings go to the standard Python logger only.
import logging

logger = logging.getLogger(__name__)
if os.getenv("BONDY_CLOUD_LOGGING") == "1":
    try:
        import google.auth
        from google.cloud import logging as google_cloud_logging

        google.auth.default()
        logger = google_cloud_logging.Client().logger(__name__)
    except Exception as e:
        logging.warning(f"Cloud Logging unavailable, using stdlib logging: {e}")
else:
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
app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


class AuditRequest(BaseModel):
    source: str
    raw_html: str | None = None
    enabled_checks: list[str] | None = None


class ApplyFixRequest(BaseModel):
    file_path: str
    before: str
    after: str


def _audit_provider() -> LLMProvider | None:
    """Provider for /api/audit. ``None`` = the real one built from the settings
    (Gemini with the environment's API key); tests override this."""
    return None


def _annotate_before_matches(fixes: list[dict], source: str) -> None:
    """Adds `before_occurrences` to each fix so the UI only offers a safe Apply.

    0 -> the snippet is not in the file (model altered it); 1 -> safe;
    >1 -> ambiguous, replacing the first match could edit the wrong place.
    """
    from bondy.app_utils.security import get_safe_demo_path

    try:
        with open(get_safe_demo_path(source), encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return
    for fix in fixes:
        before = fix.get("before") or ""
        fix["before_occurrences"] = content.count(before) if before else 0


@app.get("/")
async def root_ui():
    return FileResponse(WEB_DIR / "index.html")


@app.get("/api/checks")
async def list_checks():
    """Check categories and their WCAG mapping (single source: core/checks.py)."""
    return describe_checks()


@app.post("/api/audit")
async def run_audit(req: AuditRequest):
    try:
        validate_input_before_audit(req.source, req.raw_html)
    except ValueError as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=403)

    try:
        # run_scan is synchronous (browser + provider calls): keep the loop free.
        payload, patch_ids = await asyncio.to_thread(
            run_web_audit,
            source=req.source,
            raw_html=req.raw_html,
            enabled_checks=req.enabled_checks,
            repo_root=Path(AGENT_DIR),
            provider=_audit_provider(),
        )
    except WebAuditError as e:
        return JSONResponse(
            {"status": "error", "message": e.message}, status_code=e.status
        )
    except Exception as e:
        logger.warning(f"audit failed: {e}")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)

    if payload["source_type"] == "local_file":
        # Only real patches (image fixes) get an occurrence count, so the UI
        # never offers "Apply to File" for advice text.
        _annotate_before_matches(
            [d for d in payload["data"] if d["finding_id"] in patch_ids],
            req.source,
        )
    return payload


from collections import defaultdict

file_locks = defaultdict(asyncio.Lock)


@app.post("/api/apply-fix")
async def apply_fix(req: ApplyFixRequest, request: Request):
    from bondy.app_utils.security import get_safe_demo_path

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

            occurrences = content.count(req.before) if req.before else 0
            if occurrences > 1:
                return JSONResponse(
                    {
                        "status": "error",
                        "message": f"The original code appears {occurrences} times in the file, so the fix is ambiguous. Apply it manually using the Copy button.",
                    },
                    status_code=409,
                )
            if occurrences == 0:
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
