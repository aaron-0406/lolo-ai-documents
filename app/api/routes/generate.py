"""
Generate endpoint - Generates initial document draft.
Applies customer learnings during generation.

NOTE: Session management is handled by lolo-backend (MySQL).
This microservice is stateless - the backend passes session_id and
the microservice just generates content.
"""

from fastapi import APIRouter, HTTPException, Request
from loguru import logger

from app.config import settings
from app.models.requests import GenerateRequest
from app.models.responses import GenerateResponse
from app.agents.orchestration.generator_agent import GeneratorAgent
from app.api.routes.document_types import get_document_type_by_key
from app.services.annex_service import AnnexService
from app.utils.exceptions import CaseFileNotFoundError, InvalidDocumentTypeError

router = APIRouter()


@router.post("/generate/{case_file_id}", response_model=GenerateResponse)
async def generate_document(
    case_file_id: int,
    request_body: GenerateRequest,
    request: Request,
) -> GenerateResponse:
    """
    PASO 2: Generate an initial document draft.

    This endpoint generates a document based on:
    - The case file context (from MySQL or passed by backend)
    - The specified document type
    - Data from related tables (collaterals, binnacles, etc.)
    - Customer-specific learnings (if learning is enabled)

    Session is created by lolo-backend in MySQL before calling this endpoint.
    The backend passes the session_id which we return in the response.

    The generator will automatically:
    1. Retrieve applicable learnings for the customer
    2. Apply them to the document generation
    3. Record that learnings were applied (for effectiveness tracking)

    Args:
        case_file_id: ID of the JUDICIAL_CASE_FILE
        request_body: Generation parameters (document_type, session_id from backend)
        request: FastAPI request object

    Returns:
        GenerateResponse with draft and session_id
    """
    logger.info(f"Generating document for case {case_file_id}: {request_body.document_type}")

    try:
        # Validate document type
        doc_type = get_document_type_by_key(request_body.document_type)
        if not doc_type:
            raise InvalidDocumentTypeError(request_body.document_type)

        # Get services from app state
        mysql = request.app.state.mysql
        document_context = request.app.state.document_context

        # Check if case file exists
        if not await mysql.case_file_exists(case_file_id):
            raise CaseFileNotFoundError(case_file_id)

        # Get full case context including extracted document content from S3
        context = await document_context.get_full_context(
            case_file_id,
            max_documents=15,  # Extract more documents for generation
            max_pages_per_doc=8,  # More pages for thorough context
        )
        if not context:
            raise CaseFileNotFoundError(case_file_id)

        logger.info(
            f"Context loaded for generation: {len(context.binnacles)} binnacles, "
            f"{len(context.binnacle_documents)} documents extracted"
        )

        # Session is managed by backend - we just return the session_id they gave us
        session_id = request_body.session_id or f"ai-doc-{case_file_id}"

        # Run generator agent (with learning application)
        generator = GeneratorAgent()
        result = await generator.generate(
            document_type=request_body.document_type,
            context=context,
            custom_instructions=request_body.custom_instructions,
            session_id=session_id,  # Pass session_id for learning tracking
        )

        # CRITICAL: Save draft to MySQL BEFORE returning response
        # This ensures the draft is persisted even if the HTTP response times out
        try:
            await mysql.update_ai_session_draft(
                session_id=session_id,
                draft=result.draft,
                tokens_used=result.tokens_used,
            )
            logger.info(f"Draft saved to MySQL session {session_id[:20]}...")

            # Also save the AI message to conversation history
            await mysql.add_ai_session_message(
                session_id=session_id,
                role="assistant",
                content=result.ai_message,
            )
        except Exception as e:
            logger.error(f"Failed to save draft/message to MySQL: {e}")
            # Continue anyway - data will be in response for backend fallback

        # Log learning info and save to session for effectiveness tracking
        if result.learnings_applied > 0:
            logger.info(
                f"Applied {result.learnings_applied} learnings to generation "
                f"(session {session_id})"
            )
            # Save learning_ids to session for effectiveness tracking during refinement
            if result.learning_ids:
                await mysql.update_ai_session_learning_ids(
                    session_id=session_id,
                    learning_ids=result.learning_ids,
                )

        # Identify relevant annexes if requested
        suggested_annexes = []
        if request_body.include_annexes:
            try:
                s3 = request.app.state.s3
                annex_service = AnnexService(s3)
                suggested_annexes = await annex_service.identify_relevant_annexes(
                    document_type=request_body.document_type,
                    context=context,
                )
                # Limit to max requested
                suggested_annexes = suggested_annexes[:request_body.max_annexes]

                # Generate thumbnails for top annexes (for preview)
                suggested_annexes = await annex_service.get_annexes_with_thumbnails(
                    suggested_annexes,
                    max_thumbnails=10,
                )

                logger.info(f"Identified {len(suggested_annexes)} relevant annexes")
            except Exception as e:
                logger.warning(f"Failed to identify annexes: {e}")
                # Continue without annexes - not critical

        logger.info(f"Generated document, session {session_id}")

        # Build response with learning info
        response = GenerateResponse(
            success=True,
            session_id=session_id,
            document_type=request_body.document_type,
            draft=result.draft,
            ai_message=result.ai_message,
            tokens_used=result.tokens_used,
            suggested_annexes=suggested_annexes,
        )

        # Add learning info to response if any were applied
        if result.learnings_applied > 0:
            # Note: This requires adding learnings_applied to GenerateResponse
            # For now, we include it in ai_message
            pass

        return response

    except CaseFileNotFoundError as e:
        logger.warning(f"Case file not found: {case_file_id}")
        raise HTTPException(status_code=404, detail=e.message)

    except InvalidDocumentTypeError as e:
        logger.warning(f"Invalid document type: {request_body.document_type}")
        raise HTTPException(status_code=400, detail=e.message)

    except Exception as e:
        logger.error(f"Error generating document for case {case_file_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
