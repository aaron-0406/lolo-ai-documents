"""
Extrajudicial Context Service - Fetches complete collection history and agreements.

Provides rich context from:
1. Client data (addresses, contacts, guarantors)
2. Financial products
3. Settlement agreements with payment history
4. Collection action history (comments/notes)
5. Client files and payment vouchers from S3
"""

from datetime import datetime
from typing import Any, Optional

from loguru import logger

from app.models.schemas import (
    ExtrajudicialContext,
    ClientAddress,
    ClientContact,
    Guarantor,
    FinancialProduct,
    Agreement,
    AgreementProduct,
    Payment,
    CollectionAction,
)
from app.services.mysql_service import MySQLService
from app.services.s3_service import S3Service
from app.services.context_cache_service import ContextCacheService, get_context_cache_service


class ExtrajudicialContextService:
    """
    Service that builds complete extrajudicial context by:
    1. Fetching client and related data from MySQL
    2. Fetching agreement and payment data
    3. Fetching collection history
    4. Downloading and extracting client files and vouchers from S3
    """

    def __init__(
        self,
        mysql_service: MySQLService,
        s3_service: S3Service,
        cache_service: Optional[ContextCacheService] = None,
    ):
        self.mysql = mysql_service
        self.s3 = s3_service
        self.cache = cache_service or get_context_cache_service(mysql_service, s3_service)

    async def get_extrajudicial_context(
        self,
        case_file_id: int,
        max_files: int = 10,
        max_collection_actions: int = 30,
        extract_files: bool = True,
    ) -> Optional[ExtrajudicialContext]:
        """
        Get complete extrajudicial context for a judicial case file.

        Args:
            case_file_id: ID of the JUDICIAL_CASE_FILE
            max_files: Maximum number of files to extract
            max_collection_actions: Maximum collection actions to include
            extract_files: Whether to extract text from files

        Returns:
            ExtrajudicialContext or None if client not found
        """
        logger.info(f"Building extrajudicial context for case {case_file_id}")

        # Get client data from case file
        client_data = await self.mysql.get_client_by_case_file(case_file_id)
        if not client_data:
            logger.warning(f"No client found for case file {case_file_id}")
            return None

        client_id = client_data["id"]
        client_code = client_data.get("code", "")
        customer_id = client_data.get("customer_id")
        chb_id = client_data.get("customer_has_bank_id")

        # Fetch all related data in parallel
        addresses_data = await self.mysql.get_client_addresses(client_id)
        contacts_data = await self.mysql.get_client_contacts(client_id)
        guarantors_data = await self.mysql.get_client_guarantors(client_id)
        products_data = await self.mysql.get_client_products(client_id)
        agreement_data = await self.mysql.get_client_agreement(client_id)
        collection_data = await self.mysql.get_collection_history(
            client_id, limit=max_collection_actions
        )

        # Build structured models
        addresses = [
            ClientAddress(
                id=a["id"],
                address=a.get("address", ""),
                address_type=a.get("address_type"),
                department=a.get("department"),
                province=a.get("province"),
                district=a.get("district"),
            )
            for a in addresses_data
        ]

        contacts = [
            ClientContact(
                id=c["id"],
                name=c.get("name", ""),
                phone=c.get("phone"),
                email=c.get("email"),
                dni=c.get("dni"),
                contact_type=c.get("contact_type"),
            )
            for c in contacts_data
        ]

        guarantors = [
            Guarantor(
                id=g["id"],
                name=g.get("name", ""),
                phone=g.get("phone"),
                email=g.get("email"),
            )
            for g in guarantors_data
        ]

        products = [
            FinancialProduct(
                id=p["id"],
                code=p.get("code"),
                product_name=p.get("product_name"),
                state=p.get("state"),
                judicial_case_file_id=p.get("judicial_case_file_id"),
            )
            for p in products_data
        ]

        # Build agreement with payments
        agreement = None
        has_agreement = False
        if agreement_data:
            has_agreement = True
            approval_date = agreement_data.get("approval_date")
            if hasattr(approval_date, "strftime"):
                approval_date = approval_date.strftime("%Y-%m-%d")

            agreement_products = [
                AgreementProduct(
                    id=ap["id"],
                    account_number=ap.get("account_number"),
                    total_debt=float(ap.get("total_debt", 0) or 0),
                    negotiated_amount=float(ap.get("negotiated_amount", 0) or 0),
                    currency=ap.get("currency", "PEN"),
                )
                for ap in agreement_data.get("products", [])
            ]

            payments = []
            for pay in agreement_data.get("payments", []):
                pay_date = pay.get("payment_date")
                if hasattr(pay_date, "strftime"):
                    pay_date = pay_date.strftime("%Y-%m-%d")
                payments.append(
                    Payment(
                        id=pay["id"],
                        payment_date=str(pay_date),
                        amount=float(pay.get("amount", 0) or 0),
                        comment=pay.get("comment"),
                        voucher_count=pay.get("voucher_count", 0),
                    )
                )

            agreement = Agreement(
                id=agreement_data["id"],
                approval_date=str(approval_date),
                total_negotiated_amount=float(
                    agreement_data.get("total_negotiated_amount", 0) or 0
                ),
                paid_fees=float(agreement_data.get("paid_fees", 0) or 0),
                judicial_fees=float(agreement_data.get("judicial_fees", 0) or 0),
                products=agreement_products,
                payments=payments,
                total_paid=float(agreement_data.get("total_paid", 0) or 0),
                pending_amount=float(agreement_data.get("pending_amount", 0) or 0),
            )

        # Build collection actions
        collection_actions = []
        for action in collection_data:
            action_date = action.get("date")
            if hasattr(action_date, "strftime"):
                action_date = action_date.strftime("%Y-%m-%d")
            # Convert hour datetime to string if needed
            action_hour = action.get("hour")
            if hasattr(action_hour, "strftime"):
                action_hour = action_hour.strftime("%H:%M:%S")
            elif action_hour is not None:
                action_hour = str(action_hour)
            collection_actions.append(
                CollectionAction(
                    id=action["id"],
                    date=str(action_date),
                    hour=action_hour,
                    comment=action.get("comment", ""),
                    action_type=action.get("action_type"),
                    contact_name=action.get("contact_name"),
                    address=action.get("address"),
                    officer_name=action.get("officer_name"),
                )
            )

        # Extract files if requested
        client_files = []
        payment_vouchers = []

        if extract_files and customer_id and chb_id and client_code:
            # Get client files
            files_data = await self.mysql.get_client_files(
                client_id, customer_id, chb_id, client_code, limit=max_files
            )

            for file_info in files_data:
                # Always add file metadata for annex identification
                file_entry = {
                    "id": file_info.get("id"),
                    "filename": file_info.get("filename", ""),
                    "original_name": file_info.get("original_name", ""),
                    "s3_key": file_info.get("s3_key"),  # Required for annex identification
                    "tag": file_info.get("tag_name"),
                    "created_at": str(file_info.get("created_at", "")),
                    "extracted_text": None,
                    "page_count": 0,
                }
                try:
                    cached_content = await self.cache.get_or_extract_file_content(
                        file_info,
                        max_pages=5,
                        max_images=2,
                        analyze_images=False,  # Skip image analysis for extrajudicial
                    )
                    if cached_content and cached_content.extracted_text:
                        file_entry["extracted_text"] = cached_content.extracted_text[:3000]
                        file_entry["page_count"] = cached_content.page_count
                except Exception as e:
                    logger.warning(f"Failed to extract client file: {e}")
                client_files.append(file_entry)

            # Get payment vouchers
            vouchers_data = await self.mysql.get_payment_vouchers(
                client_id, customer_id, chb_id, client_code, limit=max_files
            )

            for voucher_info in vouchers_data:
                # Always add voucher metadata for annex identification
                voucher_entry = {
                    "id": voucher_info.get("id"),
                    "filename": voucher_info.get("filename", ""),
                    "original_name": voucher_info.get("original_name", ""),
                    "s3_key": voucher_info.get("s3_key"),  # Required for annex identification
                    "payment_id": voucher_info.get("payment_id"),
                    "payment_date": str(voucher_info.get("payment_date", "")),
                    "payment_amount": float(voucher_info.get("payment_amount", 0) or 0),
                    "created_at": str(voucher_info.get("created_at", "")),
                    "extracted_text": None,
                }
                try:
                    cached_content = await self.cache.get_or_extract_file_content(
                        voucher_info,
                        max_pages=2,
                        max_images=1,
                        analyze_images=False,
                    )
                    if cached_content and cached_content.extracted_text:
                        voucher_entry["extracted_text"] = cached_content.extracted_text[:2000]
                except Exception as e:
                    logger.warning(f"Failed to extract payment voucher: {e}")
                payment_vouchers.append(voucher_entry)

        logger.info(
            f"Extrajudicial context ready: {len(addresses)} addresses, "
            f"{len(contacts)} contacts, {len(guarantors)} guarantors, "
            f"{len(products)} products, {len(collection_actions)} actions, "
            f"{len(client_files)} files, {len(payment_vouchers)} vouchers"
        )

        return ExtrajudicialContext(
            client_id=client_id,
            client_code=client_code,
            client_name=client_data.get("name", ""),
            client_dni_ruc=client_data.get("dni_ruc"),
            client_phone=client_data.get("phone"),
            client_email=client_data.get("email"),
            addresses=addresses,
            contacts=contacts,
            guarantors=guarantors,
            products=products,
            agreement=agreement,
            has_agreement=has_agreement,
            collection_actions=collection_actions,
            total_collection_actions=len(collection_data),
            negotiation_type=client_data.get("negotiation_type"),
            management_status=client_data.get("management_status"),
            assigned_officer=client_data.get("funcionario_name"),
            client_files=client_files,
            payment_vouchers=payment_vouchers,
        )


# Singleton instance management
_extrajudicial_context_service: Optional[ExtrajudicialContextService] = None


def get_extrajudicial_context_service(
    mysql_service: MySQLService,
    s3_service: S3Service,
) -> ExtrajudicialContextService:
    """Get or create the extrajudicial context service instance."""
    global _extrajudicial_context_service
    if _extrajudicial_context_service is None:
        _extrajudicial_context_service = ExtrajudicialContextService(
            mysql_service, s3_service
        )
    return _extrajudicial_context_service
