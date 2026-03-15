"""
Refine endpoint - Conversational document refinement via chat.
Supports both informational responses (questions about laws/case) and document edits.

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
    learning_applier,
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
    Only called when there are actual document changes.
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
    Conversational refine endpoint - handles questions AND document edits.

    The agent intelligently determines whether to:
    - Answer a question (informational) - no document changes
    - Modify the document (edit) - updates the draft

    Returns:
        JSON with:
        - response_type: "informational" or "edit"
        - explanation: The agent's response (always present)
        - draft: Updated document (only for "edit" responses)
        - has_document_changes: Boolean indicating if document was modified
    """
    logger.info(f"[Sync] Processing chat for case {case_file_id}, session {request_body.session_id}")

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

        # Get learnings for this customer/document type (optional)
        learning_instructions = None
        if settings.learning_enabled and customer_id:
            try:
                learnings = await learning_applier.get_learnings_for_generation(
                    customer_id=customer_id,
                    document_type=document_type,
                )
                if learnings:
                    learnings = learning_applier.filter_by_context(learnings, case_context)
                    if learnings:
                        learning_instructions = learning_applier.format_learnings_for_prompt(
                            learnings=learnings,
                            customer_name=case_context.get("customer_name", ""),
                        )
                        logger.info(f"[Sync] Applied {len(learnings)} learnings to refine")
            except Exception as e:
                logger.warning(f"[Sync] Could not fetch learnings: {e}")

        # Run refiner agent
        refiner = RefinerAgent()

        logger.info(f"[Sync] Running conversational refiner for session {request_body.session_id}")

        result = await refiner.refine(
            current_draft=current_draft,
            feedback=request_body.feedback,
            context=case_context,
            chat_history=chat_history,
            custom_instructions=learning_instructions,
        )

        response_type = result.get("response_type", "edit")
        new_draft = result.get("new_draft")
        changes = result.get("changes", [])
        explanation = result.get("explanation", "")
        has_document_changes = result.get("has_document_changes", False)

        logger.info(f"[Sync] Response type: {response_type}, has_changes: {has_document_changes}")

        # Only save draft to MySQL if there were actual changes
        if has_document_changes and new_draft:
            await mysql.update_ai_session_draft(
                request_body.session_id,
                new_draft,
                0,  # tokens_used - not tracked in sync mode
            )
            logger.info(f"[Sync] Draft saved for session {request_body.session_id}")

        # Add AI response to session history
        await mysql.add_ai_session_message(
            session_id=request_body.session_id,
            role="assistant",
            content=explanation,
        )

        # Schedule learning extraction in background only for actual edits
        if settings.learning_enabled and customer_id and has_document_changes and new_draft:
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
            "response_type": response_type,
            "draft": new_draft if has_document_changes else current_draft,
            "changes": changes,
            "message": "Document refined successfully" if has_document_changes else "Response provided",
            "explanation": explanation,
            "has_document_changes": has_document_changes,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Sync] Error processing chat: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"error": str(e), "code": "INTERNAL_ERROR"}
        )
