"""
SeniorReviewerAgent - Final professional review of documents.
"""

import re

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger
from pydantic import BaseModel

from app.config import settings
from app.models.schemas import CaseContext
from app.prompts.validators import SENIOR_REVIEWER_PROMPT


class ValidationResult(BaseModel):
    """Result of validation."""

    passed: bool
    issues_found: list[str]
    improvements_made: list[str]
    improved_draft: str | None = None
    score: int | None = None


class SeniorReviewerAgent:
    """
    Final senior-level review of the document.
    Evaluates professional impact, persuasion, clarity, and details.
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
        Perform final senior review and improve if needed.

        Args:
            draft: Current document draft
            context: Case file context
            document_type: Type of document being validated

        Returns:
            ValidationResult with validation status, score, and improved draft
        """
        logger.info(f"SeniorReviewer reviewing: {document_type}")

        messages = [
            SystemMessage(content=SENIOR_REVIEWER_PROMPT),
            HumanMessage(content=f"""TIPO DE DOCUMENTO: {document_type}
EXPEDIENTE: {context.case_number}
CLIENTE: {context.client_name}

DOCUMENTO A REVISAR:
{draft}
"""),
        ]

        try:
            response = await self.llm.ainvoke(messages)
            return self._parse_result(response.content, draft)
        except Exception as e:
            logger.error(f"Senior review failed: {e}")
            return ValidationResult(
                passed=False,
                issues_found=[str(e)],
                improvements_made=[],
                improved_draft=None,
                score=None,
            )

    def _parse_result(self, content: str, original_draft: str) -> ValidationResult:
        """Parse the review result from LLM response."""
        issues_found = []
        improvements_made = []
        improved_draft = None
        total_score = None

        # Extract evaluation section
        eval_match = re.search(
            r"<evaluacion>(.*?)</evaluacion>",
            content,
            re.DOTALL | re.IGNORECASE,
        )

        if eval_match:
            eval_text = eval_match.group(1)

            # Extract scores
            scores = re.findall(r"(\d+)/10", eval_text)
            if scores:
                total_score = sum(int(s) for s in scores)

            # Extract weaknesses
            weaknesses = re.findall(
                r"Debilidad:\s*(.+?)(?:\n|$)",
                eval_text,
                re.IGNORECASE,
            )
            for weakness in weaknesses:
                if weakness.strip():
                    issues_found.append(weakness.strip())

            # Check for approval
            if "APROBACION FINAL: NO" in eval_text.upper():
                issues_found.append("Documento requiere mejoras antes de aprobación final")

        # Extract final document
        doc_match = re.search(
            r"<documento_final>(.*?)</documento_final>",
            content,
            re.DOTALL | re.IGNORECASE,
        )

        if doc_match:
            candidate_draft = doc_match.group(1).strip()
            # Only use improved draft if it looks like a real document (not just evaluation text)
            if (candidate_draft
                and len(candidate_draft) > 500
                and candidate_draft != original_draft
                and not candidate_draft.upper().startswith(("VALIDACIÓN", "VALIDACION", "RESULTADO", "APROBADO", "EL DOCUMENTO", "ERROR", "EVALUACION"))):
                improved_draft = candidate_draft
                improvements_made.append("Documento mejorado por revisión senior")

        # Extract improvement suggestions
        suggestions_match = re.search(
            r"<sugerencias_mejora>(.*?)</sugerencias_mejora>",
            content,
            re.DOTALL | re.IGNORECASE,
        )

        if suggestions_match:
            suggestions_text = suggestions_match.group(1)
            for line in suggestions_text.split("\n"):
                line = line.strip()
                if line.startswith("-"):
                    suggestion = line[1:].strip()
                    if suggestion:
                        improvements_made.append(suggestion)

        # Determine if passed (score >= 35/50 or 70%)
        passed = (total_score is not None and total_score >= 35) or len(issues_found) == 0

        return ValidationResult(
            passed=passed,
            issues_found=issues_found,
            improvements_made=improvements_made,
            improved_draft=improved_draft,
            score=total_score,
        )
