"""Vector index abstraction with an in-memory default and a Qdrant implementation.

Both store one point per graph node (vector + payload with org_id/label/node_id) and answer
filtered nearest-neighbour queries scoped by org (and optionally node label). The in-memory
index backs local/demo/test runs; QdrantVectorIndex backs production and requires the
`qdrant` extra. Node ids are strings, so Qdrant point ids are a deterministic UUID5 of the
node id (Qdrant point ids must be int or UUID) and the node id is carried in the payload.
"""

from __future__ import annotations

import math
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

_UUID_NS = uuid.UUID("6f9619ff-8b86-d011-b42d-00c04fc964ff")


@dataclass
class VectorPoint:
    node_id: str
    org_id: str
    vector: list[float]
    label: str = ""
    text: str = ""
    payload: dict = field(default_factory=dict)


def _point_uuid(org_id: str, node_id: str) -> str:
    return str(uuid.uuid5(_UUID_NS, f"{org_id}:{node_id}"))


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


class VectorIndex(ABC):
    dim: int

    @abstractmethod
    def upsert(self, points: list[VectorPoint]) -> None:
        """Idempotently insert/replace points (batch)."""

    @abstractmethod
    def search(
        self, *, org_id: str, query_vector: list[float], limit: int = 20, label: str | None = None
    ) -> list[tuple[str, float]]:
        """Return (node_id, score) nearest neighbours within an org, optionally by label."""

    @abstractmethod
    def count(self, *, org_id: str | None = None) -> int: ...


class InMemoryVectorIndex(VectorIndex):
    def __init__(self, dim: int = 256) -> None:
        self.dim = dim
        self._points: dict[str, VectorPoint] = {}

    def upsert(self, points: list[VectorPoint]) -> None:
        for point in points:
            self._points[_point_uuid(point.org_id, point.node_id)] = point

    def search(
        self, *, org_id: str, query_vector: list[float], limit: int = 20, label: str | None = None
    ) -> list[tuple[str, float]]:
        scored: list[tuple[str, float]] = []
        for point in self._points.values():
            if point.org_id != org_id:
                continue
            if label is not None and point.label != label:
                continue
            scored.append((point.node_id, _cosine(query_vector, point.vector)))
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[:limit]

    def count(self, *, org_id: str | None = None) -> int:
        if org_id is None:
            return len(self._points)
        return sum(1 for p in self._points.values() if p.org_id == org_id)


class QdrantVectorIndex(VectorIndex):
    def __init__(
        self, *, url: str | None = None, collection: str = "cortex_nodes", dim: int = 256, client=None
    ) -> None:
        try:
            from qdrant_client import QdrantClient, models
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("QdrantVectorIndex requires the 'qdrant' extra") from exc
        self.dim = dim
        self._collection = collection
        self._models = models
        self._client = client if client is not None else QdrantClient(url=url)
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        models = self._models
        if not self._client.collection_exists(self._collection):
            self._client.create_collection(
                collection_name=self._collection,
                vectors_config=models.VectorParams(size=self.dim, distance=models.Distance.COSINE),
            )
        # Payload index on org_id makes the tenant filter selective.
        try:  # pragma: no cover - best-effort; harmless if it already exists
            self._client.create_payload_index(
                self._collection, field_name="org_id",
                field_schema=models.PayloadSchemaType.KEYWORD,
            )
        except Exception:  # noqa: BLE001
            pass

    def upsert(self, points: list[VectorPoint]) -> None:
        if not points:
            return
        models = self._models
        structs = [
            models.PointStruct(
                id=_point_uuid(p.org_id, p.node_id),
                vector=p.vector,
                payload={"node_id": p.node_id, "org_id": p.org_id, "label": p.label, "text": p.text},
            )
            for p in points
        ]
        self._client.upsert(collection_name=self._collection, points=structs)

    def search(
        self, *, org_id: str, query_vector: list[float], limit: int = 20, label: str | None = None
    ) -> list[tuple[str, float]]:
        models = self._models
        must = [models.FieldCondition(key="org_id", match=models.MatchValue(value=org_id))]
        if label is not None:
            must.append(models.FieldCondition(key="label", match=models.MatchValue(value=label)))
        result = self._client.query_points(
            collection_name=self._collection,
            query=query_vector,
            limit=limit,
            query_filter=models.Filter(must=must),
            with_payload=True,
        )
        return [(p.payload["node_id"], float(p.score)) for p in result.points]

    def count(self, *, org_id: str | None = None) -> int:
        models = self._models
        flt = None
        if org_id is not None:
            flt = models.Filter(
                must=[models.FieldCondition(key="org_id", match=models.MatchValue(value=org_id))]
            )
        return self._client.count(collection_name=self._collection, count_filter=flt).count
