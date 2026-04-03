from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable


class AutonomyPlane:
    def __init__(
        self,
        *,
        profile_getter: Callable[[], dict[str, Any]],
        autonomy: Any,
        job_queue: Any,
        channels: Any,
        bus: Any,
        provider_activation_getter: Callable[[], dict[str, Any]],
        job_queue_status_getter: Callable[..., dict[str, Any]],
        daily_briefing_getter: Callable[[], dict[str, Any]],
        create_operator_job_callback: Callable[[str, dict[str, Any], int], dict[str, Any]],
        run_autonomy_job_callback: Callable[[str, dict[str, Any] | None], dict[str, Any]],
    ) -> None:
        self._profile_getter = profile_getter
        self.autonomy = autonomy
        self.job_queue = job_queue
        self.channels = channels
        self.bus = bus
        self.provider_activation_getter = provider_activation_getter
        self.job_queue_status_getter = job_queue_status_getter
        self.daily_briefing_getter = daily_briefing_getter
        self.create_operator_job_callback = create_operator_job_callback
        self.run_autonomy_job_callback = run_autonomy_job_callback

    @property
    def profile(self) -> dict[str, Any]:
        return dict(self._profile_getter() or {})

    def diagnostics(self) -> dict[str, Any]:
        status = self.autonomy.status()
        artifacts: dict[str, Any] = {}
        for name, raw_path in status.get("artifacts", {}).items():
            path = Path(str(raw_path))
            if not path.exists():
                artifacts[name] = {"status": "missing", "path": str(path)}
                continue
            try:
                artifacts[name] = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                artifacts[name] = {"status": "error", "path": str(path), "error": "Invalid JSON artifact"}
        return {
            "status": "ok",
            "scheduler": status,
            "provider_activation": self.provider_activation_getter(),
            "job_queue": self.job_queue_status_getter(limit=20),
            "artifacts": artifacts,
            "artifact_history": self.autonomy.artifact_history(limit=20),
        }

    def artifact_history(self, artifact_name: str | None = None, limit: int = 20) -> dict[str, Any]:
        return self.autonomy.artifact_history(artifact_name=artifact_name or None, limit=limit)

    def artifact(self, artifact_name: str) -> dict[str, Any]:
        return self.autonomy.read_artifact(artifact_name)

    def operator_digest(self) -> dict[str, Any]:
        return self.artifact("operator_digest")

    def dispatch_operator_digest(
        self,
        enqueue: bool = False,
        max_attempts: int = 3,
        history_limit: int | None = None,
        dispatch_topic: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if history_limit is not None:
            payload["history_limit"] = int(history_limit)
        if dispatch_topic:
            payload["dispatch_topic"] = str(dispatch_topic)
        if enqueue:
            return self.create_operator_job_callback(
                "autonomy",
                {"job": "dispatch_operator_digest", **payload},
                max_attempts,
            )
        return self.run_autonomy_job_callback("dispatch_operator_digest", payload=payload or None)

    def preview_self_repair(self, target_project: str | None = None, enqueue: bool = False, max_attempts: int = 3) -> dict[str, Any]:
        payload: dict[str, Any] = {"job": "preview_self_repair"}
        if target_project:
            payload["target_project"] = target_project
        if enqueue:
            return self.create_operator_job_callback("autonomy", payload, max_attempts)
        return self.run_autonomy_job_callback("preview_self_repair", payload=payload)

    def handle_job_event(self, payload: Any) -> None:
        if not isinstance(payload, dict):
            return
        self.channels.dispatch("system/autonomy/job", payload)
        alert = self.build_autonomy_alert(payload)
        if alert is not None:
            topic = str(self.profile.get("autonomy", {}).get("alerts", {}).get("dispatch_topic", "system/autonomy/alert"))
            self.channels.dispatch(topic, alert)

    def build_autonomy_alert(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        alerts_config = self.profile.get("autonomy", {}).get("alerts", {})
        if not bool(alerts_config.get("enabled", True)):
            return None
        job_name = str(payload.get("job") or "").strip()
        if not job_name:
            return None
        severity_threshold = str(alerts_config.get("minimum_severity", "high")).strip().lower() or "high"
        threshold_rank = self.severity_rank(severity_threshold)
        artifact_name_map = {
            "check_degradation_chains": "degradation_chains",
            "run_self_audit": "self_audit",
            "preview_self_repair": "preview_self_repair",
        }
        artifact_name = artifact_name_map.get(job_name)
        if not artifact_name:
            return None
        artifact = self.autonomy.read_artifact(artifact_name)
        if not isinstance(artifact, dict):
            return None

        severity = "info"
        summary = ""
        details: list[dict[str, Any]] = []

        if artifact_name == "degradation_chains":
            details = [item for item in artifact.get("chains", []) if isinstance(item, dict)]
            if any(str(item.get("severity", "")).lower() == "critical" for item in details):
                severity = "critical"
            elif details:
                severity = "high"
            summary = f"Autonomy detected {len(details)} degradation chains."
        elif artifact_name == "self_audit":
            details = [item for item in artifact.get("findings", []) if isinstance(item, dict)]
            if any(str(item.get("severity", "")).lower() == "critical" for item in details):
                severity = "critical"
            elif any(str(item.get("severity", "")).lower() in {"high", "warning"} for item in details) or artifact.get("status") == "warning":
                severity = "high"
            summary = f"Autonomy self-audit produced {len(details)} findings."
        elif artifact_name == "preview_self_repair":
            focus_areas = artifact.get("focus_areas", []) if isinstance(artifact.get("focus_areas", []), list) else []
            if focus_areas:
                severity = "high"
            summary = f"Autonomy staged a preview repair with {len(focus_areas)} focus areas."

        if self.severity_rank(severity) < threshold_rank:
            return None
        return {
            "job": job_name,
            "severity": severity,
            "summary": summary,
            "artifact_name": artifact_name,
            "artifact": artifact,
            "generated_at": artifact.get("generated_at") or int(time.time()),
        }

    def severity_rank(self, severity: str) -> int:
        ordering = {"info": 1, "warning": 2, "high": 3, "critical": 4}
        return ordering.get(str(severity).lower(), 1)

    def execute_operator_job(self, job: dict[str, Any]) -> dict[str, Any]:
        job_type = str(job.get("job_type", ""))
        payload = job.get("payload", {}) if isinstance(job.get("payload", {}), dict) else {}
        if job_type == "autonomy" or job_type.startswith("autonomy."):
            job_name = str(payload.get("job") or payload.get("job_name") or "").strip()
            if not job_name:
                return {"status": "error", "error": "Missing autonomy job name"}
            job_payload = dict(payload)
            job_payload.pop("job", None)
            job_payload.pop("job_name", None)
            return self.autonomy.run_job(job_name, payload=job_payload)
        return {"status": "error", "error": f"Unsupported job type: {job_type}"}

    def classify_operator_job(self, job_type: str, payload: dict[str, Any]) -> tuple[str, str, str]:
        if job_type != "autonomy":
            return job_type, job_type, job_type.replace(".", " ")
        job_name = str(payload.get("job") or payload.get("job_name") or "autonomy").strip()
        category_map = {
            "discover_free_models": ("autonomy.discovery", "autonomy.discovery", "Discover free models"),
            "sync_scouted_models": ("autonomy.catalog", "autonomy.catalog", "Sync scouted models"),
            "learn_fallback_rankings": ("autonomy.learning", "autonomy.learning", "Learn fallback rankings"),
            "audit_skill_bridges": ("autonomy.audit", "autonomy.audit", "Audit skill bridges"),
            "check_degradation_chains": ("autonomy.audit", "autonomy.audit", "Check degradation chains"),
            "run_self_audit": ("autonomy.audit", "autonomy.audit", "Run self audit"),
            "preview_self_repair": ("autonomy.preview_repair", "autonomy.preview_repair", "Preview self repair"),
            "dispatch_operator_digest": ("autonomy.reporting", "autonomy.reporting", "Dispatch operator digest"),
            "refresh_harness_dataset": ("autonomy.training", "autonomy.training", "Refresh harness dataset"),
        }
        return category_map.get(job_name, ("autonomy", "autonomy", job_name.replace("_", " ")))

    def create_operator_job(self, job_type: str, payload: dict[str, Any], max_attempts: int = 3) -> dict[str, Any]:
        normalized_type, job_class, label = self.classify_operator_job(job_type, payload)
        result = self.job_queue.enqueue(
            job_type=normalized_type,
            payload=payload,
            max_attempts=max_attempts,
            job_class=job_class,
            label=label,
        )
        self.bus.publish_nowait("system/jobs", {"action": "create", "job": result})
        return result