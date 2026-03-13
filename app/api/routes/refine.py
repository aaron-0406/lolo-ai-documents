"""
Refine endpoint - Refines document via chat with SSE streaming.
Integrates with the learning system to extract learnings from user feedback.

NOTE: Session management is handled by lolo-backend (MySQL).
This microservice reads session data from MySQL and updates it after refinement.
"""

import asyncio
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from loguru import logger

from app.config import settings
from app.models.requests import RefineRequest
from app.agents.orchestration.refiner_agent import RefinerAgent
from app.utils.streaming import (
    create_sse_message,
    create_sse_keepalive,
    SSE_EVENT_TOKEN,
    SSE_EVENT_DRAFT_UPDATE,
    SSE_EVENT_DONE,
    SSE_EVENT_ERROR,
)

router = APIRouter()

# SSE event for learnings
SSE_EVENT_LEARNINGS = "learnings"
SSE_EVENT_EFFECTIVENESS = "effectiveness"


@router.post("/refine/{case_file_id}")
async def refine_document_stream(
    case_file_id: int,
    request_body: RefineRequest,
    request: Request,
):
    """
    PASO 3: Refine document with SSE streaming.

    This endpoint refines the document based on user feedback using
    Server-Sent Events (SSE) to stream the response in real-time.

    Session data is read from MySQL (managed by lolo-backend).

    The endpoint also extracts learnings from user feedback and stores
    them in the backend for future use (if learning is enabled).

    SSE Events emitted:
    - token: Individual tokens of the AI response
    - draft_update: Updated document draft
    - learnings: Learnings extracted from feedback (if any)
    - done: Completion with list of changes and tokens_used
    - error: Error occurred

    Args:
        case_file_id: ID of the JUDICIAL_CASE_FILE
        request_body: Refinement parameters (session_id, feedback)
        request: FastAPI request object

    Returns:
        StreamingResponse with SSE events
    """
    logger.info(f"Refining document for case {case_file_id}, session {request_body.session_id}")

    async def event_generator():
        try:
            # Get MySQL service
            mysql = request.app.state.mysql

            # Retrieve session from MySQL
            session = await mysql.get_ai_session(request_body.session_id)
            if not session:
                yield create_sse_message(SSE_EVENT_ERROR, {
                    "error": "Session not found or expired",
                    "code": "SESSION_NOT_FOUND",
                })
                return

            # Verify session belongs to this case file
            if session["case_file_id"] != case_file_id:
                yield create_sse_message(SSE_EVENT_ERROR, {
                    "error": "Session does not match case file",
                    "code": "SESSION_MISMATCH",
                })
                return

            # Get current draft and context from session
            current_draft = session.get("current_draft", "")
            case_context = session.get("case_context", {})
            chat_history = session.get("conversation_history", [])
            document_type = session.get("document_type", "escrito_otro")

            # Extract customer_id from case_context for learning storage
            customer_id = case_context.get("customer_id")
            user_id = session.get("created_by_customer_user_id")

            # Get applied learning IDs from session for effectiveness tracking
            applied_learning_ids = session.get("applied_learning_ids", [])

            # Add user message to MySQL session
            await mysql.add_ai_session_message(
                session_id=request_body.session_id,
                role="user",
                content=request_body.feedback,
            )

            # Run refiner agent with streaming and learning extraction
            refiner = RefinerAgent()

            full_response = ""
            new_draft = ""
            changes_detected = []
            tokens_used = 0
            learnings_info = None

            # Use learning-enabled streaming if customer_id is available
            if settings.learning_enabled and customer_id:
                stream_method = refiner.refine_stream_with_learning(
                    current_draft=current_draft,
                    feedback=request_body.feedback,
                    context=case_context,
                    chat_history=chat_history,
                    document_type=document_type,
                    session_id=request_body.session_id,
                    customer_id=customer_id,
                    case_file_id=case_file_id,
                    user_id=user_id,
                    applied_learning_ids=applied_learning_ids,
                )
            else:
                stream_method = refiner.refine_stream(
                    current_draft=current_draft,
                    feedback=request_body.feedback,
                    context=case_context,
                    chat_history=chat_history,
                )

            async for chunk in stream_method:
                if chunk["type"] == "token":
                    # Stream token to client
                    yield create_sse_message(SSE_EVENT_TOKEN, {
                        "content": chunk["content"]
                    })
                    full_response += chunk["content"]

                elif chunk["type"] == "draft":
                    # Document updated - save to MySQL IMMEDIATELY for resilience
                    # This ensures draft is persisted even if connection is lost later
                    new_draft = chunk["content"]
                    try:
                        await mysql.update_ai_session_draft(
                            request_body.session_id,
                            new_draft,
                            0,  # tokens_used will be updated at the end
                        )
                        logger.debug(f"Draft saved to MySQL for session {request_body.session_id}")
                    except Exception as save_err:
                        logger.error(f"Failed to save draft to MySQL: {save_err}")

                    yield create_sse_message(SSE_EVENT_DRAFT_UPDATE, {
                        "draft": new_draft
                    })

                elif chunk["type"] == "changes":
                    changes_detected = chunk["content"]

                elif chunk["type"] == "tokens":
                    tokens_used = chunk.get("count", 0)

                elif chunk["type"] == "learnings":
                    # Learnings extracted from feedback
                    learnings_info = chunk["content"]
                    yield create_sse_message(SSE_EVENT_LEARNINGS, learnings_info)

                elif chunk["type"] == "effectiveness":
                    # Effectiveness of previously applied learnings
                    yield create_sse_message(SSE_EVENT_EFFECTIVENESS, chunk["content"])

                elif chunk["type"] == "error":
                    yield create_sse_message(SSE_EVENT_ERROR, {
                        "error": chunk["content"],
                        "code": "REFINE_ERROR",
                    })

            # Send keepalive before potentially long operations
            yield create_sse_keepalive()

            # Update tokens_used in MySQL (draft was already saved immediately when received)
            # This is a final update to ensure tokens count is accurate
            if new_draft and tokens_used > 0:
                try:
                    await mysql.update_ai_session_draft(
                        request_body.session_id,
                        new_draft,
                        tokens_used,
                    )
                except Exception as update_err:
                    # Non-critical - draft is already saved, just log the error
                    logger.warning(f"Failed to update tokens_used: {update_err}")

            # Add AI response to session history
            await mysql.add_ai_session_message(
                session_id=request_body.session_id,
                role="assistant",
                content=full_response,
            )

            # Send another keepalive after database operations
            yield create_sse_keepalive()

            # Send completion event with tokens_used for frontend to sync
            done_data = {
                "changes": changes_detected,
                "message": "Document refined successfully",
                "tokens_used": tokens_used,
            }

            # Include learning info in done event
            if learnings_info:
                done_data["learnings_extracted"] = learnings_info.get("count", 0)

            yield create_sse_message(SSE_EVENT_DONE, done_data)

        except Exception as e:
            logger.error(f"Error refining document: {e}", exc_info=True)
            yield create_sse_message(SSE_EVENT_ERROR, {
                "error": str(e),
                "code": "INTERNAL_ERROR",
            })

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
