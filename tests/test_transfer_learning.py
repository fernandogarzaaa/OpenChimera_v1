"""Tests for core.transfer_learning — cross-domain pattern reuse engine."""
from __future__ import annotations

import time

import pytest

from core._bus_fallback import EventBus
from core.transfer_learning import (
    DomainProfile,
    PatternEntry,
    PatternType,
    TransferCandidate,
    TransferLearning,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def bus():
    return EventBus()


@pytest.fixture
def tl(bus):
    return TransferLearning(bus=bus, max_patterns=100, decay_halflife_s=86400.0)


# ---------------------------------------------------------------------------
# Pattern registration
# ---------------------------------------------------------------------------

class TestPatternRegistration:
    def test_register_and_retrieve(self, tl: TransferLearning):
        entry = tl.register_pattern(
            source_domain="math",
            pattern_type=PatternType.STRATEGY,
            description="Break problem into sub-problems",
            keywords=["decomposition", "divide", "conquer"],
            success_rate=0.9,
        )
        assert entry.source_domain == "math"
        assert entry.success_rate == 0.9
        assert "decomposition" in entry.keywords

        retrieved = tl.get_pattern(entry.pattern_id)
        assert retrieved is not None
        assert retrieved.pattern_id == entry.pattern_id

    def test_register_clamps_success_rate(self, tl: TransferLearning):
        entry = tl.register_pattern("d", PatternType.HEURISTIC, "desc", ["kw"], success_rate=2.0)
        assert entry.success_rate == 1.0

    def test_register_normalises_keywords(self, tl: TransferLearning):
        entry = tl.register_pattern("d", PatternType.TEMPLATE, "desc", ["Foo", "  bar ", "FOO"])
        assert entry.keywords == ("bar", "foo")  # deduped, sorted, lowercased

    def test_get_missing_returns_none(self, tl: TransferLearning):
        assert tl.get_pattern("nonexistent") is None


# ---------------------------------------------------------------------------
# Pattern listing
# ---------------------------------------------------------------------------

class TestPatternListing:
    def test_list_all(self, tl: TransferLearning):
        tl.register_pattern("math", PatternType.STRATEGY, "desc1", ["kw1"])
        tl.register_pattern("physics", PatternType.HEURISTIC, "desc2", ["kw2"])
        patterns = tl.list_patterns()
        assert len(patterns) == 2

    def test_list_by_domain(self, tl: TransferLearning):
        tl.register_pattern("math", PatternType.STRATEGY, "desc1", ["kw1"])
        tl.register_pattern("physics", PatternType.HEURISTIC, "desc2", ["kw2"])
        math_patterns = tl.list_patterns(domain="math")
        assert len(math_patterns) == 1
        assert math_patterns[0].source_domain == "math"

    def test_list_empty_domain(self, tl: TransferLearning):
        assert tl.list_patterns(domain="nonexistent") == []


# ---------------------------------------------------------------------------
# Cross-domain matching
# ---------------------------------------------------------------------------

class TestCrossDomainMatching:
    def test_find_transfers_basic(self, tl: TransferLearning):
        tl.register_pattern("math", PatternType.STRATEGY, "decomposition", ["decompose", "split"], success_rate=0.8)
        tl.register_pattern("math", PatternType.HEURISTIC, "estimate first", ["estimate", "bound"], success_rate=0.7)

        candidates = tl.find_transfers(
            target_domain="engineering",
            target_keywords=["decompose", "modular"],
        )
        assert len(candidates) >= 1
        # The "decomposition" pattern should match
        assert any(c.pattern.description == "decomposition" for c in candidates)

    def test_same_domain_excluded(self, tl: TransferLearning):
        tl.register_pattern("math", PatternType.STRATEGY, "internal", ["kw"])
        candidates = tl.find_transfers("math", ["kw"])
        assert len(candidates) == 0

    def test_no_overlap_returns_empty(self, tl: TransferLearning):
        tl.register_pattern("math", PatternType.STRATEGY, "desc", ["alpha", "beta"])
        candidates = tl.find_transfers("engineering", ["gamma", "delta"])
        assert len(candidates) == 0

    def test_type_match_bonus(self, tl: TransferLearning):
        tl.register_pattern("math", PatternType.STRATEGY, "strat", ["plan", "execute"], success_rate=0.6)
        tl.register_pattern("physics", PatternType.HEURISTIC, "heur", ["plan", "check"], success_rate=0.6)

        strat_candidates = tl.find_transfers(
            "engineering", ["plan"], target_type=PatternType.STRATEGY,
        )
        # Strategy pattern should rank higher with type match
        if len(strat_candidates) >= 2:
            assert strat_candidates[0].type_match is True

    def test_limit_respected(self, tl: TransferLearning):
        for i in range(10):
            tl.register_pattern(f"domain{i}", PatternType.STRATEGY, f"desc{i}", ["shared"], success_rate=0.7)
        candidates = tl.find_transfers("target", ["shared"], limit=3)
        assert len(candidates) <= 3


# ---------------------------------------------------------------------------
# Transfer application
# ---------------------------------------------------------------------------

class TestTransferApplication:
    def test_apply_success(self, tl: TransferLearning):
        entry = tl.register_pattern("math", PatternType.STRATEGY, "desc", ["kw"], success_rate=0.5)
        updated = tl.apply_transfer(entry.pattern_id, "physics", success=True)
        assert updated is not None
        assert updated.transfer_count == 1
        assert updated.success_rate > 0.5  # EMA towards 1.0

    def test_apply_failure(self, tl: TransferLearning):
        entry = tl.register_pattern("math", PatternType.STRATEGY, "desc", ["kw"], success_rate=0.5)
        updated = tl.apply_transfer(entry.pattern_id, "physics", success=False)
        assert updated is not None
        assert updated.transfer_count == 1
        assert updated.success_rate < 0.5  # EMA towards 0.0

    def test_apply_missing_returns_none(self, tl: TransferLearning):
        assert tl.apply_transfer("nonexistent", "domain") is None

    def test_multiple_transfers(self, tl: TransferLearning):
        entry = tl.register_pattern("math", PatternType.STRATEGY, "desc", ["kw"], success_rate=0.5)
        for _ in range(5):
            tl.apply_transfer(entry.pattern_id, "physics", success=True)
        updated = tl.get_pattern(entry.pattern_id)
        assert updated is not None
        assert updated.transfer_count == 5
        assert updated.success_rate > 0.65  # EMA α=0.1 from 0.5 after 5 successes ≈ 0.70


# ---------------------------------------------------------------------------
# Domain profiles
# ---------------------------------------------------------------------------

class TestDomainProfile:
    def test_basic_profile(self, tl: TransferLearning):
        tl.register_pattern("math", PatternType.STRATEGY, "desc1", ["algebra", "calc"], success_rate=0.8)
        tl.register_pattern("math", PatternType.HEURISTIC, "desc2", ["estimate"], success_rate=0.6)

        profile = tl.domain_profile("math")
        assert profile.domain == "math"
        assert profile.pattern_count == 2
        assert 0.5 < profile.avg_success_rate < 1.0
        assert "algebra" in profile.top_keywords or "calc" in profile.top_keywords

    def test_empty_domain_profile(self, tl: TransferLearning):
        profile = tl.domain_profile("nonexistent")
        assert profile.pattern_count == 0
        assert profile.avg_success_rate == 0.0

    def test_list_domains(self, tl: TransferLearning):
        tl.register_pattern("math", PatternType.STRATEGY, "desc1", ["kw"])
        tl.register_pattern("physics", PatternType.HEURISTIC, "desc2", ["kw"])
        domains = tl.list_domains()
        assert "math" in domains
        assert "physics" in domains


# ---------------------------------------------------------------------------
# Pruning
# ---------------------------------------------------------------------------

class TestPruning:
    def test_prune_oldest_when_over_capacity(self, bus: EventBus):
        tl = TransferLearning(bus=bus, max_patterns=50)
        ids = []
        for i in range(55):
            entry = tl.register_pattern(f"d{i}", PatternType.STRATEGY, f"desc{i}", [f"kw{i}"])
            ids.append(entry.pattern_id)

        patterns = tl.list_patterns()
        assert len(patterns) <= 50
        # Oldest should have been pruned
        assert tl.get_pattern(ids[0]) is None


# ---------------------------------------------------------------------------
# Export / import
# ---------------------------------------------------------------------------

class TestExportImport:
    def test_round_trip(self, tl: TransferLearning, bus: EventBus):
        tl.register_pattern("math", PatternType.STRATEGY, "decompose", ["kw1", "kw2"], success_rate=0.75)
        tl.register_pattern("physics", PatternType.ANALOGY, "analogy", ["kw3"], success_rate=0.6)

        exported = tl.export_state()
        assert len(exported["patterns"]) == 2

        tl2 = TransferLearning(bus=bus)
        count = tl2.import_state(exported)
        assert count == 2

        patterns = tl2.list_patterns()
        assert len(patterns) == 2

    def test_import_invalid_entries_skipped(self, bus: EventBus):
        tl = TransferLearning(bus=bus)
        count = tl.import_state({
            "patterns": [
                {"pattern_id": "x", "source_domain": "d"},  # missing fields
                {
                    "pattern_id": "y",
                    "source_domain": "d",
                    "pattern_type": "strategy",
                    "description": "ok",
                    "keywords": ["kw"],
                    "success_rate": 0.5,
                    "transfer_count": 0,
                    "created_at": time.time(),
                    "last_used": time.time(),
                },
            ],
            "transfers": [],
        })
        assert count == 1  # only valid entry loaded


# ---------------------------------------------------------------------------
# EventBus integration
# ---------------------------------------------------------------------------

class TestEventBusIntegration:
    def test_registration_event(self, bus: EventBus, tl: TransferLearning):
        events = []
        bus.subscribe("transfer.pattern_registered", lambda e: events.append(e))
        tl.register_pattern("math", PatternType.STRATEGY, "desc", ["kw"])
        assert len(events) == 1
        assert events[0]["domain"] == "math"

    def test_application_event(self, bus: EventBus, tl: TransferLearning):
        events = []
        bus.subscribe("transfer.pattern_applied", lambda e: events.append(e))
        entry = tl.register_pattern("math", PatternType.STRATEGY, "desc", ["kw"])
        tl.apply_transfer(entry.pattern_id, "physics")
        assert len(events) == 1
        assert events[0]["target_domain"] == "physics"


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------

class TestThreadSafety:
    def test_concurrent_registration(self, tl: TransferLearning):
        import threading

        def register(domain, count):
            for i in range(count):
                tl.register_pattern(domain, PatternType.STRATEGY, f"desc{i}", [f"kw{i}"])

        threads = [
            threading.Thread(target=register, args=(f"d{i}", 10))
            for i in range(5)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        total = len(tl.list_patterns())
        assert total == 50


# ---------------------------------------------------------------------------
# Frozen dataclass verifications
# ---------------------------------------------------------------------------

class TestFrozenDataclasses:
    def test_pattern_entry_immutable(self):
        entry = PatternEntry(
            pattern_id="x", source_domain="d", pattern_type=PatternType.STRATEGY,
            description="desc", keywords=("kw",), success_rate=0.5,
            transfer_count=0, created_at=time.time(), last_used=time.time(),
        )
        with pytest.raises(AttributeError):
            entry.success_rate = 0.9  # type: ignore[misc]

    def test_transfer_candidate_immutable(self):
        entry = PatternEntry(
            pattern_id="x", source_domain="d", pattern_type=PatternType.STRATEGY,
            description="desc", keywords=("kw",), success_rate=0.5,
            transfer_count=0, created_at=time.time(), last_used=time.time(),
        )
        candidate = TransferCandidate(
            pattern=entry, target_domain="t", relevance_score=0.7,
            keyword_overlap=0.5, type_match=True,
        )
        with pytest.raises(AttributeError):
            candidate.relevance_score = 0.1  # type: ignore[misc]
