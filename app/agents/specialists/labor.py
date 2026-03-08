"""
LaborAgent - Specialist in Labor Law (Employer Defense).
"""

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger

from app.config import settings
from app.models.schemas import CaseContext
from app.prompts.specialists import LABOR_SYSTEM_PROMPT
from app.utils.context_formatter import (
    format_extracted_documents,
    format_extrajudicial_context,
)


class LaborAgent:
    """
    Specialist in Labor Law (Employer Defense).
    Generates responses to labor claims, appeals, and briefs.
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
        """Generate a document draft for labor matters."""
        logger.info(f"LaborAgent generating: {document_type}")

        prompt = self._build_prompt(document_type, context, custom_instructions)

        messages = [
            SystemMessage(content=LABOR_SYSTEM_PROMPT),
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
        """Build the generation prompt for labor documents."""
        doc_name = document_type.replace("_", " ").upper()

        prompt = f"""Genera una {doc_name} con los siguientes datos:

## DATOS DEL EXPEDIENTE
- EXPEDIENTE: {context.case_number}
- JUZGADO: {context.court or 'Juzgado Laboral'}
- SECRETARIO: {context.secretary or '[SECRETARIO]'}

## DATOS DEL DEMANDADO (EMPLEADOR - BANCO)
- RAZÓN SOCIAL: {context.customer_name}
- RUC: {context.customer_ruc or '[RUC DEL BANCO]'}
- REPRESENTANTE LEGAL: [REPRESENTANTE LEGAL]
- DOMICILIO PROCESAL: [DOMICILIO PROCESAL]

## DATOS DEL DEMANDANTE (EX TRABAJADOR)
- NOMBRE: {context.client_name}
- DNI: {context.client_dni_ruc or '[DNI]'}
- DOMICILIO: {context.client_address or '[DOMICILIO]'}
"""

        if document_type == "contestacion_laboral":
            prompt += """
## TIPO DE DOCUMENTO
CONTESTACIÓN DE DEMANDA LABORAL

## DATOS LABORALES DEL DEMANDANTE
- FECHA DE INGRESO: [FECHA DE INGRESO]
- FECHA DE CESE: [FECHA DE CESE]
- CARGO: [ÚLTIMO CARGO]
- ÚLTIMA REMUNERACIÓN: S/ [MONTO]
- MOTIVO DE CESE: [RENUNCIA/DESPIDO/MUTUO DISENSO]
- TIEMPO DE SERVICIOS: [AÑOS Y MESES]

## PRETENSIONES DEL DEMANDANTE
[Listar las pretensiones del demandante]
1. [ ] Reposición
2. [ ] Indemnización por despido arbitrario
3. [ ] CTS
4. [ ] Gratificaciones truncas
5. [ ] Vacaciones truncas
6. [ ] Horas extras
7. [ ] Utilidades
8. [ ] Otros: [ESPECIFICAR]

## ESTRUCTURA REQUERIDA
1. SUMILLA: CONTESTACIÓN DE DEMANDA
2. DATOS PROCESALES
3. PRONUNCIAMIENTO SOBRE PRETENSIONES:
   - Por cada pretensión: INFUNDADA/IMPROCEDENTE y por qué
4. PRONUNCIAMIENTO SOBRE HECHOS:
   - Negar o reconocer cada hecho con fundamento
5. HECHOS DE LA DEFENSA:
   - Relación laboral correctamente detallada
   - Beneficios debidamente pagados
   - Circunstancias del cese
6. FUNDAMENTOS DE DERECHO:
   - NLPT (Ley 29497)
   - D.S. 003-97-TR
   - Normas aplicables
7. MEDIOS PROBATORIOS:
   - Boletas de pago
   - Liquidación de beneficios sociales
   - Carta de renuncia/despido
   - Planillas
   - Otros
8. ANEXOS

## PLAZO
10 días hábiles desde notificación de la demanda
"""
        elif document_type == "apelacion_laboral":
            prompt += """
## TIPO DE DOCUMENTO
RECURSO DE APELACIÓN LABORAL

## SENTENCIA IMPUGNADA
- NÚMERO: [NÚMERO DE SENTENCIA]
- FECHA: [FECHA]
- CONTENIDO: [RESUMEN DEL FALLO]

## ESTRUCTURA REQUERIDA
1. SUMILLA: INTERPONGO RECURSO DE APELACIÓN
2. SENTENCIA IMPUGNADA
3. FUNDAMENTACIÓN DEL AGRAVIO:
   - Error de hecho
   - Error de derecho
   - Valoración de pruebas
4. PRETENSIÓN IMPUGNATORIA:
   - Revocar sentencia
   - Declarar infundada la demanda
5. FUNDAMENTACIÓN JURÍDICA:
   - Art. 32 NLPT
   - Normas sustantivas infringidas
6. FIRMA Y FECHA

## PLAZO
5 días hábiles desde notificación de sentencia
"""
        elif document_type == "casacion_laboral":
            prompt += """
## TIPO DE DOCUMENTO
RECURSO DE CASACIÓN LABORAL

## SENTENCIA DE VISTA IMPUGNADA
- SALA LABORAL: [SALA]
- NÚMERO: [NÚMERO]
- FECHA: [FECHA]

## ESTRUCTURA REQUERIDA
1. SUMILLA: INTERPONGO RECURSO DE CASACIÓN
2. SENTENCIA DE VISTA IMPUGNADA
3. REQUISITOS DE ADMISIBILIDAD (Art. 35 NLPT):
   - Monto mínimo (100 URP) o derecho de naturaleza constitucional
4. CAUSALES (Art. 34 NLPT):
   - Infracción normativa que incida directamente en la decisión
   - Apartamiento de precedentes vinculantes
5. FUNDAMENTACIÓN DE CAUSALES:
   - Norma infringida
   - Cómo se produce la infracción
   - Incidencia en el fallo
6. PRETENSIÓN CASATORIA
7. FIRMA Y FECHA

## PLAZO
10 días hábiles desde notificación de sentencia de vista
"""
        elif document_type == "alegatos_laborales":
            prompt += """
## TIPO DE DOCUMENTO
ESCRITO DE ALEGATOS

## ESTRUCTURA REQUERIDA
1. SUMILLA: ALEGATOS
2. DATOS PROCESALES
3. RESUMEN DE POSICIÓN:
   - Nuestra teoría del caso
   - Hechos probados a nuestro favor
4. ANÁLISIS DE PRUEBAS:
   - Pruebas que acreditan nuestra posición
   - Pruebas de contrario que fueron desvirtuadas
5. CONCLUSIONES:
   - Por qué debe declararse infundada la demanda
6. FIRMA Y FECHA

## OPORTUNIDAD
Después de la actuación probatoria, antes de sentencia
"""

        if custom_instructions:
            prompt += f"""
## INSTRUCCIONES ADICIONALES
{custom_instructions}
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
## INSTRUCCIONES FINALES
Genera el documento COMPLETO con todos los elementos requeridos.
Recuerda que el banco es el EMPLEADOR DEMANDADO.
Cita los artículos de la NLPT y normas laborales aplicables.
Enfócate en la defensa del empleador y los beneficios debidamente pagados.
Usa la información de los documentos extraídos como contexto adicional.
Si hay historial de cobranza o acuerdos previos, úsalos para contextualizar la relación laboral.
"""

        return prompt
