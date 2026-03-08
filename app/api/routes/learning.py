"""
Learning endpoints - Internal endpoints for learning extraction and similarity checking.

These endpoints are for internal use by the lolo-backend or other services.
"""

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Header
from loguru import logger
from pydantic import BaseModel

from app.config import settings
from app.services.learning_service import (
    learning_extractor,
    similarity_checker,
    learning_applier,
    ExtractedLearning,
    StoredLearning,
)


router = APIRouter()


# =============================================================================
# Request/Response Models
# =============================================================================

class ExtractLearningsRequest(BaseModel):
    """Request for extracting learnings from feedback."""
    document_type: str
    user_feedback: str
    original_text: str
    corrected_text: str
    document_section: Optional[str] = None


class ExtractLearningsResponse(BaseModel):
    """Response with extracted learnings."""
    success: bool
    learnings: list[dict[str, Any]]
    count: int


class CheckSimilarityRequest(BaseModel):
    """Request for checking similarity."""
    customer_id: int
    document_type: str
    new_learning: dict[str, Any]


class CheckSimilarityResponse(BaseModel):
    """Response with similarity results."""
    success: bool
    has_similar: bool
    most_similar_id: Optional[str] = None
    relationship: str
    similarity_score: float


# =============================================================================
# Helper: Validate internal API key
# =============================================================================

def validate_api_key(x_internal_api_key: str = Header(None)) -> None:
    """Validate the internal API key."""
    if not x_internal_api_key or x_internal_api_key != settings.internal_api_key:
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing internal API key",
        )


# =============================================================================
# Endpoints
# =============================================================================

@router.post("/extract", response_model=ExtractLearningsResponse)
async def extract_learnings(
    request: ExtractLearningsRequest,
    x_internal_api_key: str = Header(None),
):
    """
    POST /internal/learning/extract

    Extract generalizable learnings from user feedback.

    This endpoint is called after a document refinement to identify
    patterns that could be applied to future documents.

    Args:
        request: Extraction parameters

    Returns:
        List of extracted learnings
    """
    validate_api_key(x_internal_api_key)

    try:
        learnings = await learning_extractor.extract_learnings(
            document_type=request.document_type,
            user_feedback=request.user_feedback,
            original_text=request.original_text,
            corrected_text=request.corrected_text,
            document_section=request.document_section,
        )

        # Convert to dict format
        learnings_data = [
            {
                "learning_type": l.learning_type,
                "instruction": l.instruction,
                "instruction_summary": l.instruction_summary,
                "document_section": l.document_section,
                "applies_when": l.applies_when,
                "priority": l.priority,
                "is_generalizable": l.is_generalizable,
            }
            for l in learnings
        ]

        logger.info(f"Extracted {len(learnings_data)} learnings from feedback")

        return ExtractLearningsResponse(
            success=True,
            learnings=learnings_data,
            count=len(learnings_data),
        )

    except Exception as e:
        logger.error(f"Error extracting learnings: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error extracting learnings: {str(e)}",
        )


@router.post("/check-similarity", response_model=CheckSimilarityResponse)
async def check_similarity(
    request: CheckSimilarityRequest,
    x_internal_api_key: str = Header(None),
):
    """
    POST /internal/learning/check-similarity

    Check if a new learning is similar to existing learnings.

    This endpoint is called before creating a new learning to detect
    duplicates or conflicts.

    Args:
        request: New learning to check and customer context

    Returns:
        Similarity check results
    """
    validate_api_key(x_internal_api_key)

    try:
        # Get existing learnings from backend
        existing_learnings = await learning_applier.get_learnings_for_generation(
            customer_id=request.customer_id,
            document_type=request.document_type,
            case_context=None,
        )

        if not existing_learnings:
            return CheckSimilarityResponse(
                success=True,
                has_similar=False,
                most_similar_id=None,
                relationship="independent",
                similarity_score=0.0,
            )

        # Create ExtractedLearning from request
        new_learning = ExtractedLearning(
            learning_type=request.new_learning.get("learning_type", "content_rule"),
            instruction=request.new_learning.get("instruction", ""),
            instruction_summary=request.new_learning.get("instruction_summary"),
            document_section=request.new_learning.get("document_section"),
            applies_when=request.new_learning.get("applies_when"),
            priority=request.new_learning.get("priority", 50),
        )

        # Check similarity
        result = await similarity_checker.check_similarity(
            new_learning=new_learning,
            existing_learnings=existing_learnings,
        )

        has_similar = result.relationship in ["duplicate", "conflict", "complementary"]

        return CheckSimilarityResponse(
            success=True,
            has_similar=has_similar,
            most_similar_id=result.existing_learning_id,
            relationship=result.relationship,
            similarity_score=result.similarity_score,
        )

    except Exception as e:
        logger.error(f"Error checking similarity: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error checking similarity: {str(e)}",
        )
