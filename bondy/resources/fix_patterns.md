# Fix Patterns for Bondy

When generating a corrected code snippet (`after`), apply these recommended patterns based on the detected failure:

## 1. Missing Language Attribute (`validar-idioma-documento`)
- **Fix:** Add or correct the `lang` attribute on the `<html>` tag.
- **Rule:** Use valid BCP 47 codes (e.g., `lang="es"`, `lang="en-US"`).
- **Example:** `<html lang="en">`

## 2. Missing Accessible Name (`validar-nombre-accesible-interactivo`)
- **Fix:**
  - If it is an action icon without visible text, use `aria-label="<Action>"`.
  - If the button has visually hidden but non-semantic text, consider `aria-labelledby` or text inside a `<span class="sr-only">`.
- **Rule:** Be concise. Do not write "Button to search", just "Search".

## 3. Missing Form Labels (`validar-labels-formularios`)
- **Fix:** 
  - Preferably, add an explicit `<label for="[input-id]">`.
  - Alternative: Wrap the input inside the `<label>`.
  - As a last resort for visually hidden inputs (e.g., search bars), use `aria-label`.

## 4. Insufficient Contrast (`validar-contraste-texto`)
- **Fix:** Change the CSS color code to meet the 4.5:1 ratio. 
- **Rule:** Try to maintain the original hue, only adjusting the lightness (darkening text or lightening backgrounds).

## 5. Verbose Decorative Image (`clasificar-imagen-decorativa`)
- **Fix:** Replace the text of the `alt="..."` attribute with `alt=""`. Do not remove the attribute; leave it explicitly empty.

## 6. Poor Alt Text (`validar-calidad-alt-text`)
- **Fix:** Rewrite the `alt` text to be descriptive and contextual.
- **Rule:** Do not start with "Image of..." or "Graphic of...".

## 7. Modal Focus Trap and Logical Order (WCAG 2.1.2 / 2.4.3)
For any modal dialog component, the accessibility implementation must be comprehensive, robust, and generic. Do not hardcode specific element IDs (like `btn-1` or `email`) unless they are already present on the page and it is necessary to reference them. The fixes should follow these generic patterns:

### HTML Structure Fixes:
1. **Logical DOM Position:** Ensure the modal dialog wrapper (`.modal` or equivalent) and its backdrop (`.backdrop`) are positioned at the end of the `<body>` element. This prevents illogical tab jumps when keyboard focus moves through the document.
2. **Accessible Attributes:** The modal container must have `role="dialog"` (or `role="alertdialog"` for critical alerts), `aria-modal="true"`, and a descriptive accessible name (via `aria-label` or `aria-labelledby` pointing to the modal's heading).
3. **Close Control:** The modal must contain a keyboard-accessible close button (e.g. `<button id="close-modal" aria-label="Close modal">×</button>` or similar clear label) inside the modal content.

### JavaScript Behavior Fixes:
1. **Generic Focus Trap Selector:** When query selecting focusable elements within the modal, always use a robust, standard list of interactive tags:
   `const focusableSelector = 'a[href], area[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), button:not([disabled]), iframe, object, embed, [tabindex]:not([tabindex="-1"]), [contenteditable]';`
   Then dynamically retrieve:
   `const focusableElements = modal.querySelectorAll(focusableSelector);`
2. **Dynamic Focus Trap Loop:** Implement a generic keydown listener that traps focus within `focusableElements[0]` (first) and `focusableElements[focusableElements.length - 1]` (last):
   ```javascript
   modal.addEventListener('keydown', function(e) {
       if (e.key === 'Tab') {
           const focusables = modal.querySelectorAll('a[href], area[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), button:not([disabled]), iframe, object, embed, [tabindex]:not([tabindex="-1"]), [contenteditable]');
           if (focusables.length === 0) return;
           const first = focusables[0];
           const last = focusables[focusables.length - 1];
           if (e.shiftKey) {
               if (document.activeElement === first) {
                   e.preventDefault();
                   last.focus();
               }
           } else {
               if (document.activeElement === last) {
                   e.preventDefault();
                   first.focus();
               }
           }
       }
   });
   ```
3. **Escape Key Handling:** Add an event listener (on the window/document or the modal) to close the modal when the `Escape` key is pressed:
   ```javascript
   document.addEventListener('keydown', function(e) {
       if (e.key === 'Escape' && modal.style.display !== 'none') {
           closeModal();
       }
   });
   ```
4. **Focus Restoration:** Before opening the modal, store the element that triggered it (`document.activeElement`). When the modal is closed, programmatically return focus to that trigger element:
   ```javascript
   let triggerElement = null;
   function openModal(trigger) {
       triggerElement = trigger || document.activeElement;
       // ... show modal code ...
   }
   function closeModal() {
       // ... hide modal code ...
       if (triggerElement) {
           triggerElement.focus();
       }
   }
   ```
5. **Background Infiltration (aria-hidden):** When the modal is displayed, set `aria-hidden="true"` on the main content container(s) (typically `<main>` or any siblings of the modal/backdrop). When the modal is closed, remove the `aria-hidden` attribute from those containers:
   ```javascript
   const mainContent = document.querySelector('main') || document.getElementById('main-content');
   // On open:
   if (mainContent) mainContent.setAttribute('aria-hidden', 'true');
   // On close:
   if (mainContent) mainContent.removeAttribute('aria-hidden');
   ```

### Implementation Guideline:
- **Atomicity:** Do not combine HTML structural changes and script modifications into a single massive `before`/`after` chunk. Split them into clean, separate objects within the output JSON array (e.g., one chunk for moving the HTML modal to the end of `<body>`, another for adjusting attributes, and another for correcting the `<script>` block).
- **Preservation:** Keep all other inline styles, classes, and structure of the original code intact.

**Important Note:** DO NOT rewrite code unrelated to the original failure! If the button had `class="btn primary mb-3"`, you must keep that exact class in the `after` block.

