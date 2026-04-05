"""OpenChimera Transfer Learning — cross-domain pattern reuse.

Caches domain-agnostic reasoning patterns and enables knowledge transfer
between domains. When the system learns effective strategies in one domain,
this module identifies reusable abstractions and applies them to new domains.

Fully portable — purely in-memory with optional EventBus notifications.
No hardcoded paths, no external dependencies beyond the core bus.

Architecture
────────────
PatternEntry           Immutable record of a reusable reasoning pattern.
TransferCandidate      A pattern matched to a target domain with relevance score.
DomainProfile          Summary statistics for a single domain's knowledge.
TransferLearning       Main engine managing pattern extraction, matching, and application.

Key capabilities:
1. Pattern extraction — distils successful strategies into reusable patterns
2. Cross-domain matching — finds similar patterns across domains
3. Few-shot transfer — applies matched patterns to new domains
4. Decay — older unsupported patterns lose relevance
"""
from __future__ import annotations

import hashlib
import logging
import math
import statistics
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

from core._bus_fallback import EventBus

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class PatternType(str, Enum):
    """Category of a transferable pattern."""
    STRATEGY = "strategy"       # Reasoning strategy
    HEURISTIC = "heuristic"     # Quick decision rule
    TEMPLATE = "template"       # Structural template
    CONSTRAINT = "constraint"   # Constraint or guard rule
    ANALOGY = "analogy"         # Cross-domain analogy


# ---------------------------------------------------------------------------
# Data objects
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PatternEntry:
    """A reusable reasoning pattern extracted from experience."""
    pattern_id: str
    source_domain: str
    pattern_type: PatternType
    description: str
    keywords: Tuple[str, ...]
    success_rate: float       # 0..1 in source domain
    transfer_count: int       # times successfully transferred
    created_at: float
    last_used: float
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TransferCandidate:
    """A pattern matched to a target domain with computed relevance."""
    pattern: PatternEntry
    target_domain: str
    relevance_score: float    # 0..1, higher = better match
    keyword_overlap: float    # Jaccard coefficient of keywords
    type_match: bool          # True if pattern_type fits target need


@dataclass(frozen=True)
class DomainProfile:
    """Summary of a domain's knowledge state."""
    domain: str
    pattern_count: int
    avg_success_rate: float
    total_transfers_in: int
    total_transfers_out: int
    top_keywords: Tuple[str, ...]
    coverage_score: float     # 0..1, how well-covered the domain is


# ---------------------------------------------------------------------------
# Transfer Learning engine
# ---------------------------------------------------------------------------

class TransferLearning:
    """
    Cross-domain pattern reuse engine. Extracts, stores, matches, and
    transfers reasoning patterns between domains.

    Thread-safe. Publishes transfer events to EventBus.

    Parameters
    ──────────
    bus               EventBus for publishing events.
    max_patterns      Maximum patterns stored before pruning oldest.
    decay_halflife_s  Half-life in seconds for pattern relevance decay.
    min_relevance     Minimum relevance score to qualify as a transfer candidate.
    """

    def __init__(
        self,
        bus: EventBus,
        max_patterns: int = 500,
        decay_halflife_s: float = 86400.0,  # 24 hours
        min_relevance: float = 0.3,
    ) -> None:
        self._bus = bus
        self._max_patterns = max(50, max_patterns)
        self._decay_halflife = decay_halflife_s
        self._min_relevance = min_relevance
        self._lock = threading.RLock()

        # pattern_id → PatternEntry
        self._patterns: Dict[str, PatternEntry] = {}

        # domain → set of pattern_ids for that domain
        self._domain_index: Dict[str, Set[str]] = {}

        # keyword → set of pattern_ids containing that keyword
        self._keyword_index: Dict[str, Set[str]] = {}

        # Transfer log: list of (timestamp, source_domain, target_domain, pattern_id, score)
        self._transfer_log: List[Tuple[float, str, str, str, float]] = []

        log.info(
            "TransferLearning initialised (max_patterns=%d, decay_halflife=%.0fs)",
            self._max_patterns, self._decay_halflife,
        )

    # ------------------------------------------------------------------
    # Pattern registration
    # ------------------------------------------------------------------

    def register_pattern(
        self,
        source_domain: str,
        pattern_type: PatternType,
        description: str,
        keywords: List[str],
        success_rate: float = 0.5,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> PatternEntry:
        """
        Register a new transferable pattern. Returns the created entry.

        The pattern_id is a stable hash of (source_domain, description).
        """
        normalised_kw = tuple(sorted(set(k.lower().strip() for k in keywords if k.strip())))
        pid = self._make_id(source_domain, description)
        now = time.time()
        entry = PatternEntry(
            pattern_id=pid,
            source_domain=source_domain,
            pattern_type=pattern_type,
            description=description,
            keywords=normalised_kw,
            success_rate=max(0.0, min(1.0, success_rate)),
            transfer_count=0,
            created_at=now,
            last_used=now,
            metadata=metadata or {},
        )
        with self._lock:
            self._patterns[pid] = entry
            self._domain_index.setdefault(source_domain, set()).add(pid)
            for kw in normalised_kw:
                self._keyword_index.setdefault(kw, set()).add(pid)
            self._prune_if_needed()

        self._bus.publish("transfer.pattern_registered", {
            "pattern_id": pid, "domain": source_domain, "type": pattern_type.value,
        })
        log.debug(
            "[Transfer] Registered pattern %s in domain '%s'", pid[:8], source_domain,
        )
        return entry

    # ------------------------------------------------------------------
    # Pattern lookup
    # ------------------------------------------------------------------

    def get_pattern(self, pattern_id: str) -> Optional[PatternEntry]:
        """Retrieve a pattern by ID."""
        with self._lock:
            return self._patterns.get(pattern_id)

    def list_patterns(self, domain: Optional[str] = None) -> List[PatternEntry]:
        """List patterns, optionally filtered by domain."""
        with self._lock:
            if domain is not None:
                ids = self._domain_index.get(domain, set())
                return [self._patterns[pid] for pid in ids if pid in self._patterns]
            return list(self._patterns.values())

    # ------------------------------------------------------------------
    # Cross-domain matching
    # ------------------------------------------------------------------

    def find_transfers(
        self,
        target_domain: str,
        target_keywords: List[str],
        target_type: Optional[PatternType] = None,
        limit: int = 10,
    ) -> List[TransferCandidate]:
        """
        Find patterns from other domains that are relevant to the target.

        Ranking uses:
        1. Keyword Jaccard overlap
        2. Success rate of source pattern
        3. Pattern type match bonus
        4. Temporal decay
        """
        target_kw_set = set(k.lower().strip() for k in target_keywords if k.strip())
        if not target_kw_set:
            return []

        now = time.time()
        candidates: List[TransferCandidate] = []

        with self._lock:
            for entry in self._patterns.values():
                # Skip patterns from the same domain
                if entry.source_domain == target_domain:
                    continue

                # Keyword Jaccard
                overlap = self._jaccard(set(entry.keywords), target_kw_set)
                if overlap < 0.01:
                    continue

                # Type match bonus
                type_match = target_type is not None and entry.pattern_type == target_type

                # Temporal decay
                age_s = max(0.0, now - entry.last_used)
                decay = math.exp(-0.693 * age_s / self._decay_halflife)

                # Composite relevance
                relevance = (
                    0.4 * overlap
                    + 0.3 * entry.success_rate
                    + 0.1 * (1.0 if type_match else 0.0)
                    + 0.2 * decay
                )

                if relevance < self._min_relevance:
                    continue

                candidates.append(TransferCandidate(
                    pattern=entry,
                    target_domain=target_domain,
                    relevance_score=round(relevance, 4),
                    keyword_overlap=round(overlap, 4),
                    type_match=type_match,
                ))

        # Sort descending by relevance
        candidates.sort(key=lambda c: c.relevance_score, reverse=True)
        return candidates[:limit]

    # ------------------------------------------------------------------
    # Transfer application
    # ------------------------------------------------------------------

    def apply_transfer(
        self,
        pattern_id: str,
        target_domain: str,
        success: bool = True,
    ) -> Optional[PatternEntry]:
        """
        Record that a pattern was applied to a target domain.

        Updates the pattern's transfer_count and last_used timestamp.
        If success=True, bumps success_rate slightly (EMA with α=0.1).
        Returns the updated entry or None if pattern not found.
        """
        with self._lock:
            old = self._patterns.get(pattern_id)
            if old is None:
                return None

            alpha = 0.1
            new_rate = old.success_rate
            if success:
                new_rate = old.success_rate * (1 - alpha) + 1.0 * alpha
            else:
                new_rate = old.success_rate * (1 - alpha) + 0.0 * alpha

            updated = PatternEntry(
                pattern_id=old.pattern_id,
                source_domain=old.source_domain,
                pattern_type=old.pattern_type,
                description=old.description,
                keywords=old.keywords,
                success_rate=round(new_rate, 4),
                transfer_count=old.transfer_count + 1,
                created_at=old.created_at,
                last_used=time.time(),
                metadata=old.metadata,
            )
            self._patterns[pattern_id] = updated

            self._transfer_log.append((
                time.time(), old.source_domain, target_domain, pattern_id,
                updated.success_rate,
            ))
            # Bound the transfer log
            if len(self._transfer_log) > 2000:
                self._transfer_log = self._transfer_log[-1000:]

        self._bus.publish("transfer.pattern_applied", {
            "pattern_id": pattern_id,
            "source_domain": old.source_domain,
            "target_domain": target_domain,
            "success": success,
        })
        return updated

    # ------------------------------------------------------------------
    # Domain profiles
    # ------------------------------------------------------------------

    def domain_profile(self, domain: str) -> DomainProfile:
        """Build a summary profile for a domain's pattern knowledge."""
        with self._lock:
            ids = self._domain_index.get(domain, set())
            patterns = [self._patterns[pid] for pid in ids if pid in self._patterns]

            if not patterns:
                return DomainProfile(
                    domain=domain, pattern_count=0, avg_success_rate=0.0,
                    total_transfers_in=0, total_transfers_out=0,
                    top_keywords=(), coverage_score=0.0,
                )

            avg_rate = statistics.mean(p.success_rate for p in patterns)

            # Count transfers in/out
            transfers_out = sum(p.transfer_count for p in patterns)
            transfers_in = sum(
                1 for _, _, tgt, _, _ in self._transfer_log
                if tgt == domain
            )

            # Top keywords by frequency
            kw_counts: Dict[str, int] = {}
            for p in patterns:
                for kw in p.keywords:
                    kw_counts[kw] = kw_counts.get(kw, 0) + 1
            top_kw = tuple(
                k for k, _ in sorted(
                    kw_counts.items(), key=lambda x: x[1], reverse=True,
                )[:10]
            )

            # Coverage = fraction of patterns with success > 0.5
            high_success = sum(1 for p in patterns if p.success_rate > 0.5)
            coverage = high_success / len(patterns) if patterns else 0.0

            return DomainProfile(
                domain=domain,
                pattern_count=len(patterns),
                avg_success_rate=round(avg_rate, 4),
                total_transfers_in=transfers_in,
                total_transfers_out=transfers_out,
                top_keywords=top_kw,
                coverage_score=round(coverage, 4),
            )

    def list_domains(self) -> List[str]:
        """Return all domains that have registered patterns."""
        with self._lock:
            return sorted(self._domain_index.keys())

    # ------------------------------------------------------------------
    # Export / import (portable serialisation)
    # ------------------------------------------------------------------

    def export_state(self) -> Dict[str, Any]:
        """Export all patterns and transfer log as a serialisable dict."""
        with self._lock:
            patterns = [
                {
                    "pattern_id": p.pattern_id,
                    "source_domain": p.source_domain,
                    "pattern_type": p.pattern_type.value,
                    "description": p.description,
                    "keywords": list(p.keywords),
                    "success_rate": p.success_rate,
                    "transfer_count": p.transfer_count,
                    "created_at": p.created_at,
                    "last_used": p.last_used,
                }
                for p in self._patterns.values()
            ]
            transfers = [
                {"ts": ts, "source": s, "target": t, "pid": pid, "rate": r}
                for ts, s, t, pid, r in self._transfer_log[-200:]
            ]
            return {"patterns": patterns, "transfers": transfers}

    def import_state(self, state: Dict[str, Any]) -> int:
        """Import from an export_state() dict. Returns count of patterns loaded."""
        count = 0
        with self._lock:
            for p in state.get("patterns", []):
                try:
                    entry = PatternEntry(
                        pattern_id=p["pattern_id"],
                        source_domain=p["source_domain"],
                        pattern_type=PatternType(p["pattern_type"]),
                        description=p["description"],
                        keywords=tuple(p.get("keywords", [])),
                        success_rate=p.get("success_rate", 0.5),
                        transfer_count=p.get("transfer_count", 0),
                        created_at=p.get("created_at", time.time()),
                        last_used=p.get("last_used", time.time()),
                    )
                    self._patterns[entry.pattern_id] = entry
                    self._domain_index.setdefault(entry.source_domain, set()).add(entry.pattern_id)
                    for kw in entry.keywords:
                        self._keyword_index.setdefault(kw, set()).add(entry.pattern_id)
                    count += 1
                except (KeyError, ValueError) as exc:
                    log.warning("Skipped invalid pattern during import: %s", exc)
        return count

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _jaccard(a: set, b: set) -> float:
        """Jaccard similarity coefficient."""
        if not a and not b:
            return 0.0
        inter = len(a & b)
        union = len(a | b)
        return inter / union if union else 0.0

    @staticmethod
    def _make_id(domain: str, description: str) -> str:
        """Deterministic pattern ID from domain + description."""
        raw = f"{domain}::{description}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def _prune_if_needed(self) -> None:
        """Remove oldest patterns if over capacity (caller holds _lock)."""
        if len(self._patterns) <= self._max_patterns:
            return
        # Sort by last_used ascending, remove oldest
        by_age = sorted(self._patterns.values(), key=lambda p: p.last_used)
        to_remove = len(self._patterns) - self._max_patterns
        for entry in by_age[:to_remove]:
            del self._patterns[entry.pattern_id]
            domain_set = self._domain_index.get(entry.source_domain)
            if domain_set:
                domain_set.discard(entry.pattern_id)
            for kw in entry.keywords:
                kw_set = self._keyword_index.get(kw)
                if kw_set:
                    kw_set.discard(entry.pattern_id)
        log.debug("[Transfer] Pruned %d patterns", to_remove)
