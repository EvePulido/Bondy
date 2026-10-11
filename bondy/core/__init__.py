"""Code-driven audit pipeline (no FastAPI, no ADK).

Stages: discover pages -> deterministic scanners (``bondy.scan``) -> optional
semantic stage for images (one LLM call per batch) -> fixes -> report.
"""
