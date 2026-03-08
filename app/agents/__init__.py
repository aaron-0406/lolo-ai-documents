"""
AI Agents for document generation.

This module contains three levels of agents:
1. Orchestration Agents (Level 1): Coordinate the overall workflow
2. Specialist Agents (Level 2): Generate documents for specific legal areas
3. Quality Control Agents (Level 3): Validate and improve documents
"""

from app.agents.orchestration.analyzer_agent import AnalyzerAgent
from app.agents.orchestration.generator_agent import GeneratorAgent
from app.agents.orchestration.refiner_agent import RefinerAgent

__all__ = [
    "AnalyzerAgent",
    "GeneratorAgent",
    "RefinerAgent",
]
