from __future__ import annotations

import logging
import math
import threading
from typing import Any

from core._bus_fallback import EventBus
from core._database_fallback import DatabaseManager
from core.memory.episodic import EpisodicMemory

log = logging.getLogger(__name__)


class MetacognitionEngine:
    """Self-monitoring engine with Expected Calibration Error (ECE) diagnostics."""

    def __init__(
        self,
        db: DatabaseManager,
        bus: EventBus,
        n_bins: int = 10,
    ) -> None:
        self._db = db
        self._bus = bus
        self._n_bins = n_bins
        self._episodic = EpisodicMemory(db=db, bus=bus)
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Core ECE computation
    # ------------------------------------------------------------------

    def compute_ece(
        self,
        domain: str | None = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        """Compute Expected Calibration Error over episodic memory.

        ECE = Σ (|B_m| / n) × |acc(B_m) - conf(B_m)|
        where B_m is the set of episodes in bin m, n is total episodes.
        """
        with self._lock:
            return self._compute_ece_for_episodes(
                self._fetch_episodes(domain=domain, limit=limit),
            )

    def _fetch_episodes(
        self,
        domain: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        return self._episodic.list_episodes(domain=domain, limit=limit)

    def _compute_ece_for_episodes(
        self,
        episodes: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Run the binned ECE calculation over a list of episode dicts."""
        n_bins = self._n_bins

        # Extract (predicted_confidence, actual_outcome) pairs
        pairs: list[tuple[float, float]] = []
        for ep in episodes:
            conf = ep.get("confidence_final")
            outcome = ep.get("outcome")
            if conf is None or outcome is None:
                continue
            conf = float(conf)
            conf = max(0.0, min(1.0, conf))
            actual = 1.0 if outcome == "success" else 0.0
            pairs.append((conf, actual))

        total = len(pairs)
        if total == 0:
            return self._empty_ece_result()

        # Build equal-width bins over [0, 1]
        bin_width = 1.0 / n_bins
        bins_data: list[dict[str, Any]] = []
        ece = 0.0
        mce = 0.0

        for i in range(n_bins):
            bin_start = i * bin_width
            bin_end = (i + 1) * bin_width

            # Collect episodes falling into this bin
            bin_confs: list[float] = []
            bin_actuals: list[float] = []
            for conf, actual in pairs:
                # Last bin is inclusive on the right: [bin_start, bin_end]
                if i == n_bins - 1:
                    in_bin = bin_start <= conf <= bin_end
                else:
                    in_bin = bin_start <= conf < bin_end
                if in_bin:
                    bin_confs.append(conf)
                    bin_actuals.append(actual)

            count = len(bin_confs)
            if count == 0:
                bins_data.append(
                    {
                        "bin_start": round(bin_start, 4),
                        "bin_end": round(bin_end, 4),
                        "avg_confidence": 0.0,
                        "avg_accuracy": 0.0,
                        "count": 0,
                        "gap": 0.0,
                    }
                )
                continue

            avg_conf = sum(bin_confs) / count
            avg_acc = sum(bin_actuals) / count
            gap = abs(avg_acc - avg_conf)

            # ECE contribution: (|B_m| / n) * |acc(B_m) - conf(B_m)|
            ece += (count / total) * gap
            mce = max(mce, gap)

            bins_data.append(
                {
                    "bin_start": round(bin_start, 4),
                    "bin_end": round(bin_end, 4),
                    "avg_confidence": round(avg_conf, 6),
                    "avg_accuracy": round(avg_acc, 6),
                    "count": count,
                    "gap": round(gap, 6),
                }
            )

        ece = round(ece, 6)
        mce = round(mce, 6)

        if ece < 0.05:
            quality = "excellent"
        elif ece < 0.1:
            quality = "good"
        elif ece < 0.2:
            quality = "fair"
        else:
            quality = "poor"

        return {
            "ece": ece,
            "mce": mce,
            "n_bins": n_bins,
            "total_episodes": total,
            "bins": bins_data,
            "calibration_quality": quality,
        }

    def _empty_ece_result(self) -> dict[str, Any]:
        return {
            "ece": 0.0,
            "mce": 0.0,
            "n_bins": self._n_bins,
            "total_episodes": 0,
            "bins": [],
            "calibration_quality": "excellent",
        }

    # ------------------------------------------------------------------
    # Overconfidence / underconfidence
    # ------------------------------------------------------------------

    def compute_overconfidence_ratio(
        self,
        domain: str | None = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        """Count episodes where confidence and outcome diverge."""
        with self._lock:
            episodes = self._fetch_episodes(domain=domain, limit=limit)

        overconfident = 0
        underconfident = 0
        total = 0

        for ep in episodes:
            conf = ep.get("confidence_final")
            outcome = ep.get("outcome")
            if conf is None or outcome is None:
                continue
            conf = float(conf)
            total += 1
            if conf > 0.7 and outcome == "failure":
                overconfident += 1
            if conf < 0.3 and outcome == "success":
                underconfident += 1

        return {
            "overconfident_count": overconfident,
            "underconfident_count": underconfident,
            "total": total,
            "overconfidence_ratio": round(overconfident / total, 6) if total else 0.0,
            "underconfidence_ratio": round(underconfident / total, 6) if total else 0.0,
        }

    # ------------------------------------------------------------------
    # Per-domain calibration
    # ------------------------------------------------------------------

    def compute_domain_calibration(
        self,
        limit: int = 500,
    ) -> dict[str, dict[str, Any]]:
        """Compute ECE per domain."""
        with self._lock:
            episodes = self._fetch_episodes(limit=limit)

        by_domain: dict[str, list[dict[str, Any]]] = {}
        for ep in episodes:
            d = ep.get("domain", "general")
            by_domain.setdefault(d, []).append(ep)

        results: dict[str, dict[str, Any]] = {}
        for domain_name, domain_eps in by_domain.items():
            results[domain_name] = self._compute_ece_for_episodes(domain_eps)
        return results

    # ------------------------------------------------------------------
    # Drift detection
    # ------------------------------------------------------------------

    def detect_drift(
        self,
        window_size: int = 50,
        domain: str | None = None,
    ) -> dict[str, Any]:
        """Compare recent vs historical ECE to detect calibration drift."""
        with self._lock:
            # Fetch a generous pool; episodes are ordered by timestamp DESC
            episodes = self._fetch_episodes(domain=domain, limit=5000)

        if len(episodes) <= window_size:
            ece_all = self._compute_ece_for_episodes(episodes)
            return {
                "recent_ece": ece_all["ece"],
                "historical_ece": ece_all["ece"],
                "drift": 0.0,
                "drifting": False,
            }

        recent = episodes[:window_size]
        historical = episodes[window_size:]

        recent_ece = self._compute_ece_for_episodes(recent)["ece"]
        historical_ece = self._compute_ece_for_episodes(historical)["ece"]
        drift = round(recent_ece - historical_ece, 6)

        return {
            "recent_ece": recent_ece,
            "historical_ece": historical_ece,
            "drift": drift,
            "drifting": abs(drift) > 0.05,
        }

    # ------------------------------------------------------------------
    # Confidence histogram
    # ------------------------------------------------------------------

    def confidence_histogram(
        self,
        domain: str | None = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        """Histogram of confidence_final values across episodes."""
        with self._lock:
            episodes = self._fetch_episodes(domain=domain, limit=limit)

        confs: list[float] = []
        for ep in episodes:
            c = ep.get("confidence_final")
            if c is not None:
                confs.append(float(c))

        if not confs:
            return {"bins": [], "mean_confidence": 0.0, "std_confidence": 0.0}

        n_bins = 10
        bin_width = 1.0 / n_bins
        counts = [0] * n_bins

        for c in confs:
            idx = int(c / bin_width)
            if idx >= n_bins:
                idx = n_bins - 1
            counts[idx] += 1

        bins_out: list[dict[str, Any]] = []
        for i in range(n_bins):
            lo = round(i * bin_width, 2)
            hi = round((i + 1) * bin_width, 2)
            bins_out.append({"range": f"{lo:.2f}-{hi:.2f}", "count": counts[i]})

        mean_c = sum(confs) / len(confs)
        variance = sum((c - mean_c) ** 2 for c in confs) / len(confs)
        std_c = math.sqrt(variance)

        return {
            "bins": bins_out,
            "mean_confidence": round(mean_c, 6),
            "std_confidence": round(std_c, 6),
        }

    # ------------------------------------------------------------------
    # Full report
    # ------------------------------------------------------------------

    def metacognition_report(
        self,
        domain: str | None = None,
    ) -> dict[str, Any]:
        """Generate a comprehensive metacognition diagnostic report."""
        ece = self.compute_ece(domain=domain)
        overconf = self.compute_overconfidence_ratio(domain=domain)
        drift = self.detect_drift(domain=domain)
        histogram = self.confidence_histogram(domain=domain)

        report = {
            "calibration": ece,
            "overconfidence": overconf,
            "drift": drift,
            "histogram": histogram,
        }

        try:
            self._bus.publish(
                "metacognition.report.generated",
                {
                    "ece": ece["ece"],
                    "mce": ece["mce"],
                    "quality": ece["calibration_quality"],
                    "total_episodes": ece["total_episodes"],
                    "drifting": drift["drifting"],
                },
            )
        except Exception as exc:
            log.warning("Failed to publish metacognition report event: %s", exc)

        return report

    # ------------------------------------------------------------------
    # Quick summary
    # ------------------------------------------------------------------

    def summary(self) -> dict[str, Any]:
        """Return a lightweight snapshot of current calibration health."""
        ece = self.compute_ece()
        overconf = self.compute_overconfidence_ratio()
        return {
            "ece": ece["ece"],
            "mce": ece["mce"],
            "calibration_quality": ece["calibration_quality"],
            "total_episodes": ece["total_episodes"],
            "overconfident_count": overconf["overconfident_count"],
            "underconfident_count": overconf["underconfident_count"],
            "overconfidence_ratio": overconf["overconfidence_ratio"],
        }
