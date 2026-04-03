from __future__ import annotations

import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

from sandbox.install_simulation import start_sandbox_runtime


PNG_1X1_BASE64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9s0nX7sAAAAASUVORK5CYII="


class _LocalWebFixture:
    def __init__(self) -> None:
        self._received: list[dict[str, str]] = []
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        assert self._server is not None
        return f"http://127.0.0.1:{self._server.server_port}"

    @property
    def received(self) -> list[dict[str, str]]:
        return list(self._received)

    def __enter__(self) -> "_LocalWebFixture":
        parent = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                body = b"<html><body><h1>OpenChimera Test Page</h1><p>Browser fetch ok.</p></body></html>"
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0") or 0)
                raw_body = self.rfile.read(length).decode("utf-8") if length else ""
                parent._received.append({"path": self.path, "body": raw_body})
                parsed_form = parse_qs(raw_body)
                if self.path == "/form":
                    query = parsed_form.get("q", [""])[0]
                    response = (
                        f"<html><body><p>Form submitted for {query}</p></body></html>".encode("utf-8")
                    )
                else:
                    response = b'{"status":"ok"}'
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(response)))
                self.end_headers()
                self.wfile.write(response)

            def log_message(self, format: str, *args: object) -> None:
                return

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)


class WindowsSmokeTests(unittest.TestCase):
    def test_sandbox_runtime_supports_first_boot_operator_flows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, _LocalWebFixture() as local_web:
            with start_sandbox_runtime(
                destination=temp_dir,
                env_overrides={
                    "OPENCHIMERA_API_TOKEN": "user-token",
                    "OPENCHIMERA_ADMIN_TOKEN": "admin-token",
                },
            ) as session:
                workspace_root = Path(session.prepared["workspace_root"])

                health = session.get_json("/health")
                self.assertEqual(health.status_code, 200)
                self.assertTrue(health.payload["auth_required"])
                self.assertTrue(health.headers.get("X-Request-Id"))

                readiness = session.get_json("/v1/system/readiness")
                self.assertIn(readiness.status_code, {200, 503})
                self.assertTrue(readiness.payload["auth_required"])

                unauthorized = session.get_json("/v1/system/status")
                self.assertEqual(unauthorized.status_code, 401)

                system_status = session.get_json("/v1/system/status", token="user-token")
                self.assertEqual(system_status.status_code, 200)
                self.assertIn("provider_online", system_status.payload)
                self.assertIn("deployment", system_status.payload)
                self.assertIn(system_status.payload["deployment"]["mode"], {"local", "docker", "container", "kubernetes"})

                control_plane_status = session.get_json("/v1/control-plane/status", token="user-token")
                self.assertEqual(control_plane_status.status_code, 200)
                self.assertIn("deployment", control_plane_status.payload)
                self.assertIn("runtime_profile", control_plane_status.payload["deployment"])

                auth_status = session.get_json("/v1/auth/status", token="user-token")
                self.assertEqual(auth_status.status_code, 200)
                self.assertTrue(auth_status.payload["enabled"])
                self.assertTrue(auth_status.payload["admin_separate_from_user"])

                applied = session.post_json(
                    "/v1/onboarding/apply",
                    {
                        "preferred_local_model": "phi-3.5-mini",
                        "enabled_provider_ids": ["openchimera-gateway", "local-llama-cpp", "minimind", "openai"],
                        "preferred_cloud_provider": "openai",
                        "provider_credentials": {"openai": {"OPENAI_API_KEY": "sk-test-123456"}},
                        "channel_subscription": {
                            "id": "ops-webhook",
                            "channel": "webhook",
                            "endpoint": f"{local_web.base_url}/webhook",
                            "topics": ["system/briefing/daily", "system/autonomy/job"],
                        },
                    },
                    token="admin-token",
                )
                self.assertEqual(applied.status_code, 200)
                self.assertTrue(applied.payload["completed"])

                onboarding_status = session.get_json("/v1/onboarding/status", token="user-token")
                self.assertEqual(onboarding_status.status_code, 200)
                self.assertTrue(onboarding_status.payload["completed"])

                provider_activation = session.post_json(
                    "/v1/providers/configure",
                    {
                        "enabled_provider_ids": ["openchimera-gateway", "local-llama-cpp", "minimind", "openai"],
                        "preferred_cloud_provider": "openai",
                    },
                    token="admin-token",
                )
                self.assertEqual(provider_activation.status_code, 200)
                self.assertEqual(provider_activation.payload["preferred_cloud_provider"], "openai")

                registry = session.post_json("/v1/model-registry/refresh", {}, token="admin-token")
                self.assertEqual(registry.status_code, 200)
                self.assertIn("generated_at", registry.payload)

                credentials = session.get_json("/v1/credentials/status", token="user-token")
                self.assertEqual(credentials.status_code, 200)
                self.assertTrue(credentials.payload["providers"]["openai"]["configured"])

                channel_status = session.get_json("/v1/channels/status", token="user-token")
                self.assertEqual(channel_status.status_code, 200)
                self.assertEqual(channel_status.payload["counts"]["total"], 1)

                briefing = session.post_json("/v1/channels/dispatch/daily-briefing", {}, token="admin-token")
                self.assertEqual(briefing.status_code, 200)
                self.assertEqual(briefing.payload["delivery"]["delivery_count"], 1)

                browser_fetch = session.post_json(
                    "/v1/browser/fetch",
                    {"url": f"{local_web.base_url}/page", "max_chars": 800},
                    token="admin-token",
                )
                self.assertEqual(browser_fetch.status_code, 200)
                self.assertEqual(browser_fetch.payload["action"], "fetch")
                self.assertIn("OpenChimera Test Page", browser_fetch.payload["text_preview"])

                browser_submit = session.post_json(
                    "/v1/browser/submit-form",
                    {"url": f"{local_web.base_url}/form", "form_data": {"q": "openchimera"}, "method": "POST"},
                    token="admin-token",
                )
                self.assertEqual(browser_submit.status_code, 200)
                self.assertEqual(browser_submit.payload["action"], "submit_form")
                self.assertIn("Form submitted for openchimera", browser_submit.payload["text_preview"])

                media_status = session.get_json("/v1/media/status", token="user-token")
                self.assertEqual(media_status.status_code, 200)
                self.assertTrue(media_status.payload["enabled"])

                transcription = session.post_json(
                    "/v1/media/transcribe",
                    {"audio_text": "OpenChimera smoke test", "language": "en"},
                    token="admin-token",
                )
                self.assertEqual(transcription.status_code, 200)
                self.assertEqual(transcription.payload["transcript"], "OpenChimera smoke test")

                image_understanding = session.post_json(
                    "/v1/media/understand-image",
                    {"prompt": "Describe this image", "image_base64": PNG_1X1_BASE64},
                    token="admin-token",
                )
                if media_status.payload["backends"]["understand_image"]["available"]:
                    self.assertIn(image_understanding.status_code, {200, 502})
                    if image_understanding.status_code == 200:
                        self.assertEqual(image_understanding.payload["metadata"]["mime_type"], "image/png")
                    else:
                        self.assertIn("backend", image_understanding.payload["error"].lower())
                else:
                    self.assertEqual(image_understanding.status_code, 503)
                    self.assertIn("unavailable", image_understanding.payload["error"].lower())

                created_job = session.post_json(
                    "/v1/jobs/create",
                    {"job_type": "autonomy", "payload": {"job": "refresh_harness_dataset"}, "max_attempts": 2},
                    token="admin-token",
                    timeout=10.0,
                )
                self.assertEqual(created_job.status_code, 200)
                job_id = created_job.payload["job_id"]

                final_job_status = None
                deadline = time.time() + 20.0
                while time.time() < deadline:
                    polled = session.get_json("/v1/jobs/status", token="user-token")
                    self.assertEqual(polled.status_code, 200)
                    jobs = polled.payload.get("jobs", [])
                    final_job_status = next((item for item in jobs if item.get("job_id") == job_id), None)
                    if final_job_status and final_job_status.get("status") in {"completed", "failed"}:
                        break
                    time.sleep(0.25)

                self.assertIsNotNone(final_job_status)
                self.assertEqual(final_job_status["status"], "completed")

                metrics = session.get_json("/v1/system/metrics", token="user-token")
                self.assertEqual(metrics.status_code, 200)
                self.assertGreater(metrics.payload["http"]["total_requests"], 0)

                self.assertTrue(local_web.received)
                self.assertTrue(any(item["path"] == "/webhook" for item in local_web.received))
                self.assertTrue(any(item["path"] == "/form" for item in local_web.received))

                self.assertTrue((workspace_root / "data" / "browser_sessions.json").exists())
                self.assertTrue((workspace_root / "data" / "media_sessions.json").exists())
                self.assertTrue((workspace_root / "data" / "openchimera.db").exists())


if __name__ == "__main__":
    unittest.main()