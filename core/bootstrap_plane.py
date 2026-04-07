from __future__ import annotations

import json
from typing import Any

from core.config import ROOT, get_chimera_kb_path, get_legacy_harness_snapshot_root
from core.rag import Document


class BootstrapPlane:
    def __init__(
        self,
        *,
        profile_loader: Any,
        profile_setter: Any,
        started_getter: Any,
        started_setter: Any,
        llm_manager: Any,
        job_queue: Any,
        minimind: Any,
        autonomy: Any,
        aegis: Any,
        ascension: Any,
        bus: Any,
        status_getter: Any,
        rag: Any,
        harness_port: Any,
        onboarding: Any,
        model_registry: Any,
    ) -> None:
        self.profile_loader = profile_loader
        self.profile_setter = profile_setter
        self.started_getter = started_getter
        self.started_setter = started_setter
        self.llm_manager = llm_manager
        self.job_queue = job_queue
        self.minimind = minimind
        self.autonomy = autonomy
        self.aegis = aegis
        self.ascension = ascension
        self.bus = bus
        self.status_getter = status_getter
        self.rag = rag
        self.harness_port = harness_port
        self.onboarding = onboarding
        self.model_registry = model_registry

    def start(self) -> None:
        if self.started_getter():
            return
        self.llm_manager.start_health_monitoring()
        self.job_queue.start()
        self.minimind.refresh_runtime_state()
        if self.profile_loader().get("local_runtime", {}).get("reasoning_engine_config", {}).get("auto_start_server", False):
            self.minimind.start_server()
        if self.autonomy.should_auto_start():
            self.autonomy.start()
        self.aegis.start()
        self.ascension.start()
        self.started_setter(True)
        self.bus.publish_nowait("system/provider", self.status_getter())

    def stop(self) -> None:
        self.ascension.stop()
        self.aegis.stop()
        self.autonomy.stop()
        self.job_queue.stop()
        if self.profile_loader().get("local_runtime", {}).get("reasoning_engine_config", {}).get("shutdown_with_provider", False):
            self.minimind.stop_server()
        self.llm_manager.stop_health_monitoring()
        self.started_setter(False)

    def reload_profile(self) -> dict[str, Any]:
        profile = self.profile_loader()
        self.profile_setter(profile)
        self.model_registry.profile = profile
        return profile

    def apply_onboarding(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = self.onboarding.apply(payload)
        self.reload_profile()
        self.bus.publish_nowait("system/onboarding", {"action": "apply", "result": result})
        return result

    def reset_onboarding(self) -> dict[str, Any]:
        result = self.onboarding.reset()
        self.bus.publish_nowait("system/onboarding", {"action": "reset", "result": result})
        return result

    def validate_onboarding_credential(self, provider_id: str, key: str, value: str) -> dict[str, Any]:
        return self.onboarding.validate_credential(provider_id, key, value)

    def seed_knowledge(self) -> None:
        kb_path = get_chimera_kb_path()
        if kb_path.exists():
            try:
                data = json.loads(kb_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                data = []

            docs = []
            for item in data:
                if not isinstance(item, dict):
                    continue
                docs.append(
                    Document(
                        text=str(item.get("text", "")),
                        metadata=item.get("metadata", {}),
                        id=item.get("id"),
                    )
                )
            self.rag.add_documents(docs, persist=False)

        for path in [ROOT / "README.md", ROOT / "config" / "runtime_profile.json"]:
            self.rag.add_file(path, metadata={"source_type": "openchimera-runtime"}, persist=False)

        if self.harness_port.available:
            harness_status = self.harness_port.status()
            harness_summary = harness_status.get("summary")
            if harness_summary:
                self.rag.add_documents(
                    [
                        Document(
                            text=harness_summary,
                            metadata={"topic": "upstream-harness-port", "source_type": "harness-port"},
                        )
                    ],
                    persist=False,
                )
            self.rag.add_file(self.harness_port.root / "README.md", metadata={"source_type": "harness-port"}, persist=False)

        legacy_snapshot_root = get_legacy_harness_snapshot_root()
        self.rag.add_file(legacy_snapshot_root / "README.md", metadata={"source_type": "legacy-harness-snapshot"}, persist=False)

        if self.minimind.available:
            self.rag.add_file(self.minimind.root / "README.md", metadata={"source_type": "minimind"}, persist=False)
            self.rag.add_file(
                self.minimind.root / "CHIMERA_MINI_PROPOSAL.md",
                metadata={"source_type": "minimind"},
                persist=False,
            )