from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from core.capabilities import CapabilityRegistry
from core.config import ROOT
from core.database import DatabaseManager
from core.model_roles import ModelRoleManager


class QueryEngine:
    def __init__(
        self,
        capability_registry: CapabilityRegistry,
        model_roles: ModelRoleManager,
        tool_registry: Any | None,
        completion_callback: Callable[..., dict[str, Any]],
        job_submitter: Callable[[str, dict[str, Any], int], dict[str, Any]] | None = None,
        sessions_path: Path | None = None,
        tool_history_path: Path | None = None,
        database: DatabaseManager | None = None,
        database_path: Path | None = None,
    ):
        self.capability_registry = capability_registry
        self.model_roles = model_roles
        self.tool_registry = tool_registry
        self.completion_callback = completion_callback
        self.job_submitter = job_submitter
        self.sessions_path = sessions_path or (ROOT / "data" / "query_sessions.json")
        self.tool_history_path = tool_history_path or (ROOT / "data" / "tool_execution_history.json")
        self.database = database or DatabaseManager(db_path=database_path or (self.sessions_path.parent / "openchimera.db"))
        self.database.initialize()

    def status(self) -> dict[str, Any]:
        sessions = self.list_sessions(limit=50)
        memory = self.inspect_memory()
        tool_history = self._load_tool_history().get("events", [])
        return {
            "session_count": len(sessions),
            "active_session_ids": [item.get("session_id") for item in sessions[:10]],
            "tool_history_events": len(tool_history),
            "memory": memory,
            "model_roles": self.model_roles.status().get("roles", {}),
        }

    def list_sessions(self, limit: int = 20) -> list[dict[str, Any]]:
        sessions = self._load_sessions().get("sessions", [])
        sessions.sort(key=lambda item: (int(item.get("updated_at", 0)), str(item.get("session_id", ""))), reverse=True)
        return sessions[: max(1, int(limit))]

    def get_session(self, session_id: str) -> dict[str, Any]:
        session = self._find_session(session_id)
        if session is None:
            raise ValueError(f"Unknown session: {session_id}")
        return session

    def run_query(
        self,
        query: str = "",
        messages: list[dict[str, Any]] | None = None,
        session_id: str | None = None,
        permission_scope: str = "user",
        max_tokens: int = 512,
        allow_tool_planning: bool = True,
        execute_tools: bool = False,
        tool_requests: list[dict[str, Any]] | None = None,
        allow_agent_spawn: bool = False,
        spawn_job: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload_messages = self._normalize_messages(query=query, messages=messages)
        user_query = "\n".join(str(item.get("content", "")) for item in payload_messages if item.get("role") == "user").strip()
        query_type = self._infer_query_type(user_query)
        session = self._ensure_session(session_id=session_id, permission_scope=permission_scope, user_query=user_query)
        memory = self.inspect_memory()
        role_selection = self.model_roles.select_model_for_query_type(query_type=query_type)
        suggested_tools = self._suggest_tools(user_query) if allow_tool_planning else []
        executed_tools = self._execute_requested_tools(
            tool_requests=tool_requests,
            execute_tools=execute_tools,
            permission_scope=permission_scope,
        )
        hydrated_messages = self._hydrate_messages(
            session=session,
            payload_messages=payload_messages,
            memory=memory,
            role_selection=role_selection,
            executed_tools=executed_tools,
        )
        completion = self.completion_callback(
            messages=hydrated_messages,
            model="openchimera-local",
            max_tokens=max_tokens,
            temperature=0.4 if query_type == "reasoning" else 0.7,
            stream=False,
        )
        content = str(completion.get("choices", [{}])[0].get("message", {}).get("content", ""))
        tool_event = {
            "session_id": session["session_id"],
            "query_type": query_type,
            "suggested_tools": suggested_tools,
            "requested_tools": list(tool_requests or []),
            "executed_tools": [
                {
                    "tool_id": item.get("tool_id"),
                    "status": item.get("status"),
                    "permission_scope": item.get("permission_scope"),
                }
                for item in executed_tools
            ],
            "recorded_at": int(time.time()),
        }
        self._append_tool_event(tool_event)

        spawned_job = None
        if allow_agent_spawn and isinstance(spawn_job, dict) and self.job_submitter is not None:
            job_type = str(spawn_job.get("job_type", "autonomy"))
            job_payload = spawn_job.get("payload", {}) if isinstance(spawn_job.get("payload", {}), dict) else {}
            spawned_job = self.job_submitter(job_type, job_payload, int(spawn_job.get("max_attempts", 3)))

        turn_user = {"role": "user", "content": user_query, "recorded_at": int(time.time())}
        turn_assistant = {"role": "assistant", "content": content, "recorded_at": int(time.time())}
        session.setdefault("turns", []).extend([turn_user, turn_assistant])
        session.setdefault("task_snapshots", []).append(
            {
                "recorded_at": int(time.time()),
                "query_type": query_type,
                "permission_scope": permission_scope,
                "role_selection": role_selection,
                "suggested_tools": suggested_tools,
                "executed_tools": [item.get("tool_id") for item in executed_tools],
                "spawned_job": spawned_job,
            }
        )
        session["updated_at"] = int(time.time())
        session["last_result"] = {
            "content_preview": content[:400],
            "query_type": query_type,
            "model": completion.get("model"),
        }
        self._save_session(session)

        return {
            "session_id": session["session_id"],
            "query_type": query_type,
            "permission_context": {
                "scope": permission_scope,
                "requires_admin": any(item.get("requires_admin") for item in suggested_tools),
            },
            "memory_hydration": memory,
            "role_selection": role_selection,
            "suggested_tools": suggested_tools,
            "executed_tools": executed_tools,
            "spawned_job": spawned_job,
            "response": completion,
        }

    def inspect_memory(self) -> dict[str, Any]:
        evo_memory = self._load_json(ROOT / "memory" / "evo_memory.json", default={})
        route_memory = self._load_json(ROOT / "data" / "local_llm_route_memory.json", default={})
        repo_memory = self._load_json(ROOT / "data" / "openclaw_memory_manifest.json", default={})
        session_aliases = self._load_json(ROOT / "data" / "session_aliases.json", default={})
        sessions = self._load_sessions().get("sessions", [])

        history = evo_memory.get("history", []) if isinstance(evo_memory, dict) else []
        aliases = session_aliases.get("aliases", {}) if isinstance(session_aliases, dict) else {}
        synced_files = repo_memory.get("synced_files", {}) if isinstance(repo_memory, dict) else {}
        summaries = []
        if history:
            for item in history[-3:]:
                if not isinstance(item, dict):
                    continue
                summaries.append(f"user_memory:{item.get('task', 'unknown')}={item.get('status', 'unknown')}")
        summaries.append(f"repo_memory:synced_files={len(synced_files)}")
        summaries.append(f"session_memory:sessions={len(sessions)} aliases={len(aliases)}")
        summaries.append(f"route_memory:models={len(route_memory) if isinstance(route_memory, dict) else 0}")

        return {
            "scopes": {
                "user_memory": {
                    "history_count": len(history),
                    "last_entries": history[-3:],
                },
                "repo_memory": {
                    "synced_file_count": len(synced_files),
                },
                "session_memory": {
                    "session_count": len(sessions),
                    "alias_count": len(aliases),
                },
            },
            "summaries": summaries,
        }

    def _ensure_session(self, session_id: str | None, permission_scope: str, user_query: str) -> dict[str, Any]:
        if session_id:
            session = self._find_session(session_id)
            if session is not None:
                return session
        created_at = int(time.time())
        return {
            "session_id": session_id or f"qs-{uuid.uuid4().hex[:12]}",
            "created_at": created_at,
            "updated_at": created_at,
            "title": user_query[:80] or "OpenChimera session",
            "permission_scope": permission_scope,
            "turns": [],
            "task_snapshots": [],
        }

    def _hydrate_messages(
        self,
        session: dict[str, Any],
        payload_messages: list[dict[str, Any]],
        memory: dict[str, Any],
        role_selection: dict[str, Any],
        executed_tools: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        summaries = memory.get("summaries", []) if isinstance(memory.get("summaries", []), list) else []
        if summaries:
            messages.append({"role": "system", "content": "Memory hydration:\n- " + "\n- ".join(str(item) for item in summaries)})
        role = str(role_selection.get("role") or "main_loop_model")
        model = str(role_selection.get("model") or "unresolved")
        messages.append({"role": "system", "content": f"Preferred model role for this task: {role} -> {model}"})
        if executed_tools:
            rendered_tools: list[str] = []
            for item in executed_tools[:4]:
                result = item.get("result") if isinstance(item.get("result"), dict) else {}
                preview = json.dumps(result, default=str)[:400]
                rendered_tools.append(f"{item.get('tool_id')}: {preview}")
            if rendered_tools:
                messages.append({"role": "system", "content": "Executed tools:\n- " + "\n- ".join(rendered_tools)})
        history_turns = session.get("turns", []) if isinstance(session.get("turns", []), list) else []
        for turn in history_turns[-8:]:
            if not isinstance(turn, dict):
                continue
            messages.append({"role": str(turn.get("role", "user")), "content": str(turn.get("content", ""))})
        messages.extend(payload_messages)
        return messages

    def _execute_requested_tools(
        self,
        *,
        tool_requests: list[dict[str, Any]] | None,
        execute_tools: bool,
        permission_scope: str,
    ) -> list[dict[str, Any]]:
        if not execute_tools or not tool_requests or self.tool_registry is None:
            return []
        executed: list[dict[str, Any]] = []
        for request in tool_requests[:4]:
            if not isinstance(request, dict):
                continue
            tool_id = str(request.get("tool_id") or request.get("id") or "").strip()
            if not tool_id:
                continue
            arguments = request.get("arguments", {}) if isinstance(request.get("arguments", {}), dict) else {}
            executed.append(self.tool_registry.execute(tool_id, arguments, permission_scope=permission_scope))
        return executed

    def _suggest_tools(self, query: str) -> list[dict[str, Any]]:
        lowered = query.lower()
        suggestions: list[dict[str, Any]] = []
        catalog = {str(item.get("id")): item for item in self.capability_registry.list_kind("tools")}
        mapping = [
            ("browser.fetch", ["http", "https", "fetch", "page", "website", "url"]),
            ("browser.submit_form", ["submit", "form", "post"]),
            ("media.transcribe", ["transcribe", "speech", "audio"]),
            ("media.synthesize", ["speak", "voice", "audio", "briefing"]),
            ("jobs.create", ["job", "background", "autonomy", "schedule"]),
            ("aegis.run_workflow", ["aegis", "workflow", "remediate", "audit"]),
            ("ascension.deliberate", ["deliberate", "perspective", "consensus", "reason"]),
            ("channels.dispatch_daily_briefing", ["briefing", "notify", "dispatch", "channel"]),
        ]
        for tool_id, tokens in mapping:
            if tool_id not in catalog:
                continue
            if any(token in lowered for token in tokens):
                tool = dict(catalog[tool_id])
                tool["requires_admin"] = tool_id in {
                    "browser.fetch",
                    "browser.submit_form",
                    "jobs.create",
                    "aegis.run_workflow",
                    "ascension.deliberate",
                    "channels.dispatch_daily_briefing",
                    "media.transcribe",
                    "media.synthesize",
                }
                suggestions.append(tool)
        return suggestions[:4]

    def _infer_query_type(self, query: str) -> str:
        lowered = query.lower()
        if any(token in lowered for token in ["code", "bug", "trace", "function", "stack"]):
            return "code"
        if any(token in lowered for token in ["analyze", "reason", "compare", "architecture", "consensus"]):
            return "reasoning"
        if any(token in lowered for token in ["fast", "quick", "brief"]):
            return "fast"
        return "general"

    def _normalize_messages(self, query: str, messages: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
        if isinstance(messages, list) and messages:
            return [
                {
                    "role": str(item.get("role", "user")),
                    "content": str(item.get("content", "")),
                }
                for item in messages
                if isinstance(item, dict)
            ]
        return [{"role": "user", "content": str(query)}]

    def _load_sessions(self) -> dict[str, Any]:
        sessions = self.database.list_query_sessions()
        if not isinstance(sessions, list):
            sessions = []
        return {"sessions": sessions}

    def _save_session(self, session: dict[str, Any]) -> None:
        self.database.upsert_query_session(session)

    def _find_session(self, session_id: str) -> dict[str, Any] | None:
        return self.database.get_query_session(session_id)

    def _append_tool_event(self, event: dict[str, Any]) -> None:
        self.database.append_tool_event(event)

    def _load_tool_history(self) -> dict[str, Any]:
        events = self.database.list_tool_events()
        if not isinstance(events, list):
            events = []
        return {"events": events}

    def _load_json(self, path: Path, default: dict[str, Any]) -> dict[str, Any]:
        if not path.exists():
            return default
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return default
        return raw if isinstance(raw, dict) else default