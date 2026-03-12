"""
ProceduralAgent - Specialist in Procedural Writings and Injunctions.
"""

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger

from app.config import settings
from app.models.schemas import CaseContext
from app.prompts.specialists import PROCEDURAL_SYSTEM_PROMPT
from app.utils.context_formatter import (
    format_extracted_documents,
    format_extrajudicial_context,
)
from app.utils.learning_override import learning_override_analyzer


class ProceduralAgent:
    """
    Specialist in Civil Procedural Law.
    Generates injunctions, procedural motions, and general legal briefs.
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
        """Generate a document draft for procedural matters."""
        logger.info(f"ProceduralAgent generating: {document_type}")
        if custom_instructions:
            logger.info(f"[LEARNINGS] Custom instructions received ({len(custom_instructions)} chars):\n{custom_instructions[:800]}")
        else:
            logger.warning("[LEARNINGS] No custom instructions received!")

        prompt = self._build_prompt(document_type, context, custom_instructions)

        # Log if learnings are in the prompt
        if "REGLAS DEL ESTUDIO" in prompt:
            logger.info("[LEARNINGS] ✓ Learnings ARE included in prompt")
        else:
            logger.warning("[LEARNINGS] ✗ Learnings NOT found in prompt")

        # CRITICAL: Remove default instructions that conflict with learnings
        if custom_instructions:
            prompt = await learning_override_analyzer.remove_conflicting_instructions(prompt, custom_instructions)

        # Log the complete prompt for debugging
        logger.info(f"[PROMPT] Complete prompt being sent to LLM ({len(prompt)} chars):\n{'='*50}\n{prompt}\n{'='*50}")

        messages = [
            SystemMessage(content=PROCEDURAL_SYSTEM_PROMPT),
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
        """Build the generation prompt for procedural documents."""
        doc_name = document_type.replace("_", " ").upper()

        # Get last binnacle for reference
        last_binnacle = ""
        last_resolution = ""
        if context.binnacles:
            b = context.binnacles[0]
            last_resolution = b.get("resolution_number", "N/A")
            last_binnacle = b.get("last_performed", "N/A")

        prompt = f"""Genera un {doc_name} con los siguientes datos:

## DATOS DEL EXPEDIENTE
- EXPEDIENTE: {context.case_number}
- JUZGADO: {context.court or '[JUZGADO]'}
- SECRETARIO: {context.secretary or '[SECRETARIO]'}
- CUADERNO: Principal

## REFERENCIA (si aplica)
- ÚLTIMA RESOLUCIÓN: {last_resolution}
- ÚLTIMA ACTUACIÓN: {last_binnacle}

## DATOS DEL SOLICITANTE
- RAZÓN SOCIAL: {context.customer_name}
- RUC: {context.customer_ruc or '[RUC]'}
- DOMICILIO PROCESAL: [DOMICILIO PROCESAL]

## DATOS DE LA CONTRAPARTE
- NOMBRE: {context.client_name}
- DNI/RUC: {context.client_dni_ruc or '[DNI/RUC]'}
"""

        # Add specific content based on document type
        if document_type == "medida_cautelar_fuera":
            prompt += self._get_injunction_prompt(context, "FUERA DE PROCESO")
        elif document_type == "medida_cautelar_dentro":
            prompt += self._get_injunction_prompt(context, "DENTRO DE PROCESO")
        elif document_type == "medida_cautelar_embargo":
            prompt += self._get_embargo_prompt(context)
        elif document_type == "escrito_impulso":
            prompt += """
## PETITORIO ESPECÍFICO
Solicitar IMPULSO PROCESAL del expediente.
- Indicar días de inactividad del proceso
- Solicitar que se dicte la resolución que corresponda
- Fundamentar interés en la prosecución del proceso
"""
        elif document_type == "escrito_subsanacion":
            prompt += """
## PETITORIO ESPECÍFICO
SUBSANAR las observaciones formuladas por el Juzgado.
- Hacer referencia a la resolución que observa
- Subsanar punto por punto cada observación
- Adjuntar documentos faltantes si corresponde
"""
        elif document_type == "escrito_apersonamiento":
            prompt += """
## PETITORIO ESPECÍFICO
APERSONARME al proceso en representación del demandante.
- Señalar domicilio procesal
- Delegar facultades generales y especiales
- Adjuntar poder vigente
"""
        elif document_type == "escrito_variacion_domicilio":
            prompt += """
## PETITORIO ESPECÍFICO
VARIAR DOMICILIO PROCESAL.
- Señalar nuevo domicilio procesal
- Solicitar que las notificaciones se dirijan al nuevo domicilio
"""
        elif document_type == "escrito_desistimiento":
            prompt += """
## PETITORIO ESPECÍFICO
DESISTIMIENTO del proceso/pretensión.
- Especificar si es desistimiento del proceso o de la pretensión
- Fundamentar las razones del desistimiento
- Solicitar archivo definitivo del expediente
"""
        else:
            prompt += """
## PETITORIO ESPECÍFICO
[Describir el petitorio específico del escrito]
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
Genera el documento COMPLETO con formato de escrito procesal.
Incluye fundamentos claros y numerados.
Cita los artículos pertinentes del CPC.
Usa la información de los documentos extraídos para contextualizar mejor el escrito.
Usa el contexto extrajudicial para:
- Fundamentar urgencia o necesidad de impulso
- Evidenciar gestiones previas y diligencia
- Incluir información relevante de la cobranza prejudicial
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

    def _get_injunction_prompt(self, context: CaseContext, tipo: str) -> str:
        """Get specific prompt for injunction requests."""
        collaterals_text = self._format_assets(context.collaterals)

        return f"""
## TIPO DE MEDIDA CAUTELAR
{tipo}

## DATOS ECONÓMICOS A CAUTELAR
- MONTO EN SOLES: S/ {context.amount_demanded_soles or 0:,.2f}
- MONTO EN DÓLARES: $ {context.amount_demanded_dollars or 0:,.2f}

## BIENES SOBRE LOS QUE RECAE LA MEDIDA
{collaterals_text}

## PETITORIO ESPECÍFICO
Solicitar MEDIDA CAUTELAR de [TIPO: embargo en forma de inscripción/retención/secuestro].
- Verosimilitud del derecho (fumus boni iuris)
- Peligro en la demora (periculum in mora)
- Ofrecer contracautela (caución juratoria)

## CONTRACAUTELA
Ofrecer caución juratoria de acuerdo a ley.
"""

    def _get_embargo_prompt(self, context: CaseContext) -> str:
        """Get specific prompt for embargo requests."""
        return f"""
## TIPO DE EMBARGO
Embargo en forma de [INSCRIPCIÓN/RETENCIÓN/SECUESTRO]

## MONTO A EMBARGAR
- MONTO: S/ {context.amount_demanded_soles or 0:,.2f}

## BIENES A EMBARGAR
[Describir bienes específicos: cuentas bancarias, inmuebles, vehículos]

## PETITORIO ESPECÍFICO
Solicitar EMBARGO de los bienes del demandado.
- Identificar bienes específicos
- Indicar monto a embargar
- Solicitar oficio a entidades correspondientes
"""

    def _format_assets(self, collaterals: list) -> str:
        """Format assets for injunction requests."""
        if not collaterals:
            return """- [IDENTIFICAR BIENES DEL DEMANDADO]
  - Inmuebles: [PARTIDA REGISTRAL]
  - Cuentas bancarias: [SOLICITAR INFORMACIÓN]
  - Vehículos: [PLACA]"""

        lines = []
        for c in collaterals[:3]:
            partida = c.get("registry_entry", "[PARTIDA]")
            address = c.get("property_address", "[DIRECCIÓN]")
            lines.append(f"- Inmueble: {address} (Partida: {partida})")
        return "\n".join(lines)
