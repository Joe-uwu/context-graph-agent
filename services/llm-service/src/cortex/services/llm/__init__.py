"""llm-service: grounded reasoning.

Reasoning is a state machine (gather evidence → summarize → recommend → validate). Every
claim must cite a graph node or edge; the validator drops any uncited claim before the
result leaves the service, and confidence is inherited from the cited edges, not the
model's self-assessment (ADR-0007). The reference Reasoner is deterministic and offline;
a real LLM drops in behind the Reasoner port.
"""

from cortex.services.llm.grounding import GroundingValidator
from cortex.services.llm.reasoning import Reasoner, TemplateReasoner

__all__ = ["GroundingValidator", "Reasoner", "TemplateReasoner"]
