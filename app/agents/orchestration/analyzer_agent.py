"""
AnalyzerAgent - Analyzes case files and suggests documents.
"""

import json
from datetime import datetime
from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger
from pydantic import BaseModel

from app.config import settings
from app.models.schemas import CaseContext, DocumentSuggestion, NoActionReason
from app.prompts.analyzer import ANALYZER_SYSTEM_PROMPT
from app.utils.llm_worker import submit_to_worker


class AnalysisResult(BaseModel):
    """Result of the analysis."""

    has_suggestion: bool
    suggestion: Optional[DocumentSuggestion] = None
    alternatives: list[DocumentSuggestion] = []
    no_action_reason: Optional[NoActionReason] = None


class AnalyzerAgent:
    """
    Analyzes a judicial case file and determines the most appropriate
    document to generate based on the current procedural stage.
    Uses Haiku for fast analysis.
    """

    def __init__(self):
        # No LLM instance needed - using worker
        pass

    async def analyze(self, context: CaseContext) -> AnalysisResult:
        """
        Analyze the case file and return document suggestions.

        Args:
            context: Full context of the judicial case file

        Returns:
            AnalysisResult with suggestion and alternatives
        """
        logger.info(f"Analyzing case file: {context.case_number}")

        # Calculate days of inactivity
        days_inactive = self._calculate_inactivity(context.binnacles)

        # Determine current procedural stage
        current_stage = self._determine_stage(context)

        # Build analysis prompt
        prompt = self._build_analysis_prompt(context, days_inactive, current_stage)

        messages = [
            SystemMessage(content=ANALYZER_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ]

        try:
            # Use worker with Haiku for fast analysis
            response = await submit_to_worker(
                messages=messages,
                model=settings.claude_model_fast,  # Haiku
                max_tokens=2000,
                estimated_output_tokens=500,
            )
            return self._parse_response(response.content)
        except Exception as e:
            logger.error(f"Error analyzing case file: {e}")
            raise

    def _calculate_inactivity(self, binnacles: list) -> int:
        """Calculate days since the last procedural action."""
        if not binnacles:
            return 0

        # Get most recent binnacle date
        last_date = None
        for binnacle in binnacles:
            binnacle_date = binnacle.get("date")
            if binnacle_date:
                if isinstance(binnacle_date, str):
                    try:
                        binnacle_date = datetime.fromisoformat(binnacle_date)
                    except ValueError:
                        continue
                if last_date is None or binnacle_date > last_date:
                    last_date = binnacle_date

        if not last_date:
            return 0

        delta = datetime.now() - last_date
        return max(0, delta.days)

    def _determine_stage(self, context: CaseContext) -> str:
        """Determine the current procedural stage."""
        # Check binnacles for stage info
        if context.binnacles:
            for binnacle in context.binnacles:
                stage = binnacle.get("procedural_stage")
                if stage:
                    return stage

        # Infer from process status
        process_status = context.process_status
        if process_status:
            status_upper = process_status.upper()
            if "EJECUCION" in status_upper:
                return "ETAPA DE EJECUCION"
            elif "SENTENCIA" in status_upper:
                return "ETAPA DECISORIA"
            elif "PRUEBA" in status_upper:
                return "ETAPA PROBATORIA"

        return "ETAPA POSTULATORIA"

    def _build_analysis_prompt(
        self,
        context: CaseContext,
        days_inactive: int,
        current_stage: str,
    ) -> str:
        """Build the analysis prompt with case data."""
        # Build document content section if available
        docs_section = self._format_extracted_documents(context.binnacle_documents)

        return f"""Analiza el siguiente expediente judicial y determina qué documento
es el más apropiado para presentar en este momento.

## DATOS DEL EXPEDIENTE
- Número: {context.case_number}
- Materia: {context.subject or 'N/A'}
- Vía Procedimental: {context.procedural_way or 'N/A'}
- Cliente (Deudor): {context.client_name}
- DNI/RUC: {context.client_dni_ruc or 'N/A'}
- Deuda en soles: S/ {context.amount_demanded_soles or 0:,.2f}
- Deuda en dólares: $ {context.amount_demanded_dollars or 0:,.2f}

## ESTADO PROCESAL
- Etapa actual: {current_stage}
- Días sin actividad: {days_inactive}
- Estado del proceso: {context.process_status or 'N/A'}

## GARANTÍAS ({len(context.collaterals)} registradas)
{self._format_collaterals(context.collaterals)}

## ÚLTIMAS 5 BITÁCORAS
{self._format_binnacles(context.binnacles[:5] if context.binnacles else [])}

{docs_section}

---

Basándote en toda esta información (incluyendo el contenido de los documentos si están disponibles):
1. Determina cuál es el documento MÁS URGENTE o NECESARIO a presentar
2. Explica brevemente por qué (máximo 2 oraciones)
3. Sugiere hasta 3 alternativas ordenadas por relevancia
4. Si no hay acción necesaria, indica la razón

Responde SOLO con JSON válido, sin texto adicional."""

    def _format_collaterals(self, collaterals: list) -> str:
        """Format collateral information."""
        if not collaterals:
            return "- No hay garantías registradas"

        lines = []
        for c in collaterals[:5]:  # Limit to 5
            kind = c.get("kind_of_property", "Inmueble")
            address = c.get("property_address", "Sin dirección")[:50]
            status = c.get("status", "N/A")
            value = c.get("appraisal_value", 0)
            lines.append(f"- {kind}: {address} - Estado: {status} - Valor: S/ {value:,.2f}")
        return "\n".join(lines)

    def _format_binnacles(self, binnacles: list) -> str:
        """Format binnacle entries."""
        if not binnacles:
            return "- No hay bitácoras registradas"

        lines = []
        for b in binnacles:
            date = b.get("date", "Sin fecha")
            if isinstance(date, datetime):
                date = date.strftime("%d/%m/%Y")
            desc = b.get("last_performed", "Sin descripción")[:80]
            lines.append(f"- [{date}] {desc}")
        return "\n".join(lines)

    def _format_extracted_documents(self, documents: list) -> str:
        """Format extracted document content from S3."""
        if not documents:
            return ""

        lines = ["## CONTENIDO DE DOCUMENTOS EXTRAÍDOS DE BITÁCORAS"]
        lines.append(f"(Se extrajeron {len(documents)} documentos del expediente)\n")

        for i, doc in enumerate(documents[:5], 1):  # Limit to 5 documents for analysis
            filename = doc.get("filename", "Sin nombre")
            binnacle_date = doc.get("binnacle_date", "N/A")
            binnacle_type = doc.get("binnacle_type", "N/A")
            text = doc.get("extracted_text", "")

            # Truncate text for analysis prompt (keep it focused)
            max_chars = 2000
            if len(text) > max_chars:
                text = text[:max_chars] + "\n[... texto truncado ...]"

            lines.append(f"### Documento {i}: {filename}")
            lines.append(f"- Fecha bitácora: {binnacle_date}")
            lines.append(f"- Tipo: {binnacle_type}")
            lines.append(f"- Contenido:\n{text}\n")

        return "\n".join(lines)

    def _parse_response(self, content: str) -> AnalysisResult:
        """Parse the LLM response into AnalysisResult."""
        try:
            # Clean response - extract JSON if wrapped in markdown
            content = content.strip()
            if content.startswith("```"):
                # Remove markdown code block
                lines = content.split("\n")
                content = "\n".join(lines[1:-1])

            data = json.loads(content)

            # Build suggestion if present
            suggestion = None
            if data.get("has_suggestion") and data.get("suggestion"):
                s = data["suggestion"]
                doc_type = s.get("document_type") or s.get("type", "unknown")
                doc_name = s.get("document_name") or s.get("name") or s.get("title")

                # If still no name, try to derive from document_type
                if not doc_name:
                    doc_name = doc_type.replace("_", " ").title()
                    logger.warning(f"Suggestion missing document_name, derived: {doc_name}")

                suggestion = DocumentSuggestion(
                    document_type=doc_type,
                    document_name=doc_name,
                    reason=s.get("reason", "Documento sugerido por el análisis"),
                    confidence=s.get("confidence", 0.8),
                )

            # Build alternatives
            alternatives = []
            for alt in data.get("alternatives", []):
                # Get document name, falling back to type if not provided
                doc_name = alt.get("document_name") or alt.get("name") or alt.get("title")
                doc_type = alt.get("document_type") or alt.get("type", "unknown")

                # If still no name, try to derive from document_type
                if not doc_name:
                    doc_name = doc_type.replace("_", " ").title()
                    logger.warning(f"Alternative missing document_name, derived: {doc_name}")

                alternatives.append(
                    DocumentSuggestion(
                        document_type=doc_type,
                        document_name=doc_name,
                        reason=alt.get("reason", "Documento alternativo sugerido"),
                        confidence=alt.get("confidence", 0.5),
                    )
                )

            # Build no action reason if present
            no_action = None
            if data.get("no_action_reason"):
                nar = data["no_action_reason"]
                no_action = NoActionReason(
                    reason_code=nar["reason_code"],
                    message=nar["message"],
                )

            return AnalysisResult(
                has_suggestion=data.get("has_suggestion", False),
                suggestion=suggestion,
                alternatives=alternatives,
                no_action_reason=no_action,
            )

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse analysis response: {e}")
            logger.debug(f"Response content: {content[:500]}")
            # Return a default no-suggestion result
            return AnalysisResult(
                has_suggestion=False,
                no_action_reason=NoActionReason(
                    reason_code="PARSE_ERROR",
                    message="Error al analizar la respuesta del agente",
                ),
            )
