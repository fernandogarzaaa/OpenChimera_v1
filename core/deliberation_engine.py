"""Higher-level deliberation engine wrapping DeliberationGraph.

Provides multi-perspective deliberation with contradiction detection,
consensus building, and integration with AscensionService output.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from core._bus_fallback import EventBus
from core.deliberation import Contradiction, DeliberationGraph, Hypothesis

logger = logging.getLogger(__name__)

_DOMAIN_KEYWORD_GROUPS: tuple[set[str], ...] = (
    {"monitoring", "telemetry", "signal", "signals", "metric", "metrics"},
    {"risk", "failure", "incident", "anomaly", "degrade", "degradation"},
    {"latency", "throughput", "capacity", "bottleneck", "hotspot"},
    {"diagnosis", "triage", "mitigation", "containment", "recovery"},
    {"tradeoff", "trade-offs", "constraint", "constraints", "optimize", "optimization"},
)
_TOKEN_RE = re.compile(r"[a-z0-9-]+")


class DeliberationEngine:
    """Orchestrates multi-perspective deliberation over a graph structure.

    Accepts perspective outputs (e.g. from AscensionService), maps them to
    hypotheses, detects contradictions and support relationships via word-level
    Jaccard similarity, then computes max-flow consensus.
    """

    def __init__(self, bus: EventBus | None = None) -> None:
        self._bus = bus
        self._graph = DeliberationGraph(bus=bus)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def deliberate(self, prompt: str, perspectives: list[dict]) -> dict:
        """Run a full deliberation cycle over a set of perspectives.

        Parameters
        ----------
        prompt:
            The original prompt that was deliberated on.
        perspectives:
            List of perspective dicts, each containing at least
            ``perspective``, ``content``, and ``model`` keys.

        Returns
        -------
        dict with keys: consensus, hypotheses, contradictions, graph_summary.
        """
        self._graph.clear()

        hyp_ids: list[str] = []
        hyp_meta: list[dict[str, Any]] = []

        # --- Phase 1: add hypotheses ---
        for p in perspectives:
            content: str = p.get("content", "")
            perspective_name: str = p.get("perspective", "unknown")
            claim = content[:500]
            confidence = min(1.0, len(content) / 500) if content else 0.0

            hyp = self._graph.add_hypothesis(
                claim=claim,
                perspective=perspective_name,
                confidence=confidence,
                evidence=[{"prompt": prompt, "model": p.get("model", "unknown")}],
            )
            hyp_ids.append(hyp.id)
            hyp_meta.append({"id": hyp.id, "perspective": perspective_name, "content": content})
            logger.debug(
                "Added hypothesis %s from perspective '%s' (confidence=%.2f)",
                hyp.id,
                perspective_name,
                confidence,
            )

        # --- Phase 2: cross-check pairs ---
        for i in range(len(hyp_meta)):
            for j in range(i + 1, len(hyp_meta)):
                if hyp_meta[i]["perspective"] == hyp_meta[j]["perspective"]:
                    continue

                jaccard = _jaccard_similarity(hyp_meta[i]["content"], hyp_meta[j]["content"])
                coupling = _cross_domain_coupling_score(
                    hyp_meta[i]["content"],
                    hyp_meta[j]["content"],
                    hyp_meta[i]["perspective"],
                    hyp_meta[j]["perspective"],
                )
                effective_similarity = max(jaccard, coupling)

                if effective_similarity < 0.15:
                    severity = 1.0 - effective_similarity
                    self._graph.add_contradiction(
                        hyp_meta[i]["id"],
                        hyp_meta[j]["id"],
                        reason=f"Low overlap (jaccard={jaccard:.3f}, coupling={coupling:.3f}) between "
                        f"'{hyp_meta[i]['perspective']}' and '{hyp_meta[j]['perspective']}'",
                        severity=severity,
                    )
                elif jaccard > 0.5 or coupling >= 0.35:
                    support_weight = max(jaccard, min(0.8, coupling + 0.2))
                    self._graph.add_support(hyp_meta[i]["id"], hyp_meta[j]["id"], weight=support_weight)
                    self._graph.add_support(hyp_meta[j]["id"], hyp_meta[i]["id"], weight=support_weight)

        # --- Phase 3: consensus ---
        consensus_result = self._graph.max_flow_consensus()
        ranked = self._graph.ranked_hypotheses()
        contradictions = self._graph.detect_contradictions()
        graph_summary = self._graph.summary()

        logger.info(
            "Deliberation complete for prompt '%.60s…': %d hypotheses, %d contradictions",
            prompt,
            len(ranked),
            len(contradictions),
        )

        return {
            "consensus": consensus_result,
            "hypotheses": ranked,
            "contradictions": contradictions,
            "graph_summary": graph_summary,
        }

    def resolve_contradictions(
        self, contradictions: list[Contradiction] | None = None,
    ) -> list[dict]:
        """Resolve contradictions by preferring the higher-confidence hypothesis.

        Parameters
        ----------
        contradictions:
            List of :class:`Contradiction` objects to resolve.

        Returns
        -------
        List of resolution dicts, each containing the original contradiction,
        the resolution strategy name, and the winning hypothesis.
        """
        if contradictions is None:
            contradictions = self._graph.all_contradictions()

        resolutions: list[dict] = []
        for c in contradictions:
            hyp_a = self._graph.get_hypothesis(c.hypothesis_a)
            hyp_b = self._graph.get_hypothesis(c.hypothesis_b)

            if hyp_a is None or hyp_b is None:
                logger.warning(
                    "Skipping contradiction %s: missing hypothesis (a=%s, b=%s)",
                    getattr(c, "id", "?"),
                    c.hypothesis_a,
                    c.hypothesis_b,
                )
                continue

            winner = hyp_a if hyp_a.confidence >= hyp_b.confidence else hyp_b
            resolutions.append({
                "contradiction": c,
                "resolution": "prefer_higher_confidence",
                "winner": winner,
            })

        logger.debug("Resolved %d / %d contradictions", len(resolutions), len(contradictions))
        return resolutions

    def get_graph(self) -> DeliberationGraph:
        """Expose the internal deliberation graph."""
        return self._graph

    def clear(self) -> None:
        """Clear all graph state."""
        self._graph.clear()

    def summary(self) -> dict:
        """Return a summary of the current graph state."""
        return self._graph.summary()


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def _jaccard_similarity(text_a: str, text_b: str) -> float:
    """Compute word-level Jaccard similarity between two texts.

    Returns a float in [0.0, 1.0].  Returns 0.0 when both texts are empty.
    """
    words_a = _tokenize_text(text_a)
    words_b = _tokenize_text(text_b)
    if not words_a and not words_b:
        return 1.0
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union)


def _cross_domain_coupling_score(
    text_a: str,
    text_b: str,
    perspective_a: str,
    perspective_b: str,
) -> float:
    """Estimate conceptual coupling when lexical overlap is low.

    This intentionally stays lightweight and deterministic: it uses
    pre-defined conceptual keyword groups and perspective token overlap.
    Returns a score in [0.0, 1.0].
    """
    words_a = _tokenize_text(text_a)
    words_b = _tokenize_text(text_b)
    if not words_a or not words_b:
        return 0.0

    shared_groups = 0
    for group in _DOMAIN_KEYWORD_GROUPS:
        if words_a.intersection(group) and words_b.intersection(group):
            shared_groups += 1

    perspective_tokens_a = set(perspective_a.lower().replace("-", " ").split())
    perspective_tokens_b = set(perspective_b.lower().replace("-", " ").split())
    perspective_overlap = len(perspective_tokens_a & perspective_tokens_b) / max(
        1, len(perspective_tokens_a | perspective_tokens_b)
    )

    # Blend conceptual-group matches with weak perspective similarity.
    group_score = min(1.0, shared_groups / max(1, len(_DOMAIN_KEYWORD_GROUPS) // 2))
    return min(1.0, (0.85 * group_score) + (0.15 * perspective_overlap))


def _tokenize_text(text: str) -> set[str]:
    """Tokenize text conservatively for stable similarity comparisons."""
    tokens: set[str] = set()
    for raw in _TOKEN_RE.findall(text.lower()):
        token = raw.strip("-")
        if not token:
            continue
        # Lightweight normalization to reduce brittle lexical mismatches.
        if len(token) > 4 and token.endswith("ing"):
            token = token[:-3]
        elif len(token) > 3 and token.endswith("ed"):
            token = token[:-2]
            if token.endswith("at"):
                token = f"{token}e"
        elif len(token) > 4 and token.endswith("ly"):
            token = token[:-2]
        elif len(token) > 3 and token.endswith("s"):
            token = token[:-1]
        tokens.add(token)
    return tokens


def enhance_ascension_deliberation(
    ascension_result: dict,
    engine: DeliberationEngine,
) -> dict:
    """Post-process an AscensionService.deliberate() result through the engine.

    This does **not** modify the AscensionService API — it is a standalone
    post-processing step that enriches an existing result dict.

    Parameters
    ----------
    ascension_result:
        The dict returned by ``AscensionService.deliberate()``.
    engine:
        A :class:`DeliberationEngine` instance to run the analysis on.

    Returns
    -------
    A **new** dict containing all original keys plus:
    - ``deliberation``: output of ``engine.deliberate()``
    - ``resolution``: output of ``engine.resolve_contradictions()``
    """
    prompt: str = ascension_result.get("prompt", "")
    perspectives: list[dict] = ascension_result.get("perspectives", [])

    delib = engine.deliberate(prompt, perspectives)

    resolution = engine.resolve_contradictions(delib.get("contradictions", []))

    return {
        **ascension_result,
        "deliberation": delib,
        "resolution": resolution,
    }
