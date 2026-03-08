"""
Document templates for legal documents.

Templates define the structure and placeholders for each document type.
"""

from app.templates.base import DocumentTemplate, TemplateSection
from app.templates.demanda_ods import DEMANDA_ODS_TEMPLATE
from app.templates.demanda_eg import DEMANDA_EG_TEMPLATE
from app.templates.escrito_procesal import ESCRITO_PROCESAL_TEMPLATE

__all__ = [
    "DocumentTemplate",
    "TemplateSection",
    "DEMANDA_ODS_TEMPLATE",
    "DEMANDA_EG_TEMPLATE",
    "ESCRITO_PROCESAL_TEMPLATE",
]
