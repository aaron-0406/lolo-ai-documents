"""
Template for Demanda de Obligación de Dar Suma de Dinero (ODS).
"""

from app.templates.base import DocumentTemplate, TemplateSection

DEMANDA_ODS_TEMPLATE = DocumentTemplate(
    document_type="demanda_ods",
    document_name="Demanda de Obligación de Dar Suma de Dinero",
    description="Demanda ejecutiva para cobro de deudas mediante proceso único de ejecución",
    required_context=[
        "case_number",
        "client_name",
        "client_dni_ruc",
        "customer_name",
        "customer_ruc",
        "amount_demanded_soles",
        "court",
    ],
    sections=[
        TemplateSection(
            name="SUMILLA",
            order=1,
            content_template="SUMILLA: DEMANDA DE OBLIGACIÓN DE DAR SUMA DE DINERO",
            placeholders=[],
        ),
        TemplateSection(
            name="DATOS_PROCESALES",
            order=2,
            content_template="""SECRETARIO: A quien corresponda
EXPEDIENTE: {case_number}
CUADERNO: Principal
ESCRITO N°: 01""",
            placeholders=["case_number"],
        ),
        TemplateSection(
            name="DEMANDANTE",
            order=3,
            content_template="""DEMANDANTE: {customer_name}
RUC: {customer_ruc}
Representante Legal: {representative_name}
Domicilio Procesal: {procedural_address}""",
            placeholders=["customer_name", "customer_ruc", "representative_name", "procedural_address"],
        ),
        TemplateSection(
            name="DEMANDADO",
            order=4,
            content_template="""DEMANDADO: {client_name}
DNI/RUC: {client_dni_ruc}
Domicilio Real: {client_address}""",
            placeholders=["client_name", "client_dni_ruc", "client_address"],
        ),
        TemplateSection(
            name="MATERIA",
            order=5,
            content_template="""MATERIA: OBLIGACIÓN DE DAR SUMA DE DINERO
VÍA PROCEDIMENTAL: Proceso Único de Ejecución
CUANTÍA: S/ {amount_demanded_soles}""",
            placeholders=["amount_demanded_soles"],
        ),
        TemplateSection(
            name="PETITORIO",
            order=6,
            content_template="""I. PETITORIO

Que, interpongo demanda de OBLIGACIÓN DE DAR SUMA DE DINERO contra {client_name},
a fin de que cumpla con pagar a mi representada la suma de S/ {amount_demanded_soles}
(SON: {amount_in_words} SOLES), más los intereses legales, costas y costos del proceso.""",
            placeholders=["client_name", "amount_demanded_soles", "amount_in_words"],
        ),
        TemplateSection(
            name="FUNDAMENTOS_DE_HECHO",
            order=7,
            content_template="""II. FUNDAMENTOS DE HECHO

PRIMERO.- Mi representada, {customer_name}, es una empresa del sistema financiero
debidamente autorizada por la Superintendencia de Banca, Seguros y AFP.

SEGUNDO.- Con fecha {credit_date}, el demandado {client_name} suscribió con mi
representada un {credit_type}, por la suma de S/ {original_amount}.

TERCERO.- El demandado se comprometió a pagar dicha obligación en {payment_terms}.

CUARTO.- A pesar de los requerimientos de pago efectuados, el demandado ha
incumplido con su obligación de pago, adeudando a la fecha la suma de
S/ {amount_demanded_soles}.

QUINTO.- El título ejecutivo que sustenta la presente demanda es {executive_title},
el cual cumple con los requisitos establecidos en el artículo 688 del Código
Procesal Civil.""",
            placeholders=[
                "customer_name", "credit_date", "client_name", "credit_type",
                "original_amount", "payment_terms", "amount_demanded_soles", "executive_title"
            ],
        ),
        TemplateSection(
            name="FUNDAMENTOS_DE_DERECHO",
            order=8,
            content_template="""III. FUNDAMENTOS DE DERECHO

- Artículo 688 del Código Procesal Civil: Títulos Ejecutivos
- Artículo 689 del Código Procesal Civil: Requisitos de la demanda ejecutiva
- Artículo 690-A del Código Procesal Civil: Mandato ejecutivo
- Artículo 690-B del Código Procesal Civil: Contradicción
- Artículo 1219 del Código Civil: Efectos de las obligaciones
- Artículo 1242 del Código Civil: Interés moratorio
- Ley N° 27287, Ley de Títulos Valores""",
            placeholders=[],
        ),
        TemplateSection(
            name="MEDIOS_PROBATORIOS",
            order=9,
            content_template="""IV. MEDIOS PROBATORIOS

1. {executive_title} original que acredita la obligación.
2. Estado de cuenta de saldo deudor actualizado.
3. Copia literal de la partida registral de la empresa demandante.
4. Vigencia de poder del representante legal.
5. Carta de requerimiento de pago notarial.""",
            placeholders=["executive_title"],
        ),
        TemplateSection(
            name="ANEXOS",
            order=10,
            content_template="""V. ANEXOS

1-A: Copia del DNI del representante legal
1-B: Vigencia de poder
1-C: {executive_title} original
1-D: Estado de cuenta de saldo deudor
1-E: Carta notarial de requerimiento de pago
1-F: Tasa judicial por ofrecimiento de pruebas
1-G: Cédulas de notificación""",
            placeholders=["executive_title"],
        ),
        TemplateSection(
            name="OTROSIES",
            order=11,
            content_template="""PRIMER OTROSÍ DIGO: Que, delego facultades generales y especiales de
representación a favor del abogado que suscribe, conforme a los artículos 74
y 75 del Código Procesal Civil.

SEGUNDO OTROSÍ DIGO: Que, adjunto los anexos mencionados en {num_annexes} juegos
para la contraparte.

TERCER OTROSÍ DIGO: Que, autorizo a {authorized_person} para que recoja
cualquier documento, cédula o anexo de la presente causa.""",
            placeholders=["num_annexes", "authorized_person"],
        ),
        TemplateSection(
            name="FIRMA",
            order=12,
            content_template="""{city}, {date}


_________________________________
{lawyer_name}
Abogado
Reg. CAL N° {cal_number}""",
            placeholders=["city", "date", "lawyer_name", "cal_number"],
        ),
    ],
)
