"""
ConstitutionalAgent - Specialist in Constitutional Law.
"""

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger

from app.config import settings
from app.models.schemas import CaseContext
from app.prompts.specialists import CONSTITUTIONAL_SYSTEM_PROMPT
from app.utils.context_formatter import (
    format_extracted_documents,
    format_extrajudicial_context,
)
from app.utils.learning_override import learning_override_analyzer


class ConstitutionalAgent:
    """
    Specialist in Constitutional Procedural Law.
    Generates amparo actions, constitutional appeals, and responses.
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
        """Generate a document draft for constitutional matters."""
        logger.info(f"ConstitutionalAgent generating: {document_type}")

        prompt = self._build_prompt(document_type, context, custom_instructions)

        # CRITICAL: Remove default instructions that conflict with learnings
        if custom_instructions:
            prompt = await learning_override_analyzer.remove_conflicting_instructions(prompt, custom_instructions)

        messages = [
            SystemMessage(content=CONSTITUTIONAL_SYSTEM_PROMPT),
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
        """Build the generation prompt for constitutional documents."""
        doc_name = document_type.replace("_", " ").upper()

        prompt = f"""Genera una {doc_name} con los siguientes datos:

## DATOS DEL EXPEDIENTE
- EXPEDIENTE: {context.case_number or 'NUEVO'}
- JUZGADO: {context.court or 'Juzgado Constitucional a designar'}
"""

        if document_type == "demanda_amparo":
            prompt += f"""
## TIPO DE PROCESO
ACCIÓN DE AMPARO

## DATOS DEL DEMANDANTE (AGRAVIADO)
- NOMBRE: {context.customer_name}
- RUC: {context.customer_ruc or '[RUC]'}
- REPRESENTANTE: [REPRESENTANTE LEGAL]
- DOMICILIO PROCESAL: [DOMICILIO]

## DATOS DEL DEMANDADO (AGRESOR)
- ENTIDAD: [ENTIDAD QUE VULNERA DERECHOS]
- REPRESENTANTE: [REPRESENTANTE]
- DOMICILIO: [DOMICILIO]

## DERECHO CONSTITUCIONAL VULNERADO
[Identificar el derecho afectado]
- [ ] Art. 2 inc. 1 Const.: Derecho a la vida
- [ ] Art. 2 inc. 2 Const.: Igualdad ante la ley
- [ ] Art. 2 inc. 16 Const.: Derecho de propiedad
- [ ] Art. 62 Const.: Libertad de contratación
- [ ] Art. 70 Const.: Derecho de propiedad
- [ ] Art. 139 inc. 3 Const.: Debido proceso
- [ ] Art. 139 inc. 14 Const.: Derecho de defensa
- [ ] Otro: [ESPECIFICAR]

## ACTO LESIVO
- DESCRIPCIÓN: [DESCRIBIR EL ACTO QUE VULNERA EL DERECHO]
- FECHA: [FECHA DEL ACTO LESIVO]
- CONSECUENCIAS: [PERJUICIO CAUSADO]

## ESTRUCTURA REQUERIDA
1. SUMILLA: DEMANDA DE ACCIÓN DE AMPARO
2. DATOS DE LAS PARTES
3. PETITORIO:
   - Declarar fundada la demanda
   - Ordenar el cese de la vulneración
   - Restituir el derecho afectado
4. DERECHOS VULNERADOS (con artículo constitucional)
5. FUNDAMENTOS DE HECHO (cronológico)
6. VÍA PROCESAL (por qué no hay otra vía igualmente satisfactoria)
7. FUNDAMENTOS DE DERECHO
8. MEDIOS PROBATORIOS
9. ANEXOS

## PLAZO
60 días hábiles desde la vulneración del derecho
"""
        elif document_type == "contestacion_amparo":
            prompt += f"""
## TIPO DE PROCESO
CONTESTACIÓN DE DEMANDA DE AMPARO

## DATOS DEL DEMANDADO (BANCO)
- RAZÓN SOCIAL: {context.customer_name}
- RUC: {context.customer_ruc or '[RUC]'}
- REPRESENTANTE: [REPRESENTANTE LEGAL]
- DOMICILIO PROCESAL: [DOMICILIO]

## DATOS DEL DEMANDANTE (DEUDOR/EX CLIENTE)
- NOMBRE: {context.client_name}
- DNI/RUC: {context.client_dni_ruc or '[DNI/RUC]'}

## ESTRUCTURA REQUERIDA
1. SUMILLA: CONTESTACIÓN DE DEMANDA DE AMPARO
2. DATOS PROCESALES
3. PRONUNCIAMIENTO SOBRE HECHOS:
   - Negar o reconocer cada hecho expuesto
4. DEFENSA DE FONDO:
   - No existe vulneración de derecho constitucional
   - Actuación conforme a ley y contrato
   - Existe vía igualmente satisfactoria (proceso civil)
5. EXCEPCIONES (si aplica):
   - Incompetencia
   - Falta de agotamiento de vía previa
   - Caducidad (Art. 44 CPConst: 60 días)
6. FUNDAMENTOS DE DERECHO
7. MEDIOS PROBATORIOS
8. ANEXOS

## PLAZO
5 días hábiles desde notificación
"""
        elif document_type == "recurso_agravio_constitucional":
            prompt += f"""
## TIPO DE RECURSO
RECURSO DE AGRAVIO CONSTITUCIONAL (RAC)

## DATOS DEL RECURRENTE
- NOMBRE: {context.customer_name}
- RUC: {context.customer_ruc or '[RUC]'}

## SENTENCIA IMPUGNADA
- SALA SUPERIOR: [SALA QUE EMITIÓ LA SENTENCIA]
- NÚMERO DE SENTENCIA: [NÚMERO]
- FECHA: [FECHA]

## ESTRUCTURA REQUERIDA
1. SUMILLA: INTERPONGO RECURSO DE AGRAVIO CONSTITUCIONAL
2. SENTENCIA DE VISTA IMPUGNADA
3. FUNDAMENTACIÓN:
   - Error de la Sala al denegar el amparo
   - Vulneración del derecho constitucional
   - Precedentes del TC aplicables
4. PRETENSIÓN:
   - Declarar fundado el RAC
   - Revocar sentencia de vista
   - Amparar la pretensión
5. FIRMA Y FECHA

## PLAZO
10 días hábiles desde notificación de sentencia denegatoria
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
Genera el documento COMPLETO con todos los elementos requeridos.
Cita los artículos de la Constitución y del Código Procesal Constitucional.
Incluye jurisprudencia relevante del Tribunal Constitucional si aplica.
Usa la información de los documentos extraídos como contexto adicional.
Si hay historial de cobranza o acuerdos, utilízalos para demostrar la actuación conforme a derecho.
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
