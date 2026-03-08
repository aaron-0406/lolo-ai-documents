"""
Annexes endpoint - Get annex previews and thumbnails.
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from loguru import logger
from pydantic import BaseModel, Field

from app.services.annex_service import AnnexService

router = APIRouter()


class ThumbnailRequest(BaseModel):
    """Request to get thumbnails for annexes."""

    s3_keys: list[str] = Field(..., description="S3 keys of files to get thumbnails for")
    max_size: tuple[int, int] = Field(
        (200, 200),
        description="Maximum thumbnail size (width, height)"
    )


class ThumbnailResponse(BaseModel):
    """Response with annex thumbnails."""

    thumbnails: dict[str, Optional[str]] = Field(
        ...,
        description="Map of S3 key to base64 thumbnail (or null if failed)"
    )


class PresignedUrlRequest(BaseModel):
    """Request to get presigned URLs for annexes."""

    s3_keys: list[str] = Field(..., description="S3 keys of files")
    expiration: int = Field(3600, description="URL expiration in seconds")


class PresignedUrlResponse(BaseModel):
    """Response with presigned URLs."""

    urls: dict[str, Optional[str]] = Field(
        ...,
        description="Map of S3 key to presigned URL (or null if failed)"
    )


@router.post("/thumbnails", response_model=ThumbnailResponse)
async def get_thumbnails(
    request_body: ThumbnailRequest,
    request: Request,
) -> ThumbnailResponse:
    """
    Get thumbnails for multiple annexes.

    Converts PDFs to first-page thumbnails and resizes images.
    Returns base64-encoded PNG thumbnails.
    """
    logger.info(f"Getting thumbnails for {len(request_body.s3_keys)} files")

    try:
        s3 = request.app.state.s3
        annex_service = AnnexService(s3)

        thumbnails = {}
        for s3_key in request_body.s3_keys:
            try:
                thumbnail = await annex_service.generate_thumbnail(
                    s3_key,
                    max_size=request_body.max_size,
                )
                thumbnails[s3_key] = thumbnail
            except Exception as e:
                logger.warning(f"Failed to generate thumbnail for {s3_key}: {e}")
                thumbnails[s3_key] = None

        return ThumbnailResponse(thumbnails=thumbnails)

    except Exception as e:
        logger.error(f"Error getting thumbnails: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/presigned-urls", response_model=PresignedUrlResponse)
async def get_presigned_urls(
    request_body: PresignedUrlRequest,
    request: Request,
) -> PresignedUrlResponse:
    """
    Get presigned URLs for multiple annexes.

    Returns temporary URLs for direct file access.
    """
    logger.info(f"Getting presigned URLs for {len(request_body.s3_keys)} files")

    try:
        s3 = request.app.state.s3

        urls = {}
        for s3_key in request_body.s3_keys:
            try:
                url = await s3.generate_presigned_url(
                    s3_key,
                    expiration=request_body.expiration,
                )
                urls[s3_key] = url
            except Exception as e:
                logger.warning(f"Failed to generate presigned URL for {s3_key}: {e}")
                urls[s3_key] = None

        return PresignedUrlResponse(urls=urls)

    except Exception as e:
        logger.error(f"Error getting presigned URLs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/preview/{s3_key:path}")
async def get_annex_preview(
    s3_key: str,
    request: Request,
    width: int = 800,
    page: int = 1,
):
    """
    Get a preview image for a specific annex.

    For PDFs: Returns the specified page as an image.
    For images: Returns the resized image.

    Args:
        s3_key: S3 object key
        width: Target width for the preview
        page: Page number (1-indexed, for PDFs)
    """
    logger.info(f"Getting preview for {s3_key}, page {page}")

    try:
        s3 = request.app.state.s3
        annex_service = AnnexService(s3)

        # Download file
        file_data = await s3.download_file(s3_key)
        if not file_data:
            raise HTTPException(status_code=404, detail="File not found")

        file_type = s3_key.rsplit(".", 1)[-1].lower() if "." in s3_key else "unknown"

        if file_type == "pdf":
            # Convert specific page to image
            import fitz
            from PIL import Image
            import io

            doc = fitz.open(stream=file_data, filetype="pdf")

            if page > len(doc):
                page = len(doc)
            if page < 1:
                page = 1

            pdf_page = doc[page - 1]
            zoom = width / pdf_page.rect.width
            mat = fitz.Matrix(zoom, zoom)
            pix = pdf_page.get_pixmap(matrix=mat)
            img_bytes = pix.tobytes("png")
            doc.close()

            from fastapi.responses import Response
            return Response(
                content=img_bytes,
                media_type="image/png",
                headers={
                    "X-Total-Pages": str(len(doc)),
                    "X-Current-Page": str(page),
                }
            )

        elif file_type in ["jpg", "jpeg", "png", "gif", "webp"]:
            # Resize image
            from PIL import Image
            import io

            img = Image.open(io.BytesIO(file_data))

            # Calculate new height
            if img.width > width:
                aspect = img.height / img.width
                new_height = int(width * aspect)
                img = img.resize((width, new_height), Image.Resampling.LANCZOS)

            buffer = io.BytesIO()
            img.save(buffer, format="PNG")
            buffer.seek(0)

            from fastapi.responses import Response
            return Response(
                content=buffer.getvalue(),
                media_type="image/png",
            )

        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type: {file_type}"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting preview: {e}")
        raise HTTPException(status_code=500, detail=str(e))
