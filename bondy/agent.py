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

from google.adk.agents import LlmAgent
from google.adk.apps import App
from google.adk.models import Gemini
from google.adk.tools.skill_toolset import SkillToolset
from google.genai import types

# Load external WCAG guidelines and fix patterns
from bondy.resources import FIX_PATTERNS_PATH, SKILLS_DIR

with open(FIX_PATTERNS_PATH, encoding="utf-8") as f:
    WCAG_GUIDELINES = f.read()


import os
from google.adk.skills import load_skill_from_dir

skills_dir = str(SKILLS_DIR)
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
    from bondy.app_utils.security import get_safe_demo_path

    safe_path = get_safe_demo_path(file_path)

    with open(safe_path, "r", encoding="utf-8") as f:
        return f.read()


from bondy.app_utils.vision_tools import (
    analyze_rendered_page,
    classify_image_decorative,
    verify_image_alt_text,
)

# All skills combined into a single toolset
all_tools = SkillToolset(skills=all_skills)


# ----- Main Accessibility Agent -----
root_agent = LlmAgent(
    name="BondyAccessibilityAgent",
    model=Gemini(
        model="gemini-flash-latest",
        # Retry only the failed request (429/503) instead of restarting the audit
        retry_options=types.HttpRetryOptions(
            attempts=5, initial_delay=5, max_delay=60
        ),
    ),
    instruction="""You are Bondy, an expert web accessibility auditor and refactorer.

When a user sends you a source path (e.g. 'demo_sites/site_1_bad_alt'), you MUST:

STEP 1 — Call read_local_file(file_path=<source>) to get the HTML content.

STEP 1.5 — DETERMINISTIC BASELINE (SKIP this step if the request says to skip it): Call the `axe-accessibility-scanner` skill with the raw HTML content.
  Treat its `violations` and `unnamed_interactive_elements` as confirmed, objective findings: report every one that
  belongs to the requested criteria (map `wcag` to the criteria below). Do NOT discard them. For each, locate the
  element in the ORIGINAL source to build the exact "before" string (axe's `html` is browser-serialized).
  Then use the checks below to find what axe cannot judge (meaningfulness of alt text, decorative images,
  keyboard traps, focus order). Do not report the same element twice.

STEP 1.7 — VISUAL CHECK (SKIP this step if the request says to skip it): Call `analyze_rendered_page` once (pass source=<the demo path> when you were given a
  path, or html=<the raw HTML> otherwise) to see the page as a user does. Use what it reports (text inside images,
  unlabeled icons, unreadable areas) as extra evidence; only report an issue if you can tie it to a concrete
  element in the HTML source so the "before" string can be copied exactly.

STEP 2 — Audit these WCAG criteria in the HTML:
  - WCAG 1.1.1: <img> tags — are alt attributes meaningful? decorative images should have alt="".
    CRITICAL: For every <img> tag, you MUST use the `verify_image_alt_text` tool to visually verify the image content. NEVER guess the visual content just from the text. 
    Pass `url` (the src), `current_alt` ('' if missing) and `context_html` (surrounding lines). The tool returns JSON:
    follow its `recommendation`: "keep" -> do NOT report; "fix" -> report and use its `suggested_alt` (copy it
    verbatim, never add details it did not state); "needs_manual_review" -> report as severity "warning" and
    say the description could not be verified with confidence. Never invent visual details (breed, clothing,
    brand, people) that are not in `visible_content`.
    Also, NEVER start an alt text with redundant phrases like "Image of", "Picture of", "Graphic of", or their Spanish equivalents like "Imagen de" or "Gráfica de". This applies to any language.
    DECORATIVE CHECK: For every <img>, ALSO call `classify_image_decorative` (pass the exact <img> tag and a few
    surrounding lines of HTML). If it returns "decorative", the correct fix is alt="" (do not invent a description).
    If it returns "functional" (image is the only content of a link/button), the alt must describe the action or
    destination, not the picture.
    IMPORTANT THRESHOLD: If the current alt text is already accurate and descriptive based on the visual verification, DO NOT report it as a failure just to make stylistic improvements (e.g., making it slightly more concise). Only report an issue if the alt text is missing, completely inaccurate, or contains the forbidden redundant phrases.
  - WCAG 1.3.1 / 4.1.2: <input>, <select>, <textarea> — do they have a <label>?
  - WCAG 1.4.3: text color vs background contrast (4.5:1 normal, 3:1 large text).
    CRITICAL: For checking contrast ratios, you MUST call the `text-contrast-calculator` tool with the raw HTML string content. It will launch Playwright, compute all styles automatically, and return a JSON list of any elements failing the 4.5:1 (normal) or 3:1 (large) contrast ratio limits. You MUST report any issues it returns.
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
    tools=[
        all_tools,
        read_local_file,
        verify_image_alt_text,
        classify_image_decorative,
        analyze_rendered_page,
    ],
)

app = App(root_agent=root_agent, name="bondy")
