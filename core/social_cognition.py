"""OpenChimera Social Cognition — AGI Capability #10.

Provides a Theory-of-Mind engine, relationship memory, and social context
tracking so OpenChimera can model other agents' mental states, maintain
persistent relationship histories, and reason about social norms.

Architecture
────────────
TheoryOfMind          Model beliefs, desires and intentions of other agents.
RelationshipMemory    Persistent trust / sentiment / interaction history.
SocialContextTracker  Track active social contexts (conversations, shared goals).
SocialNormRegistry    Named norms the system respects and can evaluate.
SocialCognition       Top-level facade; all other classes are composed here.

All classes are thread-safe and publish events via EventBus when available.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from core._bus_fallback import EventBus

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class MentalState:
    """Snapshot of an agent's inferred mental state."""

    agent_id: str
    beliefs: dict[str, Any] = field(default_factory=dict)
    desires: list[str] = field(default_factory=list)
    intentions: list[str] = field(default_factory=list)
    emotion: str = "neutral"
    confidence: float = 0.5
    updated_at: float = field(default_factory=time.time)


@dataclass
class RelationshipRecord:
    """Accumulated relationship data for a single counterpart."""

    agent_id: str
    trust: float = 0.5          # 0.0 = no trust, 1.0 = full trust
    sentiment: float = 0.0      # -1.0 negative, +1.0 positive
    interaction_count: int = 0
    last_interaction: float = 0.0
    shared_goals: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class SocialContext:
    """An active social situation being tracked."""

    context_id: str
    participants: list[str] = field(default_factory=list)
    topic: str = ""
    goal: str = ""
    active: bool = True
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SocialNorm:
    """A named social norm with an associated rule string and weight."""

    name: str
    rule: str
    weight: float = 1.0
    category: str = "general"


# ---------------------------------------------------------------------------
# Theory of Mind
# ---------------------------------------------------------------------------


class TheoryOfMind:
    """Model other agents' beliefs, desires, and intentions.

    Maintains a registry of inferred mental states.  States are updated via
    :meth:`update_mental_state` and queried via :meth:`get_mental_state`.
    The engine can also answer simple perspective-taking queries via
    :meth:`predict_response`.

    Parameters
    ──────────
    bus  Optional EventBus for publishing ``social/mental_state_update`` events.
    """

    def __init__(self, bus: "Any | None" = None) -> None:
        self._bus = bus
        self._states: dict[str, MentalState] = {}
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # State management
    # ------------------------------------------------------------------

    def update_mental_state(
        self,
        agent_id: str,
        *,
        beliefs: "dict[str, Any] | None" = None,
        desires: "list[str] | None" = None,
        intentions: "list[str] | None" = None,
        emotion: "str | None" = None,
        confidence: "float | None" = None,
    ) -> MentalState:
        """Upsert the inferred mental state for *agent_id*.

        Partial updates are supported — only supplied keyword args are applied.
        Returns the new state snapshot.
        """
        with self._lock:
            state = self._states.get(agent_id)
            if state is None:
                state = MentalState(agent_id=agent_id)
                self._states[agent_id] = state
            if beliefs is not None:
                state.beliefs.update(beliefs)
            if desires is not None:
                state.desires = list(desires)
            if intentions is not None:
                state.intentions = list(intentions)
            if emotion is not None:
                state.emotion = emotion
            if confidence is not None:
                state.confidence = float(max(0.0, min(1.0, confidence)))
            state.updated_at = time.time()

        if self._bus is not None:
            self._bus.publish_nowait(
                "social/mental_state_update",
                {"agent_id": agent_id, "emotion": state.emotion, "confidence": state.confidence},
            )
        log.debug("[ToM] Updated mental state for '%s': emotion=%s conf=%.2f", agent_id, state.emotion, state.confidence)
        return state

    def get_mental_state(self, agent_id: str) -> "MentalState | None":
        """Return the current mental state for *agent_id*, or ``None``."""
        with self._lock:
            return self._states.get(agent_id)

    def all_agents(self) -> list[str]:
        """Return all agent IDs currently tracked."""
        with self._lock:
            return list(self._states)

    # ------------------------------------------------------------------
    # Perspective-taking
    # ------------------------------------------------------------------

    def predict_response(self, agent_id: str, situation: str) -> str:
        """Produce a simple natural-language prediction of how *agent_id*
        might respond to *situation* given its inferred mental state.

        Returns a best-effort string; returns ``"unknown"`` if the agent has
        no recorded mental state.
        """
        state = self.get_mental_state(agent_id)
        if state is None:
            return "unknown"
        parts: list[str] = []
        if state.emotion in {"happy", "satisfied", "excited"}:
            parts.append("likely receptive")
        elif state.emotion in {"frustrated", "angry", "confused"}:
            parts.append("may resist or question")
        else:
            parts.append("neutral stance")
        if state.intentions:
            parts.append(f"focused on: {', '.join(state.intentions[:2])}")
        return f"Agent '{agent_id}' ({state.emotion}, conf={state.confidence:.2f}): {'; '.join(parts)}."

    def snapshot(self) -> dict[str, Any]:
        """Return serialisable snapshot of all mental states."""
        with self._lock:
            return {
                agent_id: {
                    "beliefs": state.beliefs,
                    "desires": state.desires,
                    "intentions": state.intentions,
                    "emotion": state.emotion,
                    "confidence": state.confidence,
                    "updated_at": state.updated_at,
                }
                for agent_id, state in self._states.items()
            }


# ---------------------------------------------------------------------------
# Relationship Memory
# ---------------------------------------------------------------------------


class RelationshipMemory:
    """Persistent relationship history between OpenChimera and other agents.

    Trust and sentiment are updated incrementally.  Shared goals and free-text
    notes can be appended.  The full record for any counterpart is accessible
    via :meth:`get`.

    Parameters
    ──────────
    bus  Optional EventBus for publishing ``social/relationship_updated`` events.
    """

    _TRUST_DECAY_RATE: float = 0.005   # per interaction without reinforcement
    _MAX_NOTES: int = 50

    def __init__(self, bus: "Any | None" = None) -> None:
        self._bus = bus
        self._records: dict[str, RelationshipRecord] = {}
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # Updates
    # ------------------------------------------------------------------

    def record_interaction(
        self,
        agent_id: str,
        *,
        sentiment_delta: float = 0.0,
        trust_delta: float = 0.0,
        note: "str | None" = None,
        shared_goal: "str | None" = None,
    ) -> RelationshipRecord:
        """Record an interaction with *agent_id*.

        *sentiment_delta* and *trust_delta* are clamped to keep values in
        [-1, 1] and [0, 1] respectively.
        """
        with self._lock:
            rec = self._get_or_create(agent_id)
            rec.sentiment = float(max(-1.0, min(1.0, rec.sentiment + sentiment_delta)))
            rec.trust = float(max(0.0, min(1.0, rec.trust + trust_delta)))
            rec.interaction_count += 1
            rec.last_interaction = time.time()
            if note is not None:
                rec.notes.append(note)
                if len(rec.notes) > self._MAX_NOTES:
                    rec.notes = rec.notes[-self._MAX_NOTES:]
            if shared_goal and shared_goal not in rec.shared_goals:
                rec.shared_goals.append(shared_goal)

        if self._bus is not None:
            self._bus.publish_nowait(
                "social/relationship_updated",
                {"agent_id": agent_id, "trust": rec.trust, "sentiment": rec.sentiment},
            )
        log.debug(
            "[RelMem] interaction recorded: agent=%s trust=%.2f sentiment=%.2f",
            agent_id, rec.trust, rec.sentiment,
        )
        return rec

    def get(self, agent_id: str) -> "RelationshipRecord | None":
        """Return the relationship record for *agent_id*, or ``None``."""
        with self._lock:
            return self._records.get(agent_id)

    def all_agents(self) -> list[str]:
        """Return all counterpart IDs with relationship records."""
        with self._lock:
            return list(self._records)

    def trusted_agents(self, threshold: float = 0.6) -> list[str]:
        """Return agents whose trust exceeds *threshold*."""
        with self._lock:
            return [aid for aid, rec in self._records.items() if rec.trust >= threshold]

    def snapshot(self) -> list[dict[str, Any]]:
        """Return all relationship records as a list of dicts."""
        with self._lock:
            return [
                {
                    "agent_id": rec.agent_id,
                    "trust": rec.trust,
                    "sentiment": rec.sentiment,
                    "interaction_count": rec.interaction_count,
                    "last_interaction": rec.last_interaction,
                    "shared_goals": list(rec.shared_goals),
                    "notes": list(rec.notes),
                }
                for rec in self._records.values()
            ]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_or_create(self, agent_id: str) -> RelationshipRecord:
        rec = self._records.get(agent_id)
        if rec is None:
            rec = RelationshipRecord(agent_id=agent_id)
            self._records[agent_id] = rec
        return rec


# ---------------------------------------------------------------------------
# Social Context Tracker
# ---------------------------------------------------------------------------


class SocialContextTracker:
    """Track active social contexts (conversations, negotiation sessions, etc.).

    Parameters
    ──────────
    bus  Optional EventBus for publishing ``social/context_opened`` and
         ``social/context_closed`` events.
    """

    def __init__(self, bus: "Any | None" = None) -> None:
        self._bus = bus
        self._contexts: dict[str, SocialContext] = {}
        self._lock = threading.RLock()

    def open_context(
        self,
        context_id: str,
        participants: "list[str]",
        topic: str = "",
        goal: str = "",
        metadata: "dict[str, Any] | None" = None,
    ) -> SocialContext:
        """Create or reactivate a social context."""
        with self._lock:
            ctx = self._contexts.get(context_id)
            if ctx is None:
                ctx = SocialContext(
                    context_id=context_id,
                    participants=list(participants),
                    topic=topic,
                    goal=goal,
                    metadata=metadata or {},
                )
                self._contexts[context_id] = ctx
            else:
                ctx.active = True
                ctx.participants = list(participants)
                ctx.topic = topic
                ctx.goal = goal

        if self._bus is not None:
            self._bus.publish_nowait(
                "social/context_opened",
                {"context_id": context_id, "participants": participants, "topic": topic},
            )
        log.debug("[SocialCtx] Context opened: %s (%d participants)", context_id, len(participants))
        return ctx

    def close_context(self, context_id: str) -> bool:
        """Mark a context as closed.  Returns ``True`` if found."""
        with self._lock:
            ctx = self._contexts.get(context_id)
            if ctx is None:
                return False
            ctx.active = False

        if self._bus is not None:
            self._bus.publish_nowait("social/context_closed", {"context_id": context_id})
        return True

    def get_context(self, context_id: str) -> "SocialContext | None":
        with self._lock:
            return self._contexts.get(context_id)

    def active_contexts(self) -> list[SocialContext]:
        with self._lock:
            return [c for c in self._contexts.values() if c.active]

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {
                    "context_id": c.context_id,
                    "participants": c.participants,
                    "topic": c.topic,
                    "goal": c.goal,
                    "active": c.active,
                    "created_at": c.created_at,
                }
                for c in self._contexts.values()
            ]


# ---------------------------------------------------------------------------
# Social Norm Registry
# ---------------------------------------------------------------------------


class SocialNormRegistry:
    """Named social norms the system respects and can evaluate.

    Norms have a weight (importance) and a free-text rule string.  The
    :meth:`evaluate` method scores a proposed action against all active norms.
    """

    def __init__(self) -> None:
        self._norms: dict[str, SocialNorm] = {}
        self._lock = threading.RLock()
        self._seed_defaults()

    def _seed_defaults(self) -> None:
        defaults = [
            SocialNorm("reciprocity", "Return help or value given by others.", weight=0.8, category="cooperation"),
            SocialNorm("honesty", "Do not deceive or mislead others.", weight=1.0, category="ethics"),
            SocialNorm("respect_autonomy", "Do not override another agent's goals without consent.", weight=0.9, category="ethics"),
            SocialNorm("confidentiality", "Protect sensitive information shared in context.", weight=0.85, category="privacy"),
            SocialNorm("fairness", "Distribute effort and credit equitably.", weight=0.75, category="cooperation"),
        ]
        for norm in defaults:
            self._norms[norm.name] = norm

    def add_norm(self, name: str, rule: str, weight: float = 1.0, category: str = "general") -> SocialNorm:
        with self._lock:
            norm = SocialNorm(name=name, rule=rule, weight=weight, category=category)
            self._norms[name] = norm
            log.debug("[NormRegistry] Added norm '%s' (weight=%.2f)", name, weight)
            return norm

    def get_norm(self, name: str) -> "SocialNorm | None":
        with self._lock:
            return self._norms.get(name)

    def evaluate(self, action_description: str) -> dict[str, Any]:
        """Score an action description against all registered norms.

        Returns a dict with a ``total_score`` in [0, 1] (higher = more
        norm-compliant) and per-norm breakdowns.
        """
        keywords_violating = {
            "honesty": ["deceive", "lie", "mislead", "hide", "fake"],
            "respect_autonomy": ["override", "force", "coerce", "block goals"],
            "confidentiality": ["leak", "expose", "share secret", "reveal private"],
            "fairness": ["steal credit", "exploit", "unfair", "bias"],
            "reciprocity": ["ignore help", "refuse to return", "take without giving"],
        }
        action_lower = action_description.lower()
        results: list[dict[str, Any]] = []
        with self._lock:
            for name, norm in self._norms.items():
                violated = any(kw in action_lower for kw in keywords_violating.get(name, []))
                score = 0.0 if violated else 1.0
                results.append({"norm": name, "weight": norm.weight, "score": score, "violated": violated})

        total_weight = sum(r["weight"] for r in results) or 1.0
        weighted_score = sum(r["score"] * r["weight"] for r in results) / total_weight
        return {"total_score": round(weighted_score, 4), "norms": results}

    def all_norms(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {"name": n.name, "rule": n.rule, "weight": n.weight, "category": n.category}
                for n in self._norms.values()
            ]


# ---------------------------------------------------------------------------
# SocialCognition — top-level facade
# ---------------------------------------------------------------------------


class SocialCognition:
    """Top-level facade for OpenChimera's social cognition subsystem.

    Composes:
    - :class:`TheoryOfMind` — model other agents' mental states
    - :class:`RelationshipMemory` — track relationship history
    - :class:`SocialContextTracker` — track active social contexts
    - :class:`SocialNormRegistry` — evaluate social norm compliance

    Publishes events via EventBus and provides a unified ``snapshot()`` for
    persistence or introspection.

    Parameters
    ──────────
    bus  Optional :class:`~core._bus_fallback.EventBus` instance.
    """

    def __init__(self, bus: "Any | None" = None) -> None:
        self._bus = bus
        self.theory_of_mind = TheoryOfMind(bus=bus)
        self.relationship_memory = RelationshipMemory(bus=bus)
        self.social_context = SocialContextTracker(bus=bus)
        self.norm_registry = SocialNormRegistry()
        log.info("[SocialCognition] Subsystem initialised.")

    # ------------------------------------------------------------------
    # Convenience delegation methods
    # ------------------------------------------------------------------

    def observe_agent(
        self,
        agent_id: str,
        *,
        beliefs: "dict[str, Any] | None" = None,
        desires: "list[str] | None" = None,
        intentions: "list[str] | None" = None,
        emotion: "str | None" = None,
        confidence: "float | None" = None,
        sentiment_delta: float = 0.0,
        trust_delta: float = 0.0,
        note: "str | None" = None,
    ) -> dict[str, Any]:
        """One-call update: update ToM state AND record a relationship interaction.

        Returns a summary dict with the updated mental state and relationship record.
        """
        mental = self.theory_of_mind.update_mental_state(
            agent_id,
            beliefs=beliefs,
            desires=desires,
            intentions=intentions,
            emotion=emotion,
            confidence=confidence,
        )
        rel = self.relationship_memory.record_interaction(
            agent_id,
            sentiment_delta=sentiment_delta,
            trust_delta=trust_delta,
            note=note,
        )
        return {
            "mental_state": {
                "emotion": mental.emotion,
                "confidence": mental.confidence,
                "intentions": mental.intentions,
            },
            "relationship": {
                "trust": rel.trust,
                "sentiment": rel.sentiment,
                "interaction_count": rel.interaction_count,
            },
        }

    def is_trustworthy(self, agent_id: str, threshold: float = 0.6) -> bool:
        """Return True if the agent's trust score exceeds *threshold*."""
        rec = self.relationship_memory.get(agent_id)
        return rec is not None and rec.trust >= threshold

    def evaluate_action(self, action: str) -> dict[str, Any]:
        """Evaluate a proposed action against social norms."""
        return self.norm_registry.evaluate(action)

    def predict_agent_response(self, agent_id: str, situation: str) -> str:
        """Delegate to TheoryOfMind.predict_response."""
        return self.theory_of_mind.predict_response(agent_id, situation)

    # ------------------------------------------------------------------
    # Snapshot / export
    # ------------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        """Return a full serialisable snapshot of the social cognition subsystem."""
        return {
            "theory_of_mind": self.theory_of_mind.snapshot(),
            "relationships": self.relationship_memory.snapshot(),
            "active_contexts": self.social_context.snapshot(),
            "norms": self.norm_registry.all_norms(),
        }
