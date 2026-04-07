from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.rag import Document, SimpleRAG


class RagQualityTests(unittest.TestCase):
    def test_runtime_sources_are_ranked_above_generic_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            rag = SimpleRAG(Path(temp_dir) / "rag.json")
            rag.add_documents(
                [
                    Document(
                        text="OpenChimera runtime profile controls local model routing and provider behavior.",
                        metadata={"source_type": "openchimera-runtime", "filename": "runtime_profile.json", "chunk": 0},
                    ),
                    Document(
                        text="OpenChimera can also be discussed in generic notes about orchestrators.",
                        metadata={"source_type": "notes", "filename": "notes.txt", "chunk": 0},
                    ),
                ],
                persist=False,
            )

            docs = rag.retrieve("How does OpenChimera runtime profile affect routing?", top_k=2)
            self.assertEqual(docs[0].metadata["source_type"], "openchimera-runtime")

    def test_metadata_matches_boost_relevant_filename_and_topic(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            rag = SimpleRAG(Path(temp_dir) / "rag.json")
            rag.add_documents(
                [
                    Document(
                        text="MiniMind training jobs are tracked in a manifest with runtime metadata.",
                        metadata={"source_type": "minimind", "filename": "minimind_training_jobs.json", "topic": "training-jobs", "chunk": 0},
                    ),
                    Document(
                        text="General provider notes mention local runtimes and orchestrators.",
                        metadata={"source_type": "notes", "filename": "provider_notes.txt", "topic": "general", "chunk": 0},
                    ),
                ],
                persist=False,
            )

            docs = rag.retrieve("Show me MiniMind training jobs status", top_k=2)
            self.assertEqual(docs[0].metadata["filename"], "minimind_training_jobs.json")


if __name__ == "__main__":
    unittest.main()

# ---------------------------------------------------------------------------
# Tests: retrieval_backend field and embedding-aware status
# ---------------------------------------------------------------------------

class TestRAGStatusRetrievalBackend(unittest.TestCase):
    """Verify get_status() reports the active retrieval backend."""

    def test_status_has_retrieval_backend_key(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            rag = SimpleRAG(path)
            status = rag.get_status()
            self.assertIn("retrieval_backend", status)
        finally:
            import os; os.unlink(path)

    def test_retrieval_backend_is_valid_string(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            rag = SimpleRAG(path)
            backend = rag.get_status()["retrieval_backend"]
            self.assertIn(backend, {"embedding", "keyword"})
        finally:
            import os; os.unlink(path)
