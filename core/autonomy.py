from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.bus import EventBus
from core.config import ROOT, get_openclaw_root, load_runtime_profile
from core.harness_port import HarnessPortAdapter
from core.minimind_service import MiniMindService


@dataclass
class ScheduledJob:
    name: str
    interval_seconds: int
    enabled: bool = True
    last_run_at: float = 0.0
    last_status: str = "never"
    last_result: dict[str, Any] = field(default_factory=dict)


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
        self.openclaw_root = get_openclaw_root()
        self.data_root = ROOT / "data" / "autonomy"
        self.jobs = self._build_jobs()
        self._thread: threading.Thread | None = None
        self._running = False

    def _build_jobs(self) -> dict[str, ScheduledJob]:
        autonomy_config = self.profile.get("autonomy", {})
        job_config = autonomy_config.get("jobs", {})

        def job(name: str, default_interval: int) -> ScheduledJob:
            config = job_config.get(name, {})
            return ScheduledJob(
                name=name,
                interval_seconds=int(config.get("interval_seconds", default_interval)),
                enabled=bool(config.get("enabled", True)),
            )

        return {
            "sync_scouted_models": job("sync_scouted_models", 900),
            "audit_skill_bridges": job("audit_skill_bridges", 1800),
            "refresh_harness_dataset": job("refresh_harness_dataset", 21600),
        }

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

    def run_job(self, job_name: str) -> dict[str, Any]:
        job = self.jobs.get(job_name)
        if job is None:
            return {"status": "error", "error": f"Unknown job: {job_name}"}

        handlers = {
            "sync_scouted_models": self._sync_scouted_models,
            "audit_skill_bridges": self._audit_skill_bridges,
            "refresh_harness_dataset": self._refresh_harness_dataset,
        }
        handler = handlers[job_name]

        try:
            result = handler()
            job.last_status = "ok"
            job.last_result = result
        except Exception as exc:
            result = {"status": "error", "error": str(exc)}
            job.last_status = "error"
            job.last_result = result

        job.last_run_at = time.time()
        self.bus.publish_nowait("system/autonomy/job", {"job": job_name, "result": result})
        return result

    def _sync_scouted_models(self) -> dict[str, Any]:
        source_path = self.openclaw_root / "chimera_free_fallbacks.json"
        target_path = self.data_root / "scouted_models_registry.json"
        self.data_root.mkdir(parents=True, exist_ok=True)

        if not source_path.exists():
            payload = {"status": "missing", "source": str(source_path), "target": str(target_path)}
            target_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            return payload

        data = json.loads(source_path.read_text(encoding="utf-8"))
        model_count = len(data) if isinstance(data, list) else len(data.keys()) if isinstance(data, dict) else 0
        payload = {
            "status": "ok",
            "source": str(source_path),
            "target": str(target_path),
            "model_count": model_count,
            "synced_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "models": data,
        }
        target_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return {"status": "ok", "target": str(target_path), "model_count": model_count}

    def _audit_skill_bridges(self) -> dict[str, Any]:
        openclaw_skills = self.openclaw_root / "skills"
        openchimera_skills = ROOT / "skills"
        target_path = self.data_root / "skill_audit.json"
        self.data_root.mkdir(parents=True, exist_ok=True)

        openclaw_names = sorted(path.name for path in openclaw_skills.iterdir() if path.is_dir()) if openclaw_skills.exists() else []
        openchimera_names = sorted(path.name for path in openchimera_skills.iterdir() if path.is_dir()) if openchimera_skills.exists() else []
        openchimera_slug_map = {self._skill_slug(name): name for name in openchimera_names}
        missing = sorted(name for name in openclaw_names if self._skill_slug(name) not in openchimera_slug_map)
        payload = {
            "status": "ok",
            "openclaw_skill_count": len(openclaw_names),
            "openchimera_skill_count": len(openchimera_names),
            "missing_skills": missing,
            "priority_bridges": [
                name for name in missing if name in {"AstrBot", "deer-flow", "khoj", "LlamaFactory", "ragflow", "SWE-agent"}
            ],
        }
        target_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return payload

    def _skill_slug(self, name: str) -> str:
        return name.strip().lower().replace(" ", "-")

    def _refresh_harness_dataset(self) -> dict[str, Any]:
        manifest = self.minimind.build_training_dataset(
            self.harness_port,
            identity_snapshot=self.identity_snapshot,
            force=True,
        )
        return {
            "status": "ok",
            "training_output_dir": manifest.get("files", {}),
            "counts": manifest.get("counts", {}),
        }

    def status(self) -> dict[str, Any]:
        return {
            "running": self._running,
            "data_root": str(self.data_root),
            "jobs": {
                name: {
                    "enabled": job.enabled,
                    "interval_seconds": job.interval_seconds,
                    "last_run_at": job.last_run_at,
                    "last_status": job.last_status,
                    "last_result": job.last_result,
                }
                for name, job in self.jobs.items()
            },
        }