"""
Document types catalog endpoint.
"""

from fastapi import APIRouter

from app.models.responses import DocumentTypeResponse
from app.models.schemas import DocumentType, DocumentCategory, DocumentCategoryInfo

router = APIRouter()


# Category metadata (display name and icon)
CATEGORY_META = {
    "DEMANDAS": {"name": "Demandas", "icon": "FileText"},
    "DOCUMENTOS_EJECUCION": {"name": "Documentos de Ejecución", "icon": "Gavel"},
    "RECURSOS": {"name": "Recursos", "icon": "Scale"},
    "MEDIDAS_CAUTELARES": {"name": "Medidas Cautelares", "icon": "Shield"},
    "ESCRITOS_PROCESALES": {"name": "Escritos Procesales", "icon": "FileEdit"},
    "GARANTIAS": {"name": "Garantías", "icon": "Lock"},
    "ACCIONES_CIVILES": {"name": "Acciones Civiles", "icon": "Briefcase"},
    "CONSTITUCIONAL": {"name": "Constitucional", "icon": "BookOpen"},
    "LABORAL": {"name": "Laboral", "icon": "Users"},
}


# Document type catalog - organized by category
DOCUMENT_TYPES: dict[str, list[DocumentType]] = {
    "DEMANDAS": [
        DocumentType(
            key="demanda_ods",
            name="Demanda de Obligación de Dar Suma de Dinero",
            category=DocumentCategory.DEMANDAS,
            description="Demanda ejecutiva para cobro de deudas dinerarias",
            specialist="obligations",
            required_data=["client", "debt_amount", "title"],
        ),
        DocumentType(
            key="demanda_ejecucion_garantia",
            name="Demanda de Ejecución de Garantía",
            category=DocumentCategory.DEMANDAS,
            description="Demanda para ejecutar garantía hipotecaria o mobiliaria",
            specialist="guarantees",
            required_data=["client", "collateral", "debt_amount"],
        ),
        DocumentType(
            key="demanda_leasing",
            name="Demanda por Incumplimiento de Leasing",
            category=DocumentCategory.DEMANDAS,
            description="Demanda por incumplimiento de contrato de arrendamiento financiero",
            specialist="obligations",
            required_data=["client", "contract", "debt_amount"],
        ),
    ],
    "DOCUMENTOS_EJECUCION": [
        DocumentType(
            key="solicitud_tasacion",
            name="Solicitud de Tasación",
            category=DocumentCategory.EJECUCION,
            description="Solicitud de tasación del bien para remate",
            specialist="execution",
            required_data=["collateral"],
        ),
        DocumentType(
            key="solicitud_remate",
            name="Solicitud de Remate",
            category=DocumentCategory.EJECUCION,
            description="Solicitud de convocatoria a remate público",
            specialist="execution",
            required_data=["collateral", "base_price"],
        ),
        DocumentType(
            key="adjudicacion",
            name="Solicitud de Adjudicación",
            category=DocumentCategory.EJECUCION,
            description="Solicitud de adjudicación directa del bien",
            specialist="execution",
            required_data=["collateral", "auction_result"],
        ),
        DocumentType(
            key="lanzamiento",
            name="Solicitud de Lanzamiento",
            category=DocumentCategory.EJECUCION,
            description="Solicitud de desalojo/lanzamiento del inmueble",
            specialist="execution",
            required_data=["collateral", "adjudication"],
        ),
    ],
    "RECURSOS": [
        DocumentType(
            key="apelacion_auto",
            name="Recurso de Apelación de Auto",
            category=DocumentCategory.RECURSOS,
            description="Apelación contra auto judicial (5 días hábiles)",
            specialist="appeals",
            required_data=["resolution", "grievances"],
        ),
        DocumentType(
            key="apelacion_sentencia",
            name="Recurso de Apelación de Sentencia",
            category=DocumentCategory.RECURSOS,
            description="Apelación contra sentencia (10 días hábiles)",
            specialist="appeals",
            required_data=["sentence", "grievances"],
        ),
        DocumentType(
            key="casacion",
            name="Recurso de Casación",
            category=DocumentCategory.RECURSOS,
            description="Recurso de casación ante la Corte Suprema",
            specialist="appeals",
            required_data=["sentence", "cassation_grounds"],
        ),
        DocumentType(
            key="queja",
            name="Recurso de Queja",
            category=DocumentCategory.RECURSOS,
            description="Queja por denegatoria de apelación o casación",
            specialist="appeals",
            required_data=["denied_appeal", "grievances"],
        ),
    ],
    "MEDIDAS_CAUTELARES": [
        DocumentType(
            key="medida_cautelar_embargo",
            name="Medida Cautelar de Embargo",
            category=DocumentCategory.MEDIDAS_CAUTELARES,
            description="Solicitud de embargo preventivo",
            specialist="procedural",
            required_data=["debtor_assets", "debt_amount"],
        ),
        DocumentType(
            key="ampliacion_embargo",
            name="Ampliación de Embargo",
            category=DocumentCategory.MEDIDAS_CAUTELARES,
            description="Solicitud de ampliación de medida cautelar",
            specialist="procedural",
            required_data=["existing_embargo", "additional_assets"],
        ),
        DocumentType(
            key="anotacion_demanda",
            name="Anotación de Demanda",
            category=DocumentCategory.MEDIDAS_CAUTELARES,
            description="Solicitud de anotación de demanda en registros",
            specialist="procedural",
            required_data=["property_registry"],
        ),
    ],
    "ESCRITOS_PROCESALES": [
        DocumentType(
            key="escrito_impulso",
            name="Escrito de Impulso Procesal",
            category=DocumentCategory.ESCRITOS_PROCESALES,
            description="Solicitud de impulso del proceso",
            specialist="procedural",
            required_data=["current_status"],
        ),
        DocumentType(
            key="subsanacion",
            name="Escrito de Subsanación",
            category=DocumentCategory.ESCRITOS_PROCESALES,
            description="Subsanación de observaciones del juzgado",
            specialist="procedural",
            required_data=["observations"],
        ),
        DocumentType(
            key="variacion_domicilio",
            name="Variación de Domicilio Procesal",
            category=DocumentCategory.ESCRITOS_PROCESALES,
            description="Cambio de domicilio procesal",
            specialist="procedural",
            required_data=["new_address"],
        ),
        DocumentType(
            key="desistimiento",
            name="Escrito de Desistimiento",
            category=DocumentCategory.ESCRITOS_PROCESALES,
            description="Desistimiento del proceso o pretensión",
            specialist="procedural",
            required_data=["desistimiento_type"],
        ),
        DocumentType(
            key="variacion_demanda",
            name="Variación de Demanda",
            category=DocumentCategory.ESCRITOS_PROCESALES,
            description="Modificación de la demanda antes de contestación",
            specialist="procedural",
            required_data=["modifications"],
        ),
    ],
    "GARANTIAS": [
        DocumentType(
            key="incautacion_mobiliaria",
            name="Solicitud de Incautación Mobiliaria",
            category=DocumentCategory.GARANTIAS,
            description="Incautación de bienes muebles en garantía mobiliaria",
            specialist="guarantees",
            required_data=["movable_collateral"],
        ),
        DocumentType(
            key="liquidacion_deuda",
            name="Liquidación de Deuda",
            category=DocumentCategory.GARANTIAS,
            description="Cálculo y presentación de liquidación de deuda",
            specialist="obligations",
            required_data=["debt_details", "interests"],
        ),
    ],
    "ACCIONES_CIVILES": [
        DocumentType(
            key="accion_pauliana",
            name="Demanda de Acción Pauliana",
            category=DocumentCategory.ACCIONES_CIVILES,
            description="Acción de ineficacia de actos de disposición",
            specialist="civil_litigation",
            required_data=["fraudulent_act", "prejudice"],
        ),
        DocumentType(
            key="nulidad_acto",
            name="Demanda de Nulidad de Acto Jurídico",
            category=DocumentCategory.ACCIONES_CIVILES,
            description="Demanda de nulidad por causales del art. 219 CC",
            specialist="civil_litigation",
            required_data=["void_act", "nullity_ground"],
        ),
    ],
    "CONSTITUCIONAL": [
        DocumentType(
            key="demanda_amparo",
            name="Demanda de Amparo",
            category=DocumentCategory.OTROS,
            description="Proceso constitucional de amparo",
            specialist="constitutional",
            required_data=["violated_right", "threatening_act"],
        ),
        DocumentType(
            key="recurso_agravio_constitucional",
            name="Recurso de Agravio Constitucional",
            category=DocumentCategory.OTROS,
            description="RAC ante el Tribunal Constitucional",
            specialist="constitutional",
            required_data=["amparo_denial", "grievances"],
        ),
    ],
    "LABORAL": [
        DocumentType(
            key="contestacion_laboral",
            name="Contestación de Demanda Laboral",
            category=DocumentCategory.OTROS,
            description="Contestación en proceso laboral",
            specialist="labor",
            required_data=["labor_claim", "defenses"],
        ),
        DocumentType(
            key="apelacion_laboral",
            name="Apelación en Proceso Laboral",
            category=DocumentCategory.OTROS,
            description="Recurso de apelación en materia laboral",
            specialist="labor",
            required_data=["labor_sentence", "grievances"],
        ),
    ],
}


@router.get("/types", response_model=DocumentTypeResponse)
async def get_document_types() -> DocumentTypeResponse:
    """
    Get catalog of available document types organized by category.

    Returns all document types that can be generated by the AI system,
    organized by category (Demandas, Recursos, Medidas Cautelares, etc.)
    """
    total = sum(len(docs) for docs in DOCUMENT_TYPES.values())

    # Transform dict to array format expected by frontend
    categories_list = []
    for cat_key, documents in DOCUMENT_TYPES.items():
        meta = CATEGORY_META.get(cat_key, {"name": cat_key, "icon": "File"})
        categories_list.append(
            DocumentCategoryInfo(
                key=cat_key,
                name=meta["name"],
                icon=meta["icon"],
                documents=documents,
            )
        )

    return DocumentTypeResponse(
        categories=categories_list,
        total_count=total,
    )


def get_document_type_by_key(key: str) -> DocumentType | None:
    """Helper to find a document type by its key."""
    for category_docs in DOCUMENT_TYPES.values():
        for doc_type in category_docs:
            if doc_type.key == key:
                return doc_type
    return None


def get_specialist_for_document(document_type_key: str) -> str | None:
    """Get the specialist agent name for a document type."""
    doc_type = get_document_type_by_key(document_type_key)
    return doc_type.specialist if doc_type else None
