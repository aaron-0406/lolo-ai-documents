"""
Request models for API endpoints.
"""

from typing import Optional, List, Dict, Any

from pydantic import BaseModel, Field


class AnalyzeRequest(BaseModel):
    """Request to analyze a case file."""

    # Note: case_file_id comes from URL path parameter
    # This model is for any additional body parameters

    force_refresh: bool = Field(
        default=False,
        description="Force refresh of cached analysis"
    )
    case_context: Optional[Dict[str, Any]] = Field(
        None,
        description="Case context passed from backend"
    )
    job_id: Optional[str] = Field(
        None,
        description="Job ID from backend for resilient processing. "
        "If provided, result will be saved to backend before HTTP response."
    )
    include_files: Optional[bool] = Field(
        True,
        description="Whether to include file content in analysis"
    )


class GenerateRequest(BaseModel):
    """Request to generate a document."""

    document_type: str = Field(
        ...,
        description="Type of document to generate (e.g., 'solicitud_remate')"
    )
    session_id: Optional[str] = Field(
        None,
        description="Session ID created by backend (stored in MySQL)"
    )
    case_context: Optional[Dict[str, Any]] = Field(
        None,
        description="Case context passed from backend"
    )
    custom_instructions: Optional[str] = Field(
        None,
        description="Additional custom instructions for generation"
    )
    include_annexes: bool = Field(
        True,
        description="Whether to identify and return suggested annexes"
    )
    max_annexes: int = Field(
        20,
        description="Maximum number of annexes to return"
    )


class ChatMessage(BaseModel):
    """A message in the conversation history."""

    role: str = Field(..., description="Role: 'user' or 'assistant'")
    content: str = Field(..., description="Message content")
    timestamp: Optional[str] = Field(None, description="ISO timestamp")


class RefineRequest(BaseModel):
    """Request to refine a document via chat."""

    session_id: str = Field(
        ...,
        description="Session ID from backend (stored in MySQL)"
    )
    feedback: str = Field(
        ...,
        min_length=1,
        max_length=5000,
        description="User feedback for refinement"
    )
    user_name: Optional[str] = Field(
        None,
        description="Name of the user providing feedback"
    )
    # Context passed from backend (stateless mode)
    case_context: Optional[Dict[str, Any]] = Field(
        None,
        description="Case context passed from backend"
    )
    current_draft: Optional[str] = Field(
        None,
        description="Current document draft"
    )
    conversation_history: Optional[List[ChatMessage]] = Field(
        None,
        description="Conversation history from backend"
    )


class AnnexSelectionRequest(BaseModel):
    """Selection of annexes to include in final document."""

    annex_ids: List[str] = Field(
        default_factory=list,
        description="IDs of selected annexes to embed"
    )
    custom_order: Optional[List[str]] = Field(
        None,
        description="Custom ordering of annexes (list of IDs)"
    )


class FinalizeRequest(BaseModel):
    """Request to finalize and generate DOCX."""

    session_id: str = Field(
        ...,
        description="Session ID from backend (stored in MySQL)"
    )
    download_copy: bool = Field(
        default=True,
        description="Whether to include download in response"
    )
    # Context passed from backend (stateless mode)
    document_type: Optional[str] = Field(
        None,
        description="Type of document"
    )
    current_draft: Optional[str] = Field(
        None,
        description="Final document draft"
    )
    case_context: Optional[Dict[str, Any]] = Field(
        None,
        description="Case context passed from backend"
    )
    # Annex selection
    selected_annexes: Optional[AnnexSelectionRequest] = Field(
        None,
        description="Selected annexes to embed in the document"
    )
    suggested_annexes: Optional[List[Dict[str, Any]]] = Field(
        None,
        description="Full annex data passed from frontend for processing"
    )
