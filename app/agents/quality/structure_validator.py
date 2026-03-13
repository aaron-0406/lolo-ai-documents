"""
StructureValidatorAgent - Validates document structure completeness.
"""

import re
from typing import Any, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger
from pydantic import BaseModel

from app.config import settings
from app.models.schemas import CaseContext
from app.prompts.validators import STRUCTURE_VALIDATOR_PROMPT
from app.utils.learning_override import learning_override_analyzer
from app.utils.llm_worker import submit_to_worker


class ValidationResult(BaseModel):
    """Result of validation."""

    passed: bool
    issues_found: list[str]
    improvements_made: list[str]
    improved_draft: str | None = None


class StructureValidatorAgent:
    """
    Validates that the document has all required sections complete.
    Part of the quality control pipeline (Level 3).
    Uses Haiku for fast validation.
    """

    def __init__(self):
        # No LLM instance needed - using worker
        pass

    async def validate_and_improve(
        self,
        draft: str,
        context: CaseContext,
        document_type: str,
        custom_instructions: Optional[str] = None,
    ) -> ValidationResult:
        """
        Validate document structure and improve if needed.

        Args:
            draft: Current document draft
            context: Case file context
            document_type: Type of document being validated
            custom_instructions: Customer learnings/rules to apply (overrides default behavior)

        Returns:
            ValidationResult with validation status and improved draft
        """
        logger.info(f"StructureValidator validating: {document_type}")

        # Build the system prompt, applying override if learnings exist
        system_prompt = STRUCTURE_VALIDATOR_PROMPT
        if custom_instructions:
            # Remove contradicting instructions from the validator prompt
            system_prompt = await learning_override_analyzer.remove_conflicting_instructions(
                system_prompt,
                custom_instructions,
            )
            logger.info(f"[STRUCTURE_VALIDATOR] Applied learning override to system prompt")

        # Build user prompt with learnings included
        user_prompt = f"""TIPO DE DOCUMENTO: {document_type}

DOCUMENTO A VALIDAR:
{draft}
"""
        # Add learnings to user prompt so validator knows the rules
        if custom_instructions:
            user_prompt += f"""
---
{custom_instructions}

⚠️ IMPORTANTE: Las REGLAS DEL ESTUDIO JURÍDICO anteriores tienen MÁXIMA PRIORIDAD.
Si las reglas dicen "sin numeración", NO exijas numeración aunque tu checklist lo pida.
Si las reglas dicen "unificar secciones", NO exijas secciones separadas.
RESPETA el formato del documento si cumple con las reglas del estudio.
"""

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]

        try:
            # Use worker with Haiku for fast validation
            response = await submit_to_worker(
                messages=messages,
                model=settings.claude_model_fast,  # Haiku
                max_tokens=2000,
                estimated_output_tokens=500,
            )
            return self._parse_result(response.content, draft)
        except Exception as e:
            logger.error(f"Structure validation failed: {e}")
            return ValidationResult(
                passed=False,
                issues_found=[str(e)],
                improvements_made=[],
                improved_draft=None,
            )

    def _parse_result(self, content: str, original_draft: str) -> ValidationResult:
        """Parse the validation result from LLM response."""
        issues_found = []
        improvements_made = []
        improved_draft = None

        # Extract validation section
        validation_match = re.search(
            r"<validacion>(.*?)</validacion>",
            content,
            re.DOTALL | re.IGNORECASE,
        )

        if validation_match:
            validation_text = validation_match.group(1)
            # Find missing sections (marked with [ ])
            missing = re.findall(r"\[ \]\s*(.+?)(?:\n|$)", validation_text)
            for item in missing:
                issues_found.append(f"Sección faltante: {item.strip()}")

        # Extract corrected document
        doc_match = re.search(
            r"<documento_corregido>(.*?)</documento_corregido>",
            content,
            re.DOTALL | re.IGNORECASE,
        )

        if doc_match:
            candidate_draft = doc_match.group(1).strip()
            # Only use improved draft if it looks like a real document (not just evaluation text)
            # Real documents should be substantial and contain legal document markers
            if (candidate_draft
                and len(candidate_draft) > 500  # Minimum length for a real document
                and candidate_draft != original_draft
                and not candidate_draft.upper().startswith(("VALIDACIÓN", "VALIDACION", "RESULTADO", "APROBADO", "EL DOCUMENTO"))):
                improved_draft = candidate_draft
                improvements_made.append("Documento corregido con secciones faltantes")

        # Extract improvements
        improvements_match = re.search(
            r"<mejoras>(.*?)</mejoras>",
            content,
            re.DOTALL | re.IGNORECASE,
        )

        if improvements_match:
            improvements_text = improvements_match.group(1)
            for line in improvements_text.split("\n"):
                line = line.strip()
                if line.startswith("-"):
                    improvements_made.append(line[1:].strip())

        # Determine if passed
        passed = len(issues_found) == 0 or (
            improved_draft is not None and len(improvements_made) > 0
        )

        return ValidationResult(
            passed=passed,
            issues_found=issues_found,
            improvements_made=improvements_made,
            improved_draft=improved_draft,
        )
