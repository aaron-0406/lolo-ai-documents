"""
Learning Service - Handles AI learning extraction and application.

This service integrates with the lolo-backend learning system to:
1. Extract learnings from user feedback during document refinement
2. Apply stored learnings during document generation
3. Record learning applications for effectiveness tracking
"""

import json
from typing import Any, Optional

import httpx
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger
from pydantic import BaseModel

from app.config import settings


# =============================================================================
# Learning Types (must match backend)
# =============================================================================

LEARNING_TYPES = [
    "style",              # Estilo de redacción
    "format",             # Formato y estructura
    "legal_citation",     # Citas legales y jurisprudencia
    "content_rule",       # Reglas de contenido
    "terminology",        # Términos y vocabulario
    "client_preference",  # Preferencias específicas del cliente
    "error_correction",   # Corrección de errores comunes
]


# =============================================================================
# Data Models
# =============================================================================

class ExtractedLearning(BaseModel):
    """A learning extracted from user feedback."""
    learning_type: str
    instruction: str
    instruction_summary: Optional[str] = None
    document_section: Optional[str] = None
    applies_when: Optional[dict[str, Any]] = None
    original_text: Optional[str] = None
    corrected_text: Optional[str] = None
    priority: int = 50
    is_generalizable: bool = True


class StoredLearning(BaseModel):
    """A learning retrieved from the backend."""
    learning_id: str
    document_type: str
    document_section: Optional[str] = None
    learning_type: str
    instruction: str
    instruction_summary: Optional[str] = None
    applies_when: Optional[dict[str, Any]] = None
    priority: int = 50
    effectiveness_score: float = 1.0
    is_verified: bool = False


# =============================================================================
# Prompts
# =============================================================================

LEARNING_EXTRACTOR_PROMPT = """Eres un experto en análisis de feedback de usuarios para documentos legales peruanos.

Tu tarea es analizar el feedback del usuario sobre un documento legal y extraer REGLAS GENERALIZABLES que puedan aplicarse a futuros documentos del mismo tipo.

IMPORTANTE: Solo extrae reglas que sean:
1. GENERALIZABLES - Aplican a más de un documento específico
2. CLARAS - Se pueden aplicar sin ambigüedad
3. ACCIONABLES - El sistema puede aplicarlas automáticamente

NO extraigas:
- Correcciones específicas a datos de un caso particular
- Información que solo aplica a este expediente
- Cambios de formato menores sin patrón claro

TIPOS DE LECCIONES VÁLIDAS:
- style: Estilo de redacción (ej: "Usar lenguaje formal en tercera persona")
- format: Formato y estructura (ej: "Separar fundamentos de hecho y de derecho")
- legal_citation: Citas legales (ej: "Siempre citar el artículo 688 del CPC")
- content_rule: Reglas de contenido (ej: "Incluir monto actualizado de la deuda")
- terminology: Términos (ej: "Usar 'acreedor' en lugar de 'banco'")
- client_preference: Preferencias del cliente (ej: "Firma al final sin nombre")
- error_correction: Corrección de errores (ej: "Fechas en formato DD/MM/YYYY")

CONTEXTO DEL DOCUMENTO:
- Tipo: {document_type}
- Sección actual: {document_section}

DOCUMENTO ORIGINAL (fragmento relevante):
{original_text}

FEEDBACK DEL USUARIO:
{user_feedback}

DOCUMENTO CORREGIDO (fragmento relevante):
{corrected_text}

---

Analiza el feedback y responde SOLO con un JSON válido (sin markdown):
{{
  "learnings": [
    {{
      "learning_type": "tipo (style|format|legal_citation|content_rule|terminology|client_preference|error_correction)",
      "instruction": "La regla clara y completa que debe aplicarse",
      "instruction_summary": "Resumen corto (máx 100 caracteres)",
      "document_section": "petitorio|fundamentos_hecho|fundamentos_derecho|medios_probatorios|anexos|null",
      "applies_when": {{"campo": "valor"}} o null,
      "priority": 50-80,
      "is_generalizable": true o false
    }}
  ],
  "no_learnings_reason": "Razón si no se extrajo ninguna lección (opcional)"
}}

IMPORTANTE sobre applies_when:
- Usar null si la regla aplica a TODOS los casos del mismo tipo de documento
- Usar condiciones solo si la regla aplica a casos específicos según el contexto
- NUNCA incluir "document_type" (ya se filtra automáticamente)

Campos disponibles del contexto del caso (usar solo si el feedback indica una condición específica):
- "procedural_way": vía procedimental (ej: "EJECUTIVO", "CONOCIMIENTO", "UNICO DE EJECUCION")
- "subject": materia del caso (ej: "OBLIGACION DE DAR SUMA DE DINERO", "EJECUCION DE GARANTIAS")
- "bank_name": nombre del banco (ej: "BCP", "INTERBANK", "SCOTIABANK")
- "court": juzgado
- "secretary": secretario
- "process_status": estado del proceso
- "customer_name": nombre del cliente/empresa
- "client_name": nombre del demandado

Ejemplos:
- Regla general: "applies_when": null
- Solo vía ejecutiva: "applies_when": {{"procedural_way": "EJECUTIVO"}}
- Solo para BCP: "applies_when": {{"bank_name": "BCP"}}

Si no hay lecciones generalizables, devuelve: {{"learnings": [], "no_learnings_reason": "Explicación"}}
"""


LEARNING_SIMILARITY_PROMPT = """Eres un experto en análisis de similitud semántica para reglas de documentos legales.

Tu tarea es comparar una NUEVA LECCIÓN con una lista de LECCIONES EXISTENTES y determinar la relación entre ellas.

TIPOS DE RELACIÓN:
1. "duplicate" - La nueva lección es esencialmente igual a una existente (mismo significado, quizás diferente redacción)
2. "conflict" - La nueva lección contradice directamente una existente (instrucciones opuestas)
3. "complementary" - La nueva lección expande o complementa una existente (mismo tema, información adicional)
4. "independent" - La nueva lección no tiene relación significativa con las existentes

NUEVA LECCIÓN:
- Tipo: {new_learning_type}
- Instrucción: {new_instruction}
- Sección: {new_section}

LECCIONES EXISTENTES:
{existing_learnings}

---

Analiza la nueva lección contra cada lección existente y responde SOLO con un JSON válido (sin markdown):
{{
  "results": [
    {{
      "existing_learning_id": "id de la lección existente",
      "relationship": "duplicate|conflict|complementary|independent",
      "similarity_score": 0.0-1.0,
      "explanation": "Breve explicación de la relación"
    }}
  ],
  "most_similar": {{
    "learning_id": "id de la más similar o null",
    "relationship": "tipo de relación o null",
    "similarity_score": 0.0-1.0
  }}
}}

Si no hay lecciones existentes o todas son independientes, devuelve:
{{"results": [], "most_similar": {{"learning_id": null, "relationship": "independent", "similarity_score": 0.0}}}}
"""


EFFECTIVENESS_DETECTION_PROMPT = """Eres un experto en análisis de efectividad de reglas para documentos legales.

Tu tarea es determinar si las LECCIONES APLICADAS fueron efectivas comparando el TEXTO ORIGINAL (generado con las lecciones) con las CORRECCIONES DEL USUARIO.

Si el usuario corrigió algo que una lección debía prevenir, esa lección NO fue efectiva.
Si el usuario no corrigió el área cubierta por una lección, esa lección fue EFECTIVA.

LECCIONES APLICADAS:
{applied_learnings}

TEXTO ORIGINAL (generado con las lecciones):
{original_text}

CORRECCIONES DEL USUARIO:
{user_corrections}

TEXTO CORREGIDO FINAL:
{corrected_text}

---

Analiza cada lección y responde SOLO con un JSON válido (sin markdown):
{{
  "effectiveness_results": [
    {{
      "learning_id": "id de la lección",
      "was_effective": true o false,
      "reason": "Breve explicación"
    }}
  ]
}}
"""


# =============================================================================
# Similarity Checker
# =============================================================================

class SimilarityResult(BaseModel):
    """Result of similarity check between learnings."""
    existing_learning_id: Optional[str] = None
    relationship: str  # duplicate, conflict, complementary, independent
    similarity_score: float = 0.0
    explanation: Optional[str] = None


class SimilarityChecker:
    """
    Checks similarity between new and existing learnings.
    Uses Claude to semantically compare learning instructions.
    """

    def __init__(self):
        self.llm = ChatAnthropic(
            model=settings.claude_model,
            max_tokens=2000,
            api_key=settings.anthropic_api_key,
            temperature=0.1,
        )

    async def check_similarity(
        self,
        new_learning: ExtractedLearning,
        existing_learnings: list[StoredLearning],
    ) -> SimilarityResult:
        """
        Check similarity between a new learning and existing learnings.

        Args:
            new_learning: The new learning to check
            existing_learnings: List of existing learnings to compare against

        Returns:
            SimilarityResult with the most significant relationship found
        """
        if not existing_learnings:
            return SimilarityResult(
                relationship="independent",
                similarity_score=0.0,
            )

        # Format existing learnings for prompt
        existing_formatted = "\n".join([
            f"- ID: {l.learning_id}\n  Tipo: {l.learning_type}\n  Instrucción: {l.instruction}\n  Sección: {l.document_section or 'general'}"
            for l in existing_learnings
        ])

        prompt = LEARNING_SIMILARITY_PROMPT.format(
            new_learning_type=new_learning.learning_type,
            new_instruction=new_learning.instruction,
            new_section=new_learning.document_section or "general",
            existing_learnings=existing_formatted,
        )

        messages = [
            SystemMessage(content="Eres un analizador de similitud semántica. Responde SOLO con JSON válido."),
            HumanMessage(content=prompt),
        ]

        try:
            response = await self.llm.ainvoke(messages)
            content = response.content.strip()

            # Clean markdown code blocks if present
            if content.startswith("```"):
                lines = content.split("\n")
                content = "\n".join(lines[1:-1])

            data = json.loads(content)
            most_similar = data.get("most_similar", {})

            return SimilarityResult(
                existing_learning_id=most_similar.get("learning_id"),
                relationship=most_similar.get("relationship", "independent"),
                similarity_score=float(most_similar.get("similarity_score", 0.0)),
                explanation=None,
            )

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse similarity check response: {e}")
            return SimilarityResult(relationship="independent", similarity_score=0.0)
        except Exception as e:
            logger.error(f"Error checking similarity: {e}")
            return SimilarityResult(relationship="independent", similarity_score=0.0)

    async def check_for_conflicts_only(
        self,
        new_learning: ExtractedLearning,
        existing_learnings: list[StoredLearning],
    ) -> list[dict[str, Any]]:
        """
        Quick check for conflicts only (for validation before creation).

        Returns:
            List of conflicting learning IDs with similarity scores
        """
        if not existing_learnings:
            return []

        result = await self.check_similarity(new_learning, existing_learnings)

        if result.relationship == "conflict" and result.existing_learning_id:
            return [{
                "learning_id": result.existing_learning_id,
                "similarity_score": result.similarity_score,
                "type": "conflict",
            }]

        return []


# =============================================================================
# Effectiveness Detector
# =============================================================================

class EffectivenessDetector:
    """
    Detects whether applied learnings were effective by comparing
    original generated text with user corrections.
    """

    def __init__(self):
        self.llm = ChatAnthropic(
            model=settings.claude_model,
            max_tokens=2000,
            api_key=settings.anthropic_api_key,
            temperature=0.1,
        )

    async def detect_effectiveness(
        self,
        applied_learnings: list[StoredLearning],
        original_text: str,
        user_feedback: str,
        corrected_text: str,
    ) -> list[dict[str, Any]]:
        """
        Detect effectiveness of applied learnings by comparing corrections.

        Args:
            applied_learnings: Learnings that were applied during generation
            original_text: Text generated with the learnings
            user_feedback: User's feedback/correction request
            corrected_text: Final corrected text

        Returns:
            List of effectiveness results for each learning
        """
        if not applied_learnings:
            return []

        # Format applied learnings
        learnings_formatted = "\n".join([
            f"- ID: {l.learning_id}\n  Tipo: {l.learning_type}\n  Instrucción: {l.instruction}"
            for l in applied_learnings
        ])

        prompt = EFFECTIVENESS_DETECTION_PROMPT.format(
            applied_learnings=learnings_formatted,
            original_text=original_text[:3000],  # Truncate for prompt
            user_corrections=user_feedback,
            corrected_text=corrected_text[:3000],
        )

        messages = [
            SystemMessage(content="Eres un analizador de efectividad de reglas. Responde SOLO con JSON válido."),
            HumanMessage(content=prompt),
        ]

        try:
            response = await self.llm.ainvoke(messages)
            content = response.content.strip()

            # Clean markdown code blocks if present
            if content.startswith("```"):
                lines = content.split("\n")
                content = "\n".join(lines[1:-1])

            data = json.loads(content)
            return data.get("effectiveness_results", [])

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse effectiveness detection response: {e}")
            return []
        except Exception as e:
            logger.error(f"Error detecting effectiveness: {e}")
            return []


# =============================================================================
# Learning Extractor
# =============================================================================

class LearningExtractor:
    """
    Extracts generalizable learnings from user feedback.
    Uses Claude to analyze feedback and identify patterns.
    """

    def __init__(self):
        self.llm = ChatAnthropic(
            model=settings.claude_model,
            max_tokens=2000,
            api_key=settings.anthropic_api_key,
            temperature=0.1,  # Low temperature for consistent extraction
        )

    async def extract_learnings(
        self,
        document_type: str,
        user_feedback: str,
        original_text: str,
        corrected_text: str,
        document_section: Optional[str] = None,
    ) -> list[ExtractedLearning]:
        """
        Extract learnings from user feedback.

        Args:
            document_type: Type of document being refined
            user_feedback: User's feedback/request
            original_text: Original document section
            corrected_text: Corrected document section
            document_section: Which section was modified

        Returns:
            List of extracted learnings
        """
        if not settings.learning_enabled:
            return []

        prompt = LEARNING_EXTRACTOR_PROMPT.format(
            document_type=document_type,
            document_section=document_section or "general",
            original_text=original_text[:2000],  # Truncate for prompt size
            user_feedback=user_feedback,
            corrected_text=corrected_text[:2000],
        )

        messages = [
            SystemMessage(content="Eres un extractor de lecciones de documentos legales. Responde SOLO con JSON válido."),
            HumanMessage(content=prompt),
        ]

        try:
            response = await self.llm.ainvoke(messages)
            content = response.content.strip()

            # Clean markdown code blocks if present
            if content.startswith("```"):
                lines = content.split("\n")
                content = "\n".join(lines[1:-1])

            data = json.loads(content)
            learnings = []

            for learning_data in data.get("learnings", []):
                if not learning_data.get("is_generalizable", True):
                    continue

                learning = ExtractedLearning(
                    learning_type=learning_data.get("learning_type", "content_rule"),
                    instruction=learning_data.get("instruction", ""),
                    instruction_summary=learning_data.get("instruction_summary"),
                    document_section=learning_data.get("document_section"),
                    applies_when=learning_data.get("applies_when"),
                    priority=learning_data.get("priority", 50),
                    original_text=original_text[:500],
                    corrected_text=corrected_text[:500],
                    is_generalizable=True,
                )
                learnings.append(learning)

            logger.info(f"Extracted {len(learnings)} learnings from feedback")
            return learnings

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse learning extraction response: {e}")
            return []
        except Exception as e:
            logger.error(f"Error extracting learnings: {e}")
            return []


# =============================================================================
# Learning Applier
# =============================================================================

class LearningApplier:
    """
    Applies stored learnings during document generation.
    Retrieves learnings from backend and formats them for prompts.
    """

    def __init__(self):
        self.http_client = httpx.AsyncClient(timeout=10.0)

    async def get_learnings_for_generation(
        self,
        customer_id: int,
        document_type: str,
    ) -> list[StoredLearning]:
        """
        Get learnings for a document generation.

        Args:
            customer_id: Customer ID
            document_type: Type of document being generated

        Returns:
            List of learnings (filter locally with filter_by_context if needed)
        """
        if not settings.learning_enabled:
            return []

        try:
            url = f"{settings.backend_url}/api/v1/judicial/ai-learning/internal/for-generation"
            logger.debug(f"Calling learning endpoint: {url}")

            response = await self.http_client.post(
                url,
                headers={"X-Internal-Api-Key": settings.internal_api_key},
                json={
                    "customer_id": customer_id,
                    "document_type": document_type,
                },
            )

            if response.status_code != 200:
                logger.warning(f"Failed to get learnings: {response.status_code} - URL: {url}")
                logger.warning(f"Response body: {response.text[:500]}")
                return []

            data = response.json()
            learnings = []

            for learning_data in data.get("data", []):
                learning = StoredLearning(
                    learning_id=learning_data.get("learningId"),
                    document_type=learning_data.get("documentType"),
                    document_section=learning_data.get("documentSection"),
                    learning_type=learning_data.get("learningType"),
                    instruction=learning_data.get("instruction"),
                    instruction_summary=learning_data.get("instructionSummary"),
                    applies_when=learning_data.get("appliesWhen"),
                    priority=learning_data.get("priority", 50),
                    effectiveness_score=float(learning_data.get("effectivenessScore", 1.0)),
                    is_verified=learning_data.get("isVerified", False),
                )
                learnings.append(learning)

            logger.info(f"Retrieved {len(learnings)} learnings for {document_type}")
            return learnings

        except Exception as e:
            logger.error(f"Error getting learnings: {e}")
            return []

    def filter_by_context(
        self,
        learnings: list[StoredLearning],
        context: Any,
    ) -> list[StoredLearning]:
        """
        Filter learnings based on appliesWhen conditions using the case context.

        Args:
            learnings: List of learnings to filter
            context: Case context object with attributes like procedural_way, subject, etc.

        Returns:
            Filtered list of learnings that match the context
        """
        if not learnings:
            return []

        filtered = []
        for learning in learnings:
            if self._matches_context(learning.applies_when, context):
                filtered.append(learning)

        if len(filtered) < len(learnings):
            logger.debug(f"Filtered learnings: {len(learnings)} -> {len(filtered)}")

        return filtered

    def _matches_context(
        self,
        applies_when: Optional[dict[str, Any]],
        context: Any,
    ) -> bool:
        """Check if a learning's appliesWhen conditions match the context."""
        # No conditions = always applies
        if not applies_when:
            return True

        # Fields to skip (already filtered at database level or not in context)
        skip_fields = {"document_type", "documentType"}

        # Check each condition
        for key, expected_value in applies_when.items():
            # Skip fields that are filtered elsewhere
            if key in skip_fields:
                continue

            actual_value = getattr(context, key, None)
            if actual_value is None:
                # Also try dict access if context is a dict
                if isinstance(context, dict):
                    actual_value = context.get(key)

            if actual_value != expected_value:
                logger.debug(f"Learning filtered: {key}={actual_value} != {expected_value}")
                return False

        return True

    def format_learnings_for_prompt(
        self,
        learnings: list[StoredLearning],
        customer_name: Optional[str] = None,
    ) -> str:
        """
        Format learnings as a prompt section.

        Args:
            learnings: List of learnings to format
            customer_name: Optional customer name for personalization

        Returns:
            Formatted string for inclusion in prompts
        """
        if not learnings:
            return ""

        studio_name = customer_name or "el estudio jurídico"

        lines = [
            f"\n## REGLAS DEL ESTUDIO JURÍDICO (APLICAR OBLIGATORIAMENTE)\n",
            f"Las siguientes reglas han sido establecidas por {studio_name} y DEBEN aplicarse:\n",
        ]

        # Group by type
        by_type: dict[str, list[StoredLearning]] = {}
        for learning in learnings:
            if learning.learning_type not in by_type:
                by_type[learning.learning_type] = []
            by_type[learning.learning_type].append(learning)

        type_names = {
            "style": "Estilo y Redacción",
            "format": "Formato y Estructura",
            "legal_citation": "Citaciones Legales",
            "content_rule": "Reglas de Contenido",
            "terminology": "Terminología",
            "client_preference": "Preferencias del Cliente",
            "error_correction": "Correcciones de Errores",
        }

        rule_number = 1
        for learning_type, type_learnings in by_type.items():
            type_name = type_names.get(learning_type, learning_type)
            lines.append(f"\n### {type_name}")

            # Sort by priority (descending) and effectiveness
            sorted_learnings = sorted(
                type_learnings,
                key=lambda x: (x.priority, x.effectiveness_score),
                reverse=True,
            )

            for learning in sorted_learnings:
                verified_mark = " ✓" if learning.is_verified else ""
                lines.append(f"{rule_number}. {learning.instruction}{verified_mark}")
                rule_number += 1

        lines.append("\n---\n")
        return "\n".join(lines)

    async def record_application(
        self,
        learning_id: str,
        session_id: str,
        case_file_id: int,
    ) -> bool:
        """
        Record that a learning was applied.

        Args:
            learning_id: ID of the learning
            session_id: Session ID
            case_file_id: Case file ID

        Returns:
            True if successful
        """
        try:
            response = await self.http_client.post(
                f"{settings.backend_url}/api/v1/judicial/ai-learning/internal/{learning_id}/apply",
                headers={"X-Internal-Api-Key": settings.internal_api_key},
                json={
                    "session_id": session_id,
                    "case_file_id": case_file_id,
                },
            )
            return response.status_code == 201
        except Exception as e:
            logger.error(f"Error recording application: {e}")
            return False

    async def close(self):
        """Close the HTTP client."""
        await self.http_client.aclose()


# =============================================================================
# Backend Communication
# =============================================================================

class LearningBackendClient:
    """
    Client for communicating with the lolo-backend learning API.
    """

    def __init__(self):
        self.http_client = httpx.AsyncClient(timeout=10.0)
        self.base_url = f"{settings.backend_url}/api/v1/judicial/ai-learning"

    async def create_learning(
        self,
        customer_id: int,
        document_type: str,
        learning: ExtractedLearning,
        source_session_id: Optional[str] = None,
        source_case_file_id: Optional[int] = None,
        created_by_user_id: Optional[int] = None,
    ) -> Optional[str]:
        """
        Create a new learning in the backend.

        Returns:
            learning_id if successful, None otherwise
        """
        try:
            response = await self.http_client.post(
                f"{self.base_url}/internal/create",
                headers={"X-Internal-Api-Key": settings.internal_api_key},
                json={
                    "customer_id": customer_id,
                    "document_type": document_type,
                    "document_section": learning.document_section,
                    "learning_type": learning.learning_type,
                    "instruction": learning.instruction,
                    "instruction_summary": learning.instruction_summary,
                    "applies_when": learning.applies_when,
                    "original_text": learning.original_text,
                    "corrected_text": learning.corrected_text,
                    "user_feedback": None,  # Could be added if needed
                    "priority": learning.priority,
                    "source_session_id": source_session_id,
                    "source_case_file_id": source_case_file_id,
                    "created_by_customer_user_id": created_by_user_id,
                },
            )

            if response.status_code == 201:
                data = response.json()
                learning_id = data.get("data", {}).get("learningId")
                logger.info(f"Created learning: {learning_id}")
                return learning_id
            else:
                logger.warning(f"Failed to create learning: {response.status_code} - {response.text}")
                return None

        except Exception as e:
            logger.error(f"Error creating learning: {e}")
            return None

    async def mark_effectiveness(
        self,
        application_id: int,
        was_effective: bool,
        user_feedback: Optional[str] = None,
    ) -> bool:
        """
        Mark whether a learning application was effective.

        Returns:
            True if successful
        """
        try:
            response = await self.http_client.post(
                f"{self.base_url}/internal/applications/{application_id}/effectiveness",
                headers={"X-Internal-Api-Key": settings.internal_api_key},
                json={
                    "was_effective": was_effective,
                    "user_feedback": user_feedback,
                },
            )
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Error marking effectiveness: {e}")
            return False

    async def check_for_conflicts(
        self,
        customer_id: int,
        document_type: str,
        document_section: Optional[str],
        learning_type: str,
        instruction: str,
    ) -> dict[str, Any]:
        """
        Check for potential conflicts with existing learnings.

        Returns:
            Dict with hasConflicts and conflicts list
        """
        try:
            response = await self.http_client.post(
                f"{self.base_url}/internal/check-conflicts",
                headers={"X-Internal-Api-Key": settings.internal_api_key},
                json={
                    "customer_id": customer_id,
                    "document_type": document_type,
                    "document_section": document_section,
                    "learning_type": learning_type,
                    "instruction": instruction,
                },
            )

            if response.status_code == 200:
                data = response.json()
                return data.get("data", {"hasConflicts": False, "conflicts": []})
            else:
                logger.warning(f"Failed to check conflicts: {response.status_code}")
                return {"hasConflicts": False, "conflicts": []}

        except Exception as e:
            logger.error(f"Error checking conflicts: {e}")
            return {"hasConflicts": False, "conflicts": []}

    async def close(self):
        """Close the HTTP client."""
        await self.http_client.aclose()


# =============================================================================
# Module-level instances
# =============================================================================

learning_extractor = LearningExtractor()
learning_applier = LearningApplier()
learning_backend = LearningBackendClient()
similarity_checker = SimilarityChecker()
effectiveness_detector = EffectivenessDetector()
