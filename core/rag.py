from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.transactions import atomic_write_json


SOURCE_TYPE_WEIGHTS = {
    "openchimera-runtime": 1.35,
    "harness-port": 1.2,
    "minimind": 1.1,
    "legacy-harness-snapshot": 0.9,
}


@dataclass
class Document:
    text: str
    metadata: dict[str, Any] | None = None
    id: str | None = None

    def __post_init__(self) -> None:
        if self.metadata is None:
            self.metadata = {}
        if self.id is None:
            self.id = hashlib.sha256(self.text.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text, "metadata": self.metadata, "id": self.id}


class SimpleRAG:
    def __init__(self, storage_path: str | Path):
        self.documents: list[Document] = []
        self.index: dict[str, list[int]] = {}
        self.storage_path = Path(storage_path)
        self._load_from_disk()

    def _load_from_disk(self) -> None:
        if not self.storage_path.exists():
            return

        try:
            data = json.loads(self.storage_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return

        for doc_data in data:
            doc = Document(
                text=doc_data.get("text", ""),
                metadata=doc_data.get("metadata", {}),
                id=doc_data.get("id"),
            )
            self._add_to_memory(doc)

    def _save_to_disk(self) -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self.storage_path, [doc.to_dict() for doc in self.documents])

    def _add_to_memory(self, doc: Document) -> None:
        if any(existing.id == doc.id for existing in self.documents):
            return

        self.documents.append(doc)
        for word in self._tokenize(doc.text):
            self.index.setdefault(word, []).append(len(self.documents) - 1)

    def add_documents(self, documents: list[Document], persist: bool = True) -> None:
        for doc in documents:
            self._add_to_memory(doc)
        if persist:
            self._save_to_disk()

    def add_file(
        self,
        path: str | Path,
        metadata: dict[str, Any] | None = None,
        persist: bool = True,
    ) -> bool:
        file_path = Path(path)
        if not file_path.exists() or not file_path.is_file():
            return False

        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return False

        chunks = self._chunk_text(content, chunk_size=1000)
        docs = []
        for index, chunk in enumerate(chunks):
            docs.append(
                Document(
                    text=chunk,
                    metadata={
                        "source": str(file_path),
                        "filename": file_path.name,
                        "chunk": index,
                        **(metadata or {}),
                    },
                )
            )
        self.add_documents(docs, persist=persist)
        return True

    def _chunk_text(self, text: str, chunk_size: int = 1000) -> list[str]:
        words = text.split()
        if not words:
            return []
        return [" ".join(words[i : i + chunk_size]) for i in range(0, len(words), chunk_size)]

    def _tokenize(self, text: str) -> list[str]:
        normalized = re.sub(r"[^a-z0-9_\-\s]", " ", text.lower())
        return normalized.split()

    def _score(self, query: str, doc_idx: int) -> float:
        query_tokens = self._tokenize(query)
        if not query_tokens:
            return 0.0

        doc = self.documents[doc_idx]
        doc_tokens = self._tokenize(doc.text)
        if not doc_tokens:
            return 0.0

        overlap = set(query_tokens) & set(doc_tokens)
        score = len(overlap) / max(len(set(query_tokens)), 1)

        query_lower = query.lower()
        metadata = doc.metadata or {}
        source_type = str(metadata.get("source_type", "")).strip().lower()
        score *= SOURCE_TYPE_WEIGHTS.get(source_type, 1.0)

        for token in overlap:
            if len(token) > 5:
                score += 0.1

        for value in metadata.values():
            if str(value).lower() in query.lower():
                score *= 1.5

        filename = str(metadata.get("filename", "")).lower()
        topic = str(metadata.get("topic", "")).lower()
        if filename and any(token in filename for token in query_tokens):
            score += 0.35
        if topic and any(token in topic for token in query_tokens):
            score += 0.3
        if metadata.get("chunk") == 0:
            score += 0.05
        if "openchimera" in query_lower and source_type == "openchimera-runtime":
            score += 0.2
        return score

    def retrieve(self, query: str, top_k: int = 3, min_score: float = 0.05) -> list[Document]:
        scores: list[tuple[int, float]] = []
        for index in range(len(self.documents)):
            score = self._score(query, index)
            if score >= min_score:
                scores.append((index, score))

        scores.sort(key=lambda item: item[1], reverse=True)
        return [self.documents[index] for index, _ in scores[:top_k]]

    def get_status(self) -> dict[str, Any]:
        file_sources = sorted(
            {
                doc.metadata.get("filename")
                for doc in self.documents
                if doc.metadata and doc.metadata.get("filename")
            }
        )
        return {
            "documents": len(self.documents),
            "unique_words": len(self.index),
            "storage_path": str(self.storage_path),
            "file_sources": file_sources,
        }