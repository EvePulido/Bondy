# ruff: noqa
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

import uuid
import json
from typing import List, Optional, Literal
from pydantic import BaseModel, Field, field_validator

from google.adk.agents import LlmAgent
from google.adk.apps import App
from google.adk.models import Gemini
from google.adk.tools.skill_toolset import SkillToolset


# ----- Data Contracts -----
class Evidence(BaseModel):
    current_value: str
    expected_value: Optional[str] = None


class Finding(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    skill: str
    wcag_criterion: str
    severity: Literal["critical", "warning", "info"]
    selector: str
    description: str
    evidence: Evidence


class FixSuggestion(BaseModel):
    finding_id: str
    before: str
    after: str
    explanation: str


class FindingsReport(BaseModel):
    findings: list[Finding]


class FixesReport(BaseModel):
    fixes: list[FixSuggestion]

    @field_validator("fixes", mode="before")
    @classmethod
    def parse_fix_strings(cls, v):
        """Tolerates fixes sent as JSON strings by the LLM instead of dicts."""
        if isinstance(v, list):
            result = []
            for item in v:
                if isinstance(item, str):
                    try:
                        result.append(json.loads(item))
                    except Exception:
                        pass
                else:
                    result.append(item)
            return result
        return v


import os
from google.adk.skills import load_skill_from_dir

skills_dir = ".agents/skills"
all_skills = [
    load_skill_from_dir(os.path.join(skills_dir, name))
    for name in os.listdir(skills_dir)
    if os.path.isdir(os.path.join(skills_dir, name))
]


# ----- Toolset -----
def read_local_file(file_path: str) -> str:
    """Reads the content of an HTML file to scan for accessibility issues.

    Args:
        file_path: The folder name of the demo site (e.g. 'demo_sites/site_1_bad_alt').
                   The function automatically resolves the full path to index.html.
    """
    from app.app_utils.security import get_safe_demo_path

    safe_path = get_safe_demo_path(file_path)

    with open(safe_path, "r", encoding="utf-8") as f:
        return f.read()


# All skills combined into a single toolset
all_tools = SkillToolset(skills=all_skills)

# ----- Main Accessibility Agent -----
root_agent = LlmAgent(
    name="BondyAccessibilityAgent",
    model=Gemini(model="gemini-flash-latest"),
    instruction="""You are Bondy, an expert web accessibility auditor and refactorer.

When a user sends you a source path (e.g. 'demo_sites/site_1_bad_alt'), you MUST:

STEP 1 — Call read_local_file(file_path=<source>) to get the HTML content.

STEP 2 — Audit these WCAG criteria in the HTML:
  - WCAG 1.1.1: <img> tags — are alt attributes meaningful? decorative images should have alt=""
  - WCAG 1.3.1 / 4.1.2: <input>, <select>, <textarea> — do they have a <label>?
  - WCAG 1.4.3: text color vs background contrast (4.5:1 normal, 3:1 large text)
  - WCAG 2.4.4 / 4.1.2: <a> and <button> — do they have visible text or aria-label?
  - WCAG 2.1.2 / 2.4.3: Keyboard focus trap and logical focus order — check for illogical tabindex or modal traps.
  - WCAG 3.1.1: does <html> have a valid lang attribute?

STEP 3 — Respond with ONLY a valid JSON array (no markdown, no extra text) like:
[
  {
    "finding_id": "img-001",
    "before": "<img src=\"x.jpg\" alt=\"\">",
    "after": "<img src=\"x.jpg\" alt=\"Sales chart Q3\">",
    "explanation": "Image alt text was empty. Added a descriptive alt."
  }
]

If no issues found, respond with: []
Do NOT wrap the JSON in markdown code blocks. Return raw JSON only.
""",
    tools=[all_tools, read_local_file],
)

app = App(root_agent=root_agent, name="app")
