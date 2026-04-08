from __future__ import annotations

from core._bus_fallback import EventBus
from core.deliberation_engine import DeliberationEngine
from core.transfer_learning import PatternType, TransferLearning


def test_ood_composite_cross_domain_reasoning_regression() -> None:
    """OOD composite scenario should preserve coupling across domains."""
    bus = EventBus()
    engine = DeliberationEngine(bus=bus)
    transfer = TransferLearning(bus=bus)

    transfer.register_pattern(
        source_domain="clinical",
        pattern_type=PatternType.STRATEGY,
        description="triage anomalies quickly before broad intervention",
        keywords=["triage", "anomaly", "mitigation", "risk", "signal"],
        success_rate=0.88,
    )
    transfer.register_pattern(
        source_domain="finance",
        pattern_type=PatternType.HEURISTIC,
        description="contain drawdown using risk-based throttling",
        keywords=["risk", "containment", "signal", "degradation", "threshold"],
        success_rate=0.81,
    )
    transfer.register_pattern(
        source_domain="infrastructure",
        pattern_type=PatternType.TEMPLATE,
        description="monitor latency and bottleneck metrics for recovery",
        keywords=["monitoring", "latency", "bottleneck", "metrics", "recovery"],
        success_rate=0.9,
    )

    candidates = transfer.find_transfers(
        target_domain="autonomy",
        target_keywords=["triage", "anomaly", "monitoring", "risk", "recovery"],
        limit=5,
    )
    assert len(candidates) >= 2

    perspectives = [
        {
            "perspective": "clinical-ops",
            "model": "sim-a",
            "content": "triage anomaly from telemetry signal and prioritize mitigation",
        },
        {
            "perspective": "quant-risk",
            "model": "sim-b",
            "content": "contain degradation risk using thresholded monitoring signals",
        },
        {
            "perspective": "sre",
            "model": "sim-c",
            "content": "diagnosis of incident via metrics to reduce latency bottleneck and recover",
        },
    ]
    deliberation = engine.deliberate("OOD composite incident", perspectives)

    assert len(deliberation["hypotheses"]) == 3
    assert len(deliberation["contradictions"]) == 0
    assert deliberation["graph_summary"]["graph_density"] > 0.0
    assert deliberation["consensus"]["winning_hypothesis"] is not None
