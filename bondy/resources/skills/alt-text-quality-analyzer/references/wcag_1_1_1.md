# WCAG 1.1.1 Success Criterion: Non-text Content

All non-text content that is presented to the user has a text alternative that serves the equivalent purpose, except for the situations listed below.

## Guidelines for Alternative Text (alt)

- **Informative Images**: Images that represent concepts and information, typically pictures, graphs, and diagrams. The text alternative should be at least a short description conveying the essential information presented by the image.
- **Decorative Images**: Provided only for aesthetic purposes, providing no information, and having no functionality. They must have an empty alt attribute (`alt=""`) so they can be ignored by assistive technologies.
- **Functional Images**: Images used as links or buttons (e.g., a magnifying glass icon for search). The text alternative should describe the function or destination of the link/button, NOT describe the image visually (e.g., "Search" and not "Magnifying glass").

## Evaluating Quality

Alt text is **poor** if it:
- Is overly verbose or details irrelevant information (keyword stuffing).
- Describes the file format or uses redundant phrases ("image of", "photo of", "logo.png").
- Does not adequately reflect the intent or function of the image within its context.
- For a chart/diagram, fails to convey the key data or main message.
