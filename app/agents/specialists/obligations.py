"""
ObligationsAgent - Specialist in Civil Obligations and ODS.
"""

from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger

from app.config import settings
from app.models.schemas import CaseContext
from app.prompts.specialists import OBLIGATIONS_SYSTEM_PROMPT
from app.utils.context_formatter import (
    format_extracted_documents,
    format_extrajudicial_context,
)
from app.utils.learning_override import learning_override_analyzer
from app.utils.llm_worker import submit_to_worker


class ObligationsAgent:
    """
    Specialist in Civil Law - Obligations.
    Generates ODS demands and leasing breach claims.
    Uses Sonnet for high-quality document generation.
    """

    def __init__(self):
        # No LLM instance needed - using worker
        pass

    async def generate_draft(
        self,
        document_type: str,
        context: CaseContext,
        custom_instructions: str | None = None,
    ) -> str:
        """Generate a document draft for obligations matters."""
        logger.info(f"ObligationsAgent generating: {document_type}")

        prompt = self._build_prompt(document_type, context, custom_instructions)

        # CRITICAL: Remove default instructions that conflict with learnings
        if custom_instructions:
            prompt = await learning_override_analyzer.remove_conflicting_instructions(prompt, custom_instructions)

        messages = [
            SystemMessage(content=OBLIGATIONS_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ]

        # Use worker with Sonnet for high-quality generation
        response = await submit_to_worker(
            messages=messages,
            model=settings.claude_model,  # Sonnet
            max_tokens=8000,
            estimated_output_tokens=4000,
        )
        return response.content

    def _build_prompt(
        self,
        document_type: str,
        context: CaseContext,
        custom_instructions: str | None,
    ) -> str:
        """Build the generation prompt with case data."""
        doc_name = document_type.replace("_", " ").upper()

        # Format products/credits
        products_text = self._format_products(context.products)

        prompt = f"""Genera una {doc_name} con los siguientes datos:

## DATOS DEL EXPEDIENTE
- EXPEDIENTE: {context.case_number or 'NUEVO'}
- JUZGADO: {context.court or 'A designar por Mesa de Partes'}

## DATOS DEL DEMANDANTE
- RAZÓN SOCIAL: {context.customer_name}
- RUC: {context.customer_ruc or '[RUC DEL BANCO]'}
- REPRESENTANTE LEGAL: [NOMBRE DEL REPRESENTANTE]
- DOMICILIO PROCESAL: [DOMICILIO PROCESAL]

## DATOS DEL DEMANDADO
- NOMBRE: {context.client_name}
- DNI/RUC: {context.client_dni_ruc or '[DNI/RUC]'}
- DOMICILIO: {context.client_address or '[DOMICILIO DEL DEMANDADO]'}

## DATOS ECONÓMICOS
- MONTO EN SOLES: S/ {context.amount_demanded_soles or 0:,.2f}
- MONTO EN DÓLARES: $ {context.amount_demanded_dollars or 0:,.2f}
- TIPO DE CAMBIO: S/ [TIPO DE CAMBIO]

## PRODUCTOS/CRÉDITOS
{products_text}

## MATERIA Y VÍA
- MATERIA: Obligación de Dar Suma de Dinero
- VÍA PROCEDIMENTAL: Proceso Único de Ejecución
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
Incluye TODOS los fundamentos de hecho numerados.
Incluye TODOS los fundamentos de derecho con artículos específicos.
Lista TODOS los anexos necesarios.
Usa la información de los documentos extraídos como contexto adicional.
Usa el contexto extrajudicial (historial de cobranza, convenios, pagos) para:
- Demostrar la mora del deudor
- Evidenciar gestiones de cobro prejudicial realizadas
- Incluir información de pagos parciales si los hay
- Calcular saldos deudores actualizados
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

    def _format_products(self, products: list) -> str:
        """Format product/credit information."""
        if not products:
            return "- No hay productos registrados. [COMPLETAR CON DATOS DEL CRÉDITO]"

        lines = []
        for p in products:
            desc = p.get("description", "Crédito")
            amount = p.get("amount", 0)
            currency = p.get("currency", "PEN")
            symbol = "S/" if currency == "PEN" else "$"
            lines.append(f"- {desc}: {symbol} {amount:,.2f}")
        return "\n".join(lines)
