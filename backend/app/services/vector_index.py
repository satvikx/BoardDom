"""ChromaDB vector index for source chunks.

SQLite keeps each chunk's text and its [C n] label; ChromaDB keeps the embedding. Every query
is filtered by course (workspace_id) and embedding model, so one course's search can never
return another course's passages. The client is created lazily on first use.
"""

import logging
import threading
from pathlib import Path

logger = logging.getLogger(__name__)
COLLECTION = "source_chunks"


class ChromaIndex:
    def __init__(self, path: Path):
        self.path = path
        self._collection = None
        self._lock = threading.Lock()

    @property
    def collection(self):
        if self._collection is None:
            with self._lock:
                if self._collection is None:
                    import chromadb
                    from chromadb.config import Settings as ChromaSettings

                    self.path.mkdir(parents=True, exist_ok=True)
                    client = chromadb.PersistentClient(
                        path=str(self.path),
                        settings=ChromaSettings(anonymized_telemetry=False),
                    )
                    self._collection = client.get_or_create_collection(
                        COLLECTION, metadata={"hnsw:space": "cosine"}, embedding_function=None
                    )
        return self._collection

    def upsert(self, rows: list[dict]) -> None:
        """rows: {id, embedding, workspace_id, document_id, ordinal, embedding_model}."""
        if not rows:
            return
        self.collection.upsert(
            ids=[r["id"] for r in rows],
            embeddings=[r["embedding"] for r in rows],
            metadatas=[
                {
                    "workspace_id": r["workspace_id"],
                    "document_id": r["document_id"],
                    "ordinal": r["ordinal"],
                    "embedding_model": r["embedding_model"],
                }
                for r in rows
            ],
        )

    def ids(self, workspace_id: str, model: str) -> set[str]:
        found = self.collection.get(
            where={"$and": [{"workspace_id": workspace_id}, {"embedding_model": model}]},
            include=[],
        )
        return set(found["ids"])

    def all_ids(self, workspace_id: str) -> set[str]:
        return set(self.collection.get(where={"workspace_id": workspace_id}, include=[])["ids"])

    def delete(self, ids) -> None:
        ids = list(ids)
        if ids:
            self.collection.delete(ids=ids)

    def delete_workspaces(self, workspace_ids) -> None:
        """Best effort after a course or account is deleted."""
        for workspace_id in workspace_ids:
            try:
                self.collection.delete(where={"workspace_id": str(workspace_id)})
            except Exception:  # noqa: BLE001 - the SQLite rows are already gone
                logger.warning("Could not remove a course from the vector index")

    def query(self, workspace_id: str, model: str, vector: list[float], k: int):
        """[(chunk id, cosine similarity)] within one course, best first."""
        total = len(self.ids(workspace_id, model))
        if not total:
            return []
        result = self.collection.query(
            query_embeddings=[vector],
            n_results=min(k, total),
            where={"$and": [{"workspace_id": workspace_id}, {"embedding_model": model}]},
            include=["distances"],
        )
        return [
            (chunk_id, 1.0 - distance)
            for chunk_id, distance in zip(result["ids"][0], result["distances"][0], strict=True)
        ]
