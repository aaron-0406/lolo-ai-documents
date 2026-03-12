"""
ExecutionAgent - Specialist in Forced Execution and Auctions.
"""

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger

from app.config import settings
from app.models.schemas import CaseContext
from app.prompts.specialists import EXECUTION_SYSTEM_PROMPT
from app.utils.context_formatter import (
    format_extracted_documents,
    format_extrajudicial_context,
)
from app.utils.learning_override import learning_override_analyzer


class ExecutionAgent:
    """
    Specialist in Forced Execution and Auctions.
    Generates auction requests, adjudication, eviction, and appraisal requests.
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
        """Generate a document draft for execution matters."""
        logger.info(f"ExecutionAgent generating: {document_type}")

        prompt = self._build_prompt(document_type, context, custom_instructions)

        # CRITICAL: Remove default instructions that conflict with learnings
        if custom_instructions:
            prompt = await learning_override_analyzer.remove_conflicting_instructions(prompt, custom_instructions)

        messages = [
            SystemMessage(content=EXECUTION_SYSTEM_PROMPT),
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
        """Build the generation prompt for execution documents."""
        doc_name = document_type.replace("_", " ").upper()

        # Format collaterals for auction
        collaterals_text = self._format_collaterals_for_auction(context.collaterals)

        # Get last binnacle for reference
        last_binnacle = ""
        if context.binnacles:
            b = context.binnacles[0]
            last_binnacle = f"Resolución: {b.get('resolution_number', 'N/A')} - {b.get('last_performed', 'N/A')}"

        prompt = f"""Genera una {doc_name} con los siguientes datos:

## DATOS DEL EXPEDIENTE
- EXPEDIENTE: {context.case_number}
- JUZGADO: {context.court or '[JUZGADO]'}
- SECRETARIO: {context.secretary or '[SECRETARIO]'}
- CUADERNO: Principal

## REFERENCIA
- ÚLTIMA ACTUACIÓN: {last_binnacle or '[RESOLUCIÓN QUE APRUEBA TASACIÓN]'}

## DATOS DEL EJECUTANTE
- RAZÓN SOCIAL: {context.customer_name}
- RUC: {context.customer_ruc or '[RUC]'}

## DATOS DEL EJECUTADO
- NOMBRE: {context.client_name}
- DNI/RUC: {context.client_dni_ruc or '[DNI/RUC]'}

## DEUDA
- MONTO ADEUDADO: S/ {context.amount_demanded_soles or 0:,.2f}

## BIENES A REMATAR
{collaterals_text}
"""

        # Add specific content based on document type
        if document_type == "solicitud_remate":
            prompt += """
## PETITORIO ESPECÍFICO
Solicitar convocatoria a PRIMER REMATE PÚBLICO del(os) bien(es) descrito(s).
- Fijar fecha, hora y lugar del remate
- Designar Martillero Público de la nómina del Poder Judicial
- Ordenar publicación de avisos de ley
"""
        elif document_type == "solicitud_adjudicacion":
            prompt += """
## PETITORIO ESPECÍFICO
Solicitar ADJUDICACIÓN DIRECTA del bien a favor del ejecutante.
- Indicar que el remate quedó desierto en [NÚMERO] convocatorias
- Solicitar transferencia del bien por el valor de la adjudicación
"""
        elif document_type == "solicitud_lanzamiento":
            prompt += """
## PETITORIO ESPECÍFICO
Solicitar LANZAMIENTO del inmueble adjudicado/rematado.
- Indicar que el adjudicatario requiere posesión efectiva
- Solicitar auxilio de la fuerza pública
- Fijar fecha y hora para la diligencia
"""
        elif document_type == "solicitud_tasacion":
            prompt += """
## PETITORIO ESPECÍFICO
Solicitar nombramiento de PERITO TASADOR.
- Ordenar tasación comercial actualizada del(os) bien(es)
- Señalar plazo para presentación del informe pericial
"""

        # Add extracted document content if available
        if context.binnacle_documents:
            prompt += "\n" + format_extracted_documents(
                context.binnacle_documents,
                max_docs=5,
                max_chars_per_doc=2500,
            )

        # Add extrajudicial context
        if context.extrajudicial:
            prompt += "\n" + format_extrajudicial_context(
                context.extrajudicial,
                include_collection_history=True,
                include_files=True,
                max_collection_actions=10,
            )

        prompt += """
## INSTRUCCIONES POR DEFECTO
Genera el documento COMPLETO con formato de escrito procesal.
Incluye referencia a la resolución que corresponda.
Cita los artículos pertinentes del CPC (725-748).
Usa la información de los documentos extraídos para contextualizar mejor el escrito.
Usa el contexto extrajudicial para fundamentar montos, pagos parciales y saldos.
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

    def _format_collaterals_for_auction(self, collaterals: list) -> str:
        """Format collateral information for auction documents."""
        if not collaterals:
            return """### BIEN A REMATAR
- Partida Electrónica: [PARTIDA]
- Dirección: [DIRECCIÓN]
- Área: [ÁREA] m²
- Valor de Tasación: S/ [VALOR]
- Base del Remate (2/3): S/ [BASE]"""

        lines = []
        for i, c in enumerate(collaterals, 1):
            partida = c.get("registry_entry", "[PARTIDA]")
            address = c.get("property_address", "[DIRECCIÓN]")
            area = c.get("land_area", 0)
            value = c.get("appraisal_value", 0)
            base = value * 2 / 3  # 2/3 of appraisal value

            lines.append(f"""### BIEN {i}
- Partida Electrónica: {partida}
- Dirección: {address}
- Área: {area} m²
- Valor de Tasación: S/ {value:,.2f}
- Base del Remate (2/3): S/ {base:,.2f}
""")
        return "\n".join(lines)
