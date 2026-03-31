from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any

from core.autonomy import AutonomyScheduler
from core.bus import EventBus
from core.config import (
    ROOT,
    get_chimera_kb_path,
    get_legacy_harness_snapshot_root,
    get_provider_base_url,
    get_rag_storage_path,
    load_runtime_profile,
)
from core.harness_port import HarnessPortAdapter
from core.local_llm import LocalLLMManager
from core.minimind_service import MiniMindService
from core.personality import Personality
from core.rag import Document, SimpleRAG
from core.router import OpenChimeraRouter
from core.token_fracture import compress_context


LOGGER = logging.getLogger(__name__)


def _count_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // 4)


class OpenChimeraProvider:
    def __init__(self, bus: EventBus, personality: Personality):
        self.bus = bus
        self.personality = personality
        self.profile = load_runtime_profile()
        self.llm_manager = LocalLLMManager()
        self.router = OpenChimeraRouter(self.llm_manager)
        self.rag = SimpleRAG(get_rag_storage_path())
        self.harness_port = HarnessPortAdapter()
        self.minimind = MiniMindService()
        self.autonomy = AutonomyScheduler(self.bus, self.harness_port, self.minimind, self.personality.identity)
        self.started = False
        self.base_url = get_provider_base_url()
        self._seed_knowledge()

    def start(self) -> None:
        if self.started:
            return
        self.llm_manager.start_health_monitoring()
        if self.autonomy.should_auto_start():
            self.autonomy.start()
        self.started = True
        self.bus.publish_nowait("system/provider", self.status())

    def stop(self) -> None:
        self.autonomy.stop()
        self.llm_manager.stop_health_monitoring()
        self.started = False

    def _seed_knowledge(self) -> None:
        kb_path = get_chimera_kb_path()
        if kb_path.exists():
            try:
                data = json.loads(kb_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                data = []

            docs = []
            for item in data:
                if not isinstance(item, dict):
                    continue
                docs.append(
                    Document(
                        text=str(item.get("text", "")),
                        metadata=item.get("metadata", {}),
                        id=item.get("id"),
                    )
                )
            self.rag.add_documents(docs, persist=False)

        for path in [ROOT / "README.md", ROOT / "config" / "runtime_profile.json"]:
            self.rag.add_file(path, metadata={"source_type": "openchimera-runtime"}, persist=False)

        if self.harness_port.available:
            harness_status = self.harness_port.status()
            harness_summary = harness_status.get("summary")
            if harness_summary:
                self.rag.add_documents(
                    [
                        Document(
                            text=harness_summary,
                            metadata={"topic": "upstream-harness-port", "source_type": "harness-port"},
                        )
                    ],
                    persist=False,
                )
            self.rag.add_file(self.harness_port.root / "README.md", metadata={"source_type": "harness-port"}, persist=False)

        legacy_snapshot_root = get_legacy_harness_snapshot_root()
        self.rag.add_file(legacy_snapshot_root / "README.md", metadata={"source_type": "legacy-harness-snapshot"}, persist=False)

        if self.minimind.available:
            self.rag.add_file(self.minimind.root / "README.md", metadata={"source_type": "minimind"}, persist=False)
            self.rag.add_file(
                self.minimind.root / "CHIMERA_MINI_PROPOSAL.md",
                metadata={"source_type": "minimind"},
                persist=False,
            )

    def _infer_query_type(self, query: str) -> str:
        lowered = query.lower()
        if any(token in lowered for token in ["reply with exactly", "answer with exactly", "respond with exactly", "only reply"]):
            return "fast"
        if any(token in lowered for token in ["code", "python", "bug", "stack", "trace", "function"]):
            return "code"
        if any(token in lowered for token in ["why", "reason", "analyze", "compare", "architecture"]):
            return "reasoning"
        if any(token in lowered for token in ["quick", "short", "fast"]):
            return "fast"
        return "general"

    def _should_skip_retrieval(self, query: str, query_type: str) -> bool:
        lowered = query.lower()
        exact_markers = [
            "reply with exactly",
            "answer with exactly",
            "respond with exactly",
            "only reply",
            "exactly:",
        ]
        return query_type == "fast" or (len(query) <= 120 and any(marker in lowered for marker in exact_markers))

    def _build_context_messages(
        self,
        messages: list[dict[str, Any]],
        max_tokens: int,
        query_type: str,
    ) -> tuple[list[dict[str, str]], dict[str, Any], list[Document]]:
        query = "\n".join(str(item.get("content", "")) for item in messages if item.get("role") == "user").strip()
        compressed_messages, compression_stats = compress_context(messages, query=query, max_tokens=max_tokens)
        documents = [] if not query or self._should_skip_retrieval(query, query_type) else self.rag.retrieve(query, top_k=3)

        context_messages: list[dict[str, str]] = [
            {"role": "system", "content": self.personality.system_prompt},
        ]
        if documents:
            rag_context = "\n\n".join(
                f"Source: {doc.metadata.get('filename', doc.metadata.get('topic', 'internal'))}\n{doc.text[:600]}"
                for doc in documents
            )
            context_messages.append(
                {
                    "role": "system",
                    "content": "Use this retrieved OpenChimera context when relevant:\n\n" + rag_context,
                }
            )
        context_messages.extend(
            {
                "role": str(item.get("role", "user")),
                "content": str(item.get("content", "")),
            }
            for item in compressed_messages
        )
        return context_messages, compression_stats, documents

    def _fallback_answer(self, query: str, documents: list[Document], model_error: str | None) -> str:
        if documents:
            excerpts = []
            for doc in documents[:3]:
                label = doc.metadata.get("filename") or doc.metadata.get("topic") or "knowledge-base"
                excerpts.append(f"[{label}] {doc.text[:280]}")
            summary = "\n\n".join(excerpts)
            return (
                "OpenChimera could not reach a healthy local generation endpoint, so this response is assembled from indexed runtime knowledge.\n\n"
                f"Relevant context:\n{summary}\n\n"
                f"Requested query: {query or 'unknown'}\n"
                f"Model error: {model_error or 'unavailable'}"
            )

        return (
            "OpenChimera is online, but no healthy local model endpoint is currently reachable. "
            f"Query preserved: {query or 'unknown'}. "
            f"Model error: {model_error or 'unavailable'}."
        )

    def health(self) -> dict[str, Any]:
        llm_status = self.llm_manager.get_status()
        rag_status = self.rag.get_status()
        return {
            "status": "online",
            "name": "openchimera",
            "base_url": self.base_url,
            "components": {
                "local_llm": llm_status.get("healthy_count", 0) > 0,
                "rag": True,
                "token_fracture": True,
                "router": True,
                "harness_port": self.harness_port.available,
                "minimind": self.minimind.available,
                "autonomy": self.autonomy.status().get("running", False),
            },
            "healthy_models": llm_status.get("healthy_count", 0),
            "known_models": llm_status.get("total_count", 0),
            "documents": rag_status.get("documents", 0),
            "router": self.router.status(),
        }

    def list_models(self) -> dict[str, Any]:
        llm_status = self.llm_manager.get_status()
        models = []
        for name, details in llm_status.get("models", {}).items():
            models.append(
                {
                    "id": name,
                    "object": "model",
                    "created": 1704067200,
                    "owned_by": "openchimera",
                    "status": details.get("status"),
                    "endpoint": details.get("endpoint"),
                    "context_length": details.get("context_length"),
                }
            )
        models.append(
            {
                "id": "openchimera-local",
                "object": "model",
                "created": 1704067200,
                "owned_by": "openchimera",
                "status": "healthy",
                "endpoint": self.base_url,
                "context_length": self.profile.get("local_runtime", {}).get("context_length", 4096),
            }
        )
        return {"object": "list", "data": models}

    def local_runtime_status(self) -> dict[str, Any]:
        return self.llm_manager.get_runtime_status()

    def harness_port_status(self) -> dict[str, Any]:
        return self.harness_port.status()

    def minimind_status(self) -> dict[str, Any]:
        return self.minimind.status()

    def autonomy_status(self) -> dict[str, Any]:
        return self.autonomy.status()

    def build_minimind_dataset(self, force: bool = True) -> dict[str, Any]:
        result = self.minimind.build_training_dataset(
            self.harness_port,
            identity_snapshot=self.personality.identity,
            force=force,
        )
        self.bus.publish_nowait("system/minimind", {"action": "build_dataset", "result": result})
        return result

    def start_autonomy(self) -> dict[str, Any]:
        result = self.autonomy.start()
        self.bus.publish_nowait("system/autonomy", {"action": "start", "result": result})
        return result

    def stop_autonomy(self) -> dict[str, Any]:
        result = self.autonomy.stop()
        self.bus.publish_nowait("system/autonomy", {"action": "stop", "result": result})
        return result

    def run_autonomy_job(self, job_name: str) -> dict[str, Any]:
        result = self.autonomy.run_job(job_name)
        self.bus.publish_nowait("system/autonomy", {"action": "run_job", "job": job_name, "result": result})
        return result

    def start_local_models(self, models: list[str] | None = None) -> dict[str, Any]:
        result = self.llm_manager.start_configured_models(models)
        self.bus.publish_nowait("system/local-llm", {"action": "start", "result": result})
        return result

    def stop_local_models(self, models: list[str] | None = None) -> dict[str, Any]:
        result = self.llm_manager.stop_configured_models(models)
        self.bus.publish_nowait("system/local-llm", {"action": "stop", "result": result})
        return result

    def embeddings(self, input_text: str, model: str = "openchimera-local") -> dict[str, Any]:
        vector_size = 64
        vector = [0.0] * vector_size
        for token in input_text.lower().split():
            bucket = int(hashlib.sha256(token.encode("utf-8")).hexdigest(), 16) % vector_size
            vector[bucket] += 1.0
        return {
            "object": "list",
            "data": [{"object": "embedding", "index": 0, "embedding": vector}],
            "model": model,
            "usage": {"prompt_tokens": _count_tokens(input_text), "total_tokens": _count_tokens(input_text)},
        }

    def chat_completion(
        self,
        messages: list[dict[str, Any]],
        model: str = "openchimera-local",
        temperature: float = 0.7,
        max_tokens: int = 1024,
        stream: bool = False,
    ) -> dict[str, Any]:
        request_id = f"openchimera-{uuid.uuid4().hex[:12]}"
        created = int(time.time())
        query = "\n".join(str(item.get("content", "")) for item in messages if item.get("role") == "user").strip()
        query_type = self._infer_query_type(query)
        if max_tokens <= 128 and query_type == "general":
            query_type = "fast"
        context_messages, compression_stats, documents = self._build_context_messages(
            messages,
            max_tokens=max(512, max_tokens * 4),
            query_type=query_type,
        )
        request_timeout = float(self.profile.get("local_runtime", {}).get("local_timeout_s", 35.0))
        max_retries = 2
        if query_type == "fast":
            request_timeout = max(20.0, min(request_timeout, 30.0))
            max_retries = 1
        elif query_type == "general":
            request_timeout = max(25.0, min(request_timeout, 35.0))
            max_retries = 1

        attempted_models: list[str] = []
        result: dict[str, Any] = {"content": "", "model": None, "error": "No healthy local models available"}
        for _ in range(max_retries + 1):
            route = self.router.decide(
                query=query,
                query_type=query_type,
                max_tokens=max_tokens,
                exclude=attempted_models,
            )
            if route.model is None:
                result = {
                    "content": "",
                    "model": attempted_models[-1] if attempted_models else None,
                    "error": result.get("error") or "No healthy local models available",
                }
                break

            attempted_models.append(route.model)
            result = self.llm_manager.chat_completion(
                messages=context_messages,
                model=route.model,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=request_timeout,
            )
            if result.get("content") and not result.get("error"):
                result["route_reason"] = route.reason
                break

        content = result.get("content") or self._fallback_answer(query, documents, result.get("error"))
        model_used = result.get("model") or model

        prompt_tokens = sum(_count_tokens(str(item.get("content", ""))) for item in context_messages)
        completion_tokens = _count_tokens(content)
        response = {
            "id": request_id,
            "object": "chat.completion",
            "created": created,
            "model": model_used,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
            "openchimera": {
                "compression": compression_stats,
                "retrieved_documents": [doc.metadata for doc in documents],
                "fallback_used": bool(result.get("error")),
                "stream_requested": stream,
                "attempted_models": attempted_models,
                "route_reason": result.get("route_reason"),
            },
        }
        self.bus.publish_nowait(
            "llm/completion",
            {
                "request_id": request_id,
                "model": model_used,
                "query_type": query_type,
                "fallback": bool(result.get("error")),
                "attempted_models": attempted_models,
            },
        )
        return response

    def status(self) -> dict[str, Any]:
        return {
            "online": True,
            "base_url": self.base_url,
            "health": self.health(),
            "models": self.list_models().get("data", []),
            "llm": self.llm_manager.get_status(),
            "router": self.router.status(),
            "rag": self.rag.get_status(),
            "harness_port": self.harness_port_status(),
            "minimind": self.minimind_status(),
            "autonomy": self.autonomy_status(),
        }