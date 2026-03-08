"""
Analyze endpoint - Analyzes case file and suggests document.
"""

from fastapi import APIRouter, HTTPException, Request
from loguru import logger

from app.models.requests import AnalyzeRequest
from app.models.responses import AnalyzeResponse
from app.agents.orchestration.analyzer_agent import AnalyzerAgent
from app.utils.exceptions import CaseFileNotFoundError

router = APIRouter()


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
            return AnalyzeResponse(
                success=True,
                has_suggestion=True,
                suggestion=result.suggestion,
                alternatives=result.alternatives,
                no_action_reason=None,
                case_context=context,
            )
        else:
            return AnalyzeResponse(
                success=True,
                has_suggestion=False,
                suggestion=None,
                alternatives=[],
                no_action_reason=result.no_action_reason,
                case_context=context,
            )

    except CaseFileNotFoundError as e:
        logger.warning(f"Case file not found: {case_file_id}")
        raise HTTPException(status_code=404, detail=e.message)

    except Exception as e:
        logger.error(f"Error analyzing case file {case_file_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
