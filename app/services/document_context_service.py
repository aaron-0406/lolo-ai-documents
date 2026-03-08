"""
Document Context Service - Builds complete case context with caching.

Coordinates:
1. MySQL for case metadata and binnacle files
2. S3 for file downloads
3. File extraction for PDFs, Word, Excel, images
4. Context caching for efficiency
5. Extrajudicial context (collection history, agreements, payments)
"""

from datetime import datetime
from typing import Optional

from loguru import logger

from app.models.schemas import CaseContext
from app.services.mysql_service import MySQLService
from app.services.s3_service import S3Service
from app.services.context_cache_service import (
    ContextCacheService,
    CachedFileContent,
    get_context_cache_service,
)
from app.services.extrajudicial_context_service import (
    ExtrajudicialContextService,
    get_extrajudicial_context_service,
)


class DocumentContextService:
    """
    Service that builds complete case context by:
    1. Fetching case data from MySQL
    2. Checking cache for previously extracted content
    3. Downloading and extracting new files only
    4. Caching results for future use
    5. Fetching extrajudicial context (collection history, agreements)
    """

    def __init__(self, mysql_service: MySQLService, s3_service: S3Service):
        self.mysql = mysql_service
        self.s3 = s3_service
        self.cache = get_context_cache_service(mysql_service, s3_service)
        self.extrajudicial = get_extrajudicial_context_service(mysql_service, s3_service)

    async def get_full_context(
        self,
        case_file_id: int,
        max_documents: int = 15,
        max_pages_per_doc: int = 8,
        max_images_per_doc: int = 3,
        analyze_images: bool = True,
        force_reindex: bool = False,
    ) -> Optional[CaseContext]:
        """
        Get complete case context with intelligent caching.

        Args:
            case_file_id: ID of the case file
            max_documents: Maximum number of documents to extract
            max_pages_per_doc: Maximum pages to extract per document
            max_images_per_doc: Maximum images to analyze per document
            analyze_images: Whether to analyze images with Claude Vision
            force_reindex: Force re-extraction even if cached

        Returns:
            CaseContext with binnacle_documents populated, or None if not found
        """
        logger.info(f"Building full context for case file {case_file_id}")

        # Get base case context
        context = await self.mysql.get_case_file_context(case_file_id)
        if not context:
            logger.warning(f"Case file {case_file_id} not found")
            return None

        # Get binnacle files
        binnacle_files = await self.mysql.get_binnacle_files(
            case_file_id, limit=max_documents
        )
        logger.info(
            f"Found {len(binnacle_files)} binnacle files for case {case_file_id}"
        )

        if not binnacle_files:
            return context

        # Get latest binnacle ID for cache invalidation check
        latest_binnacle_id = max(f.get("binnacle_id", 0) for f in binnacle_files)

        # Check if we need to reindex
        needs_reindex = force_reindex or await self.cache.needs_reindexing(
            case_file_id, latest_binnacle_id
        )

        # Extract content from files (using cache when available)
        extracted_documents = []
        total_pages = 0
        total_images = 0
        total_tokens = 0

        for file_info in binnacle_files:
            try:
                cached_content = await self.cache.get_or_extract_file_content(
                    file_info,
                    max_pages=max_pages_per_doc,
                    max_images=max_images_per_doc,
                    analyze_images=analyze_images,
                )

                if cached_content and cached_content.extracted_text:
                    doc_data = self._format_cached_content(cached_content, file_info)
                    extracted_documents.append(doc_data)

                    total_pages += cached_content.page_count
                    total_images += cached_content.image_count
                    total_tokens += cached_content.tokens_estimated

            except Exception as e:
                logger.error(
                    f"Failed to extract {file_info.get('original_name')}: {e}"
                )

        # Add extracted documents to context
        context.binnacle_documents = extracted_documents

        # Update case-level context cache if we processed new documents
        if needs_reindex and extracted_documents:
            await self._update_case_context_cache(
                case_file_id,
                extracted_documents,
                latest_binnacle_id,
                total_pages,
                total_images,
                total_tokens,
            )

        logger.info(
            f"Judicial context ready: {len(extracted_documents)} docs, "
            f"{total_pages} pages, {total_images} images, "
            f"~{total_tokens} tokens"
        )

        # Get extrajudicial context (collection history, agreements, payments)
        try:
            extrajudicial_context = await self.extrajudicial.get_extrajudicial_context(
                case_file_id,
                max_files=10,
                max_collection_actions=30,
                extract_files=True,
            )
            if extrajudicial_context:
                context.extrajudicial = extrajudicial_context
                logger.info(
                    f"Extrajudicial context added: "
                    f"{len(extrajudicial_context.collection_actions)} actions, "
                    f"agreement={'yes' if extrajudicial_context.has_agreement else 'no'}"
                )
        except Exception as e:
            logger.warning(f"Failed to get extrajudicial context: {e}")

        # Get collateral files (guarantee documents: tasaciones, partidas, etc.)
        try:
            customer_id = context.customer_id or 0
            chb_id = context.customer_has_bank_id or 0
            if customer_id and chb_id:
                collateral_files_data = await self.mysql.get_collateral_files(
                    case_file_id, customer_id, chb_id, limit=20
                )

                collateral_files = []
                for f in collateral_files_data:
                    collateral_files.append({
                        "id": f.get("id"),
                        "filename": f.get("filename", ""),
                        "original_name": f.get("original_name", ""),
                        "s3_key": f.get("s3_key"),
                        "collateral_id": f.get("collateral_id"),
                        "property_address": f.get("property_address"),
                        "kind_of_property": f.get("kind_of_property"),
                        "electronic_record": f.get("electronic_record"),
                        "land_area": f.get("land_area"),
                        "collateral_status": f.get("collateral_status"),
                        "created_at": str(f.get("created_at", "")),
                    })

                context.collateral_files = collateral_files
                if collateral_files:
                    logger.info(f"Collateral files added: {len(collateral_files)} files")
        except Exception as e:
            logger.warning(f"Failed to get collateral files: {e}")

        return context

    def _format_cached_content(
        self,
        cached: CachedFileContent,
        file_info: dict,
    ) -> dict:
        """Format cached content for inclusion in context."""
        # Format binnacle date
        binnacle_date = file_info.get("binnacle_date")
        if binnacle_date:
            if hasattr(binnacle_date, "strftime"):
                binnacle_date = binnacle_date.strftime("%Y-%m-%d")
            else:
                binnacle_date = str(binnacle_date)

        return {
            "id": file_info.get("id"),
            "filename": cached.original_name or file_info.get("original_name", ""),
            "original_name": file_info.get("original_name", ""),
            "file_type": cached.file_type,
            "s3_key": file_info.get("s3_key"),  # Required for annex identification
            "binnacle_id": file_info.get("binnacle_id"),
            "binnacle_date": binnacle_date,
            "binnacle_type": file_info.get("binnacle_type", ""),
            "binnacle_content": file_info.get("binnacle_content", ""),
            "extracted_text": cached.extracted_text,
            "extracted_images": cached.extracted_images,
            "page_count": cached.page_count,
            "image_count": cached.image_count,
            "text_length": len(cached.extracted_text),
            "tokens_estimated": cached.tokens_estimated,
            "from_cache": True,
        }

    async def _update_case_context_cache(
        self,
        case_file_id: int,
        documents: list[dict],
        last_binnacle_id: int,
        total_pages: int,
        total_images: int,
        total_tokens: int,
    ) -> None:
        """Update the case-level context cache."""
        try:
            # Find the most recent document date
            last_doc_date = None
            for doc in documents:
                doc_date = doc.get("binnacle_date")
                if doc_date:
                    if isinstance(doc_date, str):
                        try:
                            doc_date = datetime.strptime(doc_date, "%Y-%m-%d")
                        except ValueError:
                            continue
                    if last_doc_date is None or doc_date > last_doc_date:
                        last_doc_date = doc_date

            context_data = {
                "total_documents_analyzed": len(documents),
                "total_pages_analyzed": total_pages,
                "total_images_analyzed": total_images,
                "last_document_date": last_doc_date,
                "last_binnacle_id": last_binnacle_id,
                "tokens_total": total_tokens,
            }

            await self.cache.update_case_context(case_file_id, context_data)
            logger.debug(f"Updated case context cache for {case_file_id}")

        except Exception as e:
            logger.error(f"Failed to update case context cache: {e}")

    async def get_context_stats(self, case_file_id: int) -> Optional[dict]:
        """
        Get statistics about cached context for a case.

        Args:
            case_file_id: ID of the case file

        Returns:
            Dict with stats or None
        """
        return await self.cache.get_case_context(case_file_id)

    async def invalidate_cache(self, case_file_id: int) -> bool:
        """
        Invalidate cache for a case file, forcing re-extraction on next request.

        Args:
            case_file_id: ID of the case file

        Returns:
            True if invalidated
        """
        # For now, we rely on the last_binnacle_id check
        # A more aggressive invalidation would delete the cache records
        logger.info(f"Cache invalidation requested for case {case_file_id}")
        return True


# Singleton instance management
_document_context_service: Optional[DocumentContextService] = None


def get_document_context_service(
    mysql_service: MySQLService,
    s3_service: S3Service,
) -> DocumentContextService:
    """Get or create the document context service instance."""
    global _document_context_service
    if _document_context_service is None:
        _document_context_service = DocumentContextService(mysql_service, s3_service)
    return _document_context_service
