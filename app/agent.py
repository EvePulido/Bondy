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
from google.adk.tools import SkillToolset

# ----- Data Contracts -----
class Evidence(BaseModel):
    current_value: str
    expected_value: Optional[str] = None

class Finding(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    skill: str
    wcag_criterion: str
    severity: Literal['critical', 'warning', 'info']
    selector: str
    description: str
    evidence: Evidence

class FixSuggestion(BaseModel):
    finding_id: str
    before: str
    after: str
    explanation: str

# ----- Toolset -----
# Cargar skills locales desde la carpeta (ADK Autodiscovery)
auditor_tools = SkillToolset(skills_dir=".agents/skills")
refactorizador_tools = SkillToolset(
    skills_dir=".agents/skills", 
    included_skills=["suggestion-fix-generator"]
)

# ----- Agents -----
auditor_agent = LlmAgent(
    name="Auditor",
    model=Gemini(model="gemini-flash-latest"),
    instruction="""Eres un experto auditor de accesibilidad web (WCAG 2.2 AA).
Tu única responsabilidad es utilizar las herramientas a tu disposición para escanear el HTML o source proporcionado y encontrar violaciones de accesibilidad.

REGLAS ESTRICTAS:
1. Debes usar SIEMPRE las herramientas para validar, nunca adivines.
2. Tu salida debe ser ÚNICAMENTE una lista de objetos Finding.
3. NO debes sugerir correcciones aquí, solo reportar (el Refactorizador hará las correcciones).""",
    output_schema=List[Finding],
    output_key="findings",
    tools=[auditor_tools]
)

refactorizador_agent = LlmAgent(
    name="Refactorizador",
    model=Gemini(model="gemini-flash-latest"),
    instruction="""Eres un experto Refactorizador de Accesibilidad Web.
Tu única responsabilidad es tomar los reportes de error (Findings) y usar tus herramientas para producir el código corregido.
NO modifiques selectores, no inventes código que no sea necesario y sigue los patrones de fix de WCAG.
Tu salida DEBE ser estrictamente una lista de objetos FixSuggestion.""",
    output_schema=List[FixSuggestion],
    output_key="fixes",
    tools=[refactorizador_tools]
)

from google.adk.workflow import Workflow

# ----- Orchestration Workflow -----
root_workflow = Workflow(
    name="AccessibilityWorkflow",
    edges=[
        ('START', auditor_agent),
        (auditor_agent, refactorizador_agent)
    ],
    description="Workflow que orquesta la auditoría de accesibilidad y luego la generación de sugerencias de refactorización automáticas."
)

app = App(
    root_agent=root_workflow,
    name="app",
)
