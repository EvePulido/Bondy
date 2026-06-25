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
from pathlib import Path

# Load external WCAG guidelines and fix patterns
patrones_path = (
    Path(__file__).parent.parent
    / ".agents"
    / "skills"
    / "suggestion-fix-generator"
    / "references"
    / "fix_patterns.md"
)
with open(patrones_path, encoding="utf-8") as f:
    WCAG_GUIDELINES = f.read()


# Eagerly loaded Python scripts as tools -----
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


def verify_image_alt_text(url: str, current_alt: str) -> str:
    """
    CRITICAL TOOL: Downloads an image from a URL and uses Gemini Vision to verify if the
    current_alt text accurately describes the image. MUST be used for WCAG 1.1.1.

    Args:
        url: The URL of the image to analyze (e.g., https://...).
        current_alt: The existing alt text found in the HTML.

    Returns:
        A description from the vision model of what the image actually contains.
    """
    import urllib.request
    from google.genai import Client, types

    try:
        if not url.startswith("http"):
            return "Error: Local or invalid URLs cannot be fetched. Assume the alt text needs review."

        req = urllib.request.Request(url, headers={"User-Agent": "Bondy/1.0"})
        with urllib.request.urlopen(req, timeout=10) as response:
            image_data = response.read()
            mime_type = response.headers.get_content_type()
            if not mime_type or not mime_type.startswith("image/"):
                mime_type = "image/jpeg"

        client = Client()
        image_part = types.Part.from_bytes(data=image_data, mime_type=mime_type)

        prompt = f"Look at this image. The current alt text is '{current_alt}'. What does the image actually show? Provide a highly descriptive and concise summary of the visual content so an auditor can write a good alt text."

        res = client.models.generate_content(
            model="gemini-2.5-flash", contents=[image_part, prompt]
        )
        return f"Vision Analysis Result: {res.text}"
    except Exception as e:
        return f"Error analyzing image: {str(e)}"


# ----- Main Accessibility Agent -----
root_agent = LlmAgent(
    name="BondyAccessibilityAgent",
    model=Gemini(model="gemini-flash-latest"),
    instruction="""You are Bondy, an expert web accessibility auditor and refactorer.

When a user sends you a source path (e.g. 'demo_sites/site_1_bad_alt'), you MUST:

STEP 1 — Call read_local_file(file_path=<source>) to get the HTML content.

STEP 2 — Audit these WCAG criteria in the HTML:
  - WCAG 1.1.1: <img> tags — are alt attributes meaningful? decorative images should have alt="".
    CRITICAL: For every <img> tag, you MUST use the `verify_image_alt_text` tool to visually verify the image content. NEVER guess the visual content just from the text. 
    Also, NEVER start an alt text with redundant phrases like "Image of", "Picture of", "Graphic of", or their Spanish equivalents like "Imagen de" or "Gráfica de". This applies to any language.
    IMPORTANT THRESHOLD: If the current alt text is already accurate and descriptive based on the visual verification, DO NOT report it as a failure just to make stylistic improvements (e.g., making it slightly more concise). Only report an issue if the alt text is missing, completely inaccurate, or contains the forbidden redundant phrases.
  - WCAG 1.3.1 / 4.1.2: <input>, <select>, <textarea> — do they have a <label>?
  - WCAG 1.4.3: text color vs background contrast (4.5:1 normal, 3:1 large text)
  - WCAG 2.4.4 / 4.1.2: <a> and <button> — do they have visible text or aria-label?
  - WCAG 2.1.2 / 2.4.3: Keyboard focus trap and logical focus order.
    CRITICAL: You MUST use the `focus_trap_detector` and `focus_order_validator` tools to physically test the keyboard behavior of the page. Do NOT try to guess focus issues just by reading the raw HTML text. Provide complete patches for both HTML and JS if issues are found.
  - WCAG 3.1.1: does <html> have a valid lang attribute?

STEP 3 — Respond with ONLY a valid JSON array (no markdown, no extra text) like:
[
  {
    "finding_id": "img-001",
    "wcag": "1.1.1",
    "severity": "critical",
    "title": "Missing descriptive alt text",
    "before": "<img src=\"x.jpg\" alt=\"\">",
    "after": "<img src=\"x.jpg\" alt=\"Sales chart Q3\">",
    "explanation": "Image alt text was empty. Added a descriptive alt."
  }
]

CRITICAL REQUIREMENT FOR EXHAUSTIVENESS AND ACCURACY: 
1. You MUST report ALL accessibility issues you find in the HTML document in a single pass. Ensure every finding is categorized with an appropriate "severity" ("critical" or "warning").
2. The "before" string MUST be an exact, character-for-character copy of the original HTML lines, including ALL original whitespace, indentation, and newlines. If you alter even one space, the automated string replacement will FAIL.
3. Keep the "before" block as short as necessary (maximum 15-20 lines). If a fix requires moving elements from the top of the file to the bottom, DO NOT create one giant block spanning the entire file. Instead, create two separate JSON finding objects: one to delete the element from the top, and one to insert it at the bottom.
4. MODAL DIALOGS SINGLE-PASS RULE: If a page has a modal dialog, you must audit and fix all of its accessibility issues in a single run. Do NOT suggest a partial fix on the first pass and wait for a second pass to suggest the rest. Your output JSON array must simultaneously contain separate objects to:
   - Position the modal dialog and backdrop at the end of the <body> to ensure logical focus order.
   - Set role="dialog" (or role="alertdialog") and aria-modal="true" on the modal container.
   - Ensure the modal contains a keyboard-accessible, descriptive close button (with an aria-label if it uses an icon).
   - Trap focus inside the modal dynamically when it is open using a robust focusable elements selector (covering links, buttons, inputs, select, textarea, contenteditable, and tabindex) and looping between first and last elements.
   - Listen to the "Escape" key to close the modal.
   - Handle background inertness dynamically by setting aria-hidden="true" on the <main> container (or appropriate layout wrappers) when the modal opens, and removing it when it closes.
   - Restore focus to the triggering element when the modal is closed.
   Apply these patterns generically without hardcoding IDs that are not present in the HTML structure, so they are robust and reusable for any page.

---
EXTERNAL GUIDELINES AND PATTERNS:
"""
    + WCAG_GUIDELINES
    + """
---

If no issues found, respond with: []
Do NOT wrap the JSON in markdown code blocks. Return raw JSON only.
""",
    tools=[all_tools, read_local_file, verify_image_alt_text],
)

app = App(root_agent=root_agent, name="app")
