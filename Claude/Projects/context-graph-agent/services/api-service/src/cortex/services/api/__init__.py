"""api-service: the public edge.

REST + WebSocket, org-scoped. Reads across the graph, retrieval, and notification stores;
mutates no pipeline store directly — user actions become user.actions events so the
pipeline stays the single writer (ADR-0004). See docs/design/api-and-events.md.
"""
