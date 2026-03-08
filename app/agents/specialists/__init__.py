"""
Specialist Agents (Level 2).

Each specialist has deep knowledge in their specific area of Peruvian law:
- ObligationsAgent: Civil obligations, ODS, leasing
- GuaranteesAgent: Mortgages, collateral execution
- ExecutionAgent: Auctions, adjudication, eviction
- ProceduralAgent: Procedural writings, injunctions
- AppealsAgent: Appeals, cassation, complaints
- CivilLitigationAgent: Nullity, Paulian action
- ConstitutionalAgent: Amparo, constitutional processes
- LaborAgent: Labor processes (employer defense)
"""

from app.agents.specialists.obligations import ObligationsAgent
from app.agents.specialists.guarantees import GuaranteesAgent
from app.agents.specialists.execution import ExecutionAgent
from app.agents.specialists.procedural import ProceduralAgent
from app.agents.specialists.appeals import AppealsAgent
from app.agents.specialists.civil_litigation import CivilLitigationAgent
from app.agents.specialists.constitutional import ConstitutionalAgent
from app.agents.specialists.labor import LaborAgent

__all__ = [
    "ObligationsAgent",
    "GuaranteesAgent",
    "ExecutionAgent",
    "ProceduralAgent",
    "AppealsAgent",
    "CivilLitigationAgent",
    "ConstitutionalAgent",
    "LaborAgent",
]
