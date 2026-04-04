"""Tests for core.service_plane — service orchestration facade."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from core.service_plane import ServicePlane


def _make_plane(**overrides) -> ServicePlane:
    defaults: dict = dict(
        aegis=MagicMock(),
        ascension=MagicMock(),
        minimind=MagicMock(),
        autonomy=MagicMock(),
        llm_manager=MagicMock(),
        harness_port=MagicMock(),
        identity_snapshot={},
        subsystems=MagicMock(),
        bus=MagicMock(),
        clawd_hybrid_rtx_status_getter=MagicMock(return_value={"status": "ok"}),
        qwen_agent_status_getter=MagicMock(return_value={"status": "ok"}),
        context_hub_status_getter=MagicMock(return_value={"status": "ok"}),
        deepagents_stack_status_getter=MagicMock(return_value={"status": "ok"}),
        aether_operator_stack_status_getter=MagicMock(return_value={"status": "ok"}),
        aegis_mobile_gateway_status_getter=MagicMock(return_value={"status": "ok"}),
    )
    defaults.update(overrides)
    return ServicePlane(**defaults)


class TestServicePlane(unittest.TestCase):
    def test_aegis_status_delegates(self) -> None:
        plane = _make_plane()
        plane.aegis.status.return_value = {"active": True}
        self.assertEqual(plane.aegis_status(), {"active": True})

    def test_run_aegis_workflow_publishes(self) -> None:
        plane = _make_plane()
        plane.aegis.run_workflow.return_value = {"completed": True}
        plane.run_aegis_workflow(target_project="proj1")
        plane.bus.publish_nowait.assert_called_once()
        topic, payload = plane.bus.publish_nowait.call_args[0]
        self.assertEqual(topic, "system/aegis")
        self.assertEqual(payload["action"], "run_workflow")

    def test_ascension_status_delegates(self) -> None:
        plane = _make_plane()
        plane.ascension.status.return_value = {"deliberating": False}
        self.assertEqual(plane.ascension_status(), {"deliberating": False})

    def test_deliberate_publishes(self) -> None:
        plane = _make_plane()
        plane.ascension.deliberate.return_value = {"answer": "42"}
        plane.deliberate(prompt="What is truth?")
        plane.bus.publish_nowait.assert_called_once()
        topic, payload = plane.bus.publish_nowait.call_args[0]
        self.assertEqual(topic, "system/ascension")
        self.assertEqual(payload["action"], "deliberate")

    def test_start_minimind_server_publishes(self) -> None:
        plane = _make_plane()
        plane.minimind.start_server.return_value = {"started": True}
        plane.start_minimind_server()
        plane.bus.publish_nowait.assert_called_once()

    def test_stop_minimind_server_publishes(self) -> None:
        plane = _make_plane()
        plane.minimind.stop_server.return_value = {"stopped": True}
        plane.stop_minimind_server()
        plane.bus.publish_nowait.assert_called_once()

    def test_build_minimind_dataset_publishes(self) -> None:
        plane = _make_plane()
        plane.minimind.build_training_dataset.return_value = {"rows": 100}
        plane.build_minimind_dataset()
        plane.bus.publish_nowait.assert_called_once()

    def test_start_minimind_training_no_dataset(self) -> None:
        plane = _make_plane()
        plane.minimind.start_training_job.return_value = {"job_id": "j1"}
        plane.start_minimind_training()
        plane.minimind.start_training_job.assert_called_once_with(mode="reason_sft", force_dataset=False)

    def test_start_minimind_training_with_force_dataset(self) -> None:
        plane = _make_plane()
        plane.minimind.build_training_dataset.return_value = {"rows": 50}
        plane.minimind.start_training_job.return_value = {"job_id": "j2"}
        plane.start_minimind_training(force_dataset=True)
        # Should publish 3 events: build_dataset + build_dataset_before_training notification + start_training
        self.assertEqual(plane.bus.publish_nowait.call_count, 3)

    def test_stop_minimind_training_publishes(self) -> None:
        plane = _make_plane()
        plane.minimind.stop_training_job.return_value = {"stopped": True}
        plane.stop_minimind_training("j1")
        plane.minimind.stop_training_job.assert_called_once_with("j1")
        plane.bus.publish_nowait.assert_called_once()

    def test_start_autonomy_publishes(self) -> None:
        plane = _make_plane()
        plane.autonomy.start.return_value = {"running": True}
        plane.start_autonomy()
        plane.bus.publish_nowait.assert_called_once()

    def test_stop_autonomy_publishes(self) -> None:
        plane = _make_plane()
        plane.autonomy.stop.return_value = {"stopped": True}
        plane.stop_autonomy()
        plane.bus.publish_nowait.assert_called_once()

    def test_run_autonomy_job_publishes(self) -> None:
        plane = _make_plane()
        plane.autonomy.run_job.return_value = {"done": True}
        plane.run_autonomy_job("daily-check", {"key": "val"})
        plane.bus.publish_nowait.assert_called_once()

    def test_start_local_models_publishes(self) -> None:
        plane = _make_plane()
        plane.llm_manager.start_configured_models.return_value = {"started": []}
        plane.start_local_models(["phi-3.5-mini"])
        plane.bus.publish_nowait.assert_called_once()

    def test_stop_local_models_publishes(self) -> None:
        plane = _make_plane()
        plane.llm_manager.stop_configured_models.return_value = {"stopped": []}
        plane.stop_local_models()
        plane.bus.publish_nowait.assert_called_once()

    def test_invoke_subsystem_publishes(self) -> None:
        plane = _make_plane()
        plane.subsystems.invoke.return_value = {"done": True}
        plane.invoke_subsystem("custom/sys", "run", {"x": 1})
        plane.bus.publish_nowait.assert_called_once()

    def test_invoke_managed_aegis_swarm(self) -> None:
        plane = _make_plane()
        plane.aegis.run_workflow.return_value = {"ok": True}
        result = plane.invoke_managed_subsystem("aegis_swarm", {"target_project": "proj", "preview": False})
        plane.aegis.run_workflow.assert_called_once()

    def test_invoke_managed_clawd_hybrid_rtx(self) -> None:
        plane = _make_plane()
        result = plane.invoke_managed_subsystem("clawd_hybrid_rtx", {})
        plane.clawd_hybrid_rtx_status_getter.assert_called_once()

    def test_invoke_managed_qwen_agent(self) -> None:
        plane = _make_plane()
        plane.invoke_managed_subsystem("qwen_agent", {})
        plane.qwen_agent_status_getter.assert_called_once()

    def test_invoke_managed_context_hub(self) -> None:
        plane = _make_plane()
        plane.invoke_managed_subsystem("context_hub", {})
        plane.context_hub_status_getter.assert_called_once()

    def test_invoke_managed_deepagents_stack(self) -> None:
        plane = _make_plane()
        plane.invoke_managed_subsystem("deepagents_stack", {})
        plane.deepagents_stack_status_getter.assert_called_once()

    def test_invoke_managed_aether_operator_stack(self) -> None:
        plane = _make_plane()
        plane.invoke_managed_subsystem("aether_operator_stack", {})
        plane.aether_operator_stack_status_getter.assert_called_once()

    def test_invoke_managed_aegis_mobile_gateway(self) -> None:
        plane = _make_plane()
        plane.invoke_managed_subsystem("aegis_mobile_gateway", {})
        plane.aegis_mobile_gateway_status_getter.assert_called_once()

    def test_invoke_managed_minimind_status(self) -> None:
        plane = _make_plane()
        plane.minimind.status.return_value = {"running": False}
        plane.invoke_managed_subsystem("minimind", {"action": "status"})
        plane.minimind.status.assert_called_once()

    def test_invoke_managed_minimind_start_server(self) -> None:
        plane = _make_plane()
        plane.minimind.start_server.return_value = {}
        plane.invoke_managed_subsystem("minimind", {"action": "start_server"})
        plane.minimind.start_server.assert_called_once()

    def test_invoke_managed_minimind_stop_server(self) -> None:
        plane = _make_plane()
        plane.minimind.stop_server.return_value = {}
        plane.invoke_managed_subsystem("minimind", {"action": "stop_server"})
        plane.minimind.stop_server.assert_called_once()

    def test_invoke_managed_minimind_stop_training(self) -> None:
        plane = _make_plane()
        plane.minimind.stop_training_job.return_value = {}
        plane.invoke_managed_subsystem("minimind", {"action": "stop_training", "job_id": "j1"})
        plane.minimind.stop_training_job.assert_called_once_with("j1")

    def test_invoke_managed_unknown_raises(self) -> None:
        plane = _make_plane()
        with self.assertRaises(ValueError):
            plane.invoke_managed_subsystem("unknown_sys", {})

    def test_invoke_managed_ascension_engine(self) -> None:
        plane = _make_plane()
        plane.ascension.deliberate.return_value = {"answer": "resolved"}
        plane.invoke_managed_subsystem("ascension_engine", {"prompt": "What is good?", "max_tokens": 128})
        plane.ascension.deliberate.assert_called_once()


if __name__ == "__main__":
    unittest.main()
