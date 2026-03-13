"""
Refine endpoint - Refines document via chat.
Integrates with the learning system to extract learnings from user feedback.

NOTE: Session management is handled by lolo-backend (MySQL).
This microservice reads session data from MySQL and updates it after refinement.
Learning extraction runs as a background task after the response is sent.
"""

from fastapi import APIRouter, HTTPException, Request, BackgroundTasks
from loguru import logger

from app.config import settings
from app.models.requests import RefineRequest
from app.agents.orchestration.refiner_agent import RefinerAgent
from app.services.learning_service import (
    learning_extractor,
    learning_backend,
)

router = APIRouter()


async def extract_and_store_learnings_background(
    customer_id: int,
    document_type: str,
    feedback: str,
    original_draft: str,
    new_draft: str,
    session_id: str,
    case_file_id: int,
    user_id: int | None,
):
    """
    Background task to extract and store learnings.
    This runs after the response is sent to avoid blocking.
    """
    try:
        logger.info(f"[Background] Extracting learnings for session {session_id}")

        learnings = await learning_extractor.extract_learnings(
            document_type=document_type,
            user_feedback=feedback,
            original_text=original_draft,
            corrected_text=new_draft,
            document_section=None,
        )

        if not learnings:
            logger.info(f"[Background] No learnings extracted for session {session_id}")
            return

        logger.info(f"[Background] Extracted {len(learnings)} learnings, storing...")

        for learning in learnings:
            try:
                learning_id = await learning_backend.create_learning(
                    customer_id=customer_id,
                    document_type=document_type,
                    learning=learning,
                    source_session_id=session_id,
                    source_case_file_id=case_file_id,
                    created_by_user_id=user_id,
                )
                if learning_id:
                    logger.debug(f"[Background] Created learning {learning_id}")
            except Exception as e:
                logger.error(f"[Background] Failed to create learning: {e}")

        logger.info(f"[Background] Finished storing learnings for session {session_id}")

    except Exception as e:
        logger.error(f"[Background] Error extracting learnings: {e}", exc_info=True)


@router.post("/refine-sync/{case_file_id}")
async def refine_document_sync(
    case_file_id: int,
    request_body: RefineRequest,
    request: Request,
    background_tasks: BackgroundTasks,
):
    """
    Synchronous refine endpoint - returns JSON response.

    This is the recommended endpoint for the job system as it:
    - Returns immediately when refinement is complete
    - Saves draft to MySQL before responding
    - Extracts learnings in background (non-blocking)
    - Is more reliable than SSE streaming

    Args:
        case_file_id: ID of the JUDICIAL_CASE_FILE
        request_body: Refinement parameters (session_id, feedback)
        request: FastAPI request object
        background_tasks: FastAPI background tasks

    Returns:
        JSON with success, draft, changes, and message
    """
    logger.info(f"[Sync] Refining document for case {case_file_id}, session {request_body.session_id}")

    try:
        # Get MySQL service
        mysql = request.app.state.mysql

        # Retrieve session from MySQL
        session = await mysql.get_ai_session(request_body.session_id)
        if not session:
            raise HTTPException(
                status_code=404,
                detail={"error": "Session not found or expired", "code": "SESSION_NOT_FOUND"}
            )

        # Verify session belongs to this case file
        if session["case_file_id"] != case_file_id:
            raise HTTPException(
                status_code=400,
                detail={"error": "Session does not match case file", "code": "SESSION_MISMATCH"}
            )

        # Get current draft and context from session
        current_draft = session.get("current_draft", "")
        case_context = session.get("case_context", {})
        chat_history = session.get("conversation_history", [])
        document_type = session.get("document_type", "escrito_otro")

        # Extract customer_id from case_context for learning storage
        customer_id = case_context.get("customer_id")
        user_id = session.get("created_by_customer_user_id")

        # Add user message to MySQL session
        await mysql.add_ai_session_message(
            session_id=request_body.session_id,
            role="user",
            content=request_body.feedback,
        )

        # Run refiner agent (non-streaming version)
        refiner = RefinerAgent()

        logger.info(f"[Sync] Running refiner for session {request_body.session_id}")

        result = await refiner.refine(
            current_draft=current_draft,
            feedback=request_body.feedback,
            context=case_context,
            chat_history=chat_history,
        )

        new_draft = result.get("new_draft", "")
        changes = result.get("changes", [])
        explanation = result.get("explanation", "")

        logger.info(f"[Sync] Refinement complete, saving draft to MySQL")

        # Save draft to MySQL IMMEDIATELY
        await mysql.update_ai_session_draft(
            request_body.session_id,
            new_draft,
            0,  # tokens_used - not tracked in sync mode
        )

        # Add AI response to session history
        await mysql.add_ai_session_message(
            session_id=request_body.session_id,
            role="assistant",
            content=explanation,
        )

        logger.info(f"[Sync] Draft saved for session {request_body.session_id}")

        # Schedule learning extraction in background (fire-and-forget)
        if settings.learning_enabled and customer_id and new_draft:
            background_tasks.add_task(
                extract_and_store_learnings_background,
                customer_id=customer_id,
                document_type=document_type,
                feedback=request_body.feedback,
                original_draft=current_draft,
                new_draft=new_draft,
                session_id=request_body.session_id,
                case_file_id=case_file_id,
                user_id=user_id,
            )
            logger.info(f"[Sync] Learning extraction scheduled in background")

        return {
            "success": True,
            "draft": new_draft,
            "changes": changes,
            "message": "Document refined successfully",
            "explanation": explanation,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Sync] Error refining document: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"error": str(e), "code": "INTERNAL_ERROR"}
        )
