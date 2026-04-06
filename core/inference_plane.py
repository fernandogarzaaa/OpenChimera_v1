from __future__ import annotations

import json
import logging
import os
import time
import uuid
from typing import Any
from urllib import error, request

from core.rag import Document
from core.token_fracture import compress_context


LOGGER = logging.getLogger(__name__)


def _count_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // 4)


class InferencePlane:
    def __init__(
        self,
        *,
        personality: Any,
        rag: Any,
        llm_manager: Any,
        minimind: Any,
        router: Any,
        model_registry: Any,
        credential_store: Any,
        observability: Any,
        bus: Any,
        profile_getter: Any,
    ) -> None:
        self.personality = personality
        self.rag = rag
        self.llm_manager = llm_manager
        self.minimind = minimind
        self.router = router
        self.model_registry = model_registry
        self.credential_store = credential_store
        self.observability = observability
        self.bus = bus
        self._profile_getter = profile_getter

    @property
    def profile(self) -> dict[str, Any]:
        return dict(self._profile_getter() or {})

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

    def _should_force_fast_path(self, query: str, query_type: str, max_tokens: int) -> bool:
        if query_type != "general":
            return False
        if max_tokens > 64:
            return False
        lowered = query.lower()
        substantive_markers = [
            "summary",
            "summarize",
            "technical",
            "architecture",
            "explain",
            "describe",
            "overview",
        ]
        if any(marker in lowered for marker in substantive_markers):
            return False
        return len(query.strip()) <= 120

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

    def _free_model_fallback_enabled(self) -> bool:
        return bool(self.profile.get("providers", {}).get("prefer_free_models", False))

    def _openrouter_api_key(self) -> str:
        env_value = os.getenv("OPENROUTER_API_KEY", "").strip()
        if env_value:
            return env_value
        stored = self.credential_store.get_provider_credentials("openrouter")
        return str(stored.get("OPENROUTER_API_KEY", "")).strip()

    def _huggingface_api_key(self) -> str:
        env_value = os.getenv("HF_TOKEN", "").strip()
        if env_value:
            return env_value
        stored = self.credential_store.get_provider_credentials("huggingface")
        return str(stored.get("HF_TOKEN", "")).strip()

    def _post_json_request(
        self,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        request_headers = {"Content-Type": "application/json"}
        if headers:
            request_headers.update(headers)
        req = request.Request(url, data=body, headers=request_headers, method="POST")
        with request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}

    def _call_openrouter_free_model(
        self,
        model_id: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        timeout: float,
    ) -> dict[str, Any]:
        api_key = self._openrouter_api_key()
        if not api_key:
            raise RuntimeError("OpenRouter API key is not configured")
        return self._post_json_request(
            "https://openrouter.ai/api/v1/chat/completions",
            {
                "model": model_id,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": False,
            },
            headers={
                "Authorization": f"Bearer {api_key}",
                "HTTP-Referer": "https://openchimera.local",
                "X-Title": "OpenChimera",
            },
            timeout=timeout,
        )

    def _call_ollama_free_model(
        self,
        model_id: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        timeout: float,
    ) -> dict[str, Any]:
        return self._post_json_request(
            "http://127.0.0.1:11434/api/chat",
            {
                "model": model_id,
                "messages": messages,
                "stream": False,
                "options": {
                    "temperature": temperature,
                    "num_predict": max_tokens,
                },
            },
            timeout=timeout,
        )

    def _call_huggingface_free_model(
        self,
        model_id: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        timeout: float,
    ) -> dict[str, Any]:
        hf_model = model_id.removeprefix("huggingface/")
        api_key = self._huggingface_api_key()
        headers: dict[str, str] = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        return self._post_json_request(
            f"https://router.huggingface.co/hf-inference/models/{hf_model}/v1/chat/completions",
            {
                "model": hf_model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": False,
            },
            headers=headers,
            timeout=timeout,
        )

    def _extract_remote_completion_text(self, payload: dict[str, Any]) -> str:
        choices = payload.get("choices", []) if isinstance(payload, dict) else []
        if choices:
            content = choices[0].get("message", {}).get("content", "")
            if isinstance(content, list):
                text_parts = [str(item.get("text", "")) for item in content if isinstance(item, dict)]
                return "\n".join(part for part in text_parts if part).strip()
            return str(content).strip()
        message = payload.get("message", {}) if isinstance(payload, dict) else {}
        if isinstance(message, dict):
            return str(message.get("content", "")).strip()
        return ""

    def _supports_free_fallback_candidate(self, candidate: dict[str, Any]) -> bool:
        provider = str(candidate.get("provider") or "").strip().lower()
        model_id = str(candidate.get("id") or "").strip()
        source = str(candidate.get("source") or "").strip().lower()
        if provider == "ollama":
            return True
        if provider == "huggingface" or model_id.startswith("huggingface/"):
            return True
        if source in {"autonomy-sync", "autonomy-discovery"} and self._openrouter_api_key():
            return True
        if model_id.endswith(":free") and self._openrouter_api_key():
            return True
        if model_id == "openrouter/free" and self._openrouter_api_key():
            return True
        return False

    def _free_fallback_candidates(self, query_type: str, exclude: list[str] | None = None) -> list[dict[str, Any]]:
        exclude_set = {str(item) for item in (exclude or [])}
        registry = self.model_registry.status()
        candidates: list[tuple[int, int, int, int, str, dict[str, Any]]] = []
        for item in registry.get("cloud_models", []):
            if not isinstance(item, dict):
                continue
            model_id = str(item.get("id") or "").strip()
            if not model_id or model_id in exclude_set:
                continue
            if not self._supports_free_fallback_candidate(item):
                continue
            recommended_for = [str(entry) for entry in item.get("recommended_for", []) if str(entry).strip()]
            capability_rank = 0 if query_type in recommended_for else (1 if "fallback" in recommended_for else 2)
            provider = str(item.get("provider") or "").strip().lower()
            learned_rank = int(item.get("learned_rank") or 999999)
            degraded_rank = 1 if bool(item.get("learned_degraded", False)) else 0
            provider_rank = 0 if provider == "ollama" else 1
            candidates.append((capability_rank, degraded_rank, learned_rank, provider_rank, model_id, dict(item)))
        candidates.sort(key=lambda entry: (entry[0], entry[1], entry[2], entry[3], entry[4]))
        return [item for _, _, _, _, _, item in candidates]

    def _run_free_model_fallback(
        self,
        messages: list[dict[str, str]],
        query_type: str,
        temperature: float,
        max_tokens: int,
        timeout: float,
        exclude: list[str] | None = None,
    ) -> dict[str, Any]:
        attempted: list[str] = []
        for candidate in self._free_fallback_candidates(query_type=query_type, exclude=exclude):
            model_id = str(candidate.get("id") or "").strip()
            provider = str(candidate.get("provider") or "").strip().lower() or "openrouter"
            if not model_id:
                continue
            attempted.append(model_id)
            started_at = time.time()
            try:
                if provider == "ollama":
                    payload = self._call_ollama_free_model(model_id, messages, temperature, max_tokens, timeout)
                elif provider == "huggingface" or model_id.startswith("huggingface/"):
                    provider = "huggingface"
                    payload = self._call_huggingface_free_model(model_id, messages, temperature, max_tokens, timeout)
                else:
                    provider = "openrouter"
                    payload = self._call_openrouter_free_model(model_id, messages, temperature, max_tokens, timeout)
                content = self._extract_remote_completion_text(payload)
                latency_ms = (time.time() - started_at) * 1000
                if not self.llm_manager._is_usable_completion(content):
                    self.llm_manager._record_route_outcome(model_id, query_type, success=False, latency_ms=latency_ms, low_quality=True)
                    continue
                self.llm_manager._record_route_outcome(model_id, query_type, success=True, latency_ms=latency_ms, low_quality=False)
                return {
                    "content": content,
                    "model": model_id,
                    "query_type": query_type,
                    "prompt_strategy": "remote-chat-guided",
                    "prompt_strategies_tried": ["remote-chat-guided"],
                    "latency_ms": latency_ms,
                    "error": None,
                    "route_reason": f"free-fallback-{provider}",
                    "fallback_used": True,
                    "free_fallback_provider": provider,
                    "free_fallback_source": str(candidate.get("source") or "catalog"),
                    "attempted_models": attempted,
                }
            except (RuntimeError, error.HTTPError, error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
                latency_ms = (time.time() - started_at) * 1000
                self.llm_manager._record_route_outcome(model_id, query_type, success=False, latency_ms=latency_ms, low_quality=False)
                LOGGER.debug("Free fallback candidate failed for %s: %s", model_id, exc)
                continue
        return {
            "content": "",
            "model": attempted[-1] if attempted else None,
            "query_type": query_type,
            "prompt_strategy": "remote-chat-guided",
            "prompt_strategies_tried": ["remote-chat-guided"],
            "error": f"All free fallback models failed (tried: {', '.join(attempted)})" if attempted else "No supported free fallback models available",
            "fallback_used": False,
            "attempted_models": attempted,
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
        if self._should_force_fast_path(query, query_type, max_tokens):
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
        if query_type == "reasoning":
            minimind_result = self.minimind.reasoning_completion(
                messages=context_messages,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=max(request_timeout, 60.0),
            )
            if minimind_result.get("content") and not minimind_result.get("error"):
                result = {
                    "content": minimind_result["content"],
                    "model": minimind_result.get("model", "minimind"),
                    "query_type": query_type,
                    "prompt_strategy": "minimind_reasoning",
                    "route_reason": "minimind-reasoning-engine",
                }

        for _ in range(max_retries + 1):
            if result.get("content") and not result.get("error"):
                break
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
                query_type=query_type,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=request_timeout,
            )
            if result.get("content") and not result.get("error"):
                result["route_reason"] = route.reason
                break

        if (not result.get("content") or result.get("error")) and self._free_model_fallback_enabled():
            free_fallback_result = self._run_free_model_fallback(
                messages=context_messages,
                query_type=query_type,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=max(request_timeout, 45.0),
                exclude=attempted_models,
            )
            attempted_models.extend(
                [
                    model_name
                    for model_name in free_fallback_result.get("attempted_models", [])
                    if model_name not in attempted_models
                ]
            )
            if free_fallback_result.get("content") and not free_fallback_result.get("error"):
                result = free_fallback_result

        content = result.get("content") or self._fallback_answer(query, documents, result.get("error"))
        model_used = result.get("model") or model
        prompt_strategy = result.get("prompt_strategy")
        prompt_strategies_tried = result.get("prompt_strategies_tried")
        if prompt_strategy is None and model_used and model_used != "minimind":
            prompt_strategy = self.llm_manager._prompt_strategy_for_model(str(model_used))
        if prompt_strategies_tried is None and prompt_strategy is not None:
            prompt_strategies_tried = [prompt_strategy]
        fallback_used = bool(result.get("fallback_used")) or bool(result.get("error"))

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
                "fallback_used": fallback_used,
                "query_type": query_type,
                "stream_requested": stream,
                "attempted_models": attempted_models,
                "prompt_strategy": prompt_strategy,
                "prompt_strategies_tried": prompt_strategies_tried,
                "route_reason": result.get("route_reason"),
                "free_fallback_used": bool(result.get("fallback_used")),
                "free_fallback_provider": result.get("free_fallback_provider"),
                "free_fallback_source": result.get("free_fallback_source"),
                "minimind_runtime": self.minimind.get_runtime_status(),
            },
        }
        self.bus.publish_nowait(
            "llm/completion",
            {
                "request_id": request_id,
                "model": model_used,
                "query_type": query_type,
                "fallback": fallback_used,
                "attempted_models": attempted_models,
                "prompt_strategy": prompt_strategy,
                "prompt_strategies_tried": prompt_strategies_tried,
            },
        )
        self.observability.record_completion(
            request_id=request_id,
            model=str(model_used),
            query_type=str(query_type),
            fallback=fallback_used,
        )
        return response