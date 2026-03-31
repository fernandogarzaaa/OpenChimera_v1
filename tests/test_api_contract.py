from __future__ import annotations

import json
import unittest
from urllib import request

from core.api_server import OpenChimeraAPIServer


class _FakeRouter:
    def status(self) -> dict[str, object]:
        return {"available_models": ["qwen2.5-7b"], "healthy_models": 1, "known_models": 1}


class _FakeProvider:
    def __init__(self) -> None:
        self.router = _FakeRouter()

    def health(self) -> dict[str, object]:
        return {"status": "online", "name": "openchimera"}

    def list_models(self) -> dict[str, object]:
        return {"object": "list", "data": []}

    def local_runtime_status(self) -> dict[str, object]:
        return {"enabled": True}

    def harness_port_status(self) -> dict[str, object]:
        return {"available": True}

    def minimind_status(self) -> dict[str, object]:
        return {"available": True, "runtime": {"server": {"running": False}}}

    def autonomy_status(self) -> dict[str, object]:
        return {"running": False}

    def model_registry_status(self) -> dict[str, object]:
        return {"providers": [{"id": "local-llama-cpp"}], "recommendations": {"needs_cloud_fallback": False}}

    def refresh_model_registry(self) -> dict[str, object]:
        return {"generated_at": "2026-01-01T00:00:00+00:00", "providers": [{"id": "local-llama-cpp"}]}

    def onboarding_status(self) -> dict[str, object]:
        return {
            "suggested_local_models": [{"id": "phi-3.5-mini"}],
            "minimind_optimization_profile": {"approach": "airllm-inspired"},
        }

    def integration_status(self) -> dict[str, object]:
        return {"engines": {"project_evo_swarm": {"detected": True, "integrated_runtime": True}}}

    def aegis_status(self) -> dict[str, object]:
        return {"available": True, "running": True}

    def run_aegis_workflow(self, target_project: str | None = None, preview: bool = True) -> dict[str, object]:
        return {"status": "preview" if preview else "ok", "target": target_project or "d:/OpenChimera"}

    def ascension_status(self) -> dict[str, object]:
        return {"available": True, "running": True}

    def deliberate(self, prompt: str, perspectives: list[str] | None = None, max_tokens: int = 256) -> dict[str, object]:
        return {"status": "ok", "prompt": prompt, "perspectives": [{"perspective": "architect", "content": "answer"}]}

    def daily_briefing(self) -> dict[str, object]:
        return {"summary": "OpenChimera daily briefing", "priorities": []}

    def chat_completion(self, **_: object) -> dict[str, object]:
        return {
            "id": "test",
            "object": "chat.completion",
            "created": 0,
            "model": "openchimera-local",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
            "openchimera": {
                "query_type": "general",
                "prompt_strategy": "chat_guided",
                "prompt_strategies_tried": ["chat_guided"],
            },
        }

    def embeddings(self, *_: object, **__: object) -> dict[str, object]:
        return {"object": "list", "data": []}

    def start_local_models(self, _: object = None) -> dict[str, object]:
        return {"started": []}

    def stop_local_models(self, _: object = None) -> dict[str, object]:
        return {"stopped": []}

    def start_autonomy(self) -> dict[str, object]:
        return {"status": "online"}

    def stop_autonomy(self) -> dict[str, object]:
        return {"status": "offline"}

    def run_autonomy_job(self, job: str) -> dict[str, object]:
        return {"job": job, "status": "ok"}

    def build_minimind_dataset(self, force: bool = True) -> dict[str, object]:
        return {"built": True, "force": force}

    def start_minimind_server(self) -> dict[str, object]:
        return {"status": "started"}

    def stop_minimind_server(self) -> dict[str, object]:
        return {"status": "stopped"}

    def start_minimind_training(self, mode: str = "reason_sft", force_dataset: bool = False) -> dict[str, object]:
        return {"status": "running", "mode": mode, "force_dataset": force_dataset}

    def stop_minimind_training(self, job_id: str) -> dict[str, object]:
        return {"status": "stopped", "job_id": job_id}


class ApiContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = _FakeProvider()
        self.server = OpenChimeraAPIServer(
            self.provider,
            host="127.0.0.1",
            port=0,
            system_status_provider=lambda: {"provider_online": True, "supervision": {"running": True}},
        )
        started = self.server.start()
        self.assertTrue(started)
        assert self.server.server is not None
        self.base_url = f"http://127.0.0.1:{self.server.server.server_port}"

    def tearDown(self) -> None:
        self.server.stop()

    def _get(self, path: str) -> dict[str, object]:
        with request.urlopen(f"{self.base_url}{path}", timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))

    def _post(self, path: str, payload: dict[str, object]) -> dict[str, object]:
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            f"{self.base_url}{path}",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with request.urlopen(req, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))

    def test_system_status_endpoint_returns_provider_snapshot(self) -> None:
        payload = self._get("/v1/system/status")
        self.assertTrue(payload["provider_online"])
        self.assertTrue(payload["supervision"]["running"])

    def test_minimind_endpoints_round_trip(self) -> None:
        self.assertTrue(self._get("/v1/minimind/status")["available"])
        self.assertEqual(self._post("/v1/minimind/dataset/build", {"force": True})["built"], True)
        self.assertEqual(self._post("/v1/minimind/server/start", {})["status"], "started")
        self.assertEqual(self._post("/v1/minimind/training/start", {"mode": "reason_sft", "force_dataset": True})["status"], "running")
        self.assertEqual(self._post("/v1/minimind/training/stop", {"job_id": "job-1"})["job_id"], "job-1")
        self.assertEqual(self._post("/v1/minimind/server/stop", {})["status"], "stopped")

    def test_chat_completion_exposes_prompt_metadata(self) -> None:
        payload = self._post("/v1/chat/completions", {"messages": [{"role": "user", "content": "Hello"}]})
        self.assertEqual(payload["openchimera"]["query_type"], "general")
        self.assertEqual(payload["openchimera"]["prompt_strategy"], "chat_guided")
        self.assertEqual(payload["openchimera"]["prompt_strategies_tried"], ["chat_guided"])

    def test_model_registry_and_onboarding_endpoints(self) -> None:
        registry = self._get("/v1/model-registry/status")
        self.assertEqual(registry["providers"][0]["id"], "local-llama-cpp")
        refreshed = self._post("/v1/model-registry/refresh", {})
        self.assertIn("generated_at", refreshed)
        onboarding = self._get("/v1/onboarding/status")
        self.assertEqual(onboarding["suggested_local_models"][0]["id"], "phi-3.5-mini")
        self.assertEqual(onboarding["minimind_optimization_profile"]["approach"], "airllm-inspired")

    def test_integrations_status_endpoint(self) -> None:
        integrations = self._get("/v1/integrations/status")
        self.assertTrue(integrations["engines"]["project_evo_swarm"]["detected"])

    def test_advanced_capability_endpoints(self) -> None:
        self.assertTrue(self._get("/v1/aegis/status")["available"])
        self.assertTrue(self._get("/v1/ascension/status")["running"])
        self.assertEqual(self._get("/v1/briefings/daily")["summary"], "OpenChimera daily briefing")
        aegis_run = self._post("/v1/aegis/run", {"preview": True, "target_project": "d:/OpenChimera"})
        self.assertEqual(aegis_run["status"], "preview")
        ascension = self._post("/v1/ascension/deliberate", {"prompt": "What should we improve next?"})
        self.assertEqual(ascension["status"], "ok")


if __name__ == "__main__":
    unittest.main()