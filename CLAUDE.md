# LOLO AI Documents — AI Context

> Microservicio de generación de documentos legales con IA para la plataforma LOLO.

## Resumen

Microservicio Python/FastAPI que utiliza Claude AI para generar, analizar y refinar documentos legales para procesos judiciales de cobranza en Perú.

**Puerto desarrollo:** 8000
**Base URL:** `/api/v1/documents`
**Modelos IA:** `claude-sonnet-4-6` (generación), `claude-haiku-4-5` (análisis)

---

## Arquitectura Multi-Agente (3 Niveles)

```
┌─────────────────────────────────────────────────────────────┐
│                    NIVEL 1: ORQUESTACIÓN                     │
├─────────────────────────────────────────────────────────────┤
│  AnalyzerAgent     GeneratorAgent      RefinerAgent         │
│  (analiza caso)    (coordina gen.)     (refina por chat)    │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    NIVEL 2: ESPECIALISTAS                    │
├─────────────────────────────────────────────────────────────┤
│  ObligationsAgent   │ GuaranteesAgent  │ ExecutionAgent     │
│  ProceduralAgent    │ AppealsAgent     │ CivilLitigationAgent│
│  ConstitutionalAgent│ LaborAgent       │                     │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    NIVEL 3: VALIDADORES                      │
├─────────────────────────────────────────────────────────────┤
│  StructureValidator │ DataValidator    │ LegalValidator     │
│  SeniorReviewer     │                  │                     │
└─────────────────────────────────────────────────────────────┘
```

---

## Estructura de Directorios

```
app/
├── main.py                        # Entry point FastAPI
├── config.py                      # Pydantic Settings
├── agents/
│   ├── orchestration/             # Nivel 1
│   │   ├── analyzer_agent.py      # Analiza caso y sugiere docs
│   │   ├── generator_agent.py     # Coordina generación
│   │   └── refiner_agent.py       # Refinamiento por chat (SSE)
│   ├── specialists/               # Nivel 2 (8 agentes)
│   │   ├── obligations_agent.py   # ODS, leasing, pagaré
│   │   ├── guarantees_agent.py    # Ejecución de garantías
│   │   ├── execution_agent.py     # Remates, embargos
│   │   ├── procedural_agent.py    # Escritos procesales
│   │   ├── appeals_agent.py       # Apelación, casación
│   │   ├── civil_litigation_agent.py
│   │   ├── constitutional_agent.py
│   │   └── labor_agent.py
│   └── quality/                   # Nivel 3 (4 validadores)
│       ├── structure_validator.py
│       ├── data_validator.py
│       ├── legal_validator.py
│       └── senior_reviewer.py
├── api/
│   └── routes/
│       ├── health.py              # GET /health
│       ├── documents.py           # CRUD documentos
│       ├── analyze.py             # POST /analyze/{case_id}
│       ├── generate.py            # POST /generate/{case_id}
│       ├── refine.py              # POST /refine/{case_id} (SSE)
│       ├── finalize.py            # POST /finalize/{case_id}
│       └── types.py               # GET /types (catálogo)
├── models/                        # Schemas Pydantic
│   ├── document.py
│   ├── session.py
│   └── case_context.py
├── prompts/                       # System prompts para agentes
│   ├── analyzer/
│   ├── specialists/
│   └── validators/
├── services/
│   ├── mysql_service.py           # Queries async a db_lolo
│   ├── s3_service.py              # Descarga documentos caso
│   ├── learning_service.py        # Integración con learnings
│   ├── document_context_service.py # Agrega contexto del caso
│   └── session_service.py         # Gestión de sesiones MySQL
├── templates/                     # Generadores DOCX
│   ├── base_template.py
│   └── document_generators/
├── utils/
│   ├── llm_worker.py              # Rate limiting, token budget
│   ├── context_formatter.py       # Formatea contexto para prompts
│   └── pdf_extractor.py           # Extrae texto de PDFs
└── workflows/
    └── generation_workflow.py     # Flujo completo de generación
```

---

## API Endpoints

| Método | Endpoint | Descripción | Rate Limit |
|--------|----------|-------------|------------|
| GET | `/health` | Health check (ECS/ALB) | - |
| GET | `/api/v1/documents/types` | Catálogo de 28+ tipos de documentos | 10/min |
| POST | `/api/v1/documents/analyze/{case_id}` | Analiza caso y sugiere documentos | 10/min |
| POST | `/api/v1/documents/generate/{case_id}` | Genera borrador inicial | 5/min |
| POST | `/api/v1/documents/refine/{case_id}` | Refinamiento por chat (SSE) | 20/min |
| POST | `/api/v1/documents/finalize/{case_id}` | Genera DOCX final | 5/min |
| POST | `/api/v1/documents/annexes/{case_id}` | Genera anexos | 10/min |

---

## Flujo de Generación

```
1. Frontend llama POST /analyze/{case_id}
   → AnalyzerAgent lee contexto del caso (MySQL + S3)
   → Sugiere documentos apropiados según etapa procesal
   → Retorna: { suggested_documents: [...], case_summary: "..." }

2. Usuario selecciona documento, frontend llama POST /generate/{case_id}
   → GeneratorAgent selecciona specialist apropiado
   → Specialist genera borrador
   → Quality validators revisan (estructura, datos, legal)
   → SeniorReviewer da aprobación final
   → LearningService aplica reglas del customer
   → Retorna: { session_id: "...", draft: "...", suggestions: [...] }

3. Usuario refina por chat, frontend llama POST /refine/{case_id}
   → RefinerAgent procesa instrucción
   → Streaming SSE con cambios en tiempo real
   → Actualiza sesión en MySQL

4. Usuario finaliza, frontend llama POST /finalize/{case_id}
   → Genera DOCX con formato profesional
   → Sube a S3
   → Retorna URL de descarga
```

---

## Integración con LOLO

### Base de Datos Compartida
```python
# Misma DB que lolo-backend
MYSQL_HOST = "lolo-db-v3.cnq2wi6i4c60.us-west-2.rds.amazonaws.com"
MYSQL_DATABASE = "db_lolo"

# Tablas que lee:
- JUDICIAL_CASE_FILE        # Datos del expediente
- JUDICIAL_BINNACLE         # Historial del caso
- JUDICIAL_COLLATERAL       # Garantías
- JUDICIAL_OBSERVATION      # Observaciones
- CLIENT                    # Datos del deudor
- CUSTOMER_HAS_BANK         # Contexto del tenant

# Tablas que escribe:
- JUDICIAL_AI_DOCUMENT_SESSION  # Sesiones de generación
- JUDICIAL_AI_JOB               # Jobs de generación
```

### Sistema de Learning
```python
# Obtiene reglas específicas del customer desde lolo-backend
response = await httpx.post(
    f"{BACKEND_URL}/api/v1/judicial/internal/learning",
    headers={"X-Internal-API-Key": INTERNAL_API_KEY},
    json={"customer_id": customer_id, "document_type": doc_type}
)
# Aplica reglas al prompt del agente
```

### S3 Compartido
```python
# Lee documentos del caso desde S3
bucket = "archivosstorage"
prefix = f"CHB/{customer_has_bank_id}/judicial/{case_file_id}/"
# Extrae texto de PDFs para contexto
```

---

## Tipos de Documentos (28+)

### Obligaciones (6)
- `demanda_ods` — Demanda Obligación de Dar Suma de Dinero
- `demanda_leasing` — Demanda por Leasing
- `demanda_pagare` — Demanda por Pagaré
- `demanda_letra_cambio` — Demanda por Letra de Cambio
- `demanda_factura` — Demanda por Factura
- `ampliacion_demanda` — Ampliación de Demanda

### Garantías (3)
- `ejecucion_garantia_hipotecaria` — Ejecución de Garantía Hipotecaria
- `ejecucion_garantia_mobiliaria` — Ejecución de Garantía Mobiliaria
- `embargo_forma_deposito` — Embargo en Forma de Depósito

### Medidas Cautelares (3)
- `medida_cautelar_embargo` — Medida Cautelar de Embargo
- `medida_cautelar_anotacion` — Anotación de Demanda
- `medida_cautelar_secuestro` — Secuestro Conservativo

### Escritos Procesales (5)
- `escrito_apersonamiento` — Apersonamiento al Proceso
- `escrito_variacion_domicilio` — Variación de Domicilio
- `escrito_impulso_procesal` — Impulso Procesal
- `escrito_desistimiento` — Desistimiento
- `escrito_conclusion` — Conclusión del Proceso

### Ejecución y Remate (5)
- `solicitud_remate` — Solicitud de Remate
- `bases_remate` — Bases de Remate
- `acta_remate` — Acta de Remate
- `adjudicacion_directa` — Adjudicación Directa
- `liquidacion_credito` — Liquidación de Crédito

### Recursos (4)
- `recurso_apelacion` — Recurso de Apelación
- `recurso_casacion` — Recurso de Casación
- `recurso_queja` — Queja de Derecho
- `recurso_reposicion` — Reposición

### Litigios Civiles (2)
- `accion_pauliana` — Acción Pauliana
- `nulidad_acto_juridico` — Nulidad de Acto Jurídico

### Constitucional/Laboral (3+)
- `amparo` — Acción de Amparo
- `habeas_corpus` — Hábeas Corpus
- `demanda_laboral` — Demanda Laboral

---

## Variables de Entorno

```env
# API
PORT=8000
HOST=0.0.0.0

# Claude AI
ANTHROPIC_API_KEY=****
CLAUDE_MODEL=claude-sonnet-4-6
CLAUDE_MODEL_FAST=claude-haiku-4-5

# Database (compartida con lolo-backend)
MYSQL_HOST=****
MYSQL_PORT=3306
MYSQL_USER=****
MYSQL_PASSWORD=****
MYSQL_DATABASE=db_lolo

# AWS S3 (compartido)
AWS_ACCESS_KEY_ID=****
AWS_SECRET_ACCESS_KEY=****
AWS_BUCKET_NAME=archivosstorage
AWS_REGION=us-west-2

# Integración con lolo-backend
BACKEND_URL=http://localhost:5000
INTERNAL_API_KEY=****

# Sesiones
SESSION_TTL_SECONDS=14400  # 4 horas (igual que JWT)

# Rate Limits
RATE_LIMIT_ANALYZE=10
RATE_LIMIT_GENERATE=5
RATE_LIMIT_REFINE=20

# Features
LEARNING_ENABLED=true
```

---

## Comandos de Desarrollo

```bash
# Activar virtualenv
source venv/bin/activate  # Linux/Mac
.\venv\Scripts\activate   # Windows

# Instalar dependencias
pip install -r requirements.txt
# o con poetry
poetry install

# Ejecutar servidor
uvicorn app.main:app --reload --port 8000

# Tests
pytest --cov=app

# Type checking
mypy app/

# Linting
ruff check app/
black app/
```

---

---

## Sistema de Tracking de Tokens

### Captura de Tokens Reales

El sistema captura tokens reales desde la respuesta de Claude API:

```python
# app/utils/llm_worker.py (líneas ~214-224)
response = await anthropic_client.messages.create(...)

# Captura tokens reales del response
usage = response.usage
input_tokens = usage.input_tokens    # Tokens reales de entrada
output_tokens = usage.output_tokens  # Tokens reales de salida
```

### Persistencia de Tokens

Los tokens se persisten en `JUDICIAL_AI_TOKEN_USAGE` con cada operación:

```python
# Estructura de datos enviada
token_usage = {
    "session_id": session_id,
    "job_id": job_id,
    "operation_type": "GENERATE",  # ANALYZE, GENERATE, REFINE, FINALIZE
    "model_used": "claude-sonnet-4-6",
    "input_tokens": usage.input_tokens,
    "output_tokens": usage.output_tokens,
    "customer_id": customer_id,
    "customer_has_bank_id": chb_id
}
```

### Puntos de Captura

| Archivo | Línea | Operación |
|---------|-------|-----------|
| `agents/orchestration/analyzer_agent.py` | ~150 | ANALYZE |
| `agents/orchestration/generator_agent.py` | ~221, ~256 | GENERATE |
| `agents/orchestration/refiner_agent.py` | ~180 | REFINE |
| `workflows/generation_workflow.py` | ~320 | FINALIZE |

---

## Notas para IA

1. **Contexto del caso es crítico:** Siempre leer JUDICIAL_CASE_FILE y JUDICIAL_BINNACLE antes de generar
2. **Learnings personalizan:** El sistema de learning del customer modifica cómo se generan documentos
3. **Rate limiting por costo:** Claude API es costoso, respetar límites
4. **Sesiones en MySQL:** No hay Redis, todo persiste en JUDICIAL_AI_DOCUMENT_SESSION
5. **SSE para refinamiento:** El endpoint /refine usa Server-Sent Events, no WebSockets
6. **Async everywhere:** Todo el código es async/await, usar aiomysql y aioboto3
7. **Validación en 3 niveles:** Cada documento pasa por structure, data y legal validators
8. **DOCX final:** python-docx genera el documento final con formato profesional
9. **Tokens reales, no estimados:** Siempre usar `response.usage.input_tokens` y `response.usage.output_tokens` de la API, nunca hardcoded
