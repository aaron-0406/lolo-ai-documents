"""
DataValidatorAgent - Validates data coherence and correctness.
"""

import re

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger
from pydantic import BaseModel

from app.config import settings
from app.models.schemas import CaseContext
from app.prompts.validators import DATA_VALIDATOR_PROMPT


class ValidationResult(BaseModel):
    """Result of validation."""

    passed: bool
    issues_found: list[str]
    improvements_made: list[str]
    improved_draft: str | None = None


class DataValidatorAgent:
    """
    Validates data coherence and correctness in the document.
    Part of the quality control pipeline (Level 3).
    """

    def __init__(self):
        self.llm = ChatAnthropic(
            model=settings.claude_model,
            max_tokens=8000,
            api_key=settings.anthropic_api_key,
        )

    async def validate_and_improve(
        self,
        draft: str,
        context: CaseContext,
        document_type: str,
    ) -> ValidationResult:
        """
        Validate data coherence and improve if needed.

        Args:
            draft: Current document draft
            context: Case file context
            document_type: Type of document being validated

        Returns:
            ValidationResult with validation status and improved draft
        """
        logger.info(f"DataValidator validating: {document_type}")

        # Build context summary for validation
        context_summary = self._build_context_summary(context)

        messages = [
            SystemMessage(content=DATA_VALIDATOR_PROMPT),
            HumanMessage(content=f"""TIPO DE DOCUMENTO: {document_type}

DATOS DE REFERENCIA (del sistema):
{context_summary}

DOCUMENTO A VALIDAR:
{draft}
"""),
        ]

        try:
            response = await self.llm.ainvoke(messages)
            return self._parse_result(response.content, draft)
        except Exception as e:
            logger.error(f"Data validation failed: {e}")
            return ValidationResult(
                passed=False,
                issues_found=[str(e)],
                improvements_made=[],
                improved_draft=None,
            )

    def _build_context_summary(self, context: CaseContext) -> str:
        """Build a summary of context data for validation."""
        return f"""- Número de expediente: {context.case_number}
- Cliente: {context.client_name}
- DNI/RUC: {context.client_dni_ruc}
- Monto soles: S/ {context.amount_demanded_soles or 0:,.2f}
- Monto dólares: $ {context.amount_demanded_dollars or 0:,.2f}
- Juzgado: {context.court}
- Materia: {context.subject}
- Vía: {context.procedural_way}
"""

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
            # Find incorrect items (marked with [ ] and INCORRECTO/ERROR)
            errors = re.findall(
                r"\[ \]\s*(.+?)\s*[-–]\s*(INCORRECTO|ERROR|FALTANTE).*?(?:\n|$)",
                validation_text,
                re.IGNORECASE,
            )
            for item, _ in errors:
                issues_found.append(f"Dato incorrecto: {item.strip()}")

        # Extract corrected document
        doc_match = re.search(
            r"<documento_corregido>(.*?)</documento_corregido>",
            content,
            re.DOTALL | re.IGNORECASE,
        )

        if doc_match:
            candidate_draft = doc_match.group(1).strip()
            # Only use improved draft if it looks like a real document (not just evaluation text)
            if (candidate_draft
                and len(candidate_draft) > 500
                and candidate_draft != original_draft
                and not candidate_draft.upper().startswith(("VALIDACIÓN", "VALIDACION", "RESULTADO", "APROBADO", "EL DOCUMENTO", "DATOS"))):
                improved_draft = candidate_draft
                improvements_made.append("Datos corregidos en el documento")

        # Extract corrections
        corrections_match = re.search(
            r"<correcciones>(.*?)</correcciones>",
            content,
            re.DOTALL | re.IGNORECASE,
        )

        if corrections_match:
            corrections_text = corrections_match.group(1)
            for line in corrections_text.split("\n"):
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
