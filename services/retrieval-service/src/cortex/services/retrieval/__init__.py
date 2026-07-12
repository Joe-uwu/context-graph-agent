"""retrieval-service: hybrid retrieval and the evidence sets reasoning runs on.

Graph traversal is the lead signal; vector similarity and keyword widen recall. The
evidence set returned to llm-service carries provenance so every claim can cite it. See
docs/design/hybrid-retrieval.md.
"""

from cortex.services.retrieval.service import EvidenceSet, RetrievalService

__all__ = ["EvidenceSet", "RetrievalService"]
