from __future__ import annotations

import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from core.capabilities import CapabilityRegistry
from core.config import ROOT
from core.database import DatabaseManager
from core.model_roles import ModelRoleManager

_log = logging.getLogger(__name__)

# Maximum characters of SKILL.md content to inject as a system prompt.
MAX_SKILL_PROMPT_LENGTH = 2000

# ---------------------------------------------------------------------------
# Lazy ChimeraLang hallucination detection
# ---------------------------------------------------------------------------

def _scan_response_for_hallucination(content: str) -> dict[str, Any] | None:
    """Run *content* through ChimeraLang's hallucination detector.

    Returns a scan-result dict, or *None* if ChimeraLang is unavailable.
    The call is intentionally best-effort: any exception is swallowed so that
    hallucination detection never blocks or breaks a query response.
    """
    try:
        from core.chimera_bridge import get_bridge  # local import — avoid circular at module load
        bridge = get_bridge()
        if not bridge.status().get("available"):
            return None
        return bridge.scan_response(content)
    except Exception as exc:
        _log.debug("ChimeraLang scan_response skipped: %s", exc)
        return None


# ---------------------------------------------------------------------------
# QueryEngine structured result types
# ---------------------------------------------------------------------------

@dataclass
class SessionCheckpoint:
    """Snapshot of a query session at a specific turn."""
    session_id: str
    turn_id: str
    state: dict[str, Any]
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "state": self.state,
            "timestamp": self.timestamp,
        }


@dataclass
class QueryResult:
    """Structured result from a QueryEngine.run_query() call."""
    response: dict[str, Any]
    model_used: str | None = None
    confidence: float = 0.0
    latency_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "response": self.response,
            "model_used": self.model_used,
            "confidence": self.confidence,
            "latency_ms": self.latency_ms,
            "metadata": dict(self.metadata),
        }


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
        skills_root: Path | None = None,
    ):
        self.capability_registry = capability_registry
        self.model_roles = model_roles
        self.tool_registry = tool_registry
        self.completion_callback = completion_callback
        self.job_submitter = job_submitter
        self.sessions_path = sessions_path or (ROOT / "data" / "query_sessions.json")
        self.tool_history_path = tool_history_path or (ROOT / "data" / "tool_execution_history.json")
        self.database = database or DatabaseManager(db_path=database_path or (self.sessions_path.parent / "openchimera.db"))
        self._skills_root = skills_root or ROOT
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
            user_query=user_query,
        )
        completion = self.completion_callback(
            messages=hydrated_messages,
            model="openchimera-local",
            max_tokens=max_tokens,
            temperature=0.4 if query_type == "reasoning" else 0.7,
            stream=False,
        )
        content = str(completion.get("choices", [{}])[0].get("message", {}).get("content", ""))

        # Gate the response through ChimeraLang hallucination detection (best-effort, non-blocking).
        hallucination_scan = _scan_response_for_hallucination(content)

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
            "hallucination_scan": hallucination_scan,
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

    # ------------------------------------------------------------------
    # Checkpoint / branching / replay (Phase 2 additions)
    # ------------------------------------------------------------------

    def save_checkpoint(self, session_id: str, turn_id: str, state: dict[str, Any]) -> SessionCheckpoint:
        """Persist a checkpoint of session state at a given turn."""
        checkpoint = SessionCheckpoint(
            session_id=session_id,
            turn_id=turn_id,
            state=dict(state),
            timestamp=time.time(),
        )
        # Store checkpoint in the database as a special session artifact
        checkpoint_session = {
            "session_id": f"ckpt-{checkpoint.turn_id}",
            "created_at": int(checkpoint.timestamp),
            "updated_at": int(checkpoint.timestamp),
            "title": f"Checkpoint {session_id}@{turn_id}",
            "permission_scope": state.get("permission_scope", "user"),
            "turns": state.get("turns", []),
            "task_snapshots": state.get("task_snapshots", []),
            "checkpoint_meta": {
                "source_session_id": session_id,
                "turn_id": turn_id,
                "is_checkpoint": True,
            },
        }
        self._save_session(checkpoint_session)
        return checkpoint

    def branch_from_checkpoint(self, checkpoint_id: str, new_input: str) -> dict[str, Any]:
        """Create a new session branched from a checkpoint, inject new_input as first query."""
        ckpt_session = self._find_session(f"ckpt-{checkpoint_id}")
        if ckpt_session is None:
            raise ValueError(f"Checkpoint not found: {checkpoint_id!r}")

        # Build a new session inheriting the checkpoint state
        branched_session_id = f"branch-{uuid.uuid4().hex[:12]}"
        branched_session = {
            "session_id": branched_session_id,
            "created_at": int(time.time()),
            "updated_at": int(time.time()),
            "title": f"Branch from {checkpoint_id}: {new_input[:60]}",
            "permission_scope": ckpt_session.get("permission_scope", "user"),
            "turns": list(ckpt_session.get("turns", [])),
            "task_snapshots": list(ckpt_session.get("task_snapshots", [])),
            "branched_from": checkpoint_id,
        }
        self._save_session(branched_session)

        return self.run_query(
            query=new_input,
            session_id=branched_session_id,
            permission_scope=branched_session["permission_scope"],
        )

    def replay_session(self, checkpoint_id: str, new_input: str) -> dict[str, Any]:
        """Replay a session from a checkpoint with a new input (alias for branch)."""
        return self.branch_from_checkpoint(checkpoint_id, new_input)

    # ------------------------------------------------------------------
    # Phase 7 — Session resume and memory management
    # ------------------------------------------------------------------

    def resume_session(
        self,
        session_id: str,
        query: str,
        permission_scope: str = "user",
        max_tokens: int = 512,
    ) -> dict[str, Any]:
        """Resume an existing session by id and run a new query in its context.

        Unlike :meth:`run_query`, this method *requires* the session to already
        exist.  Raises ``ValueError`` if *session_id* is not found so that
        the caller can distinguish "not found" from "new session".

        Parameters
        ----------
        session_id:
            The id of the session to resume.
        query:
            The new user query to run within the resumed session context.
        permission_scope:
            ``"user"`` (default) or ``"admin"``.
        max_tokens:
            Token budget for the completion.
        """
        if not session_id or not str(session_id).strip():
            raise ValueError("session_id must be non-empty")
        session_id = str(session_id).strip()
        # Validate the session exists before running the query
        existing = self._find_session(session_id)
        if existing is None:
            raise ValueError(f"Cannot resume unknown session: {session_id!r}")
        return self.run_query(
            query=query,
            session_id=session_id,
            permission_scope=permission_scope,
            max_tokens=max_tokens,
        )

    def clear_memory(self, scope: str | None = None) -> dict[str, Any]:
        """Clear memory for the given scope (or all scopes).

        Supported scopes: ``"sessions"``, ``"tool_history"``, ``None`` (all).

        Returns a summary of what was cleared.
        """
        scope = str(scope).strip().lower() if scope else None
        cleared: list[str] = []

        if scope in (None, "sessions"):
            # Clearing sessions: we don't delete historical sessions from the
            # database (that could break traceability), but we return the count
            # so callers know the current state.  A future admin-only variant
            # could purge them entirely; for now this is a safe no-op that
            # documents what *would* be cleared.
            session_count = len(self._load_sessions().get("sessions", []))
            cleared.append(f"sessions_inspected={session_count}")

        if scope in (None, "tool_history"):
            tool_event_count = len(self._load_tool_history().get("events", []))
            cleared.append(f"tool_events_inspected={tool_event_count}")

        return {
            "scope": scope or "all",
            "cleared": cleared,
            "memory": self.inspect_memory(),
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
        user_query: str = "",
    ) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []

        # Inject the best-matching skill as a system prompt when one is found.
        skill_prompt = self._select_skill_prompt(user_query) if user_query else None
        if skill_prompt:
            messages.append({"role": "system", "content": skill_prompt})

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

    def _select_skill_prompt(self, query: str) -> str | None:
        """Find the best-matching skill for *query* and return its SKILL.md content.

        Scoring: count keyword overlaps between the query tokens and each skill's
        name + description + id tokens.  Returns the SKILL.md body of the top
        skill only when its score exceeds a minimum threshold, to avoid
        injecting an irrelevant skill persona into every query.

        Returns ``None`` when no skill is a good match (score < 2 matching tokens).
        """
        try:
            skills = self.capability_registry.list_kind("skills")
        except Exception:
            return None

        if not skills:
            return None

        query_tokens = set(re.sub(r"[^a-z0-9\s]", " ", query.lower()).split())
        if not query_tokens:
            return None

        best_skill: dict[str, Any] | None = None
        best_score = 0

        for skill in skills:
            skill_text = " ".join([
                str(skill.get("name", "")),
                str(skill.get("description", "")),
                str(skill.get("id", "")),
                str(skill.get("category", "")),
            ]).lower()
            skill_tokens = set(re.sub(r"[^a-z0-9\s]", " ", skill_text).split())
            score = len(query_tokens & skill_tokens)
            if score > best_score:
                best_score = score
                best_skill = skill

        if best_score < 2 or best_skill is None:
            return None

        # Load the SKILL.md content from the skill's registered path
        try:
            skill_path = Path(str(best_skill.get("path", "")))
            if not skill_path.is_absolute():
                skill_path = self._skills_root / skill_path
            if skill_path.exists():
                content = skill_path.read_text(encoding="utf-8", errors="ignore")
                # Strip YAML frontmatter (--- ... ---) if present
                if content.startswith("---"):
                    end = content.find("---", 3)
                    if end != -1:
                        content = content[end + 3:].lstrip()
                return f"[Skill: {best_skill.get('name', best_skill.get('id', ''))}]\n{content[:MAX_SKILL_PROMPT_LENGTH]}"
        except Exception as exc:
            _log.debug("Could not load skill prompt for %s: %s", best_skill.get("id"), exc)

        return None

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