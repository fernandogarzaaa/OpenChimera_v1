from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib import request

from core.bus import EventBus
from core.causal_reasoning import CausalReasoning
from core.config import ROOT, get_legacy_workspace_root, load_runtime_profile
from core.harness_port import HarnessPortAdapter
from core.minimind_service import MiniMindService
from core.transactions import atomic_write_json
from core.transfer_learning import TransferLearning


@dataclass
class ScheduledJob:
    name: str
    description: str
    category: str
    interval_seconds: int
    enabled: bool = True
    last_run_at: float = 0.0
    last_status: str = "never"
    last_result: dict[str, Any] = field(default_factory=dict)


JOB_SPECS: dict[str, dict[str, Any]] = {
    "sync_scouted_models": {
        "default_interval": 900,
        "description": "Merge legacy free-fallback models with autonomy discovery results.",
        "category": "catalog",
    },
    "discover_free_models": {
        "default_interval": 3600,
        "description": "Probe free or no-cost model catalogs and persist a normalized discovery registry.",
        "category": "discovery",
    },
    "learn_fallback_rankings": {
        "default_interval": 1800,
        "description": "Summarize route-memory outcomes into learned fallback rankings and degradation signals.",
        "category": "learning",
    },
    "audit_skill_bridges": {
        "default_interval": 1800,
        "description": "Audit legacy OpenClaw skills against OpenChimera skill coverage.",
        "category": "audit",
    },
    "refresh_harness_dataset": {
        "default_interval": 21600,
        "description": "Refresh the MiniMind harness-backed dataset used for local reasoning workflows.",
        "category": "training",
    },
    "check_degradation_chains": {
        "default_interval": 1800,
        "description": "Detect degraded local/runtime/fallback chains and publish preview-safe remediation signals.",
        "category": "audit",
    },
    "run_self_audit": {
        "default_interval": 3600,
        "description": "Build a consolidated runtime self-audit across providers, subsystems, and integration bridges.",
        "category": "audit",
    },
    "preview_self_repair": {
        "default_interval": 7200,
        "description": "Generate a preview-only repair plan and optional Aegis remediation bridge summary.",
        "category": "repair-preview",
    },
    "dispatch_operator_digest": {
        "default_interval": 14400,
        "description": "Roll up recent alerts, failed jobs, and channel delivery failures into an operator digest and dispatch it.",
        "category": "reporting",
    },
}


class AutonomyScheduler:
    def __init__(
        self,
        bus: EventBus,
        harness_port: HarnessPortAdapter,
        minimind: MiniMindService,
        identity_snapshot: dict[str, Any],
    ):
        self.bus = bus
        self.harness_port = harness_port
        self.minimind = minimind
        self.identity_snapshot = identity_snapshot
        self.profile = load_runtime_profile()
        self.legacy_workspace_root = get_legacy_workspace_root()
        self.data_root = ROOT / "data" / "autonomy"
        self.artifact_history_path = self.data_root / "artifact_history.json"
        self.job_state_path = self.data_root / "job_state.json"
        self.jobs = self._build_jobs()
        self._restore_job_state()
        self.runtime_context_providers: dict[str, Any] = {}
        self._thread: threading.Thread | None = None
        self._running = False
        try:
            self._causal = CausalReasoning(bus=self.bus)
            self._transfer = TransferLearning(bus=self.bus)
        except Exception as _exc:
            import logging as _log_mod
            _log_mod.getLogger(__name__).warning("Failed to init causal/transfer subsystems: %s", _exc)
            self._causal = None
            self._transfer = None

    def bind_runtime_context(self, **providers: Any) -> None:
        for name, provider in providers.items():
            if callable(provider):
                self.runtime_context_providers[name] = provider

    def _build_jobs(self) -> dict[str, ScheduledJob]:
        autonomy_config = self.profile.get("autonomy", {})
        job_config = autonomy_config.get("jobs", {})
        jobs: dict[str, ScheduledJob] = {}
        for name, spec in JOB_SPECS.items():
            config = job_config.get(name, {})
            jobs[name] = ScheduledJob(
                name=name,
                description=str(spec.get("description", name)),
                category=str(spec.get("category", "maintenance")),
                interval_seconds=int(config.get("interval_seconds", spec.get("default_interval", 900))),
                enabled=bool(config.get("enabled", True)),
            )
        return jobs

    def should_auto_start(self) -> bool:
        autonomy_config = self.profile.get("autonomy", {})
        return bool(autonomy_config.get("enabled", True) and autonomy_config.get("auto_start", True))

    def start(self) -> dict[str, Any]:
        if self._running:
            return self.status()

        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="OpenChimera-Autonomy")
        self._thread.start()
        self.bus.publish_nowait("system/autonomy", {"status": "online"})
        return self.status()

    def stop(self) -> dict[str, Any]:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        self.bus.publish_nowait("system/autonomy", {"status": "offline"})
        return self.status()

    def _run_loop(self) -> None:
        while self._running:
            now = time.time()
            for job in self.jobs.values():
                if not job.enabled:
                    continue
                if job.last_run_at == 0.0 or (now - job.last_run_at) >= job.interval_seconds:
                    self.run_job(job.name)
            time.sleep(5)

    def run_job(self, job_name: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        job = self.jobs.get(job_name)
        if job is None:
            return {"status": "error", "error": f"Unknown job: {job_name}"}

        handlers = {
            "sync_scouted_models": self._sync_scouted_models,
            "discover_free_models": self._discover_free_models,
            "learn_fallback_rankings": self._learn_fallback_rankings,
            "audit_skill_bridges": self._audit_skill_bridges,
            "refresh_harness_dataset": self._refresh_harness_dataset,
            "check_degradation_chains": self._check_degradation_chains,
            "run_self_audit": self._run_self_audit,
            "preview_self_repair": self._preview_self_repair,
            "dispatch_operator_digest": self._dispatch_operator_digest,
        }
        handler = handlers[job_name]

        try:
            result = handler(payload or {})
            job.last_status = "ok"
            job.last_result = result
        except Exception as exc:
            result = {"status": "error", "error": str(exc)}
            job.last_status = "error"
            job.last_result = result

        job.last_run_at = time.time()
        self._save_job_state()
        self.bus.publish_nowait("system/autonomy/job", {"job": job_name, "result": result})
        return result

    def _sync_scouted_models(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        source_path = self.legacy_workspace_root / "chimera_free_fallbacks.json"
        discovered_path = self.data_root / "discovered_models.json"
        target_path = self.data_root / "scouted_models_registry.json"
        self.data_root.mkdir(parents=True, exist_ok=True)

        legacy_models: list[dict[str, Any]] = []
        discovered_models: list[dict[str, Any]] = []
        if source_path.exists():
            data = json.loads(source_path.read_text(encoding="utf-8"))
            legacy_models = self._normalize_model_catalog(data, source="legacy-openclaw-sync")
        if discovered_path.exists():
            try:
                discovered_payload = json.loads(discovered_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                discovered_payload = {}
            discovered_models = self._normalize_model_catalog(discovered_payload.get("models", []), source="autonomy-discovery")

        merged_models = self._dedupe_models([*legacy_models, *discovered_models])
        payload = {
            "status": "ok" if merged_models else "missing",
            "source": str(source_path),
            "discovered_source": str(discovered_path),
            "target": str(target_path),
            "legacy_model_count": len(legacy_models),
            "discovered_model_count": len(discovered_models),
            "model_count": len(merged_models),
            "synced_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "models": merged_models,
        }
        self._write_artifact("scouted_models_registry", payload, job_name="sync_scouted_models")
        return {
            "status": payload["status"],
            "target": str(target_path),
            "legacy_model_count": len(legacy_models),
            "discovered_model_count": len(discovered_models),
            "model_count": len(merged_models),
        }

    def _discover_free_models(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        target_path = self.data_root / "discovered_models.json"
        self.data_root.mkdir(parents=True, exist_ok=True)

        discovered: list[dict[str, Any]] = []
        source_results: list[dict[str, Any]] = []
        for source in self._discovery_sources():
            if not bool(source.get("enabled", True)):
                continue
            try:
                models = self._probe_discovery_source(source)
                discovered.extend(models)
                source_results.append({"name": str(source.get("name", "unnamed-source")), "status": "ok", "model_count": len(models)})
            except Exception as exc:
                source_results.append({"name": str(source.get("name", "unnamed-source")), "status": "error", "error": str(exc)})

        merged = self._dedupe_models(discovered)
        payload = {
            "status": "ok" if merged or any(item.get("status") == "ok" for item in source_results) else "error",
            "discovered_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "model_count": len(merged),
            "sources": source_results,
            "models": merged,
        }
        self._write_artifact("discovered_models", payload, job_name="discover_free_models")
        return {"status": payload["status"], "target": str(target_path), "model_count": len(merged), "sources": source_results}

    def _audit_skill_bridges(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        legacy_skill_source = self.legacy_workspace_root / "skills"
        openchimera_skills = ROOT / "skills"
        target_path = self.data_root / "skill_audit.json"
        self.data_root.mkdir(parents=True, exist_ok=True)

        legacy_skill_names = sorted(path.name for path in legacy_skill_source.iterdir() if path.is_dir()) if legacy_skill_source.exists() else []
        openchimera_names = sorted(path.name for path in openchimera_skills.iterdir() if path.is_dir()) if openchimera_skills.exists() else []
        openchimera_slug_map = {self._skill_slug(name): name for name in openchimera_names}
        missing = sorted(name for name in legacy_skill_names if self._skill_slug(name) not in openchimera_slug_map)
        payload = {
            "status": "ok",
            "legacy_skill_count": len(legacy_skill_names),
            "openclaw_skill_count": len(legacy_skill_names),
            "openchimera_skill_count": len(openchimera_names),
            "missing_skills": missing,
            "priority_bridges": [
                name for name in missing if name in {"AstrBot", "deer-flow", "khoj", "LlamaFactory", "ragflow", "SWE-agent"}
            ],
        }
        self._write_artifact("skill_audit", payload, job_name="audit_skill_bridges")
        return payload

    def _learn_fallback_rankings(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        route_memory_path = ROOT / "data" / "local_llm_route_memory.json"
        target_path = self.data_root / "learned_fallback_rankings.json"
        self.data_root.mkdir(parents=True, exist_ok=True)

        if not route_memory_path.exists():
            payload = {
                "status": "missing",
                "route_memory_path": str(route_memory_path),
                "target": str(target_path),
                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "query_types": {},
                "degraded_models": [],
            }
            self._write_artifact("learned_fallback_rankings", payload, job_name="learn_fallback_rankings")
            return {
                "status": "missing",
                "target": str(target_path),
                "query_type_count": 0,
                "degraded_model_count": 0,
            }

        try:
            raw = json.loads(route_memory_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            raw = {}

        query_types: dict[str, list[dict[str, Any]]] = {}
        degraded_models: list[dict[str, Any]] = []
        for model_name, query_buckets in raw.items():
            if not isinstance(query_buckets, dict):
                continue
            for query_type, bucket in query_buckets.items():
                if not isinstance(bucket, dict):
                    continue
                entry = self._build_learned_ranking_entry(str(model_name), str(query_type), bucket)
                query_types.setdefault(str(query_type), []).append(entry)
                if bool(entry.get("degraded")):
                    degraded_models.append(
                        {
                            "model": str(model_name),
                            "query_type": str(query_type),
                            "score": entry["score"],
                            "confidence": entry["confidence"],
                            "reasons": entry["reasons"],
                        }
                    )

        for entries in query_types.values():
            entries.sort(key=lambda item: (-float(item.get("score", 0.0)), float(item.get("avg_latency_ms", 0.0)), str(item.get("model") or "")))
            for index, item in enumerate(entries, start=1):
                item["rank"] = index

        payload = {
            "status": "ok",
            "route_memory_path": str(route_memory_path),
            "target": str(target_path),
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "query_types": query_types,
            "degraded_models": degraded_models,
        }
        self._write_artifact("learned_fallback_rankings", payload, job_name="learn_fallback_rankings")
        if self._transfer is not None:
            try:
                from core.transfer_learning import PatternType
                keywords = list(query_types.keys()) + ["fallback", "ranking", "model"]
                avg_success = 0.0
                total_entries = sum(len(entries) for entries in query_types.values())
                if total_entries > 0:
                    success_sum = sum(
                        float(entry.get("success_ratio", 0.0))
                        for entries in query_types.values()
                        for entry in entries
                    )
                    avg_success = success_sum / total_entries
                self._transfer.register_pattern(
                    source_domain="fallback_ranking",
                    pattern_type=PatternType.STRATEGY,
                    description="Learned model fallback ranking strategy",
                    keywords=keywords,
                    success_rate=avg_success,
                    metadata={"query_type_count": len(query_types), "degraded_model_count": len(degraded_models)},
                )
            except Exception as _exc:
                import logging as _log_mod
                _log_mod.getLogger(__name__).warning("Transfer pattern registration failed: %s", _exc)
        return {
            "status": "ok",
            "target": str(target_path),
            "query_type_count": len(query_types),
            "degraded_model_count": len(degraded_models),
        }

    def _build_learned_ranking_entry(self, model_name: str, query_type: str, bucket: dict[str, Any]) -> dict[str, Any]:
        successes = int(bucket.get("successes", 0))
        failures = int(bucket.get("failures", 0))
        low_quality_failures = int(bucket.get("low_quality_failures", 0))
        attempts = successes + failures
        avg_latency_ms = float(bucket.get("avg_latency_ms", 0.0))
        success_ratio = (successes / attempts) if attempts else 0.0
        recency_bonus = self._learning_recency_bonus(
            bucket.get("last_success_at"),
            bucket.get("last_failure_at"),
        )
        latency_penalty = min(avg_latency_ms / 2000.0, 2.0) if avg_latency_ms > 0 else 0.0
        score = (successes * 2.0) + (success_ratio * 3.0) + recency_bonus - (failures * 1.5) - (low_quality_failures * 2.5) - latency_penalty
        confidence = min(attempts / 6.0, 1.0)
        degraded = failures >= max(successes + 1, 2) or low_quality_failures >= 2
        reasons: list[str] = []
        if low_quality_failures >= 2:
            reasons.append("repeated-low-quality")
        if failures >= max(successes + 1, 2):
            reasons.append("failure-rate")
        if avg_latency_ms >= 4000:
            reasons.append("slow-latency")
        if attempts == 0:
            reasons.append("no-signal")
        return {
            "model": model_name,
            "query_type": query_type,
            "attempts": attempts,
            "successes": successes,
            "failures": failures,
            "low_quality_failures": low_quality_failures,
            "success_ratio": round(success_ratio, 4),
            "avg_latency_ms": round(avg_latency_ms, 2),
            "score": round(score, 4),
            "confidence": round(confidence, 4),
            "degraded": degraded,
            "reasons": reasons,
        }

    def _learning_recency_bonus(self, last_success_at: Any, last_failure_at: Any) -> float:
        success_bonus = self._recency_weight(last_success_at, fresh_seconds=6 * 3600, stale_seconds=7 * 24 * 3600)
        failure_penalty = self._recency_weight(last_failure_at, fresh_seconds=6 * 3600, stale_seconds=7 * 24 * 3600)
        return success_bonus - failure_penalty

    def _recency_weight(self, timestamp: Any, *, fresh_seconds: float, stale_seconds: float) -> float:
        if not timestamp:
            return 0.0
        age_seconds = max(time.time() - float(timestamp), 0.0)
        if age_seconds <= fresh_seconds:
            return 1.0
        if age_seconds >= stale_seconds:
            return 0.1
        span = max(stale_seconds - fresh_seconds, 1.0)
        remaining = max(stale_seconds - age_seconds, 0.0)
        return 0.1 + 0.9 * (remaining / span)

    def _skill_slug(self, name: str) -> str:
        return name.strip().lower().replace(" ", "-")

    def _refresh_harness_dataset(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        manifest = self.minimind.build_training_dataset(
            self.harness_port,
            identity_snapshot=self.identity_snapshot,
            force=True,
        )
        result = {
            "status": "ok",
            "training_output_dir": manifest.get("files", {}),
            "counts": manifest.get("counts", {}),
        }
        self._write_artifact("refresh_harness_dataset", result, job_name="refresh_harness_dataset")
        return result

    def _check_degradation_chains(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        context = self._build_runtime_context()
        report = self._build_degradation_report(context)
        self._write_artifact("degradation_chains", report, job_name="check_degradation_chains")
        if self._causal is not None:
            try:
                for chain in report.get("chains", []):
                    chain_id = chain.get("id", "unknown_chain")
                    models = chain.get("models", [])
                    if models:
                        for model in models:
                            self._causal.add_cause(
                                cause=f"model_degradation:{model}",
                                effect=f"fallback_chain_failure:{chain_id}",
                                strength=0.8,
                                confidence=0.7,
                            )
                    else:
                        self._causal.add_cause(
                            cause="model_degradation",
                            effect=f"fallback_chain_failure:{chain_id}",
                            strength=0.8,
                            confidence=0.7,
                        )
            except Exception as _exc:
                import logging as _log_mod
                _log_mod.getLogger(__name__).warning("Causal edge recording failed: %s", _exc)
        return {
            "status": report["status"],
            "target": str(self.data_root / "degradation_chains.json"),
            "chain_count": len(report.get("chains", [])),
            "critical_count": sum(1 for item in report.get("chains", []) if item.get("severity") == "critical"),
        }

    def _run_self_audit(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        context = self._build_runtime_context()
        report = self._build_self_audit_report(context)
        self._write_artifact("self_audit", report, job_name="run_self_audit")
        result: dict[str, Any] = {
            "status": report["status"],
            "target": str(self.data_root / "self_audit.json"),
            "finding_count": len(report.get("findings", [])),
            "recommendation_count": len(report.get("recommendations", [])),
        }
        if self._causal is not None:
            try:
                result["causal_graph"] = self._causal.summary()
            except Exception as _exc:
                import logging as _log_mod
                _log_mod.getLogger(__name__).warning("Causal summary failed: %s", _exc)
        return result

    def _preview_self_repair(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        context = self._build_runtime_context()
        audit_report = self._build_self_audit_report(context)
        degradation_report = self._build_degradation_report(context)
        target_project = str(payload.get("target_project") or ROOT)
        focus_areas = [item.get("id") for item in degradation_report.get("chains", [])[:5] if item.get("id")]
        preview_context = {
            "focus_areas": focus_areas,
            "recommendations": audit_report.get("recommendations", [])[:6],
            "degradation_chains": degradation_report.get("chains", [])[:5],
            "finding_count": len(audit_report.get("findings", [])),
        }
        aegis_preview = self._call_runtime_provider(
            "aegis_preview",
            {
                "status": "missing",
                "target": target_project,
                "error": "Aegis preview bridge unavailable",
            },
            target_project=target_project,
            preview_context=preview_context,
        )
        report = {
            "status": "preview",
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "target_project": target_project,
            "focus_areas": focus_areas,
            "recommendations": audit_report.get("recommendations", [])[:8],
            "self_audit": {
                "status": audit_report.get("status"),
                "finding_count": len(audit_report.get("findings", [])),
                "findings": audit_report.get("findings", [])[:8],
            },
            "degradation_chains": degradation_report.get("chains", [])[:8],
            "aegis_preview": aegis_preview,
        }
        self._write_artifact("preview_self_repair", report, job_name="preview_self_repair")
        return {
            "status": "preview",
            "target": str(self.data_root / "preview_self_repair.json"),
            "focus_area_count": len(focus_areas),
            "recommendation_count": len(report.get("recommendations", [])),
        }

    def _dispatch_operator_digest(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        context = self._build_runtime_context()
        digest_config = self.profile.get("autonomy", {}).get("digests", {})
        history_limit = max(1, int(payload.get("history_limit") or digest_config.get("history_limit", 5) or 5))
        dispatch_topic = str(payload.get("dispatch_topic") or digest_config.get("dispatch_topic", "system/briefing/daily")).strip() or "system/briefing/daily"
        alert_topic = str(self.profile.get("autonomy", {}).get("alerts", {}).get("dispatch_topic", "system/autonomy/alert")).strip() or "system/autonomy/alert"

        briefing = self._call_runtime_provider("daily_briefing", {})
        recent_alerts = self._call_runtime_provider("channel_history", {"history": [], "count": 0}, topic=alert_topic, limit=history_limit)
        failed_deliveries = self._call_runtime_provider("channel_history", {"history": [], "count": 0}, status="error", limit=history_limit)
        failed_jobs = self._call_runtime_provider("job_queue", {"jobs": [], "counts": {}}, status_filter="failed", limit=history_limit)

        failed_job_items = failed_jobs.get("jobs", []) if isinstance(failed_jobs.get("jobs", []), list) else []
        alert_items = recent_alerts.get("history", []) if isinstance(recent_alerts.get("history", []), list) else []
        failed_delivery_items = failed_deliveries.get("history", []) if isinstance(failed_deliveries.get("history", []), list) else []

        report = {
            "status": "ok",
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "dispatch_topic": dispatch_topic,
            "briefing": briefing,
            "recent_alerts": alert_items[:history_limit],
            "failed_jobs": failed_job_items[:history_limit],
            "failed_channel_deliveries": failed_delivery_items[:history_limit],
            "summary": {
                "recent_alert_count": len(alert_items),
                "failed_job_count": len(failed_job_items),
                "failed_channel_delivery_count": len(failed_delivery_items),
            },
        }
        self._write_artifact("operator_digest", report, job_name="dispatch_operator_digest")

        digest_payload = {
            "summary": (
                f"Operator digest: {len(alert_items)} recent alerts, "
                f"{len(failed_job_items)} failed jobs, {len(failed_delivery_items)} failed channel deliveries."
            ),
            "briefing": briefing,
            "recent_alerts": [item.get("payload_preview", {}) for item in alert_items[:history_limit] if isinstance(item, dict)],
            "failed_jobs": [
                {
                    "job_id": item.get("job_id"),
                    "job_type": item.get("job_type"),
                    "job_class": item.get("job_class"),
                    "status": item.get("status"),
                }
                for item in failed_job_items[:history_limit]
                if isinstance(item, dict)
            ],
            "failed_channel_deliveries": [
                {
                    "topic": item.get("topic"),
                    "error_count": item.get("error_count"),
                    "payload_preview": item.get("payload_preview", {}),
                }
                for item in failed_delivery_items[:history_limit]
                if isinstance(item, dict)
            ],
        }
        dispatch_result = self._call_runtime_provider(
            "channel_dispatch",
            {"status": "missing", "error": "Channel dispatch bridge unavailable", "topic": dispatch_topic},
            topic=dispatch_topic,
            payload=digest_payload,
        )
        report["dispatch"] = dispatch_result
        self._write_artifact("operator_digest", report, job_name="dispatch_operator_digest")
        return {
            "status": report["status"],
            "target": str(self.data_root / "operator_digest.json"),
            "dispatch_topic": dispatch_topic,
            "recent_alert_count": len(alert_items),
            "failed_job_count": len(failed_job_items),
            "failed_channel_delivery_count": len(failed_delivery_items),
        }

    def status(self) -> dict[str, Any]:
        return {
            "running": self._running,
            "data_root": str(self.data_root),
            "artifacts": {
                "scouted_models_registry": str(self.data_root / "scouted_models_registry.json"),
                "discovered_models": str(self.data_root / "discovered_models.json"),
                "learned_fallback_rankings": str(self.data_root / "learned_fallback_rankings.json"),
                "skill_audit": str(self.data_root / "skill_audit.json"),
                "refresh_harness_dataset": str(self.data_root / "refresh_harness_dataset.json"),
                "degradation_chains": str(self.data_root / "degradation_chains.json"),
                "self_audit": str(self.data_root / "self_audit.json"),
                "preview_self_repair": str(self.data_root / "preview_self_repair.json"),
                "operator_digest": str(self.data_root / "operator_digest.json"),
                "artifact_history": str(self.artifact_history_path),
                "job_state": str(self.job_state_path),
            },
            "jobs": {
                name: {
                    "description": job.description,
                    "category": job.category,
                    "enabled": job.enabled,
                    "interval_seconds": job.interval_seconds,
                    "last_run_at": job.last_run_at,
                    "last_status": job.last_status,
                    "last_result": job.last_result,
                }
                for name, job in self.jobs.items()
            },
        }

    def _restore_job_state(self) -> None:
        if not self.job_state_path.exists():
            return
        try:
            payload = json.loads(self.job_state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return
        jobs = payload.get("jobs", {}) if isinstance(payload, dict) else {}
        if not isinstance(jobs, dict):
            return
        for name, saved in jobs.items():
            job = self.jobs.get(str(name))
            if job is None or not isinstance(saved, dict):
                continue
            job.last_run_at = float(saved.get("last_run_at", 0.0) or 0.0)
            job.last_status = str(saved.get("last_status", "never") or "never")
            last_result = saved.get("last_result", {})
            job.last_result = last_result if isinstance(last_result, dict) else {}

    def _save_job_state(self) -> None:
        self.job_state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "jobs": {
                name: {
                    "last_run_at": job.last_run_at,
                    "last_status": job.last_status,
                    "last_result": job.last_result,
                }
                for name, job in self.jobs.items()
            }
        }
        atomic_write_json(self.job_state_path, payload)

    def artifact_history(self, artifact_name: str | None = None, limit: int = 20) -> dict[str, Any]:
        entries = self._load_artifact_history()
        if artifact_name:
            entries = [item for item in entries if str(item.get("artifact_name", "")).strip() == artifact_name]
        entries = sorted(entries, key=lambda item: float(item.get("recorded_at", 0.0)), reverse=True)
        limited = entries[: max(1, int(limit))]
        return {
            "status": "ok",
            "artifact_name": artifact_name or "",
            "history": limited,
            "count": len(limited),
            "history_path": str(self.artifact_history_path),
        }

    def read_artifact(self, artifact_name: str) -> dict[str, Any]:
        path = self._artifact_path(artifact_name)
        if path is None:
            return {"status": "error", "error": f"Unknown autonomy artifact: {artifact_name}"}
        if not path.exists():
            return {"status": "missing", "artifact_name": artifact_name, "path": str(path)}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"status": "error", "artifact_name": artifact_name, "path": str(path), "error": "Invalid JSON artifact"}
        if isinstance(payload, dict):
            payload.setdefault("artifact_name", artifact_name)
            payload.setdefault("path", str(path))
            return payload
        return {"status": "ok", "artifact_name": artifact_name, "path": str(path), "payload": payload}

    def _discovery_sources(self) -> list[dict[str, Any]]:
        sources = self.profile.get("model_inventory", {}).get("discovery_sources", [])
        configured = [item for item in sources if isinstance(item, dict)]
        if configured:
            return configured
        return [
            {
                "name": "openrouter-free",
                "provider": "openrouter",
                "url": "https://openrouter.ai/api/v1/models",
                "kind": "remote-openrouter",
                "enabled": True,
            },
            {
                "name": "ollama-local",
                "provider": "ollama",
                "url": "http://127.0.0.1:11434/api/tags",
                "kind": "local-ollama",
                "enabled": True,
            },
        ]

    def _probe_discovery_source(self, source: dict[str, Any]) -> list[dict[str, Any]]:
        kind = str(source.get("kind") or "").strip().lower()
        url = str(source.get("url") or "").strip()
        provider = str(source.get("provider") or "scouted").strip() or "scouted"
        if kind == "local-ollama" or "11434" in url:
            return self._probe_ollama_models(url, provider)
        return self._probe_openrouter_models(url, provider)

    def _probe_openrouter_models(self, url: str, provider: str) -> list[dict[str, Any]]:
        req = request.Request(url, headers={"User-Agent": "OpenChimera/1.0"})
        with request.urlopen(req, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
        items = payload.get("data", []) if isinstance(payload, dict) else []
        discovered: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            pricing = item.get("pricing", {}) if isinstance(item.get("pricing", {}), dict) else {}
            prompt_cost = str(pricing.get("prompt", "")).strip()
            completion_cost = str(pricing.get("completion", "")).strip()
            if prompt_cost not in {"0", "0.0", "0.00"} or completion_cost not in {"0", "0.0", "0.00"}:
                continue
            model_id = str(item.get("id") or "").strip()
            if not model_id:
                continue
            discovered.append(
                {
                    "id": model_id,
                    "provider": provider,
                    "recommended_for": ["fallback", "general"],
                    "strength": str(item.get("name") or "free remote model"),
                    "context_length": int(item.get("context_length") or item.get("top_provider", {}).get("context_length") or 0),
                    "cost": 0,
                    "source": "autonomy-discovery",
                }
            )
        return discovered

    def _probe_ollama_models(self, url: str, provider: str) -> list[dict[str, Any]]:
        req = request.Request(url, headers={"User-Agent": "OpenChimera/1.0"})
        with request.urlopen(req, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
        items = payload.get("models", []) if isinstance(payload, dict) else []
        discovered: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            model_id = str(item.get("model") or item.get("name") or "").strip()
            if not model_id:
                continue
            discovered.append(
                {
                    "id": model_id,
                    "provider": provider,
                    "recommended_for": ["fallback", "general"],
                    "strength": "local no-cost ollama fallback",
                    "context_length": 0,
                    "cost": 0,
                    "source": "autonomy-discovery",
                }
            )
        return discovered

    def _normalize_model_catalog(self, raw: Any, *, source: str) -> list[dict[str, Any]]:
        if isinstance(raw, dict):
            items = [{"id": key, **(value if isinstance(value, dict) else {})} for key, value in raw.items()]
        elif isinstance(raw, list):
            items = [item for item in raw if isinstance(item, dict)]
        else:
            items = []

        normalized: list[dict[str, Any]] = []
        for item in items:
            model_id = str(item.get("id") or item.get("model") or item.get("name") or "").strip()
            if not model_id:
                continue
            normalized.append(
                {
                    "id": model_id,
                    "provider": str(item.get("provider") or "scouted"),
                    "recommended_for": list(item.get("recommended_for") or ["fallback"]),
                    "strength": str(item.get("strength") or item.get("name") or "scouted fallback model"),
                    "context_length": int(item.get("context_length") or 0),
                    "cost": item.get("cost", 0),
                    "source": str(item.get("source") or source),
                }
            )
        return normalized

    def _dedupe_models(self, models: list[dict[str, Any]]) -> list[dict[str, Any]]:
        deduped: dict[str, dict[str, Any]] = {}
        for item in models:
            model_id = str(item.get("id") or "").strip()
            if not model_id:
                continue
            existing = deduped.get(model_id)
            if existing is None or (existing.get("source") == "legacy-openclaw-sync" and item.get("source") != "legacy-openclaw-sync"):
                deduped[model_id] = dict(item)
        return list(deduped.values())

    def _artifact_path(self, artifact_name: str) -> Path | None:
        return {
            "scouted_models_registry": self.data_root / "scouted_models_registry.json",
            "discovered_models": self.data_root / "discovered_models.json",
            "learned_fallback_rankings": self.data_root / "learned_fallback_rankings.json",
            "skill_audit": self.data_root / "skill_audit.json",
            "refresh_harness_dataset": self.data_root / "refresh_harness_dataset.json",
            "degradation_chains": self.data_root / "degradation_chains.json",
            "self_audit": self.data_root / "self_audit.json",
            "preview_self_repair": self.data_root / "preview_self_repair.json",
            "operator_digest": self.data_root / "operator_digest.json",
            "artifact_history": self.artifact_history_path,
        }.get(artifact_name)

    def _write_artifact(self, artifact_name: str, payload: dict[str, Any], *, job_name: str) -> None:
        path = self._artifact_path(artifact_name)
        if path is None:
            raise ValueError(f"Unknown autonomy artifact: {artifact_name}")
        self.data_root.mkdir(parents=True, exist_ok=True)
        atomic_write_json(path, payload)
        self._record_artifact_history(artifact_name, path, payload, job_name=job_name)

    def _load_artifact_history(self) -> list[dict[str, Any]]:
        if not self.artifact_history_path.exists():
            return []
        try:
            payload = json.loads(self.artifact_history_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
        history = payload.get("history", []) if isinstance(payload, dict) else []
        return [item for item in history if isinstance(item, dict)]

    def _record_artifact_history(self, artifact_name: str, path: Path, payload: dict[str, Any], *, job_name: str) -> None:
        history = self._load_artifact_history()
        entry = {
            "artifact_name": artifact_name,
            "job_name": job_name,
            "path": str(path),
            "status": str(payload.get("status", "ok")),
            "recorded_at": time.time(),
            "generated_at": payload.get("generated_at") or payload.get("synced_at") or payload.get("discovered_at") or time.strftime("%Y-%m-%dT%H:%M:%S"),
            "summary": self._artifact_summary(artifact_name, payload),
        }
        history.append(entry)
        trimmed = self._apply_artifact_retention(history)
        atomic_write_json(self.artifact_history_path, {"history": trimmed})

    def _apply_artifact_retention(self, history: list[dict[str, Any]]) -> list[dict[str, Any]]:
        retention = self.profile.get("autonomy", {}).get("artifacts", {}).get("retention", {})
        max_entries = max(1, int(retention.get("max_history_entries", 100) or 100))
        max_age_days = max(1, int(retention.get("max_age_days", 30) or 30))
        cutoff = time.time() - (max_age_days * 24 * 3600)
        trimmed = [item for item in history if float(item.get("recorded_at", 0.0)) >= cutoff]
        trimmed = sorted(trimmed, key=lambda item: float(item.get("recorded_at", 0.0)), reverse=True)
        return trimmed[:max_entries]

    def _artifact_summary(self, artifact_name: str, payload: dict[str, Any]) -> str:
        if artifact_name == "discovered_models":
            return f"{int(payload.get('model_count', 0) or 0)} discovered free models"
        if artifact_name == "scouted_models_registry":
            return f"{int(payload.get('model_count', 0) or 0)} merged scouted fallback models"
        if artifact_name == "learned_fallback_rankings":
            count = len(payload.get("query_types", {})) if isinstance(payload.get("query_types", {}), dict) else 0
            return f"{count} ranked query groups"
        if artifact_name == "skill_audit":
            count = len(payload.get("missing_skills", [])) if isinstance(payload.get("missing_skills", []), list) else 0
            return f"{count} missing bridge skills"
        if artifact_name == "refresh_harness_dataset":
            return f"dataset refresh status={payload.get('status', 'ok')}"
        if artifact_name == "degradation_chains":
            count = len(payload.get("chains", [])) if isinstance(payload.get("chains", []), list) else 0
            return f"{count} degradation chains"
        if artifact_name == "self_audit":
            count = len(payload.get("findings", [])) if isinstance(payload.get("findings", []), list) else 0
            return f"{count} self-audit findings"
        if artifact_name == "preview_self_repair":
            count = len(payload.get("focus_areas", [])) if isinstance(payload.get("focus_areas", []), list) else 0
            return f"{count} repair focus areas"
        if artifact_name == "operator_digest":
            summary = payload.get("summary", {}) if isinstance(payload.get("summary", {}), dict) else {}
            return (
                f"alerts={int(summary.get('recent_alert_count', 0) or 0)} "
                f"failed_jobs={int(summary.get('failed_job_count', 0) or 0)} "
                f"failed_deliveries={int(summary.get('failed_channel_delivery_count', 0) or 0)}"
            )
        return str(payload.get("status", "ok"))

    def _call_runtime_provider(self, name: str, default: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        provider = self.runtime_context_providers.get(name)
        if not callable(provider):
            return default
        try:
            result = provider(**kwargs)
        except TypeError:
            result = provider()
        except Exception as exc:
            return {"status": "error", "error": str(exc)}
        return result if isinstance(result, dict) else default

    def _build_runtime_context(self) -> dict[str, Any]:
        return {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "health": self._call_runtime_provider("health", {}),
            "provider_activation": self._call_runtime_provider("provider_activation", {}),
            "onboarding": self._call_runtime_provider("onboarding", {}),
            "integrations": self._call_runtime_provider("integrations", {}),
            "subsystems": self._call_runtime_provider("subsystems", {}),
            "job_queue": self._call_runtime_provider("job_queue", {}),
            "autonomy_jobs": {
                name: {
                    "enabled": job.enabled,
                    "last_status": job.last_status,
                    "last_run_at": job.last_run_at,
                    "category": job.category,
                }
                for name, job in self.jobs.items()
            },
        }

    def _build_degradation_report(self, context: dict[str, Any]) -> dict[str, Any]:
        health = context.get("health", {}) if isinstance(context.get("health", {}), dict) else {}
        provider_activation = context.get("provider_activation", {}) if isinstance(context.get("provider_activation", {}), dict) else {}
        integrations = context.get("integrations", {}) if isinstance(context.get("integrations", {}), dict) else {}
        subsystems = context.get("subsystems", {}) if isinstance(context.get("subsystems", {}), dict) else {}
        job_queue = context.get("job_queue", {}) if isinstance(context.get("job_queue", {}), dict) else {}
        fallback_learning = provider_activation.get("fallback_learning", {}) if isinstance(provider_activation.get("fallback_learning", {}), dict) else {}
        chains: list[dict[str, Any]] = []
        recommendations: list[str] = []

        healthy_models = int(health.get("healthy_models", 0) or 0)
        minimind_available = bool(health.get("components", {}).get("minimind", False)) if isinstance(health.get("components", {}), dict) else False
        if healthy_models <= 0 and not minimind_available:
            chains.append(
                {
                    "id": "generation-path-offline",
                    "severity": "critical",
                    "summary": "No healthy local generation path is currently online.",
                    "recommendations": ["Start a local model runtime or provision a cloud fallback.", "Run preview_self_repair to stage a safe remediation plan."],
                }
            )
            recommendations.append("Restore at least one healthy local or cloud generation path.")

        stale_jobs = [
            name
            for name, details in context.get("autonomy_jobs", {}).items()
            if details.get("enabled") and details.get("last_status") in {"never", "error"}
        ]
        if stale_jobs:
            chains.append(
                {
                    "id": "autonomy-job-drift",
                    "severity": "high",
                    "summary": "One or more autonomy jobs have never succeeded or are currently failing.",
                    "jobs": stale_jobs,
                    "recommendations": ["Run the affected audit or discovery jobs manually.", "Queue a self-audit to confirm whether the failure is isolated or systemic."],
                }
            )
            recommendations.append("Stabilize failing autonomy jobs before enabling deeper repair workflows.")

        degraded_models = [str(item) for item in fallback_learning.get("degraded_models", []) if str(item).strip()]
        if provider_activation.get("prefer_free_models") and degraded_models:
            chains.append(
                {
                    "id": "degraded-free-fallbacks",
                    "severity": "medium",
                    "summary": "Free-model preference is enabled while some learned fallback candidates are degraded.",
                    "models": degraded_models,
                    "recommendations": ["Review learned fallback rankings before trusting cost-aware fallback paths.", "Prefer top-ranked non-degraded free models or disable prefer_free_models temporarily."],
                }
            )
            recommendations.append("Review degraded learned fallback models before relying on cost-aware failover.")

        remediation = [str(item) for item in integrations.get("remediation", []) if str(item).strip()]
        if remediation:
            chains.append(
                {
                    "id": "integration-bridge-gaps",
                    "severity": "medium",
                    "summary": "Integration audit still reports missing first-class bridges or recovered lineage gaps.",
                    "issues": remediation[:5],
                    "recommendations": ["Keep unresolved lineage in audit visibility until a real bridge exists.", "Use preview_self_repair to package the highest-priority bridge work for Aegis review."],
                }
            )
            recommendations.append("Prioritize the highest-value runtime bridge gaps exposed by the integration audit.")

        subsystem_items = subsystems.get("subsystems", []) if isinstance(subsystems.get("subsystems", []), list) else []
        unhealthy_subsystems = [
            str(item.get("id") or "unknown")
            for item in subsystem_items
            if bool(item.get("integrated_runtime")) and str(item.get("health", "")).lower() not in {"running", "available", "healthy"}
        ]
        if unhealthy_subsystems:
            chains.append(
                {
                    "id": "subsystem-health-drift",
                    "severity": "medium",
                    "summary": "One or more managed subsystems are not reporting a healthy runtime state.",
                    "subsystems": unhealthy_subsystems,
                    "recommendations": ["Inspect the affected subsystem status and recent events.", "Use Aegis preview workflows before attempting repair changes."],
                }
            )
            recommendations.append("Investigate non-healthy managed subsystems before relying on them in operator workflows.")

        failed_jobs = int(job_queue.get("counts", {}).get("failed", 0) or 0) if isinstance(job_queue.get("counts", {}), dict) else 0
        if failed_jobs > 0:
            chains.append(
                {
                    "id": "operator-job-failures",
                    "severity": "medium",
                    "summary": "The durable operator queue contains failed jobs that may indicate unresolved runtime drift.",
                    "failed_jobs": failed_jobs,
                    "recommendations": ["Replay failed jobs only after confirming the underlying dependency is healthy.", "Use self-audit artifacts to distinguish transient failures from systemic issues."],
                }
            )
            recommendations.append("Review failed durable jobs before replaying them blindly.")

        return {
            "status": "degraded" if chains else "ok",
            "generated_at": context.get("generated_at"),
            "chains": chains,
            "recommendations": recommendations,
        }

    def _build_self_audit_report(self, context: dict[str, Any]) -> dict[str, Any]:
        degradation = self._build_degradation_report(context)
        findings: list[dict[str, Any]] = []
        recommendations = list(degradation.get("recommendations", []))

        health = context.get("health", {}) if isinstance(context.get("health", {}), dict) else {}
        provider_activation = context.get("provider_activation", {}) if isinstance(context.get("provider_activation", {}), dict) else {}
        onboarding = context.get("onboarding", {}) if isinstance(context.get("onboarding", {}), dict) else {}
        integrations = context.get("integrations", {}) if isinstance(context.get("integrations", {}), dict) else {}
        fallback_learning = provider_activation.get("fallback_learning", {}) if isinstance(provider_activation.get("fallback_learning", {}), dict) else {}
        discovery = provider_activation.get("discovery", {}) if isinstance(provider_activation.get("discovery", {}), dict) else {}

        findings.extend(degradation.get("chains", []))

        external_blockers = 0
        if not bool(discovery.get("local_model_assets_available", False)):
            search_roots = discovery.get("local_search_roots", []) if isinstance(discovery.get("local_search_roots", []), list) else []
            findings.append(
                {
                    "id": "local-model-assets-missing",
                    "severity": "medium",
                    "summary": "No local GGUF assets are available in the configured or discovered model search roots.",
                    "search_roots": search_roots[:8],
                    "recommendations": [
                        "Place at least one GGUF model in a discovered search root or update the runtime profile to point at an existing model directory.",
                        "Re-run openchimera doctor after model assets are added to confirm local launcher readiness.",
                    ],
                }
            )
            recommendations.append("Provision at least one local GGUF asset or point OpenChimera at an existing GGUF model directory.")
            external_blockers += 1

        onboarding_blockers = onboarding.get("blockers", []) if isinstance(onboarding.get("blockers", []), list) else []
        if any("push channel" in str(item).lower() for item in onboarding_blockers):
            findings.append(
                {
                    "id": "operator-channel-missing",
                    "severity": "medium",
                    "summary": "No push channel is configured for operator notifications.",
                    "blockers": onboarding_blockers,
                    "recommendations": [
                        "Configure a webhook, Slack, Discord, or Telegram subscription for operator notifications.",
                    ],
                }
            )
            recommendations.append("Configure at least one operator notification channel.")
            external_blockers += 1

        if bool(fallback_learning.get("learned_rankings_available", False)):
            findings.append(
                {
                    "id": "fallback-learning-online",
                    "severity": "info",
                    "summary": "Learned fallback rankings are available for operator review.",
                    "top_ranked_models": fallback_learning.get("top_ranked_models", []),
                }
            )

        if bool(health.get("components", {}).get("autonomy", False)) if isinstance(health.get("components", {}), dict) else False:
            findings.append(
                {
                    "id": "autonomy-runtime-online",
                    "severity": "info",
                    "summary": "Autonomy scheduler is online and emitting runtime job signals.",
                }
            )

        remediation = integrations.get("remediation", []) if isinstance(integrations.get("remediation", []), list) else []
        if not remediation and not degradation.get("chains") and external_blockers == 0:
            findings.append(
                {
                    "id": "runtime-stable",
                    "severity": "info",
                    "summary": "No immediate degradation chains or integration remediation gaps were detected.",
                }
            )

        return {
            "status": "warning" if degradation.get("chains") or external_blockers else "ok",
            "generated_at": context.get("generated_at"),
            "summary": {
                "healthy_models": int(health.get("healthy_models", 0) or 0),
                "integration_gap_count": len(remediation),
                "degradation_chain_count": len(degradation.get("chains", [])),
                "external_blocker_count": external_blockers,
            },
            "findings": findings,
            "recommendations": recommendations,
        }