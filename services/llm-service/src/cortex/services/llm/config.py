"""llm-service configuration."""

from __future__ import annotations

from cortex.platform.config import ServiceSettings

SERVICE_NAME = "llm-service"
GROUP = "llm-service"


class LlmSettings(ServiceSettings):
    http_port: int = 8006

    # k-hop radius of evidence gathered before reasoning.
    evidence_hops: int = 3

    # Reasoning engine: "native" (hand-rolled typed state graph, default) or "langgraph"
    # (the same nine nodes compiled on the langgraph library). Both use the same LLM plug-in.
    reasoner_engine: str = "native"

    # Reasoner: "template" (offline default) or "openai" (any OpenAI-compatible chat endpoint —
    # OpenAI, Azure, Ollama, vLLM). The grounding validator gates the output either way.
    llm_provider: str = "template"
    llm_model: str = "gpt-4o-mini"
    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
