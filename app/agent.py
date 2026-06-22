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
from typing import List, Optional, Literal
from pydantic import BaseModel, Field

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


import os
from google.adk.skills import load_skill_from_dir

skills_dir = ".agents/skills"
all_skills = [
    load_skill_from_dir(os.path.join(skills_dir, name))
    for name in os.listdir(skills_dir)
    if os.path.isdir(os.path.join(skills_dir, name))
]

# ----- Toolset -----
auditor_tools = SkillToolset(skills=all_skills)
refactorizador_tools = SkillToolset(
    skills=[s for s in all_skills if s.name == "suggestion-fix-generator"]
)

# ----- Agents -----
auditor_agent = LlmAgent(
    name="Auditor",
    model=Gemini(model="gemini-flash-latest"),
    instruction="""You are an expert web accessibility auditor (WCAG 2.2 AA).
Your sole responsibility is to use the tools at your disposal to scan the provided HTML or source and find accessibility violations.

STRICT RULES:
1. You must ALWAYS use tools to validate, never guess.
2. Your output must be ONLY a list of Finding objects.
3. Do NOT suggest fixes here, only report (the Refactorer will handle the fixes).""",
    output_schema=List[Finding],
    output_key="findings",
    tools=[auditor_tools],
)

refactorizador_agent = LlmAgent(
    name="Refactorizador",
    model=Gemini(model="gemini-flash-latest"),
    instruction="""You are an expert Web Accessibility Refactorer.
Your sole responsibility is to take the error reports (Findings) and use your tools to produce the corrected code.
Do NOT modify selectors, do not invent unnecessary code, and follow the WCAG fix patterns.
Your output MUST be strictly a list of FixSuggestion objects.""",
    output_schema=List[FixSuggestion],
    output_key="fixes",
    tools=[refactorizador_tools],
)

from google.adk.workflow import Workflow

# ----- Orchestration Workflow -----
root_workflow = Workflow(
    name="AccessibilityWorkflow",
    edges=[("START", auditor_agent), (auditor_agent, refactorizador_agent)],
    description="Workflow that orchestrates the accessibility audit and then the automatic generation of refactoring suggestions.",
)

root_agent = root_workflow

app = App(
    root_agent=root_agent,
    name="app",
)
