---
name: image-decorator-classifier
description: |
  Determines if a web page image is purely decorative (i.e. serves only aesthetic purposes and provides no unique information) and should therefore be marked with alt="" instead of carrying a redundant description. Use this tool when analyzing image quality and deciding if a descriptive alt text is necessary based on the visual content and surrounding text.
---

## Instructions

1. Receives the URL or bytes of the image (`image_url_or_bytes`) and its surrounding DOM context (`dom_context` like adjacent text and headings).
2. Analyces the visual content of the image against the adjacent textual information.
3. Evaluates if the image provides any unique additional information, functionality, or vital context.
4. Returns whether the image is purely decorative (`is_decorative`) and a detailed justification: `{ "is_decorative": bool, "justification": string }`.
5. AI Model: gemini-3.5-flash.

## Resources
- **references/decorativa_vs_informativa.md**: Contains guidance on classifying decorative vs informative images.
- **Note**: There are no scripts in this skill. The LLM must perform the classification itself directly without attempting to run any script.

## When NOT to activate this skill

- If the element is an icon or image used as the sole content within an interactive link or button (which makes it functional, not decorative).
