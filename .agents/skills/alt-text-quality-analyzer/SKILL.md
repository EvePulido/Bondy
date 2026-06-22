---
name: alt-text-quality-analyzer
description: |
  Analyzes a web page image against its current alt attribute text using multimodal vision models. Evaluates if the alt text accurately describes the image context, checking if it is empty, generic, or mismatched with the visual content. Use this to verify descriptive quality of image alt tags (WCAG 1.1.1).
---

## Instructions

1. Receives the URL or bytes of the image (`image_url_or_bytes`), the current alt text (`current_alt`), and the surrounding DOM context (`dom_context`).
2. Uses computer vision to analyze the image content.
3. Compares the image content with the `current_alt` attribute.
4. Evaluates the description quality based on WCAG 1.1.1 guidelines.
5. Returns a verdict (`good`, `poor`, `missing`, `redundant`), a detailed explanation, and a suggested fix: `{ "verdict": string, "explanation": string, "suggested_fix": string|null }`.
6. AI Model: gemini-3.5-flash.

## Resources
- **references/wcag_1_1_1.md**: Contains reference guidelines for WCAG 1.1.1.
- **Note**: There are no scripts in this skill. The LLM must perform the analysis itself directly without attempting to run any script.

## When NOT to activate this skill

- If the element under evaluation is not an `<img>` tag or does not represent an image role.
- If the image has already been classified as purely decorative.
