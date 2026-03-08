"""Data models package."""

from app.models.requests import (
    AnalyzeRequest,
    GenerateRequest,
    RefineRequest,
    FinalizeRequest,
)
from app.models.responses import (
    AnalyzeResponse,
    GenerateResponse,
    RefineResponse,
    FinalizeResponse,
    DocumentTypeResponse,
    HealthResponse,
)
from app.models.schemas import (
    CaseContext,
    DocumentSuggestion,
    ChatMessage,
    DocumentSession,
    DocumentType,
    BinnacleSuggestion,
)

__all__ = [
    # Requests
    "AnalyzeRequest",
    "GenerateRequest",
    "RefineRequest",
    "FinalizeRequest",
    # Responses
    "AnalyzeResponse",
    "GenerateResponse",
    "RefineResponse",
    "FinalizeResponse",
    "DocumentTypeResponse",
    "HealthResponse",
    # Schemas
    "CaseContext",
    "DocumentSuggestion",
    "ChatMessage",
    "DocumentSession",
    "DocumentType",
    "BinnacleSuggestion",
]
