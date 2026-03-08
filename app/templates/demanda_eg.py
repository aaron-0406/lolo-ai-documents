"""
Template for Demanda de Ejecución de Garantías.
"""

from app.templates.base import DocumentTemplate, TemplateSection

DEMANDA_EG_TEMPLATE = DocumentTemplate(
    document_type="demanda_eg",
    document_name="Demanda de Ejecución de Garantías",
    description="Demanda para ejecución de garantías hipotecarias o mobiliarias",
    required_context=[
        "case_number",
        "client_name",
        "client_dni_ruc",
        "customer_name",
        "customer_ruc",
        "amount_demanded_soles",
        "court",
        "collateral_address",
        "registry_entry",
    ],
    sections=[
        TemplateSection(
            name="SUMILLA",
            order=1,
            content_template="SUMILLA: DEMANDA DE EJECUCIÓN DE GARANTÍAS",
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
            content_template="""DEMANDANTE (ACREEDOR HIPOTECARIO): {customer_name}
RUC: {customer_ruc}
Representante Legal: {representative_name}
Domicilio Procesal: {procedural_address}""",
            placeholders=["customer_name", "customer_ruc", "representative_name", "procedural_address"],
        ),
        TemplateSection(
            name="DEMANDADO",
            order=4,
            content_template="""DEMANDADO (DEUDOR HIPOTECARIO): {client_name}
DNI/RUC: {client_dni_ruc}
Domicilio Real: {client_address}""",
            placeholders=["client_name", "client_dni_ruc", "client_address"],
        ),
        TemplateSection(
            name="MATERIA",
            order=5,
            content_template="""MATERIA: EJECUCIÓN DE GARANTÍAS
VÍA PROCEDIMENTAL: Proceso de Ejecución de Garantías
CUANTÍA: S/ {amount_demanded_soles}""",
            placeholders=["amount_demanded_soles"],
        ),
        TemplateSection(
            name="PETITORIO",
            order=6,
            content_template="""I. PETITORIO

Que, interpongo demanda de EJECUCIÓN DE GARANTÍAS contra {client_name},
a fin de que:

1. Se ordene el pago de la suma de S/ {amount_demanded_soles} (SON: {amount_in_words}
   SOLES), correspondiente al saldo deudor del crédito garantizado, más los
   intereses compensatorios y moratorios pactados.

2. En caso de incumplimiento, se proceda al REMATE del inmueble dado en garantía
   hipotecaria, ubicado en {collateral_address}, inscrito en la Partida
   Electrónica N° {registry_entry} del Registro de Predios de {registry_office}.

3. Se ordene el pago de las costas y costos del proceso.""",
            placeholders=[
                "client_name", "amount_demanded_soles", "amount_in_words",
                "collateral_address", "registry_entry", "registry_office"
            ],
        ),
        TemplateSection(
            name="FUNDAMENTOS_DE_HECHO",
            order=7,
            content_template="""II. FUNDAMENTOS DE HECHO

PRIMERO.- CONSTITUCIÓN DE LA HIPOTECA
Con fecha {mortgage_date}, mediante Escritura Pública otorgada ante el Notario
{notary_name}, el demandado constituyó PRIMERA Y PREFERENTE HIPOTECA a favor
de mi representada, sobre el inmueble ubicado en {collateral_address},
inscrito en la Partida Electrónica N° {registry_entry}.

SEGUNDO.- CRÉDITO GARANTIZADO
La hipoteca fue constituida en garantía del crédito otorgado al demandado
por la suma de S/ {original_amount}, según {credit_document}.

TERCERO.- INCUMPLIMIENTO
El demandado ha incumplido con el pago de las cuotas pactadas desde
{default_date}, acumulándose a la fecha un saldo deudor de S/ {amount_demanded_soles}.

CUARTO.- VENCIMIENTO DEL PLAZO
Conforme al contrato suscrito, el incumplimiento de {num_installments} cuotas
consecutivas genera el vencimiento anticipado del plazo total de la obligación.

QUINTO.- TASACIÓN DEL INMUEBLE
El inmueble dado en garantía tiene una tasación comercial de S/ {appraisal_value},
según informe de tasación de fecha {appraisal_date}.""",
            placeholders=[
                "mortgage_date", "notary_name", "collateral_address", "registry_entry",
                "original_amount", "credit_document", "default_date", "amount_demanded_soles",
                "num_installments", "appraisal_value", "appraisal_date"
            ],
        ),
        TemplateSection(
            name="FUNDAMENTOS_DE_DERECHO",
            order=8,
            content_template="""III. FUNDAMENTOS DE DERECHO

- Artículo 720 del Código Procesal Civil: Procedencia de la ejecución de garantías
- Artículo 721 del Código Procesal Civil: Mandato de ejecución
- Artículo 722 del Código Procesal Civil: Contradicción
- Artículo 723 del Código Procesal Civil: Orden de remate
- Artículo 1097 del Código Civil: Definición de hipoteca
- Artículo 1099 del Código Civil: Requisitos de validez de la hipoteca
- Artículo 1107 del Código Civil: Rango de la hipoteca
- Artículo 1122 del Código Civil: Extinción de la hipoteca""",
            placeholders=[],
        ),
        TemplateSection(
            name="MEDIOS_PROBATORIOS",
            order=9,
            content_template="""IV. MEDIOS PROBATORIOS

1. Escritura Pública de constitución de hipoteca.
2. Copia literal de la Partida Electrónica N° {registry_entry}.
3. Tasación comercial actualizada del inmueble.
4. Estado de cuenta de saldo deudor.
5. Certificado de gravámenes del inmueble.
6. Contrato de crédito que originó la obligación.
7. Requerimiento de pago notarial.""",
            placeholders=["registry_entry"],
        ),
        TemplateSection(
            name="ANEXOS",
            order=10,
            content_template="""V. ANEXOS

1-A: Copia del DNI del representante legal
1-B: Vigencia de poder
1-C: Escritura Pública de Hipoteca
1-D: Copia literal de Partida Registral N° {registry_entry}
1-E: Tasación comercial actualizada
1-F: Estado de cuenta de saldo deudor
1-G: Certificado de gravámenes
1-H: Contrato de crédito
1-I: Carta notarial de requerimiento
1-J: Tasa judicial
1-K: Cédulas de notificación""",
            placeholders=["registry_entry"],
        ),
        TemplateSection(
            name="OTROSIES",
            order=11,
            content_template="""PRIMER OTROSÍ DIGO: Que, delego facultades generales y especiales de
representación a favor del abogado que suscribe.

SEGUNDO OTROSÍ DIGO: Que, adjunto los anexos indicados en {num_annexes} juegos.

TERCER OTROSÍ DIGO: Que, solicito se tenga presente que el inmueble materia
de ejecución se encuentra {occupancy_status}.""",
            placeholders=["num_annexes", "occupancy_status"],
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
