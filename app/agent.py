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
def read_local_file(file_path: str) -> str:
    """Reads the content of an HTML file or directory to scan for accessibility issues.

    Args:
        file_path: The file path or folder name (e.g. 'demo_sites/site_1_bad_alt').
    """
    from app.app_utils.security import get_safe_demo_path

    # Resolve path safely using security module
    safe_path = get_safe_demo_path(file_path)

    with open(safe_path, "r", encoding="utf-8") as f:
        return f.read()


# ----- Specialized Toolsets -----
image_skills = [
    s
    for s in all_skills
    if s.name in ("alt-text-quality-analyzer", "image-decorator-classifier")
]
form_skills = [s for s in all_skills if s.name == "form-labels-validator"]
keyboard_skills = [
    s for s in all_skills if s.name in ("focus-order-validator", "focus-trap-detector")
]
doc_skills = [
    s
    for s in all_skills
    if s.name
    in (
        "document-language-validator",
        "text-contrast-calculator",
        "interactive-elements-validator",
    )
]

image_tools = SkillToolset(skills=image_skills)
form_tools = SkillToolset(skills=form_skills)
keyboard_tools = SkillToolset(skills=keyboard_skills)
doc_tools = SkillToolset(skills=doc_skills)

refactorizador_tools = SkillToolset(
    skills=[s for s in all_skills if s.name == "suggestion-fix-generator"]
)

# ----- Specialized Subagents -----
image_auditor = LlmAgent(
    name="ImageAuditor",
    model=Gemini(model="gemini-3.1-flash-lite"),
    instruction="""You are an expert web accessibility auditor specialized in non-text content (WCAG 1.1.1).
Use your tools to check if image elements have valid alt attributes or if they are decorative.
Output must be strictly a list of Finding objects.""",
    output_key="findings",
    output_schema=list[Finding],
    tools=[image_tools, read_local_file],
)

form_auditor = LlmAgent(
    name="FormAuditor",
    model=Gemini(model="gemini-3.1-flash-lite"),
    instruction="""You are an expert web accessibility auditor specialized in form elements (WCAG 1.3.1 / 4.1.2).
Use your tools to check if text fields, select tags, checkboxes, and textareas have associated labels.
Output must be strictly a list of Finding objects.""",
    output_key="findings",
    output_schema=list[Finding],
    tools=[form_tools, read_local_file],
)

keyboard_auditor = LlmAgent(
    name="KeyboardAuditor",
    model=Gemini(model="gemini-3.1-flash-lite"),
    instruction="""You are an expert web accessibility auditor specialized in keyboard navigation (WCAG 2.1.2 / 2.4.3).
Use your tools to simulate tab cycles and identify focus traps or illogical tab orders.
Output must be strictly a list of Finding objects.""",
    output_key="findings",
    output_schema=list[Finding],
    tools=[keyboard_tools, read_local_file],
)

doc_auditor = LlmAgent(
    name="DocAuditor",
    model=Gemini(model="gemini-3.1-flash-lite"),
    instruction="""You are an expert web accessibility auditor specialized in page structure, contrast, and empty interactives (WCAG 1.4.3 / 3.1.1 / 2.4.4 / 4.1.2).
Use your tools to check page language, color contrast, and empty links/buttons.
Output must be strictly a list of Finding objects.""",
    output_key="findings",
    output_schema=list[Finding],
    tools=[doc_tools, read_local_file],
)

refactorizador_agent = LlmAgent(
    name="Refactorizador",
    model=Gemini(model="gemini-3.1-flash-lite"),
    instruction="""You are an expert Web Accessibility Refactorer.
Your sole responsibility is to take the merged list of error reports (Findings) and use your tools to produce the corrected code.
Do NOT modify selectors, do not invent unnecessary code, and follow the WCAG fix patterns.
Your output MUST be strictly a list of FixSuggestion objects.""",
    output_key="fixes",
    output_schema=list[FixSuggestion],
    tools=[refactorizador_tools],
)

from google.adk.workflow import Workflow, JoinNode, node

# ----- Join Node and Merging Function Node -----
join_node = JoinNode(name="JoinAudits")


from typing import Any


@node
def merge_findings(node_input: dict[str, Any]) -> list[Finding]:
    """Merges all findings from specialized agents into a single unified list."""
    merged: list[Finding] = []
    for agent_output in node_input.values():
        if isinstance(agent_output, list):
            for item in agent_output:
                if isinstance(item, Finding):
                    merged.append(item)
                elif isinstance(item, dict):
                    try:
                        merged.append(Finding.model_validate(item))
                    except Exception:
                        pass
    return merged


# ----- Orchestration Workflow -----
root_workflow = Workflow(
    name="AccessibilityWorkflow",
    edges=[
        ("START", image_auditor),
        ("START", form_auditor),
        ("START", keyboard_auditor),
        ("START", doc_auditor),
        (image_auditor, join_node),
        (form_auditor, join_node),
        (keyboard_auditor, join_node),
        (doc_auditor, join_node),
        (join_node, merge_findings),
        (merge_findings, refactorizador_agent),
    ],
    description="Workflow that orchestrates concurrent specialized accessibility audits and then the automatic generation of refactoring suggestions.",
)

root_agent = root_workflow

from google.adk.agents.context_cache_config import ContextCacheConfig

app = App(
    root_agent=root_agent,
    name="app",
    context_cache_config=ContextCacheConfig(
        min_tokens=1024,
        ttl_seconds=1800,
    )
)
