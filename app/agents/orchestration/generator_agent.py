"""
GeneratorAgent - Orchestrates document generation with quality pipeline.
Integrates with the learning system to apply customer-specific learnings.
"""

from datetime import datetime
from typing import Any, Optional

from loguru import logger
from pydantic import BaseModel

from app.config import settings
from app.models.schemas import CaseContext
from app.services.learning_service import learning_applier, StoredLearning

# Import specialist agents
from app.agents.specialists.obligations import ObligationsAgent
from app.agents.specialists.guarantees import GuaranteesAgent
from app.agents.specialists.execution import ExecutionAgent
from app.agents.specialists.procedural import ProceduralAgent
from app.agents.specialists.appeals import AppealsAgent
from app.agents.specialists.civil_litigation import CivilLitigationAgent
from app.agents.specialists.constitutional import ConstitutionalAgent
from app.agents.specialists.labor import LaborAgent

# Import quality control agents
from app.agents.quality.structure_validator import StructureValidatorAgent
from app.agents.quality.data_validator import DataValidatorAgent
from app.agents.quality.legal_validator import LegalValidatorAgent
from app.agents.quality.senior_reviewer import SeniorReviewerAgent


class GenerationResult(BaseModel):
    """Result of document generation."""

    draft: str
    ai_message: str
    tokens_used: int
    agents_used: list[str]
    validation_results: list[dict[str, Any]]
    generated_at: str
    learnings_applied: int = 0
    learning_ids: list[str] = []


class GeneratorAgent:
    """
    Orchestrator that coordinates:
    1. Retrieval and application of customer learnings
    2. Selection of the appropriate specialist agent
    3. Initial draft generation
    4. Complete quality validation pipeline
    """

    # Document type to specialist mapping
    SPECIALIST_MAPPING = {
        # Obligations specialist
        "demanda_ods": "obligations",
        "demanda_leasing": "obligations",
        # Guarantees specialist
        "demanda_eg": "guarantees",
        "incautacion_mobiliaria": "guarantees",
        # Execution specialist
        "solicitud_remate": "execution",
        "solicitud_adjudicacion": "execution",
        "solicitud_lanzamiento": "execution",
        "solicitud_tasacion": "execution",
        "solicitud_nuevas_bases": "execution",
        # Procedural specialist
        "medida_cautelar_fuera": "procedural",
        "medida_cautelar_dentro": "procedural",
        "medida_cautelar_embargo": "procedural",
        "escrito_impulso": "procedural",
        "escrito_subsanacion": "procedural",
        "escrito_variacion_domicilio": "procedural",
        "escrito_apersonamiento": "procedural",
        "escrito_desistimiento": "procedural",
        "escrito_otro": "procedural",
        # Appeals specialist
        "recurso_apelacion": "appeals",
        "recurso_casacion": "appeals",
        "recurso_queja": "appeals",
        "recurso_reposicion": "appeals",
        # Civil litigation specialist
        "demanda_accion_pauliana": "civil_litigation",
        "demanda_nulidad_acto": "civil_litigation",
        # Constitutional specialist
        "demanda_amparo": "constitutional",
        "contestacion_amparo": "constitutional",
        "recurso_agravio_constitucional": "constitutional",
        # Labor specialist
        "contestacion_laboral": "labor",
        "apelacion_laboral": "labor",
        "casacion_laboral": "labor",
        "alegatos_laborales": "labor",
    }

    def __init__(self):
        # Level 2: Initialize ALL 8 specialist agents
        self.specialists = {
            "obligations": ObligationsAgent(),
            "guarantees": GuaranteesAgent(),
            "execution": ExecutionAgent(),
            "procedural": ProceduralAgent(),
            "appeals": AppealsAgent(),
            "civil_litigation": CivilLitigationAgent(),
            "constitutional": ConstitutionalAgent(),
            "labor": LaborAgent(),
        }

        # Level 3: Quality control pipeline (executed sequentially)
        self.quality_pipeline = [
            StructureValidatorAgent(),
            DataValidatorAgent(),
            LegalValidatorAgent(),
            SeniorReviewerAgent(),
        ]

    def _select_specialist(self, document_type: str) -> str:
        """Select the appropriate specialist based on document type."""
        return self.SPECIALIST_MAPPING.get(document_type, "procedural")

    async def generate(
        self,
        document_type: str,
        context: CaseContext,
        custom_instructions: str | None = None,
        session_id: str | None = None,
    ) -> GenerationResult:
        """
        Generate a document using the full pipeline:
        1. Retrieve and apply customer learnings
        2. Specialist generates initial draft
        3. Quality pipeline validates and improves

        Args:
            document_type: Type of document to generate
            context: Case file context
            custom_instructions: Optional custom instructions from user
            session_id: Optional session ID for tracking applications

        Returns:
            GenerationResult with draft and metadata
        """
        logger.info(f"Generating document: {document_type}")

        agents_used = []
        validation_results = []
        total_tokens = 0
        learnings_applied = 0
        learning_ids = []

        # Step 0: Retrieve and format customer learnings
        learning_prompt_section = ""
        if settings.learning_enabled and context.customer_id:
            try:
                learnings = await learning_applier.get_learnings_for_generation(
                    customer_id=context.customer_id,
                    document_type=document_type,
                    case_context=context.model_dump() if context else None,
                )

                if learnings:
                    learning_prompt_section = learning_applier.format_learnings_for_prompt(
                        learnings=learnings,
                        customer_name=context.customer_name,
                    )
                    learnings_applied = len(learnings)
                    learning_ids = [l.learning_id for l in learnings]

                    # Record applications (non-blocking)
                    if session_id:
                        for learning in learnings:
                            await learning_applier.record_application(
                                learning_id=learning.learning_id,
                                session_id=session_id,
                                case_file_id=context.case_file_id,
                            )

                    logger.info(f"Applying {learnings_applied} learnings to generation")
                    agents_used.append(f"LearningApplier:{learnings_applied}")

            except Exception as e:
                logger.error(f"Error applying learnings: {e}")
                # Continue without learnings if there's an error

        # Combine custom instructions with learnings
        combined_instructions = self._combine_instructions(
            custom_instructions,
            learning_prompt_section,
        )

        # Step 1: Select and run specialist
        specialist_key = self._select_specialist(document_type)
        specialist = self.specialists[specialist_key]
        agents_used.append(f"Specialist:{specialist_key}")

        logger.info(f"Using specialist: {specialist_key}")

        try:
            draft = await specialist.generate_draft(
                document_type=document_type,
                context=context,
                custom_instructions=combined_instructions,
            )
            total_tokens += 4000  # Estimate
        except Exception as e:
            logger.error(f"Specialist failed: {e}")
            raise

        # Step 2: Run quality pipeline
        original_draft = draft  # Keep original as fallback
        current_draft = draft
        max_iterations = 3  # Prevent infinite loops

        for validator in self.quality_pipeline:
            validator_name = validator.__class__.__name__
            logger.info(f"Running validator: {validator_name}")

            try:
                result = await validator.validate_and_improve(
                    draft=current_draft,
                    context=context,
                    document_type=document_type,
                )

                validation_results.append({
                    "validator": validator_name,
                    "passed": result.passed,
                    "issues_found": result.issues_found,
                    "improvements_made": result.improvements_made,
                })

                # If validator improved the draft, use the new version
                if result.improved_draft:
                    current_draft = result.improved_draft

                agents_used.append(f"Quality:{validator_name}")
                total_tokens += 2000  # Estimate per validator

            except Exception as e:
                logger.warning(f"Validator {validator_name} failed: {e}")
                validation_results.append({
                    "validator": validator_name,
                    "passed": False,
                    "issues_found": [str(e)],
                    "improvements_made": [],
                    "error": True,
                })

        # Validate final draft - if it looks corrupted, use original
        if (len(current_draft) < 500
            or current_draft.upper().startswith(("ERROR", "VALIDACIÓN", "VALIDACION", "RESULTADO"))
            or "NO SE HA PROPORCIONADO" in current_draft.upper()):
            logger.warning("Final draft appears corrupted, using original specialist draft")
            current_draft = original_draft

        # Generate AI message for user
        ai_message = self._generate_ai_message(
            document_type,
            agents_used,
            validation_results,
            learnings_applied,
        )

        return GenerationResult(
            draft=current_draft,
            ai_message=ai_message,
            tokens_used=total_tokens,
            agents_used=agents_used,
            validation_results=validation_results,
            generated_at=datetime.now().isoformat(),
            learnings_applied=learnings_applied,
            learning_ids=learning_ids,
        )

    def _combine_instructions(
        self,
        custom_instructions: Optional[str],
        learning_section: str,
    ) -> Optional[str]:
        """Combine custom instructions with learning section."""
        parts = []

        if learning_section:
            parts.append(learning_section)

        if custom_instructions:
            parts.append(f"\n## INSTRUCCIONES ADICIONALES DEL USUARIO\n{custom_instructions}")

        if parts:
            return "\n".join(parts)
        return None

    def _generate_ai_message(
        self,
        document_type: str,
        agents_used: list[str],
        validation_results: list[dict],
        learnings_applied: int = 0,
    ) -> str:
        """Generate a friendly message for the user."""
        doc_name = document_type.replace("_", " ").title()

        # Count passed validations
        passed = sum(1 for v in validation_results if v.get("passed", False))
        total = len(validation_results)

        if passed == total:
            quality_msg = "El documento ha pasado todas las validaciones de calidad."
        elif passed > total / 2:
            quality_msg = f"El documento ha pasado {passed} de {total} validaciones."
        else:
            quality_msg = "El documento requiere revisión adicional."

        # Add learning info
        learning_msg = ""
        if learnings_applied > 0:
            learning_msg = f"\n\nSe aplicaron {learnings_applied} reglas personalizadas del estudio jurídico."

        return f"""He generado el borrador de {doc_name}.

{quality_msg}{learning_msg}

El documento fue procesado por {len(agents_used)} agentes especializados. Puedes revisar el contenido y solicitar los cambios que necesites a través del chat.

¿Hay algo que desees modificar o ajustar?"""
