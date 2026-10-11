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

FROM python:3.12-slim

RUN pip install --no-cache-dir uv==0.8.13

WORKDIR /code

COPY ./pyproject.toml ./README.md ./uv.lock* ./

COPY ./bondy ./bondy
COPY ./examples ./examples

RUN uv sync --frozen --extra server --extra agent --extra gcp

# Run from the project virtualenv: `uv run` at start-up would re-resolve and
# could need network access in a locked-down Cloud Run revision.
ENV PATH="/code/.venv/bin:${PATH}"

# Browser for axe-core / contrast / focus checks. Off by default to keep the
# image small (~400 MB less): without it Bondy runs in STATIC MODE (HTML-parsing
# checks only; the response says so in `notes`). Build with
# `--build-arg INSTALL_CHROMIUM=true` for the full deterministic scan.
ARG INSTALL_CHROMIUM=false
RUN if [ "$INSTALL_CHROMIUM" = "true" ]; then \
        playwright install --with-deps chromium; \
    fi

ARG COMMIT_SHA=""
ENV COMMIT_SHA=${COMMIT_SHA}

# Cloud deployments keep Cloud Logging (opt-in since the local/BYOK refactor)
ENV BONDY_CLOUD_LOGGING=1

ARG AGENT_VERSION=0.0.0
ENV AGENT_VERSION=${AGENT_VERSION}

EXPOSE 8080

CMD ["uvicorn", "bondy.fast_api_app:app", "--host", "0.0.0.0", "--port", "8080"]