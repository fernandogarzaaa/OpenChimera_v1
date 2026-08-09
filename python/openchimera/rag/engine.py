"""RAG engine placeholder."""

from typing import Any


class RagEngine:
    def __init__(self) -> None:
        self.docs: list[dict[str, Any]] = []

    def add_documents(self, texts: list[str], metadatas: list[dict] | None = None) -> None:
        for i, text in enumerate(texts):
            self.docs.append({"text": text, "metadata": (metadatas or [{}])[i]})

    def query(self, q: str, top_k: int = 5) -> list[dict[str, Any]]:
        # Simple keyword match fallback
        results = []
        for doc in self.docs:
            if any(word in doc["text"].lower() for word in q.lower().split()):
                results.append(doc)
                if len(results) >= top_k:
                    break
        return results
