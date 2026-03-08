"""
Response models for API endpoints.
"""

from typing import Any, Optional

from pydantic import BaseModel, Field

from app.models.schemas import (
    AnnexInfo,
    CaseContext,
    DocumentSuggestion,
    NoActionReason,
    DocumentType,
    DocumentCategoryInfo,
    BinnacleSuggestion,
)


class AnalyzeResponse(BaseModel):
    """Response from case analysis."""

    success: bool = Field(..., description="Whether analysis succeeded")
    has_suggestion: bool = Field(..., description="Whether a document is suggested")

    # When has_suggestion is True
    suggestion: Optional[DocumentSuggestion] = Field(
        None,
        description="Suggested document to generate"
    )
    alternatives: list[DocumentSuggestion] = Field(
        default_factory=list,
        description="Alternative document suggestions"
    )

    # When has_suggestion is False
    no_action_reason: Optional[NoActionReason] = Field(
        None,
        description="Reason why no action is needed"
    )

    # Always included
    case_context: CaseContext = Field(..., description="Case context data")


class GenerateResponse(BaseModel):
    """Response from document generation."""

    success: bool = Field(..., description="Whether generation succeeded")
    session_id: str = Field(..., description="Session ID for continuation")
    document_type: str = Field(..., description="Document type generated")
    draft: str = Field(..., description="Generated document draft (HTML/Markdown)")
    ai_message: str = Field(..., description="AI explanation of what was generated")
    tokens_used: Optional[int] = Field(None, description="Tokens consumed")
    suggested_annexes: list[AnnexInfo] = Field(
        default_factory=list,
        description="Suggested annexes to include with the document"
    )


class RefineResponse(BaseModel):
    """Response from document refinement (non-streaming)."""

    success: bool = Field(..., description="Whether refinement succeeded")
    draft: str = Field(..., description="Updated document draft")
    changes: list[str] = Field(default_factory=list, description="List of changes made")
    ai_response: str = Field(..., description="AI explanation of changes")


class FinalizeResponse(BaseModel):
    """Response from document finalization."""

    success: bool = Field(..., description="Whether finalization succeeded")
    document_base64: str = Field(..., description="DOCX file as base64")
    filename: str = Field(..., description="Suggested filename")
    file_size_bytes: int = Field(..., description="File size in bytes")
    binnacle_suggestion: BinnacleSuggestion = Field(
        ...,
        description="Suggested binnacle entry data"
    )
    annex_count: int = Field(
        default=0,
        description="Number of annexes embedded in the document"
    )


class DocumentTypeResponse(BaseModel):
    """Response with available document types."""

    categories: list[DocumentCategoryInfo] = Field(
        ...,
        description="Document types organized by category"
    )
    total_count: int = Field(..., description="Total number of document types")


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = Field(..., description="Overall status: healthy or unhealthy")
    version: str = Field(..., description="Application version")
    services: dict[str, str] = Field(
        ...,
        description="Status of each service: ok or error"
    )
    timestamp: str = Field(..., description="Check timestamp")


class ErrorResponse(BaseModel):
    """Error response."""

    success: bool = Field(default=False)
    error: str = Field(..., description="Error message")
    code: str = Field(..., description="Error code")
    details: Optional[dict[str, Any]] = Field(None, description="Additional details")
