"""
Finalize endpoint - Generates final DOCX document with annexes.

NOTE: Session management is handled by lolo-backend (MySQL).
This microservice reads session data from MySQL to generate the DOCX.
"""

import base64
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
from loguru import logger

from app.models.requests import FinalizeRequest
from app.models.responses import FinalizeResponse
from app.models.schemas import AnnexInfo, AnnexSource, BinnacleSuggestion, CaseContext
from app.services.annex_service import AnnexService
from app.services.docx_service import DocxService

router = APIRouter()


@router.post("/finalize/{case_file_id}", response_model=FinalizeResponse)
async def finalize_document(
    case_file_id: int,
    request_body: FinalizeRequest,
    request: Request,
) -> FinalizeResponse:
    """
    PASO 4: Finalize and generate DOCX.

    This endpoint:
    - Retrieves the final draft from MySQL session
    - Generates a properly formatted DOCX file
    - Suggests binnacle entry data
    - Marks session as completed
    - Returns the document as base64

    Args:
        case_file_id: ID of the JUDICIAL_CASE_FILE
        request_body: Finalization parameters (session_id)
        request: FastAPI request object

    Returns:
        FinalizeResponse with DOCX base64 and binnacle suggestion
    """
    logger.info(f"Finalizing document for case {case_file_id}, session {request_body.session_id}")

    try:
        # Get MySQL service
        mysql = request.app.state.mysql

        # Retrieve session from MySQL
        session = await mysql.get_ai_session(request_body.session_id)
        if not session:
            raise HTTPException(
                status_code=404,
                detail=f"Session not found or expired: {request_body.session_id}",
            )

        # Verify session belongs to this case file
        if session["case_file_id"] != case_file_id:
            raise HTTPException(
                status_code=400,
                detail="Session does not match case file",
            )

        # Get data from session
        current_draft = session.get("current_draft", "")
        document_type = session.get("document_type", "documento")
        case_context = session.get("case_context", {})

        # Build CaseContext for DOCX generation
        context = CaseContext(
            case_file_id=case_context.get("case_file_id", case_file_id),
            case_number=case_context.get("case_number", ""),
            client_id=case_context.get("client_id", 0),
            client_name=case_context.get("client_name", ""),
            client_dni_ruc=case_context.get("client_dni_ruc"),
            court_name=case_context.get("court"),
            subject=case_context.get("subject"),
            procedural_way=case_context.get("procedural_way"),
            process_status=case_context.get("process_status"),
            current_stage=case_context.get("current_stage"),
            binnacles=case_context.get("binnacles", []),
            collaterals=case_context.get("collaterals", []),
            bank_name=case_context.get("bank_name"),
        )

        # Process selected annexes if provided
        processed_annexes = []
        annex_count = 0

        if request_body.selected_annexes and request_body.selected_annexes.annex_ids:
            try:
                s3 = request.app.state.s3
                annex_service = AnnexService(s3)

                # Reconstruct AnnexInfo from passed data
                annexes = []
                if request_body.suggested_annexes:
                    for annex_data in request_body.suggested_annexes:
                        try:
                            annexes.append(AnnexInfo(
                                id=annex_data.get("id", ""),
                                file_id=annex_data.get("file_id", 0),
                                name=annex_data.get("name", ""),
                                original_name=annex_data.get("original_name", ""),
                                file_type=annex_data.get("file_type", ""),
                                s3_key=annex_data.get("s3_key", ""),
                                source=AnnexSource(annex_data.get("source", "judicial_binnacle")),
                            ))
                        except Exception as e:
                            logger.warning(f"Failed to parse annex data: {e}")

                # Get annexes in custom order if provided
                annex_ids = request_body.selected_annexes.custom_order or request_body.selected_annexes.annex_ids

                # Process annexes (download + convert to images)
                processed_annexes = await annex_service.process_annexes_for_embedding(
                    annex_ids=annex_ids,
                    annexes=annexes,
                    max_pages_per_pdf=5,
                    image_width=1200,
                )
                annex_count = len(processed_annexes)
                logger.info(f"Processed {annex_count} annexes for embedding")

            except Exception as e:
                logger.error(f"Failed to process annexes: {e}")
                # Continue without annexes - document generation should not fail

        # Generate DOCX (with or without annexes)
        docx_service = DocxService()

        if processed_annexes:
            docx_bytes = await docx_service.generate_with_annexes(
                draft=current_draft,
                document_type=document_type,
                context=context,
                annexes=processed_annexes,
            )
        else:
            docx_bytes = await docx_service.generate(
                draft=current_draft,
                document_type=document_type,
                context=context,
            )

        # Generate filename
        case_number = context.case_number.replace("/", "-").replace("\\", "-")
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"{document_type}_{case_number}_{timestamp}.docx"

        # Create binnacle suggestion
        annex_text = f" con {annex_count} anexos adjuntos" if annex_count > 0 else ""
        binnacle_suggestion = BinnacleSuggestion(
            date=datetime.utcnow().strftime("%Y-%m-%d"),
            binnacle_type_id=None,  # To be filled by frontend
            binnacle_type_name="ESCRITO",
            procedural_stage_id=None,  # To be filled by frontend
            procedural_stage_name=context.current_stage or "En trámite",
            description=f"Se presenta {document_type.replace('_', ' ').title()} "
                        f"generado con asistencia de IA{annex_text}.",
        )

        # Mark session as completed in MySQL
        await mysql.complete_ai_session(request_body.session_id)

        logger.info(f"Finalized document: {filename} with {annex_count} annexes")

        return FinalizeResponse(
            success=True,
            document_base64=base64.b64encode(docx_bytes).decode("utf-8"),
            filename=filename,
            file_size_bytes=len(docx_bytes),
            binnacle_suggestion=binnacle_suggestion,
            annex_count=annex_count,
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.error(f"Error finalizing document: {e}")
        raise HTTPException(status_code=500, detail=str(e))
