"""
Analyze endpoint - Analyzes case file and suggests document.

NOTE: If job_id is provided, the result is saved to the backend via internal
endpoint BEFORE returning the HTTP response. This enables recovery if the
HTTP connection is lost - the backend can poll the job for the result.
"""

from fastapi import APIRouter, HTTPException, Request
from loguru import logger
import httpx

from app.config import settings
from app.models.requests import AnalyzeRequest
from app.models.responses import AnalyzeResponse
from app.agents.orchestration.analyzer_agent import AnalyzerAgent
from app.utils.exceptions import CaseFileNotFoundError

router = APIRouter()


async def save_result_to_backend(job_id: str, result: dict, status: str = "COMPLETED", error: str = None) -> bool:
    """
    Save analyze result to backend job record for resilient processing.

    This is called BEFORE returning the HTTP response, so even if the
    connection is lost, the backend can recover the result by polling.

    Args:
        job_id: Job ID from backend
        result: The analyze result to save
        status: Job status - "COMPLETED" or "FAILED"
        error: Error message if status is "FAILED"

    Returns:
        True if saved successfully, False otherwise
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            payload = {"result": result, "status": status}
            if error:
                payload["error"] = error

            response = await client.post(
                f"{settings.backend_url}/api/v1/judicial/ai-documents/jobs/{job_id}/result/internal",
                headers={"X-Internal-API-Key": settings.internal_api_key},
                json=payload,
            )

            if response.status_code == 200:
                logger.info(f"Saved analyze result to backend job {job_id[:20]}...")
                return True
            else:
                logger.warning(f"Failed to save result to backend: {response.status_code} - {response.text}")
                return False

    except Exception as e:
        logger.warning(f"Error saving result to backend job {job_id}: {e}")
        # Don't fail the request - the HTTP response will still contain the result
        return False


@router.post("/analyze/{case_file_id}", response_model=AnalyzeResponse)
async def analyze_case_file(
    case_file_id: int,
    request_body: AnalyzeRequest,
    request: Request,
) -> AnalyzeResponse:
    """
    PASO 1A: Analyze a case file and suggest the next document to generate.

    This endpoint analyzes the current state of a judicial case file and:
    - Determines the current procedural stage
    - Identifies what documents have already been filed
    - Suggests the most appropriate next document
    - Or indicates that no action is currently needed

    Args:
        case_file_id: ID of the JUDICIAL_CASE_FILE to analyze
        request_body: Additional request options
        request: FastAPI request object

    Returns:
        AnalyzeResponse with suggestion or no-action reason
    """
    logger.info(f"Analyzing case file {case_file_id}")

    try:
        # Get services from app state
        mysql = request.app.state.mysql
        document_context = request.app.state.document_context

        # Check if case file exists
        if not await mysql.case_file_exists(case_file_id):
            raise CaseFileNotFoundError(case_file_id)

        # Get full case context including extracted document content from S3
        context = await document_context.get_full_context(
            case_file_id,
            max_documents=10,  # Extract up to 10 most recent documents
            max_pages_per_doc=5,  # Extract up to 5 pages per document
        )
        if not context:
            raise CaseFileNotFoundError(case_file_id)

        logger.info(
            f"Context loaded: {len(context.binnacles)} binnacles, "
            f"{len(context.binnacle_documents)} documents extracted"
        )

        # Run analyzer agent
        analyzer = AnalyzerAgent()
        result = await analyzer.analyze(context)

        # Build response
        if result.has_suggestion:
            response = AnalyzeResponse(
                success=True,
                has_suggestion=True,
                suggestion=result.suggestion,
                alternatives=result.alternatives,
                no_action_reason=None,
                case_context=context,
            )
        else:
            response = AnalyzeResponse(
                success=True,
                has_suggestion=False,
                suggestion=None,
                alternatives=[],
                no_action_reason=result.no_action_reason,
                case_context=context,
            )

        # CRITICAL: Save result to backend BEFORE returning HTTP response
        # This enables recovery if the HTTP connection is lost
        if request_body.job_id:
            await save_result_to_backend(
                job_id=request_body.job_id,
                result=response.model_dump(mode="json"),  # mode="json" serializes datetime
                status="COMPLETED",
            )

        return response

    except CaseFileNotFoundError as e:
        logger.warning(f"Case file not found: {case_file_id}")
        # Save error to backend if job_id provided
        if request_body.job_id:
            await save_result_to_backend(
                job_id=request_body.job_id,
                result=None,
                status="FAILED",
                error=e.message,
            )
        raise HTTPException(status_code=404, detail=e.message)

    except Exception as e:
        logger.error(f"Error analyzing case file {case_file_id}: {e}")
        # Save error to backend if job_id provided
        if request_body.job_id:
            await save_result_to_backend(
                job_id=request_body.job_id,
                result=None,
                status="FAILED",
                error=str(e),
            )
        raise HTTPException(status_code=500, detail=str(e))
