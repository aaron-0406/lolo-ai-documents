"""
CivilLitigationAgent - Specialist in Complex Civil Litigation.
"""

from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger

from app.config import settings
from app.models.schemas import CaseContext
from app.prompts.specialists import CIVIL_LITIGATION_SYSTEM_PROMPT
from app.utils.context_formatter import (
    format_extracted_documents,
    format_extrajudicial_context,
)
from app.utils.learning_override import learning_override_analyzer
from app.utils.llm_worker import submit_to_worker


class CivilLitigationAgent:
    """
    Specialist in Complex Civil Litigation.
    Generates Paulian action and nullity claims.
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
        """Generate a document draft for civil litigation matters."""
        logger.info(f"CivilLitigationAgent generating: {document_type}")

        prompt = self._build_prompt(document_type, context, custom_instructions)

        # CRITICAL: Remove default instructions that conflict with learnings
        if custom_instructions:
            prompt = await learning_override_analyzer.remove_conflicting_instructions(prompt, custom_instructions)

        messages = [
            SystemMessage(content=CIVIL_LITIGATION_SYSTEM_PROMPT),
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
        """Build the generation prompt for civil litigation documents."""
        doc_name = document_type.replace("_", " ").upper()

        prompt = f"""Genera una {doc_name} con los siguientes datos:

## DATOS DEL EXPEDIENTE
- EXPEDIENTE: {context.case_number or 'NUEVO'}
- JUZGADO: {context.court or 'A designar por Mesa de Partes'}

## DATOS DEL DEMANDANTE (ACREEDOR PERJUDICADO)
- RAZÓN SOCIAL: {context.customer_name}
- RUC: {context.customer_ruc or '[RUC DEL BANCO]'}
- REPRESENTANTE LEGAL: [NOMBRE DEL REPRESENTANTE]
- DOMICILIO PROCESAL: [DOMICILIO PROCESAL]

## DATOS DEL DEMANDADO (DEUDOR)
- NOMBRE: {context.client_name}
- DNI/RUC: {context.client_dni_ruc or '[DNI/RUC]'}
- DOMICILIO: {context.client_address or '[DOMICILIO DEL DEUDOR]'}

## CRÉDITO ADEUDADO
- MONTO EN SOLES: S/ {context.amount_demanded_soles or 0:,.2f}
- MONTO EN DÓLARES: $ {context.amount_demanded_dollars or 0:,.2f}
- FECHA DE ORIGEN DEL CRÉDITO: [FECHA DE ORIGEN]
- TÍTULO EJECUTIVO: [PAGARÉ/LETRA/CONTRATO]
"""

        if document_type == "demanda_accion_pauliana":
            prompt += """
## TIPO DE DEMANDA
ACCIÓN PAULIANA (Ineficacia de Acto Jurídico)

## TERCERO ADQUIRENTE (si aplica)
- NOMBRE: [NOMBRE DEL TERCERO]
- DNI/RUC: [DNI/RUC DEL TERCERO]
- DOMICILIO: [DOMICILIO DEL TERCERO]

## ACTO JURÍDICO IMPUGNADO
- TIPO DE ACTO: [COMPRAVENTA/DONACIÓN/ANTICIPO DE LEGÍTIMA]
- FECHA DEL ACTO: [FECHA]
- BIEN TRANSFERIDO: [DESCRIPCIÓN DEL BIEN]
- VALOR DEL BIEN: S/ [VALOR]
- INSCRIPCIÓN REGISTRAL: [PARTIDA ELECTRÓNICA]

## ELEMENTOS A ACREDITAR (Art. 195 CC)
1. CRÉDITO ANTERIOR AL ACTO:
   - Fecha del crédito: [ANTERIOR AL ACTO]
   - Fecha del acto impugnado: [POSTERIOR AL CRÉDITO]

2. EVENTUS DAMNI (Perjuicio al acreedor):
   - Insolvencia del deudor tras el acto
   - Imposibilidad de cobrar el crédito

3. CONSILIUM FRAUDIS (Conocimiento del fraude):
   - Conocimiento del deudor del perjuicio
   - Si es oneroso: mala fe del tercero

## PETITORIO
1. Declarar INEFICAZ el acto jurídico de [TIPO] celebrado entre [DEUDOR] y [TERCERO] con fecha [FECHA]
2. Ordenar la INSCRIPCIÓN de la sentencia en el Registro de Propiedad Inmueble
3. Pago de costas y costos del proceso

## FUNDAMENTOS DE DERECHO
- Art. 195 CC: Requisitos de la acción pauliana
- Art. 196 CC: Presunción de perjuicio
- Art. 197 CC: Acción contra subadquirente
- Art. 199 CC: Imprescriptibilidad respecto del deudor
- Art. 200 CC: Plazo de prescripción (2 años)
- Art. 475 CPC: Proceso de conocimiento
"""
        elif document_type == "demanda_nulidad_acto":
            prompt += """
## TIPO DE DEMANDA
NULIDAD DE ACTO JURÍDICO

## ACTO JURÍDICO IMPUGNADO
- TIPO DE ACTO: [CONTRATO/ESCRITURA/DOCUMENTO]
- FECHA DEL ACTO: [FECHA]
- PARTES DEL ACTO: [PARTES INTERVINIENTES]
- INSCRIPCIÓN REGISTRAL: [SI APLICA]

## CAUSAL DE NULIDAD INVOCADA (Art. 219 CC)
[Seleccionar la(s) causal(es) aplicable(s)]
1. [ ] Falta de manifestación de voluntad del agente
2. [ ] Incapacidad absoluta
3. [ ] Objeto física o jurídicamente imposible
4. [ ] Fin ilícito
5. [ ] Simulación absoluta
6. [ ] Falta de formalidad prescrita bajo sanción de nulidad
7. [ ] Declaración nula por ley
8. [ ] Contrario al orden público o buenas costumbres

## HECHOS QUE CONFIGURAN LA NULIDAD
[Describir detalladamente los hechos que configuran la causal invocada]

## PETITORIO
1. Declarar NULO el acto jurídico de [TIPO] de fecha [FECHA]
2. Ordenar la CANCELACIÓN de la inscripción registral (si aplica)
3. Ordenar la RESTITUCIÓN de los bienes (si aplica)
4. Pago de costas y costos del proceso

## FUNDAMENTOS DE DERECHO
- Art. 219 CC: Causales de nulidad
- Art. 220 CC: Legitimación para alegar nulidad
- Art. 2001 inc. 1 CC: Prescripción (10 años)
- Art. 475 CPC: Proceso de conocimiento
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
                max_collection_actions=15,
            )

        prompt += """
## INSTRUCCIONES POR DEFECTO
Genera el documento COMPLETO con todos los elementos requeridos.
Incluye fundamentos de hecho y derecho detallados y numerados.
Cita los artículos específicos del Código Civil y CPC.
Lista todos los medios probatorios necesarios.
Usa la información de los documentos extraídos como contexto adicional.
Si hay acuerdos de pago incumplidos o historial de cobranza, úsalos para acreditar el eventus damni y consilium fraudis.
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
