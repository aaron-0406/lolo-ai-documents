"""
Prompt templates for AI document generation agents.
"""

from app.prompts.analyzer import ANALYZER_SYSTEM_PROMPT
from app.prompts.refiner import REFINER_SYSTEM_PROMPT
from app.prompts.validators import (
    STRUCTURE_VALIDATOR_PROMPT,
    DATA_VALIDATOR_PROMPT,
    LEGAL_VALIDATOR_PROMPT,
    SENIOR_REVIEWER_PROMPT,
)

__all__ = [
    "ANALYZER_SYSTEM_PROMPT",
    "REFINER_SYSTEM_PROMPT",
    "STRUCTURE_VALIDATOR_PROMPT",
    "DATA_VALIDATOR_PROMPT",
    "LEGAL_VALIDATOR_PROMPT",
    "SENIOR_REVIEWER_PROMPT",
]
