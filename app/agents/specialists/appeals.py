"""
AppealsAgent - Specialist in Appeals and Cassation.
"""

from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger

from app.config import settings
from app.models.schemas import CaseContext
from app.prompts.specialists import APPEALS_SYSTEM_PROMPT
from app.utils.context_formatter import (
    format_extracted_documents,
    format_extrajudicial_context,
)
from app.utils.learning_override import learning_override_analyzer
from app.utils.llm_worker import submit_to_worker


class AppealsAgent:
    """
    Specialist in Appellate Law.
    Generates appeals, cassation, complaints, and reconsideration requests.
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
    ) -> dict:
        """Generate a document draft for appeals matters.

        Returns:
            dict with 'draft' (str) and 'token_usage' (dict with input_tokens, output_tokens, model)
        """
        logger.info(f"AppealsAgent generating: {document_type}")

        prompt = self._build_prompt(document_type, context, custom_instructions)

        # CRITICAL: Remove default instructions that conflict with learnings
        if custom_instructions:
            prompt = await learning_override_analyzer.remove_conflicting_instructions(prompt, custom_instructions)

        messages = [
            SystemMessage(content=APPEALS_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ]

        # Use worker with Sonnet for high-quality generation
        llm_response = await submit_to_worker(
            messages=messages,
            model=settings.claude_model,  # Sonnet
            max_tokens=8000,
            estimated_output_tokens=4000,
        )
        return {
            "draft": llm_response.message.content,
            "token_usage": {
                "input_tokens": llm_response.token_usage.input_tokens,
                "output_tokens": llm_response.token_usage.output_tokens,
                "model": llm_response.token_usage.model,
            }
        }

    def _build_prompt(
        self,
        document_type: str,
        context: CaseContext,
        custom_instructions: str | None,
    ) -> str:
        """Build the generation prompt for appeals documents."""
        doc_name = document_type.replace("_", " ").upper()

        # Get resolution to appeal
        resolution_info = ""
        if context.binnacles:
            b = context.binnacles[0]
            resolution_info = f"""
- RESOLUCIÓN IMPUGNADA: {b.get('resolution_number', '[NÚMERO DE RESOLUCIÓN]')}
- FECHA DE RESOLUCIÓN: {b.get('resolution_date', '[FECHA]')}
- FECHA DE NOTIFICACIÓN: [FECHA DE NOTIFICACIÓN]
- CONTENIDO: {b.get('last_performed', '[DESCRIBIR CONTENIDO]')[:200]}
"""

        prompt = f"""Genera un {doc_name} con los siguientes datos:

## DATOS DEL EXPEDIENTE
- EXPEDIENTE: {context.case_number}
- JUZGADO/SALA: {context.court or '[ÓRGANO JURISDICCIONAL]'}
- SECRETARIO: {context.secretary or '[SECRETARIO]'}
- CUADERNO: Principal

## RESOLUCIÓN A IMPUGNAR
{resolution_info or '- [COMPLETAR DATOS DE LA RESOLUCIÓN IMPUGNADA]'}

## DATOS DEL IMPUGNANTE
- RAZÓN SOCIAL: {context.customer_name}
- RUC: {context.customer_ruc or '[RUC]'}
- ABOGADO: [NOMBRE DEL ABOGADO]
- DOMICILIO PROCESAL: [DOMICILIO PROCESAL]

## DATOS DE LA CONTRAPARTE
- NOMBRE: {context.client_name}
- DNI/RUC: {context.client_dni_ruc or '[DNI/RUC]'}
"""

        # Add specific content based on document type
        if document_type == "recurso_apelacion":
            prompt += """
## TIPO DE RECURSO
RECURSO DE APELACIÓN

## ESTRUCTURA REQUERIDA
1. SUMILLA: INTERPONGO RECURSO DE APELACIÓN
2. RESOLUCIÓN IMPUGNADA (número, fecha, contenido)
3. FUNDAMENTACIÓN DEL AGRAVIO:
   - Error in iudicando (error de derecho sustantivo)
   - Error in procedendo (error de procedimiento)
4. PRETENSIÓN IMPUGNATORIA:
   - Revocatoria total/parcial
   - Nulidad (si corresponde)
5. FUNDAMENTACIÓN JURÍDICA:
   - Arts. 364-383 CPC
   - Normas sustantivas infringidas
6. FIRMA Y FECHA

## PLAZOS
- Contra autos: 3 días hábiles
- Contra sentencias: 5 días hábiles
"""
        elif document_type == "recurso_casacion":
            prompt += """
## TIPO DE RECURSO
RECURSO DE CASACIÓN

## ESTRUCTURA REQUERIDA
1. SUMILLA: INTERPONGO RECURSO DE CASACIÓN
2. SENTENCIA DE VISTA IMPUGNADA
3. REQUISITOS DE ADMISIBILIDAD (Art. 387 CPC):
   - Interposición contra sentencia de segunda instancia
   - Ante órgano que emitió la resolución
   - Plazo de 10 días hábiles
4. REQUISITOS DE PROCEDENCIA (Art. 388 CPC):
   - Indicar naturaleza del agravio
   - Describir incidencia en la decisión
5. CAUSALES INVOCADAS (Art. 386 CPC):
   - Infracción normativa material
   - Infracción normativa procesal
   - Apartamiento de precedente vinculante
6. FUNDAMENTACIÓN DE CADA CAUSAL:
   - Norma infringida
   - Cómo se produce la infracción
   - Incidencia directa en el fallo
7. PRETENSIÓN CASATORIA:
   - Anulación y reenvío, o
   - Actuación en sede de instancia
8. FIRMA Y FECHA
"""
        elif document_type == "recurso_queja":
            prompt += """
## TIPO DE RECURSO
RECURSO DE QUEJA

## ESTRUCTURA REQUERIDA
1. SUMILLA: INTERPONGO RECURSO DE QUEJA
2. RESOLUCIÓN DENEGATORIA DE APELACIÓN/CASACIÓN
3. FUNDAMENTACIÓN:
   - Error en la denegación
   - Por qué procede el recurso denegado
4. PRETENSIÓN:
   - Declarar fundada la queja
   - Ordenar conceder el recurso indebidamente denegado
5. FIRMA Y FECHA

## PLAZOS
- 3 días hábiles desde notificación de denegación
- Ante el superior jerárquico
"""
        elif document_type == "recurso_reposicion":
            prompt += """
## TIPO DE RECURSO
RECURSO DE REPOSICIÓN

## ESTRUCTURA REQUERIDA
1. SUMILLA: INTERPONGO RECURSO DE REPOSICIÓN
2. DECRETO IMPUGNADO
3. FUNDAMENTACIÓN:
   - Error en el decreto
   - Petición correcta
4. FIRMA Y FECHA

## NOTA
- Solo procede contra DECRETOS
- Plazo: 3 días hábiles
- Resuelve el mismo juez
"""

        # Add extracted document content if available (especially relevant for appeals)
        if context.binnacle_documents:
            prompt += "\n" + format_extracted_documents(
                context.binnacle_documents,
                max_docs=8,  # More docs for appeals since they need to reference specific resolutions
                max_chars_per_doc=3000,
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
Genera el documento COMPLETO con todos los elementos requeridos.
Fundamenta claramente el agravio y la pretensión impugnatoria.
Cita los artículos específicos del CPC que correspondan.
Usa el contenido de los documentos extraídos para fundamentar el recurso,
especialmente el contenido de la resolución que se está impugnando.
Si hay acuerdos de pago incumplidos o historial de cobranza, úsalos como evidencia adicional del agravio.
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
