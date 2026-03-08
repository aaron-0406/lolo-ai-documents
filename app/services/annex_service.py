"""
AnnexService - Handles identification, fetching, and processing of document annexes.
"""

import base64
import io
import uuid
from typing import Optional

import fitz  # PyMuPDF
from loguru import logger
from PIL import Image

# Register HEIF/HEIC support with Pillow (for iPhone photos)
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    logger.warning("pillow-heif not installed, HEIC/HEIF support disabled")

from app.config import settings
from app.models.schemas import (
    AnnexInfo,
    AnnexSource,
    CaseContext,
    ProcessedAnnex,
)
from app.services.s3_service import S3Service


class AnnexService:
    """
    Service for handling document annexes (attachments).

    Responsibilities:
    - Identify relevant annexes based on document type and context
    - Generate preview URLs and thumbnails
    - Download and convert files (PDF to images)
    - Process annexes for embedding in final document
    """

    # Document types and their typically relevant annexes
    DOCUMENT_ANNEX_MAPPING = {
        # Execution documents need payment docs and titles
        "demanda_ejecutiva": [
            "pagare", "letra", "liquidacion", "estado_cuenta", "contrato", "titulo"
        ],
        "demanda_ejecucion_garantias": [
            "hipoteca", "tasacion", "partida_registral", "liquidacion", "titulo"
        ],
        "demanda_odsd": [
            "contrato", "liquidacion", "estado_cuenta", "requerimiento"
        ],
        # Appeals need prior resolutions and notifications
        "recurso_apelacion": [
            "resolucion", "notificacion", "sentencia", "auto"
        ],
        "recurso_casacion": [
            "sentencia", "resolucion", "auto"
        ],
        "recurso_queja": [
            "resolucion", "denegatoria", "auto"
        ],
        # Civil litigation
        "demanda_accion_pauliana": [
            "titulo", "partida_registral", "contrato", "liquidacion"
        ],
        "demanda_nulidad_acto": [
            "escritura", "contrato", "partida_registral"
        ],
        # Default for others
        "default": [
            "titulo", "contrato", "liquidacion", "resolucion"
        ],
    }

    # Keywords to identify annex types from filenames
    ANNEX_KEYWORDS = {
        "pagare": ["pagare", "pagaré", "titulo_valor"],
        "letra": ["letra", "cambio"],
        "liquidacion": ["liquidacion", "liquidación", "estado_deuda"],
        "estado_cuenta": ["estado_cuenta", "extracto", "saldo"],
        "contrato": ["contrato", "acuerdo", "convenio"],
        "titulo": ["titulo", "título", "pagare", "letra"],
        "hipoteca": ["hipoteca", "garantia", "garantía"],
        "tasacion": ["tasacion", "tasación", "avaluo", "avalúo", "valuacion"],
        "partida_registral": ["partida", "registral", "sunarp", "registro"],
        "resolucion": ["resolucion", "resolución", "auto"],
        "notificacion": ["notificacion", "notificación", "cedula", "cédula"],
        "sentencia": ["sentencia", "fallo"],
        "escritura": ["escritura", "publica", "pública"],
        "voucher": ["voucher", "comprobante", "pago", "recibo", "deposito"],
        "requerimiento": ["requerimiento", "carta_notarial", "notarial"],
    }

    def __init__(self, s3_service: S3Service):
        self.s3 = s3_service
        self._thumbnail_cache: dict[str, str] = {}

    async def identify_relevant_annexes(
        self,
        document_type: str,
        context: CaseContext,
    ) -> list[AnnexInfo]:
        """
        Identify and return relevant annexes for a document type.

        Analyzes files from:
        - Judicial binnacle documents
        - Judicial collateral files (tasaciones, partidas, etc.)
        - Extrajudicial client files
        - Payment vouchers

        Returns ranked list of relevant annexes with metadata.
        """
        logger.info(f"Identifying relevant annexes for document: {document_type}")

        all_annexes: list[AnnexInfo] = []

        # Get relevant keywords for this document type
        relevant_types = self.DOCUMENT_ANNEX_MAPPING.get(
            document_type,
            self.DOCUMENT_ANNEX_MAPPING["default"]
        )

        # 1. Process judicial binnacle documents
        if context.binnacle_documents:
            for doc in context.binnacle_documents:
                annex = self._create_annex_from_binnacle_doc(doc, relevant_types)
                if annex:
                    all_annexes.append(annex)

        # 2. Process judicial collateral files (tasaciones, partidas registrales, etc.)
        if context.collateral_files:
            for file_info in context.collateral_files:
                annex = self._create_annex_from_collateral_file(file_info, relevant_types)
                if annex:
                    all_annexes.append(annex)

        # 3. Process extrajudicial client files
        if context.extrajudicial and context.extrajudicial.client_files:
            for file_info in context.extrajudicial.client_files:
                annex = self._create_annex_from_client_file(file_info, relevant_types)
                if annex:
                    all_annexes.append(annex)

        # 4. Process payment vouchers
        if context.extrajudicial and context.extrajudicial.payment_vouchers:
            for voucher in context.extrajudicial.payment_vouchers:
                annex = self._create_annex_from_payment_voucher(voucher, relevant_types)
                if annex:
                    all_annexes.append(annex)

        # Sort by relevance (relevant types first, then by date)
        all_annexes = self._sort_by_relevance(all_annexes, relevant_types)

        # Generate preview URLs for top annexes
        for annex in all_annexes[:20]:  # Limit to 20 for performance
            try:
                annex.preview_url = await self.s3.generate_presigned_url(
                    annex.s3_key,
                    expiration=3600  # 1 hour
                )
            except Exception as e:
                logger.warning(f"Failed to generate preview URL for {annex.s3_key}: {e}")

        logger.info(f"Found {len(all_annexes)} relevant annexes")
        return all_annexes

    def _create_annex_from_binnacle_doc(
        self,
        doc: dict,
        relevant_types: list[str],
    ) -> Optional[AnnexInfo]:
        """Create AnnexInfo from a binnacle document."""
        s3_key = doc.get("s3_key") or doc.get("file_path")
        if not s3_key:
            return None

        filename = doc.get("original_name") or doc.get("filename") or s3_key.split("/")[-1]
        file_type = self._get_file_type(filename)

        # Only include images and PDFs
        if file_type not in self.SUPPORTED_FILE_TYPES:
            return None

        relevance = self._calculate_relevance(filename, relevant_types)

        return AnnexInfo(
            id=f"binnacle_{doc.get('id', uuid.uuid4().hex[:8])}",
            file_id=doc.get("id") or 0,
            name=self._generate_display_name(filename),
            original_name=filename,
            file_type=file_type,
            s3_key=s3_key,
            source=AnnexSource.JUDICIAL_BINNACLE,
            relevance_reason=relevance["reason"] if relevance["score"] > 0 else None,
            created_at=self._format_date(doc.get("binnacle_date") or doc.get("date") or doc.get("created_at")),
        )

    # Supported image and document types for annexes
    SUPPORTED_FILE_TYPES = ["pdf", "jpg", "jpeg", "png", "gif", "webp", "bmp", "tiff", "tif", "heic", "heif"]

    def _create_annex_from_client_file(
        self,
        file_info: dict,
        relevant_types: list[str],
    ) -> Optional[AnnexInfo]:
        """Create AnnexInfo from a client file."""
        s3_key = file_info.get("s3_key")
        if not s3_key:
            return None

        filename = file_info.get("original_name") or file_info.get("name") or s3_key.split("/")[-1]
        file_type = self._get_file_type(filename)

        # Only include images and PDFs
        if file_type not in self.SUPPORTED_FILE_TYPES:
            return None

        relevance = self._calculate_relevance(filename, relevant_types)

        return AnnexInfo(
            id=f"client_{file_info.get('id', uuid.uuid4().hex[:8])}",
            file_id=file_info.get("id") or 0,
            name=self._generate_display_name(filename),
            original_name=filename,
            file_type=file_type,
            s3_key=s3_key,
            source=AnnexSource.EXTRAJUDICIAL_CLIENT,
            relevance_reason=relevance["reason"] if relevance["score"] > 0 else None,
            created_at=self._format_date(file_info.get("created_at")),
        )

    def _create_annex_from_payment_voucher(
        self,
        voucher: dict,
        relevant_types: list[str],
    ) -> Optional[AnnexInfo]:
        """Create AnnexInfo from a payment voucher."""
        s3_key = voucher.get("s3_key")
        if not s3_key:
            return None

        filename = voucher.get("original_name") or voucher.get("name") or s3_key.split("/")[-1]
        file_type = self._get_file_type(filename)

        # Only include images and PDFs
        if file_type not in self.SUPPORTED_FILE_TYPES:
            return None

        payment_date = voucher.get("payment_date", "")
        payment_amount = voucher.get("payment_amount", 0)

        return AnnexInfo(
            id=f"voucher_{voucher.get('id', uuid.uuid4().hex[:8])}",
            file_id=voucher.get("id") or 0,
            name=f"Voucher de pago - {payment_date}" if payment_date else self._generate_display_name(filename),
            original_name=filename,
            file_type=file_type,
            s3_key=s3_key,
            source=AnnexSource.EXTRAJUDICIAL_PAYMENT,
            relevance_reason=f"Comprobante de pago por S/ {payment_amount:,.2f}" if payment_amount else "Comprobante de pago",
            created_at=self._format_date(voucher.get("created_at")),
        )

    def _create_annex_from_collateral_file(
        self,
        file_info: dict,
        relevant_types: list[str],
    ) -> Optional[AnnexInfo]:
        """Create AnnexInfo from a collateral (guarantee) file."""
        s3_key = file_info.get("s3_key")
        if not s3_key:
            return None

        filename = file_info.get("original_name") or file_info.get("filename") or s3_key.split("/")[-1]
        file_type = self._get_file_type(filename)

        # Only include images and PDFs
        if file_type not in self.SUPPORTED_FILE_TYPES:
            return None

        relevance = self._calculate_relevance(filename, relevant_types)

        # Build descriptive name including property info
        property_address = file_info.get("property_address", "")
        kind_of_property = file_info.get("kind_of_property", "")
        electronic_record = file_info.get("electronic_record", "")
        collateral_status = file_info.get("collateral_status", "")

        # Generate display name with context
        display_name = self._generate_display_name(filename)
        if kind_of_property:
            display_name = f"{kind_of_property} - {display_name}"
        elif property_address and len(property_address) < 50:
            display_name = f"{display_name} - {property_address[:30]}"

        # Build relevance reason
        reason_parts = []
        if relevance["score"] > 0:
            reason_parts.append(relevance["reason"])
        if electronic_record:
            reason_parts.append(f"Partida: {electronic_record}")
        if collateral_status:
            reason_parts.append(f"Estado: {collateral_status}")

        relevance_reason = " | ".join(reason_parts) if reason_parts else "Documento de garantía"

        return AnnexInfo(
            id=f"collateral_{file_info.get('id', uuid.uuid4().hex[:8])}",
            file_id=file_info.get("id") or 0,
            name=display_name,
            original_name=filename,
            file_type=file_type,
            s3_key=s3_key,
            source=AnnexSource.JUDICIAL_COLLATERAL,
            relevance_reason=relevance_reason,
            created_at=self._format_date(file_info.get("created_at")),
        )

    def _calculate_relevance(
        self,
        filename: str,
        relevant_types: list[str],
    ) -> dict:
        """Calculate relevance score for a filename."""
        filename_lower = filename.lower()

        for annex_type in relevant_types:
            keywords = self.ANNEX_KEYWORDS.get(annex_type, [annex_type])
            for keyword in keywords:
                if keyword in filename_lower:
                    return {
                        "score": 1.0,
                        "reason": f"Documento tipo: {annex_type}",
                    }

        return {"score": 0.0, "reason": None}

    def _sort_by_relevance(
        self,
        annexes: list[AnnexInfo],
        relevant_types: list[str],
    ) -> list[AnnexInfo]:
        """Sort annexes by relevance to the document type."""
        def get_sort_key(annex: AnnexInfo) -> tuple:
            # Has relevance reason = high priority
            has_relevance = 0 if annex.relevance_reason else 1
            # Payment vouchers are often important
            is_voucher = 0 if annex.source == AnnexSource.EXTRAJUDICIAL_PAYMENT else 1
            # Sort by created date (newest first)
            date_str = annex.created_at or "0000-00-00"
            return (has_relevance, is_voucher, date_str)

        return sorted(annexes, key=get_sort_key)

    def _get_file_type(self, filename: str) -> str:
        """Extract file type from filename."""
        if "." in filename:
            return filename.rsplit(".", 1)[1].lower()
        return "unknown"

    def _generate_display_name(self, filename: str) -> str:
        """Generate a clean display name from filename."""
        # Remove extension
        name = filename.rsplit(".", 1)[0] if "." in filename else filename
        # Replace underscores and hyphens with spaces
        name = name.replace("_", " ").replace("-", " ")
        # Capitalize words
        name = " ".join(word.capitalize() for word in name.split())
        return name[:50]  # Limit length

    def _format_date(self, date_value) -> Optional[str]:
        """Convert date/datetime to string format."""
        if date_value is None:
            return None
        if hasattr(date_value, "strftime"):
            return date_value.strftime("%Y-%m-%d")
        return str(date_value) if date_value else None

    async def generate_thumbnail(
        self,
        s3_key: str,
        max_size: tuple[int, int] = (200, 200),
    ) -> Optional[str]:
        """
        Generate a thumbnail for a file (base64 encoded).

        For PDFs: renders first page as image.
        For images: resizes to thumbnail.
        """
        cache_key = f"{s3_key}_{max_size[0]}x{max_size[1]}"

        if cache_key in self._thumbnail_cache:
            return self._thumbnail_cache[cache_key]

        try:
            # Download file from S3
            file_data = await self.s3.download_file(s3_key)
            if not file_data:
                return None

            file_type = self._get_file_type(s3_key)

            if file_type == "pdf":
                thumbnail = self._pdf_to_thumbnail(file_data, max_size)
            elif file_type in ["jpg", "jpeg", "png", "gif", "webp", "bmp", "tiff", "tif", "heic", "heif"]:
                thumbnail = self._image_to_thumbnail(file_data, max_size)
            else:
                return None

            if thumbnail:
                self._thumbnail_cache[cache_key] = thumbnail

            return thumbnail

        except Exception as e:
            logger.error(f"Failed to generate thumbnail for {s3_key}: {e}")
            return None

    def _pdf_to_thumbnail(
        self,
        pdf_data: bytes,
        max_size: tuple[int, int],
    ) -> Optional[str]:
        """Convert first page of PDF to thumbnail."""
        try:
            doc = fitz.open(stream=pdf_data, filetype="pdf")
            page = doc[0]

            # Render at lower DPI for thumbnail
            mat = fitz.Matrix(72/72, 72/72)  # 72 DPI
            pix = page.get_pixmap(matrix=mat)

            # Convert to PIL Image
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            img.thumbnail(max_size, Image.Resampling.LANCZOS)

            # Convert to base64
            buffer = io.BytesIO()
            img.save(buffer, format="PNG")
            base64_str = base64.b64encode(buffer.getvalue()).decode()

            doc.close()
            return f"data:image/png;base64,{base64_str}"

        except Exception as e:
            logger.error(f"Failed to convert PDF to thumbnail: {e}")
            return None

    def _image_to_thumbnail(
        self,
        image_data: bytes,
        max_size: tuple[int, int],
    ) -> Optional[str]:
        """Resize image to thumbnail."""
        try:
            img = Image.open(io.BytesIO(image_data))
            img.thumbnail(max_size, Image.Resampling.LANCZOS)

            # Convert to PNG for consistency
            buffer = io.BytesIO()
            img.save(buffer, format="PNG")
            base64_str = base64.b64encode(buffer.getvalue()).decode()

            return f"data:image/png;base64,{base64_str}"

        except Exception as e:
            logger.error(f"Failed to convert image to thumbnail: {e}")
            return None

    async def process_annexes_for_embedding(
        self,
        annex_ids: list[str],
        annexes: list[AnnexInfo],
        max_pages_per_pdf: int = 5,
        image_width: int = 1200,
    ) -> list[ProcessedAnnex]:
        """
        Download and process selected annexes for embedding in DOCX.

        - Downloads files from S3
        - Converts PDFs to images (one per page)
        - Resizes images to appropriate width
        - Returns list of processed annexes with image data
        """
        logger.info(f"Processing {len(annex_ids)} annexes for embedding")

        # Create lookup by ID
        annex_lookup = {a.id: a for a in annexes}

        processed: list[ProcessedAnnex] = []

        for annex_id in annex_ids:
            annex = annex_lookup.get(annex_id)
            if not annex:
                logger.warning(f"Annex not found: {annex_id}")
                continue

            try:
                # Download from S3
                file_data = await self.s3.download_file(annex.s3_key)
                if not file_data:
                    logger.warning(f"Failed to download annex: {annex.s3_key}")
                    continue

                # Convert to images
                if annex.file_type == "pdf":
                    images = self._pdf_to_images(file_data, max_pages_per_pdf, image_width)
                elif annex.file_type in ["jpg", "jpeg", "png", "gif", "webp", "bmp", "tiff", "tif", "heic", "heif"]:
                    images = [self._resize_image(file_data, image_width)]
                else:
                    logger.warning(f"Unsupported file type: {annex.file_type}")
                    continue

                processed.append(ProcessedAnnex(
                    id=annex.id,
                    name=annex.name,
                    original_name=annex.original_name,
                    source=annex.source,
                    image_data=[img for img in images if img],
                    image_count=len([img for img in images if img]),
                ))

            except Exception as e:
                logger.error(f"Failed to process annex {annex_id}: {e}")
                continue

        logger.info(f"Successfully processed {len(processed)} annexes")
        return processed

    def _pdf_to_images(
        self,
        pdf_data: bytes,
        max_pages: int,
        target_width: int,
    ) -> list[bytes]:
        """Convert PDF pages to images."""
        images = []

        try:
            doc = fitz.open(stream=pdf_data, filetype="pdf")
            page_count = min(len(doc), max_pages)

            for page_num in range(page_count):
                page = doc[page_num]

                # Calculate zoom to achieve target width
                zoom = target_width / page.rect.width
                mat = fitz.Matrix(zoom, zoom)
                pix = page.get_pixmap(matrix=mat)

                # Convert to PNG bytes
                img_bytes = pix.tobytes("png")
                images.append(img_bytes)

            doc.close()

        except Exception as e:
            logger.error(f"Failed to convert PDF to images: {e}")

        return images

    def _resize_image(
        self,
        image_data: bytes,
        target_width: int,
    ) -> Optional[bytes]:
        """Resize image to target width while maintaining aspect ratio."""
        try:
            img = Image.open(io.BytesIO(image_data))

            # Calculate new height maintaining aspect ratio
            aspect_ratio = img.height / img.width
            new_height = int(target_width * aspect_ratio)

            # Only resize if image is larger than target
            if img.width > target_width:
                img = img.resize((target_width, new_height), Image.Resampling.LANCZOS)

            # Convert to PNG
            buffer = io.BytesIO()
            img.save(buffer, format="PNG")
            return buffer.getvalue()

        except Exception as e:
            logger.error(f"Failed to resize image: {e}")
            return None

    async def get_annexes_with_thumbnails(
        self,
        annexes: list[AnnexInfo],
        max_thumbnails: int = 10,
    ) -> list[AnnexInfo]:
        """
        Generate thumbnails for annexes (for preview).
        Only generates for first N annexes for performance.
        """
        for annex in annexes[:max_thumbnails]:
            if not annex.thumbnail_url:
                thumbnail = await self.generate_thumbnail(annex.s3_key)
                if thumbnail:
                    annex.thumbnail_url = thumbnail

        return annexes
