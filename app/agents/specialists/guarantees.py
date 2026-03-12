"""
GuaranteesAgent - Specialist in Real Estate Guarantees.
"""

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger

from app.config import settings
from app.models.schemas import CaseContext
from app.prompts.specialists import GUARANTEES_SYSTEM_PROMPT
from app.utils.context_formatter import (
    format_extracted_documents,
    format_extrajudicial_context,
)
from app.utils.learning_override import learning_override_analyzer


class GuaranteesAgent:
    """
    Specialist in Real Guarantees Law.
    Generates mortgage execution and collateral seizure claims.
    """

    def __init__(self):
        self.llm = ChatAnthropic(
            model=settings.claude_model,
            max_tokens=8000,
            api_key=settings.anthropic_api_key,
        )

    async def generate_draft(
        self,
        document_type: str,
        context: CaseContext,
        custom_instructions: str | None = None,
    ) -> str:
        """Generate a document draft for guarantee matters."""
        logger.info(f"GuaranteesAgent generating: {document_type}")

        # Verify collaterals exist for guarantee execution
        if not context.collaterals:
            logger.warning("No collaterals found for guarantee execution")

        prompt = self._build_prompt(document_type, context, custom_instructions)

        # CRITICAL: Remove default instructions that conflict with learnings
        if custom_instructions:
            prompt = await learning_override_analyzer.remove_conflicting_instructions(prompt, custom_instructions)

        messages = [
            SystemMessage(content=GUARANTEES_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ]

        response = await self.llm.ainvoke(messages)
        return response.content

    def _build_prompt(
        self,
        document_type: str,
        context: CaseContext,
        custom_instructions: str | None,
    ) -> str:
        """Build the generation prompt with collateral data."""
        doc_name = document_type.replace("_", " ").upper()

        # Format collaterals
        collaterals_text = self._format_collaterals(context.collaterals)

        prompt = f"""Genera una {doc_name} con los siguientes datos:

## DATOS DEL EXPEDIENTE
- EXPEDIENTE: {context.case_number or 'NUEVO'}
- JUZGADO: {context.court or 'A designar por Mesa de Partes'}

## DATOS DEL DEMANDANTE (ACREEDOR HIPOTECARIO)
- RAZÓN SOCIAL: {context.customer_name}
- RUC: {context.customer_ruc or '[RUC DEL BANCO]'}
- REPRESENTANTE LEGAL: [NOMBRE DEL REPRESENTANTE]
- DOMICILIO PROCESAL: [DOMICILIO PROCESAL]

## DATOS DEL DEMANDADO (DEUDOR HIPOTECARIO)
- NOMBRE: {context.client_name}
- DNI/RUC: {context.client_dni_ruc or '[DNI/RUC]'}
- DOMICILIO: {context.client_address or '[DOMICILIO DEL DEMANDADO]'}

## DATOS ECONÓMICOS (SALDO DEUDOR)
- MONTO EN SOLES: S/ {context.amount_demanded_soles or 0:,.2f}
- MONTO EN DÓLARES: $ {context.amount_demanded_dollars or 0:,.2f}
- INTERESES: [CALCULAR SEGÚN CONTRATO]

## GARANTÍAS HIPOTECARIAS
{collaterals_text}

## MATERIA Y VÍA
- MATERIA: Ejecución de Garantías
- VÍA PROCEDIMENTAL: Proceso de Ejecución de Garantías
"""

        # Add extracted document content if available
        if context.binnacle_documents:
            prompt += "\n" + format_extracted_documents(
                context.binnacle_documents,
                max_docs=5,
                max_chars_per_doc=2500,
            )

        # Add extrajudicial context (collection history, agreements, payments)
        if context.extrajudicial:
            prompt += "\n" + format_extrajudicial_context(
                context.extrajudicial,
                include_collection_history=True,
                include_files=True,
                max_collection_actions=10,
            )

        prompt += """
## INSTRUCCIONES POR DEFECTO
Genera el documento COMPLETO siguiendo la estructura obligatoria.
Incluye descripción detallada de cada garantía hipotecaria.
Cita los artículos 720-724 del CPC y artículos relevantes del CC.
Lista los anexos obligatorios: partida registral, tasación, estado de cuenta.
Usa la información de los documentos extraídos como contexto adicional.
Si hay acuerdos de pago o historial de cobranza, úsalos para documentar los requerimientos previos y el saldo deudor.
"""

        # CRITICAL: Add custom instructions (learnings) at the END for maximum priority
        if custom_instructions:
            prompt += f"""
---
{custom_instructions}

⚠️ PRIORIDAD MÁXIMA: Las REGLAS DEL ESTUDIO JURÍDICO anteriores SOBREESCRIBEN cualquier instrucción previa.
Si las reglas dicen "sin numeración", NO numeres aunque arriba diga "numerados".
Si las reglas dicen "unificar secciones", hazlo aunque la estructura por defecto sea diferente.
SIEMPRE prevalecen las reglas del estudio sobre las instrucciones por defecto.
"""

        return prompt

    def _format_collaterals(self, collaterals: list) -> str:
        """Format collateral information."""
        if not collaterals:
            return """- [COMPLETAR DATOS DE GARANTÍA]
  - Partida Electrónica: [NÚMERO]
  - Dirección: [DIRECCIÓN COMPLETA]
  - Valor de Tasación: S/ [MONTO]"""

        lines = []
        for i, c in enumerate(collaterals, 1):
            partida = c.get("registry_entry", "[PARTIDA]")
            address = c.get("property_address", "[DIRECCIÓN]")
            dept = c.get("department", "")
            prov = c.get("province", "")
            dist = c.get("district", "")
            location = f"{dist}, {prov}, {dept}".strip(", ")
            area = c.get("land_area", 0)
            value = c.get("appraisal_value", 0)
            status = c.get("status", "Vigente")

            lines.append(f"""### GARANTÍA {i}
- Partida Electrónica: {partida}
- Dirección: {address}
- Ubicación: {location}
- Área del Terreno: {area} m²
- Valor de Tasación: S/ {value:,.2f}
- Estado: {status}
""")
        return "\n".join(lines)
