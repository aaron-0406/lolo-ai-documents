"""
Context Cache Service - Manages caching of extracted document content.

Two-level caching:
1. Per-file: JUDICIAL_BIN_FILE_EXTRACTED_CONTENT
2. Per-case: JUDICIAL_CASE_FILE_AI_CONTEXT
"""

import json
from datetime import datetime
from typing import Any, Optional

from loguru import logger

from app.services.mysql_service import MySQLService
from app.services.s3_service import S3Service
from app.services.file_extraction_service import (
    FileExtractionService,
    ExtractionResult,
    get_file_extraction_service,
)


class CachedFileContent:
    """Cached content for a single file."""

    def __init__(
        self,
        file_id: int,
        file_hash: str,
        file_type: str,
        extracted_text: str,
        extracted_images: list[dict],
        page_count: int,
        image_count: int,
        tokens_estimated: int,
        binnacle_date: Optional[datetime] = None,
        binnacle_type: Optional[str] = None,
        original_name: Optional[str] = None,
    ):
        self.file_id = file_id
        self.file_hash = file_hash
        self.file_type = file_type
        self.extracted_text = extracted_text
        self.extracted_images = extracted_images
        self.page_count = page_count
        self.image_count = image_count
        self.tokens_estimated = tokens_estimated
        self.binnacle_date = binnacle_date
        self.binnacle_type = binnacle_type
        self.original_name = original_name


class ContextCacheService:
    """
    Service for caching extracted document context.

    Flow:
    1. Check if file content is already cached
    2. If cached and hash matches, return cached content
    3. If not cached or hash changed, extract and cache
    4. Aggregate per-case context when needed
    """

    def __init__(
        self,
        mysql_service: MySQLService,
        s3_service: S3Service,
        extraction_service: Optional[FileExtractionService] = None,
    ):
        self.mysql = mysql_service
        self.s3 = s3_service
        self.extraction = extraction_service or get_file_extraction_service()

    async def get_file_cached_content(
        self,
        file_id: int,
    ) -> Optional[CachedFileContent]:
        """
        Get cached content for a file if it exists.

        Args:
            file_id: ID of the JUDICIAL_BIN_FILE

        Returns:
            CachedFileContent or None if not cached
        """
        if not self.mysql._pool:
            return None

        async with self.mysql._pool.acquire() as conn:
            async with conn.cursor() as cur:
                query = """
                    SELECT
                        ec.id_judicial_bin_file_extracted_content,
                        ec.file_hash,
                        ec.file_type,
                        ec.extracted_text,
                        ec.extracted_images,
                        ec.extraction_status,
                        ec.page_count,
                        ec.image_count,
                        ec.tokens_estimated
                    FROM JUDICIAL_BIN_FILE_EXTRACTED_CONTENT ec
                    WHERE ec.judicial_bin_file_id_judicial_bin_file = %s
                    AND ec.extraction_status = 'completed'
                """
                await cur.execute(query, (file_id,))
                result = await cur.fetchone()

                if result:
                    images = result[4]
                    if isinstance(images, str):
                        images = json.loads(images)

                    return CachedFileContent(
                        file_id=file_id,
                        file_hash=result[1],
                        file_type=result[2],
                        extracted_text=result[3] or "",
                        extracted_images=images or [],
                        page_count=result[6] or 0,
                        image_count=result[7] or 0,
                        tokens_estimated=result[8] or 0,
                    )

                return None

    async def cache_file_content(
        self,
        file_id: int,
        file_hash: str,
        file_type: str,
        result: ExtractionResult,
    ) -> bool:
        """
        Cache extracted content for a file.

        Args:
            file_id: ID of the JUDICIAL_BIN_FILE
            file_hash: SHA256 hash of the file
            file_type: Type of file (pdf, docx, xlsx, image)
            result: Extraction result to cache

        Returns:
            True if cached successfully
        """
        if not self.mysql._pool:
            return False

        async with self.mysql._pool.acquire() as conn:
            async with conn.cursor() as cur:
                # Check if record exists
                await cur.execute(
                    "SELECT id_judicial_bin_file_extracted_content "
                    "FROM JUDICIAL_BIN_FILE_EXTRACTED_CONTENT "
                    "WHERE judicial_bin_file_id_judicial_bin_file = %s",
                    (file_id,)
                )
                existing = await cur.fetchone()

                images_json = json.dumps(result.images) if result.images else None

                if existing:
                    # Update existing record
                    query = """
                        UPDATE JUDICIAL_BIN_FILE_EXTRACTED_CONTENT
                        SET file_hash = %s,
                            file_type = %s,
                            extracted_text = %s,
                            extracted_images = %s,
                            extraction_status = %s,
                            extraction_error = %s,
                            page_count = %s,
                            image_count = %s,
                            tokens_estimated = %s,
                            updated_at = NOW()
                        WHERE judicial_bin_file_id_judicial_bin_file = %s
                    """
                    await cur.execute(query, (
                        file_hash,
                        file_type,
                        result.text,
                        images_json,
                        "completed" if result.success else "failed",
                        result.error,
                        result.page_count,
                        result.image_count,
                        result.tokens_estimated,
                        file_id,
                    ))
                else:
                    # Insert new record
                    query = """
                        INSERT INTO JUDICIAL_BIN_FILE_EXTRACTED_CONTENT (
                            judicial_bin_file_id_judicial_bin_file,
                            file_hash,
                            file_type,
                            extracted_text,
                            extracted_images,
                            extraction_status,
                            extraction_error,
                            page_count,
                            image_count,
                            tokens_estimated,
                            created_at,
                            updated_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                    """
                    await cur.execute(query, (
                        file_id,
                        file_hash,
                        file_type,
                        result.text,
                        images_json,
                        "completed" if result.success else "failed",
                        result.error,
                        result.page_count,
                        result.image_count,
                        result.tokens_estimated,
                    ))

                await conn.commit()
                return True

    async def get_or_extract_file_content(
        self,
        file_info: dict,
        max_pages: int = 10,
        max_images: int = 5,
        analyze_images: bool = True,
    ) -> Optional[CachedFileContent]:
        """
        Get cached content or extract and cache if not available.

        Args:
            file_info: File metadata from MySQL (must include s3_key, id, original_name)
            max_pages: Max pages to extract
            max_images: Max images to analyze
            analyze_images: Whether to analyze images with Claude Vision

        Returns:
            CachedFileContent or None if extraction failed
        """
        file_id = file_info.get("id")
        s3_key = file_info.get("s3_key")
        original_name = file_info.get("original_name", "unknown")

        if not file_id or not s3_key:
            logger.warning(f"Invalid file info: {file_info}")
            return None

        # Check cache first
        cached = await self.get_file_cached_content(file_id)

        # Download file to check hash
        file_bytes = await self.s3.get_file(s3_key)
        if not file_bytes:
            logger.warning(f"Could not download file from S3: {s3_key}")
            return cached  # Return cached if available, even if can't verify

        current_hash = self.extraction.get_file_hash(file_bytes)

        # If cached and hash matches, return cached
        if cached and cached.file_hash == current_hash:
            logger.debug(f"Using cached content for file {file_id}")
            cached.binnacle_date = file_info.get("binnacle_date")
            cached.binnacle_type = file_info.get("binnacle_type")
            cached.original_name = original_name
            return cached

        # Need to extract
        logger.info(f"Extracting content for file {file_id}: {original_name}")
        file_type = self.extraction.detect_file_type(original_name, file_bytes)

        result = await self.extraction.extract(
            content=file_bytes,
            filename=original_name,
            max_pages=max_pages,
            max_images=max_images,
            analyze_images=analyze_images,
        )

        if result.success:
            # Cache the result
            await self.cache_file_content(file_id, current_hash, file_type, result)

            return CachedFileContent(
                file_id=file_id,
                file_hash=current_hash,
                file_type=file_type,
                extracted_text=result.text,
                extracted_images=result.images,
                page_count=result.page_count,
                image_count=result.image_count,
                tokens_estimated=result.tokens_estimated,
                binnacle_date=file_info.get("binnacle_date"),
                binnacle_type=file_info.get("binnacle_type"),
                original_name=original_name,
            )

        logger.error(f"Extraction failed for {original_name}: {result.error}")
        return None

    async def get_case_context(
        self,
        case_file_id: int,
    ) -> Optional[dict]:
        """
        Get cached case-level context if available.

        Args:
            case_file_id: ID of the JUDICIAL_CASE_FILE

        Returns:
            Cached context dict or None
        """
        if not self.mysql._pool:
            return None

        async with self.mysql._pool.acquire() as conn:
            async with conn.cursor() as cur:
                query = """
                    SELECT
                        context_summary,
                        key_facts,
                        key_dates,
                        parties_info,
                        amounts_info,
                        legal_references,
                        total_documents_analyzed,
                        total_pages_analyzed,
                        total_images_analyzed,
                        last_document_date,
                        last_binnacle_id,
                        context_version
                    FROM JUDICIAL_CASE_FILE_AI_CONTEXT
                    WHERE judicial_case_file_id_judicial_case_file = %s
                """
                await cur.execute(query, (case_file_id,))
                result = await cur.fetchone()

                if result:
                    return {
                        "context_summary": result[0],
                        "key_facts": json.loads(result[1]) if result[1] else [],
                        "key_dates": json.loads(result[2]) if result[2] else [],
                        "parties_info": json.loads(result[3]) if result[3] else [],
                        "amounts_info": json.loads(result[4]) if result[4] else [],
                        "legal_references": json.loads(result[5]) if result[5] else [],
                        "total_documents_analyzed": result[6],
                        "total_pages_analyzed": result[7],
                        "total_images_analyzed": result[8],
                        "last_document_date": result[9],
                        "last_binnacle_id": result[10],
                        "context_version": result[11],
                    }

                return None

    async def update_case_context(
        self,
        case_file_id: int,
        context_data: dict,
    ) -> bool:
        """
        Update or create case-level context.

        Args:
            case_file_id: ID of the JUDICIAL_CASE_FILE
            context_data: Context data to store

        Returns:
            True if updated successfully
        """
        if not self.mysql._pool:
            return False

        async with self.mysql._pool.acquire() as conn:
            async with conn.cursor() as cur:
                # Check if exists
                await cur.execute(
                    "SELECT id_judicial_case_file_ai_context, context_version "
                    "FROM JUDICIAL_CASE_FILE_AI_CONTEXT "
                    "WHERE judicial_case_file_id_judicial_case_file = %s",
                    (case_file_id,)
                )
                existing = await cur.fetchone()

                if existing:
                    new_version = (existing[1] or 0) + 1
                    query = """
                        UPDATE JUDICIAL_CASE_FILE_AI_CONTEXT
                        SET context_summary = %s,
                            key_facts = %s,
                            key_dates = %s,
                            parties_info = %s,
                            amounts_info = %s,
                            legal_references = %s,
                            total_documents_analyzed = %s,
                            total_pages_analyzed = %s,
                            total_images_analyzed = %s,
                            last_document_date = %s,
                            last_binnacle_id = %s,
                            context_version = %s,
                            tokens_total = %s,
                            updated_at = NOW()
                        WHERE judicial_case_file_id_judicial_case_file = %s
                    """
                    await cur.execute(query, (
                        context_data.get("context_summary"),
                        json.dumps(context_data.get("key_facts", [])),
                        json.dumps(context_data.get("key_dates", [])),
                        json.dumps(context_data.get("parties_info", [])),
                        json.dumps(context_data.get("amounts_info", [])),
                        json.dumps(context_data.get("legal_references", [])),
                        context_data.get("total_documents_analyzed", 0),
                        context_data.get("total_pages_analyzed", 0),
                        context_data.get("total_images_analyzed", 0),
                        context_data.get("last_document_date"),
                        context_data.get("last_binnacle_id"),
                        new_version,
                        context_data.get("tokens_total", 0),
                        case_file_id,
                    ))
                else:
                    query = """
                        INSERT INTO JUDICIAL_CASE_FILE_AI_CONTEXT (
                            judicial_case_file_id_judicial_case_file,
                            context_summary,
                            key_facts,
                            key_dates,
                            parties_info,
                            amounts_info,
                            legal_references,
                            total_documents_analyzed,
                            total_pages_analyzed,
                            total_images_analyzed,
                            last_document_date,
                            last_binnacle_id,
                            context_version,
                            tokens_total,
                            created_at,
                            updated_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1, %s, NOW(), NOW())
                    """
                    await cur.execute(query, (
                        case_file_id,
                        context_data.get("context_summary"),
                        json.dumps(context_data.get("key_facts", [])),
                        json.dumps(context_data.get("key_dates", [])),
                        json.dumps(context_data.get("parties_info", [])),
                        json.dumps(context_data.get("amounts_info", [])),
                        json.dumps(context_data.get("legal_references", [])),
                        context_data.get("total_documents_analyzed", 0),
                        context_data.get("total_pages_analyzed", 0),
                        context_data.get("total_images_analyzed", 0),
                        context_data.get("last_document_date"),
                        context_data.get("last_binnacle_id"),
                        context_data.get("tokens_total", 0),
                    ))

                await conn.commit()
                return True

    async def needs_reindexing(
        self,
        case_file_id: int,
        latest_binnacle_id: Optional[int] = None,
    ) -> bool:
        """
        Check if case context needs to be re-indexed.

        Args:
            case_file_id: ID of the case file
            latest_binnacle_id: ID of the latest binnacle

        Returns:
            True if re-indexing is needed
        """
        cached_context = await self.get_case_context(case_file_id)

        if not cached_context:
            return True

        if latest_binnacle_id and cached_context.get("last_binnacle_id"):
            return latest_binnacle_id > cached_context["last_binnacle_id"]

        return False


# Singleton instance
_context_cache_service: Optional[ContextCacheService] = None


def get_context_cache_service(
    mysql_service: MySQLService,
    s3_service: S3Service,
) -> ContextCacheService:
    """Get or create the context cache service instance."""
    global _context_cache_service
    if _context_cache_service is None:
        _context_cache_service = ContextCacheService(mysql_service, s3_service)
    return _context_cache_service
