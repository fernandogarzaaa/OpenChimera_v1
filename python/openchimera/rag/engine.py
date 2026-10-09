"""Full RAG engine with embedding-based retrieval."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from openchimera.config import load_settings

_ENGINE_INSTANCE: RagEngine | None = None


def get_engine() -> RagEngine:
    global _ENGINE_INSTANCE
    if _ENGINE_INSTANCE is None:
        settings = load_settings()
        _ENGINE_INSTANCE = RagEngine(settings)
    return _ENGINE_INSTANCE


class RagEngine:
    """Production RAG engine with optional ChromaDB + sentence-transformers."""

    def __init__(self, settings: Any | None = None) -> None:
        self.settings = settings
        self._chroma_client = None
        self._collection = None
        self._embedding_fn = None
        self._docs: list[dict[str, Any]] = []
        self._initialized = False
        self._init()

    def _init(self) -> None:
        if self._initialized:
            return
        try:
            import chromadb
            from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

            persist_dir = "data/rag_db"
            if self.settings and hasattr(self.settings, "rag"):
                persist_dir = self.settings.rag.persist_dir

            Path(persist_dir).mkdir(parents=True, exist_ok=True)
            self._chroma_client = chromadb.PersistentClient(path=persist_dir)
            self._collection = self._chroma_client.get_or_create_collection("openchimera_docs")
            self._embedding_fn = SentenceTransformerEmbeddingFunction(
                model_name="sentence-transformers/all-MiniLM-L6-v2"
            )
            self._initialized = True
        except ImportError:
            # Fallback: keyword-based in-memory search
            self._chroma_client = None
            self._initialized = True

    def add_documents(self, texts: list[str], metadatas: list[dict] | None = None) -> None:
        if not texts:
            return
        if self._collection is not None:
            ids = [hashlib.md5(t.encode()).hexdigest()[:16] for t in texts]
            self._collection.add(
                documents=texts,
                metadatas=metadatas or [{} for _ in texts],
                ids=ids,
            )
        else:
            for i, text in enumerate(texts):
                self._docs.append({"text": text, "metadata": (metadatas or [{}])[i]})

    def query(self, q: str, top_k: int = 5) -> list[dict[str, Any]]:
        if self._collection is not None:
            try:
                results = self._collection.query(query_texts=[q], n_results=top_k)
                docs = []
                for i, doc_texts in enumerate(results.get("documents", [])):
                    for j, text in enumerate(doc_texts):
                        meta = results["metadatas"][i][j] if results.get("metadatas") else {}
                        dist = results["distances"][i][j] if results.get("distances") else None
                        docs.append({"text": text, "metadata": meta, "distance": dist})
                return docs
            except Exception:
                pass

        # Fallback keyword search
        results = []
        query_words = q.lower().split()
        for doc in self._docs:
            score = sum(1 for word in query_words if word in doc["text"].lower())
            if score > 0:
                results.append({**doc, "score": score})
        results.sort(key=lambda x: x.get("score", 0), reverse=True)
        return results[:top_k]

    def get_stats(self) -> dict[str, Any]:
        if self._collection is not None:
            try:
                count = self._collection.count()
                return {"total_documents": count, "backend": "chroma"}
            except Exception:
                pass
        return {"total_documents": len(self._docs), "backend": "memory"}
