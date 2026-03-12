"""
Core data schemas for the AI Document Generation system.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class DocumentCategory(str, Enum):
    """Document categories - must match frontend DocumentCategory type."""

    # Main categories (match frontend)
    OBLIGACIONES = "obligaciones"
    GARANTIAS = "garantias"
    MEDIDAS_CAUTELARES = "medidas_cautelares"
    ESCRITOS_PROCESALES = "escritos_procesales"
    EJECUCION = "ejecucion"
    RECURSOS = "recursos"
    LITIGIOS_CIVILES = "litigios_civiles"
    CONSTITUCIONAL_LABORAL = "constitucional_laboral"

    # Legacy/internal categories (for document type definitions)
    DEMANDAS = "demandas"
    ACCIONES_CIVILES = "acciones_civiles"
    OTROS = "otros"


class DocumentType(BaseModel):
    """Document type definition."""

    key: str = Field(..., description="Unique identifier for the document type")
    name: str = Field(..., description="Human-readable name")
    category: DocumentCategory = Field(..., description="Document category")
    description: str = Field(..., description="Brief description of the document")
    specialist: str = Field(..., description="Specialist agent to handle this document")
    required_data: list[str] = Field(default_factory=list, description="Required data fields")


class DocumentCategoryInfo(BaseModel):
    """Category with its documents."""

    key: str = Field(..., description="Category key")
    name: str = Field(..., description="Category display name")
    icon: str = Field(..., description="Icon name for the category")
    documents: list[DocumentType] = Field(..., description="Documents in this category")


# =============================================================================
# Extrajudicial Context Models
# =============================================================================


class ClientAddress(BaseModel):
    """Client address from DIRECTION table."""

    id: int
    address: str
    address_type: Optional[str] = None
    department: Optional[str] = None
    province: Optional[str] = None
    district: Optional[str] = None


class ClientContact(BaseModel):
    """Contact person from EXT_CONTACT table."""

    id: int
    name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    dni: Optional[str] = None
    contact_type: Optional[str] = None  # Familiar, Trabajo, Referencia, etc.


class Guarantor(BaseModel):
    """Guarantor/co-debtor from GUARANTOR table."""

    id: int
    name: str
    dni_ruc: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None


class FinancialProduct(BaseModel):
    """Financial product from PRODUCT table."""

    id: int
    code: Optional[str] = None
    product_name: Optional[str] = None
    state: Optional[str] = None
    judicial_case_file_id: Optional[int] = None  # If escalated to judicial


class AgreementProduct(BaseModel):
    """Product within an agreement."""

    id: int
    account_number: Optional[str] = None
    total_debt: float = 0
    negotiated_amount: float = 0
    currency: str = "PEN"


class Payment(BaseModel):
    """Payment record from EXT_AGREEMENT_PAYMENT."""

    id: int
    payment_date: str
    amount: float
    comment: Optional[str] = None
    voucher_count: int = 0


class Agreement(BaseModel):
    """Settlement agreement from EXT_AGREEMENT."""

    id: int
    approval_date: str
    total_negotiated_amount: float = 0
    paid_fees: float = 0
    judicial_fees: float = 0
    products: list[AgreementProduct] = Field(default_factory=list)
    payments: list[Payment] = Field(default_factory=list)
    total_paid: float = 0
    pending_amount: float = 0


class CollectionAction(BaseModel):
    """Collection action from COMMENT table."""

    id: int
    date: str
    hour: Optional[str] = None
    comment: str
    action_type: Optional[str] = None  # Llamada, Visita, etc.
    contact_name: Optional[str] = None
    address: Optional[str] = None
    officer_name: Optional[str] = None


class ExtrajudicialContext(BaseModel):
    """Complete extrajudicial context for a client."""

    # Client basic info
    client_id: int
    client_code: str
    client_name: str
    client_dni_ruc: Optional[str] = None
    client_phone: Optional[str] = None
    client_email: Optional[str] = None

    # Related entities
    addresses: list[ClientAddress] = Field(default_factory=list)
    contacts: list[ClientContact] = Field(default_factory=list)
    guarantors: list[Guarantor] = Field(default_factory=list)
    products: list[FinancialProduct] = Field(default_factory=list)

    # Agreement and payments
    agreement: Optional[Agreement] = None
    has_agreement: bool = False

    # Collection history
    collection_actions: list[CollectionAction] = Field(default_factory=list)
    total_collection_actions: int = 0

    # Negotiation info
    negotiation_type: Optional[str] = None
    management_status: Optional[str] = None
    assigned_officer: Optional[str] = None

    # Files extracted
    client_files: list[dict] = Field(default_factory=list)
    payment_vouchers: list[dict] = Field(default_factory=list)


class CaseContext(BaseModel):
    """Context information about a judicial case."""

    case_file_id: int = Field(..., description="ID of the case file")
    case_number: str = Field(..., description="Case number (expediente)")
    client_id: int = Field(..., description="Client ID")
    client_name: str = Field(..., description="Client name")
    client_dni_ruc: Optional[str] = Field(None, description="Client DNI or RUC")
    client_address: Optional[str] = Field(None, description="Client address")
    client_phone: Optional[str] = Field(None, description="Client phone")
    client_email: Optional[str] = Field(None, description="Client email")

    # Court information
    court: Optional[str] = Field(None, description="Court name")
    court_name: Optional[str] = Field(None, description="Court name (alias)")
    judge_name: Optional[str] = Field(None, description="Judge name")
    secretary: Optional[str] = Field(None, description="Secretary name")
    secretary_name: Optional[str] = Field(None, description="Secretary name (alias)")

    # Case details
    subject: Optional[str] = Field(None, description="Legal subject")
    procedural_way: Optional[str] = Field(None, description="Procedural way")
    process_status: Optional[str] = Field(None, description="Current process status")
    current_stage: Optional[str] = Field(None, description="Current procedural stage")

    # Economic data
    amount_demanded_soles: Optional[float] = Field(None, description="Amount in soles")
    amount_demanded_dollars: Optional[float] = Field(None, description="Amount in dollars")

    # Parties
    demandante: Optional[dict[str, Any]] = Field(None, description="Plaintiff data")
    demandado: Optional[dict[str, Any]] = Field(None, description="Defendant data")

    # Related data
    binnacles: list[dict[str, Any]] = Field(default_factory=list, description="Recent binnacles")
    collaterals: list[dict[str, Any]] = Field(default_factory=list, description="Collaterals")
    products: list[dict[str, Any]] = Field(default_factory=list, description="Financial products")

    # Document contents extracted from S3
    binnacle_documents: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Extracted text content from binnacle PDF documents"
    )
    collateral_files: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Files from judicial collaterals (tasaciones, partidas registrales, etc.)"
    )

    # Extrajudicial context (collection history, agreements, payments)
    extrajudicial: Optional[ExtrajudicialContext] = Field(
        None,
        description="Complete extrajudicial context including collection history and agreements"
    )

    # Calculated fields
    last_action_date: Optional[datetime] = Field(None, description="Date of last action")
    days_since_last_action: Optional[int] = Field(None, description="Days since last action")

    # Bank/Customer info
    customer_has_bank_id: Optional[int] = Field(None, description="CHB ID")
    customer_id: Optional[int] = Field(None, description="Customer ID")
    client_code: Optional[str] = Field(None, description="Client code for S3 paths")
    customer_name: Optional[str] = Field(None, description="Customer/Bank company name")
    customer_ruc: Optional[str] = Field(None, description="Customer RUC")
    bank_name: Optional[str] = Field(None, description="Bank name")


class DocumentSuggestion(BaseModel):
    """Suggested document from analysis."""

    document_type: str = Field(..., description="Document type key")
    document_name: str = Field(..., description="Human-readable document name")
    reason: str = Field(..., description="Reason for suggestion")
    confidence: float = Field(..., ge=0, le=1, description="Confidence score 0-1")


class NoActionReason(BaseModel):
    """Reason why no action is needed."""

    reason_code: str = Field(..., description="Reason code")
    message: str = Field(..., description="Reason message")
    summary: Optional[str] = Field(None, description="Brief summary")
    details: list[str] = Field(default_factory=list, description="Detailed reasons")
    next_review_date: Optional[str] = Field(None, description="Suggested next review date")
    next_review_action: Optional[str] = Field(None, description="Suggested next action")


class ChatMessage(BaseModel):
    """Chat message in refinement conversation."""

    id: str = Field(..., description="Unique message ID")
    role: str = Field(..., description="Message role: user or assistant")
    content: str = Field(..., description="Message content")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Message timestamp")
    user_name: Optional[str] = Field(None, description="User name for user messages")


class DocumentSession(BaseModel):
    """Active document generation session."""

    session_id: str = Field(..., description="Unique session ID")
    case_file_id: int = Field(..., description="Associated case file ID")
    document_type: str = Field(..., description="Document type being generated")
    context: CaseContext = Field(..., description="Case context")
    current_draft: str = Field(default="", description="Current document draft")
    chat_history: list[ChatMessage] = Field(default_factory=list, description="Chat history")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_activity: datetime = Field(default_factory=datetime.utcnow)


class BinnacleSuggestion(BaseModel):
    """Suggested binnacle entry data."""

    date: str = Field(..., description="Suggested date (YYYY-MM-DD)")
    binnacle_type_id: Optional[int] = Field(None, description="Binnacle type ID")
    binnacle_type_name: str = Field(..., description="Binnacle type name")
    procedural_stage_id: Optional[int] = Field(None, description="Procedural stage ID")
    procedural_stage_name: str = Field(..., description="Procedural stage name")
    description: str = Field(..., description="Pre-filled description")


class ValidationResult(BaseModel):
    """Result from a validation agent."""

    is_valid: bool = Field(..., description="Whether validation passed")
    errors: list[str] = Field(default_factory=list, description="Validation errors")
    warnings: list[str] = Field(default_factory=list, description="Validation warnings")
    suggestions: list[str] = Field(default_factory=list, description="Improvement suggestions")


class SeniorReviewResult(BaseModel):
    """Result from senior reviewer agent."""

    score: float = Field(..., ge=0, le=1, description="Quality score 0-1")
    approved: bool = Field(..., description="Whether document is approved")
    improvement_suggestions: list[str] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)


# =============================================================================
# Annex Models (for document attachments/images)
# =============================================================================


class AnnexSource(str, Enum):
    """Source of the annex file."""

    JUDICIAL_BINNACLE = "judicial_binnacle"
    JUDICIAL_COLLATERAL = "judicial_collateral"  # Guarantee/collateral files (tasaciones, partidas, etc.)
    EXTRAJUDICIAL_CLIENT = "extrajudicial_client"
    EXTRAJUDICIAL_PAYMENT = "extrajudicial_payment"


class AnnexInfo(BaseModel):
    """Information about an available annex."""

    id: str = Field(..., description="Unique identifier for this annex")
    file_id: int = Field(..., description="Original file ID in database")
    name: str = Field(..., description="Display name of the annex")
    original_name: str = Field(..., description="Original filename")
    file_type: str = Field(..., description="File extension (pdf, jpg, png, etc.)")
    s3_key: str = Field(..., description="S3 object key")
    source: AnnexSource = Field(..., description="Source of the annex")
    relevance_reason: Optional[str] = Field(None, description="Why AI suggested this annex")
    preview_url: Optional[str] = Field(None, description="Presigned URL for preview")
    thumbnail_url: Optional[str] = Field(None, description="Thumbnail URL (base64 or presigned)")
    page_count: Optional[int] = Field(None, description="Number of pages (for PDFs)")
    file_size: Optional[int] = Field(None, description="File size in bytes")
    created_at: Optional[str] = Field(None, description="File creation date")


class ProcessedAnnex(BaseModel):
    """Annex after processing (with images extracted)."""

    id: str
    name: str
    original_name: str
    source: AnnexSource
    image_data: list[bytes] = Field(default_factory=list, description="Image bytes (PNG format)")
    image_count: int = 0


class AnnexSelection(BaseModel):
    """User's selection of annexes to include."""

    annex_ids: list[str] = Field(default_factory=list, description="IDs of selected annexes")
    custom_order: Optional[list[str]] = Field(None, description="Custom ordering of annexes")


class DocumentGenerationRequest(BaseModel):
    """Request to generate a document."""

    document_type: str = Field(..., description="Type of document to generate")
    custom_instructions: Optional[str] = Field(None, description="Custom user instructions")
    include_annexes: bool = Field(True, description="Whether to include annexes in response")


class DocumentGenerationResponse(BaseModel):
    """Response from document generation."""

    draft_content: str = Field(..., description="Generated document content (markdown)")
    document_type: str = Field(..., description="Type of document generated")
    validation_result: Optional[ValidationResult] = Field(None, description="Validation results")
    suggested_annexes: list[AnnexInfo] = Field(
        default_factory=list,
        description="Suggested annexes to include with the document"
    )
    binnacle_suggestion: Optional[BinnacleSuggestion] = Field(
        None, description="Suggested binnacle entry"
    )
    generation_time_ms: Optional[int] = Field(None, description="Generation time in milliseconds")


class FinalizeDocumentRequest(BaseModel):
    """Request to finalize document with selected annexes."""

    session_id: str = Field(..., description="Session ID from generation")
    selected_annexes: AnnexSelection = Field(
        default_factory=AnnexSelection,
        description="Selected annexes to embed"
    )
    format: str = Field("docx", description="Output format: docx or pdf")


class FinalizeDocumentResponse(BaseModel):
    """Response with the final document."""

    document_url: Optional[str] = Field(None, description="URL to download the document")
    document_base64: Optional[str] = Field(None, description="Base64 encoded document")
    filename: str = Field(..., description="Suggested filename")
    format: str = Field(..., description="Document format")
    annex_count: int = Field(0, description="Number of annexes included")
    total_pages: Optional[int] = Field(None, description="Total pages in document")
