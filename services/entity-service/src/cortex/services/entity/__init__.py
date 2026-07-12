"""entity-service: turn raw events into typed entities + candidate relationships.

Two-tier extraction: deterministic parsers pull certain structure at confidence 1.0; an
LLM pass (LlmExtractor port) pulls fuzzy structure with calibrated, sub-1.0 confidence.
The LLM never invents ids — it links within entities the deterministic tier found.
"""
