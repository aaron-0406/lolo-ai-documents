"""
Template for generic procedural writings (escritos procesales).
"""

from app.templates.base import DocumentTemplate, TemplateSection

ESCRITO_PROCESAL_TEMPLATE = DocumentTemplate(
    document_type="escrito_procesal",
    document_name="Escrito Procesal",
    description="Plantilla genérica para escritos procesales",
    required_context=[
        "case_number",
        "court",
        "secretary",
        "customer_name",
    ],
    sections=[
        TemplateSection(
            name="SUMILLA",
            order=1,
            content_template="SUMILLA: {sumilla}",
            placeholders=["sumilla"],
        ),
        TemplateSection(
            name="DATOS_PROCESALES",
            order=2,
            content_template="""SECRETARIO: {secretary}
EXPEDIENTE: {case_number}
CUADERNO: {notebook}
ESCRITO N°: {escrito_number}""",
            placeholders=["secretary", "case_number", "notebook", "escrito_number"],
        ),
        TemplateSection(
            name="REFERENCIA",
            order=3,
            content_template="""REFERENCIA: Resolución N° {resolution_number} de fecha {resolution_date}""",
            placeholders=["resolution_number", "resolution_date"],
            required=False,
        ),
        TemplateSection(
            name="IDENTIFICACION",
            order=4,
            content_template="""{customer_name}, debidamente representado por su abogado que suscribe,
con domicilio procesal en {procedural_address}, en los seguidos contra
{client_name}, sobre {subject}; a Ud. atentamente digo:""",
            placeholders=["customer_name", "procedural_address", "client_name", "subject"],
        ),
        TemplateSection(
            name="PETITORIO",
            order=5,
            content_template="""I. PETITORIO

Que, por medio del presente escrito, solicito a su Despacho:

{petitorio_content}""",
            placeholders=["petitorio_content"],
        ),
        TemplateSection(
            name="FUNDAMENTOS",
            order=6,
            content_template="""II. FUNDAMENTOS

{fundamentos_content}""",
            placeholders=["fundamentos_content"],
        ),
        TemplateSection(
            name="ANEXOS",
            order=7,
            content_template="""III. ANEXOS

{anexos_content}""",
            placeholders=["anexos_content"],
            required=False,
        ),
        TemplateSection(
            name="FIRMA",
            order=8,
            content_template="""POR TANTO:
A Ud. pido acceder a lo solicitado por ser de ley.

{city}, {date}


_________________________________
{lawyer_name}
Abogado
Reg. CAL N° {cal_number}""",
            placeholders=["city", "date", "lawyer_name", "cal_number"],
        ),
    ],
)


# Specific templates for common procedural writings

ESCRITO_IMPULSO_TEMPLATE = DocumentTemplate(
    document_type="escrito_impulso",
    document_name="Escrito de Impulso Procesal",
    description="Escrito para solicitar impulso del proceso por inactividad",
    required_context=["case_number", "court", "secretary", "customer_name"],
    sections=[
        TemplateSection(
            name="SUMILLA",
            order=1,
            content_template="SUMILLA: SOLICITO IMPULSO PROCESAL",
            placeholders=[],
        ),
        TemplateSection(
            name="DATOS_PROCESALES",
            order=2,
            content_template="""SECRETARIO: {secretary}
EXPEDIENTE: {case_number}
CUADERNO: Principal""",
            placeholders=["secretary", "case_number"],
        ),
        TemplateSection(
            name="CUERPO",
            order=3,
            content_template="""{customer_name}, debidamente representado, en los seguidos contra
{client_name}, sobre {subject}; a Ud. atentamente digo:

Que, habiendo transcurrido más de {days_inactive} días sin que se haya
emitido resolución alguna en el presente proceso, solicito a su Despacho
se sirva IMPULSAR EL PROCESO, dictando la resolución que corresponda según
el estado de la causa.

Fundamento mi pedido en el principio de celeridad procesal consagrado en
el artículo V del Título Preliminar del Código Procesal Civil, así como
en el derecho a un proceso sin dilaciones indebidas.

POR TANTO:
Solicito a Ud. acceder a lo solicitado.

{city}, {date}


_________________________________
{lawyer_name}
Abogado
Reg. CAL N° {cal_number}""",
            placeholders=[
                "customer_name", "client_name", "subject", "days_inactive",
                "city", "date", "lawyer_name", "cal_number"
            ],
        ),
    ],
)


ESCRITO_SUBSANACION_TEMPLATE = DocumentTemplate(
    document_type="escrito_subsanacion",
    document_name="Escrito de Subsanación",
    description="Escrito para subsanar observaciones del juzgado",
    required_context=["case_number", "court", "secretary", "customer_name"],
    sections=[
        TemplateSection(
            name="SUMILLA",
            order=1,
            content_template="SUMILLA: SUBSANO OBSERVACIONES",
            placeholders=[],
        ),
        TemplateSection(
            name="DATOS_PROCESALES",
            order=2,
            content_template="""SECRETARIO: {secretary}
EXPEDIENTE: {case_number}
CUADERNO: Principal
REFERENCIA: Resolución N° {resolution_number} de fecha {resolution_date}""",
            placeholders=["secretary", "case_number", "resolution_number", "resolution_date"],
        ),
        TemplateSection(
            name="CUERPO",
            order=3,
            content_template="""{customer_name}, debidamente representado, en los seguidos contra
{client_name}, sobre {subject}; a Ud. atentamente digo:

Que, en cumplimiento de lo ordenado en la Resolución N° {resolution_number}
de fecha {resolution_date}, procedo a SUBSANAR las observaciones formuladas
por su Despacho, conforme al siguiente detalle:

{subsanacion_detalle}

En tal sentido, habiendo cumplido con subsanar las observaciones indicadas,
solicito se tenga por subsanada la demanda y se proceda conforme a ley.

POR TANTO:
Solicito a Ud. tener por subsanadas las observaciones y continuar con el
trámite del proceso.

{city}, {date}


_________________________________
{lawyer_name}
Abogado
Reg. CAL N° {cal_number}""",
            placeholders=[
                "customer_name", "client_name", "subject", "resolution_number",
                "resolution_date", "subsanacion_detalle", "city", "date",
                "lawyer_name", "cal_number"
            ],
        ),
    ],
)
