from __future__ import annotations

from typing import Any


class ServicePlane:
    def __init__(
        self,
        *,
        aegis: Any,
        ascension: Any,
        minimind: Any,
        autonomy: Any,
        llm_manager: Any,
        harness_port: Any,
        identity_snapshot: dict[str, Any],
        subsystems: Any,
        bus: Any,
        clawd_hybrid_rtx_status_getter: Any,
        qwen_agent_status_getter: Any,
        context_hub_status_getter: Any,
        deepagents_stack_status_getter: Any,
        aether_operator_stack_status_getter: Any,
        aegis_mobile_gateway_status_getter: Any,
    ) -> None:
        self.aegis = aegis
        self.ascension = ascension
        self.minimind = minimind
        self.autonomy = autonomy
        self.llm_manager = llm_manager
        self.harness_port = harness_port
        self.identity_snapshot = identity_snapshot
        self.subsystems = subsystems
        self.bus = bus
        self.clawd_hybrid_rtx_status_getter = clawd_hybrid_rtx_status_getter
        self.qwen_agent_status_getter = qwen_agent_status_getter
        self.context_hub_status_getter = context_hub_status_getter
        self.deepagents_stack_status_getter = deepagents_stack_status_getter
        self.aether_operator_stack_status_getter = aether_operator_stack_status_getter
        self.aegis_mobile_gateway_status_getter = aegis_mobile_gateway_status_getter

    def invoke_subsystem(self, subsystem_id: str, action: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        result = self.subsystems.invoke(subsystem_id, action, payload)
        self.bus.publish_nowait("system/subsystems", {"action": "invoke", "subsystem_id": subsystem_id, "result": result})
        return result

    def invoke_managed_subsystem(self, subsystem_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        if subsystem_id == "aegis_swarm":
            return self.run_aegis_workflow(
                target_project=str(payload.get("target_project") or "") or None,
                preview=bool(payload.get("preview", True)),
            )
        if subsystem_id == "ascension_engine":
            raw_perspectives = payload.get("perspectives")
            perspectives = [str(item) for item in raw_perspectives] if isinstance(raw_perspectives, list) else None
            return self.deliberate(
                prompt=str(payload.get("prompt", "")),
                perspectives=perspectives,
                max_tokens=int(payload.get("max_tokens", 256)),
            )
        if subsystem_id == "clawd_hybrid_rtx":
            return self.clawd_hybrid_rtx_status_getter()
        if subsystem_id == "qwen_agent":
            return self.qwen_agent_status_getter()
        if subsystem_id == "context_hub":
            return self.context_hub_status_getter()
        if subsystem_id == "deepagents_stack":
            return self.deepagents_stack_status_getter()
        if subsystem_id == "aether_operator_stack":
            return self.aether_operator_stack_status_getter()
        if subsystem_id == "aegis_mobile_gateway":
            return self.aegis_mobile_gateway_status_getter()
        if subsystem_id == "minimind":
            action = str(payload.get("action", "status"))
            if action == "build_dataset":
                return self.build_minimind_dataset(force=bool(payload.get("force", True)))
            if action == "start_server":
                return self.start_minimind_server()
            if action == "stop_server":
                return self.stop_minimind_server()
            if action == "start_training":
                return self.start_minimind_training(
                    mode=str(payload.get("mode", "reason_sft")),
                    force_dataset=bool(payload.get("force_dataset", False)),
                )
            if action == "stop_training":
                return self.stop_minimind_training(str(payload.get("job_id", "")))
            return self.minimind.status()
        raise ValueError(f"Unsupported subsystem invocation: {subsystem_id}")

    def aegis_status(self) -> dict[str, Any]:
        return self.aegis.status()

    def run_aegis_workflow(
        self,
        target_project: str | None = None,
        preview: bool = True,
        preview_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result = self.aegis.run_workflow(target_project=target_project, preview=preview, preview_context=preview_context)
        self.bus.publish_nowait("system/aegis", {"action": "run_workflow", "result": result})
        return result

    def ascension_status(self) -> dict[str, Any]:
        return self.ascension.status()

    def deliberate(self, prompt: str, perspectives: list[str] | None = None, max_tokens: int = 256) -> dict[str, Any]:
        result = self.ascension.deliberate(prompt=prompt, perspectives=perspectives, max_tokens=max_tokens)
        self.bus.publish_nowait("system/ascension", {"action": "deliberate", "result": result})
        return result

    def build_minimind_dataset(self, force: bool = True) -> dict[str, Any]:
        result = self.minimind.build_training_dataset(
            self.harness_port,
            identity_snapshot=self.identity_snapshot,
            force=force,
        )
        self.bus.publish_nowait("system/minimind", {"action": "build_dataset", "result": result})
        return result

    def start_minimind_server(self) -> dict[str, Any]:
        result = self.minimind.start_server()
        self.bus.publish_nowait("system/minimind", {"action": "start_server", "result": result})
        return result

    def stop_minimind_server(self) -> dict[str, Any]:
        result = self.minimind.stop_server()
        self.bus.publish_nowait("system/minimind", {"action": "stop_server", "result": result})
        return result

    def start_minimind_training(self, mode: str = "reason_sft", force_dataset: bool = False) -> dict[str, Any]:
        if force_dataset:
            dataset_result = self.build_minimind_dataset(force=True)
            self.bus.publish_nowait(
                "system/minimind",
                {"action": "build_dataset_before_training", "mode": mode, "result": dataset_result},
            )
        result = self.minimind.start_training_job(mode=mode, force_dataset=False)
        self.bus.publish_nowait("system/minimind", {"action": "start_training", "mode": mode, "result": result})
        return result

    def stop_minimind_training(self, job_id: str) -> dict[str, Any]:
        result = self.minimind.stop_training_job(job_id)
        self.bus.publish_nowait("system/minimind", {"action": "stop_training", "job_id": job_id, "result": result})
        return result

    def start_autonomy(self) -> dict[str, Any]:
        result = self.autonomy.start()
        self.bus.publish_nowait("system/autonomy", {"action": "start", "result": result})
        return result

    def stop_autonomy(self) -> dict[str, Any]:
        result = self.autonomy.stop()
        self.bus.publish_nowait("system/autonomy", {"action": "stop", "result": result})
        return result

    def run_autonomy_job(self, job_name: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        result = self.autonomy.run_job(job_name, payload=payload)
        self.bus.publish_nowait("system/autonomy", {"action": "run_job", "job": job_name, "payload": payload or {}, "result": result})
        return result

    def start_local_models(self, models: list[str] | None = None) -> dict[str, Any]:
        result = self.llm_manager.start_configured_models(models)
        self.bus.publish_nowait("system/local-llm", {"action": "start", "result": result})
        return result

    def stop_local_models(self, models: list[str] | None = None) -> dict[str, Any]:
        result = self.llm_manager.stop_configured_models(models)
        self.bus.publish_nowait("system/local-llm", {"action": "stop", "result": result})
        return result