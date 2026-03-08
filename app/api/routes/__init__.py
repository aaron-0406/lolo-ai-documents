"""API route modules."""

from app.api.routes import analyze, generate, refine, finalize, document_types, health, annexes

__all__ = ["analyze", "generate", "refine", "finalize", "document_types", "health", "annexes"]
