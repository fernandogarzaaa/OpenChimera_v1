from __future__ import annotations

import json
import logging
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from core.config import get_provider_host, get_provider_port
from core.provider import OpenChimeraProvider


LOGGER = logging.getLogger(__name__)


class _ProviderHTTPServer(ThreadingHTTPServer):
    def __init__(
        self,
        server_address: tuple[str, int],
        provider: OpenChimeraProvider,
        system_status_provider: callable | None = None,
    ):
        super().__init__(server_address, _ProviderRequestHandler)
        self.provider = provider
        self.system_status_provider = system_status_provider


class _ProviderRequestHandler(BaseHTTPRequestHandler):
    server: _ProviderHTTPServer

    def do_GET(self) -> None:
        if self.path == "/health":
            self._write_json(self.server.provider.health())
            return
        if self.path == "/v1/models":
            self._write_json(self.server.provider.list_models())
            return
        if self.path == "/v1/runtime/status":
            self._write_json(self.server.provider.local_runtime_status())
            return
        if self.path == "/v1/router/status":
            self._write_json(self.server.provider.router.status())
            return
        if self.path == "/v1/harness/status":
            self._write_json(self.server.provider.harness_port_status())
            return
        if self.path == "/v1/minimind/status":
            self._write_json(self.server.provider.minimind_status())
            return
        if self.path == "/v1/autonomy/status":
            self._write_json(self.server.provider.autonomy_status())
            return
        if self.path == "/v1/model-registry/status":
            self._write_json(self.server.provider.model_registry_status())
            return
        if self.path == "/v1/onboarding/status":
            self._write_json(self.server.provider.onboarding_status())
            return
        if self.path == "/v1/integrations/status":
            self._write_json(self.server.provider.integration_status())
            return
        if self.path == "/v1/aegis/status":
            self._write_json(self.server.provider.aegis_status())
            return
        if self.path == "/v1/ascension/status":
            self._write_json(self.server.provider.ascension_status())
            return
        if self.path == "/v1/briefings/daily":
            self._write_json(self.server.provider.daily_briefing())
            return
        if self.path == "/v1/system/status":
            if self.server.system_status_provider is None:
                self._write_json({"error": "System status unavailable"}, status=HTTPStatus.SERVICE_UNAVAILABLE)
                return
            self._write_json(self.server.system_status_provider())
            return
        self._write_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        payload = self._read_json_body()
        if payload is None:
            self._write_json({"error": "Invalid JSON body"}, status=HTTPStatus.BAD_REQUEST)
            return

        if self.path == "/v1/chat/completions":
            response = self.server.provider.chat_completion(
                messages=payload.get("messages", []),
                model=payload.get("model", "openchimera-local"),
                temperature=float(payload.get("temperature", 0.7)),
                max_tokens=int(payload.get("max_tokens") or payload.get("max_completion_tokens") or 1024),
                stream=bool(payload.get("stream", False)),
            )
            if payload.get("stream"):
                self._write_stream(response)
                return
            self._write_json(response)
            return

        if self.path == "/v1/embeddings":
            input_text = payload.get("input", "")
            if isinstance(input_text, list):
                input_text = "\n".join(str(item) for item in input_text)
            self._write_json(self.server.provider.embeddings(str(input_text), model=payload.get("model", "openchimera-local")))
            return

        if self.path == "/v1/runtime/start":
            models = payload.get("models")
            requested_models = [str(item) for item in models] if isinstance(models, list) else None
            self._write_json(self.server.provider.start_local_models(requested_models))
            return

        if self.path == "/v1/runtime/stop":
            models = payload.get("models")
            requested_models = [str(item) for item in models] if isinstance(models, list) else None
            self._write_json(self.server.provider.stop_local_models(requested_models))
            return

        if self.path == "/v1/model-registry/refresh":
            self._write_json(self.server.provider.refresh_model_registry())
            return

        if self.path == "/v1/aegis/run":
            self._write_json(
                self.server.provider.run_aegis_workflow(
                    target_project=str(payload.get("target_project") or "") or None,
                    preview=bool(payload.get("preview", True)),
                )
            )
            return

        if self.path == "/v1/ascension/deliberate":
            raw_perspectives = payload.get("perspectives")
            perspectives = [str(item) for item in raw_perspectives] if isinstance(raw_perspectives, list) else None
            self._write_json(
                self.server.provider.deliberate(
                    prompt=str(payload.get("prompt", "")),
                    perspectives=perspectives,
                    max_tokens=int(payload.get("max_tokens", 256)),
                )
            )
            return

        if self.path == "/v1/autonomy/start":
            self._write_json(self.server.provider.start_autonomy())
            return

        if self.path == "/v1/autonomy/stop":
            self._write_json(self.server.provider.stop_autonomy())
            return

        if self.path == "/v1/autonomy/run":
            self._write_json(self.server.provider.run_autonomy_job(str(payload.get("job", ""))))
            return

        if self.path == "/v1/minimind/dataset/build":
            self._write_json(self.server.provider.build_minimind_dataset(force=bool(payload.get("force", True))))
            return

        if self.path == "/v1/minimind/server/start":
            self._write_json(self.server.provider.start_minimind_server())
            return

        if self.path == "/v1/minimind/server/stop":
            self._write_json(self.server.provider.stop_minimind_server())
            return

        if self.path == "/v1/minimind/training/start":
            self._write_json(
                self.server.provider.start_minimind_training(
                    mode=str(payload.get("mode", "reason_sft")),
                    force_dataset=bool(payload.get("force_dataset", False)),
                )
            )
            return

        if self.path == "/v1/minimind/training/stop":
            self._write_json(self.server.provider.stop_minimind_training(str(payload.get("job_id", ""))))
            return

        self._write_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)

    def log_message(self, format: str, *args: Any) -> None:
        LOGGER.debug("OpenChimera API: " + format, *args)

    def _read_json_body(self) -> dict[str, Any] | None:
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return None

        raw = self.rfile.read(content_length) if content_length > 0 else b"{}"
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return None

    def _write_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _write_stream(self, response: dict[str, Any]) -> None:
        content = response.get("choices", [{}])[0].get("message", {}).get("content", "")
        words = content.split()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        for index, word in enumerate(words):
            chunk = {
                "id": response.get("id"),
                "object": "chat.completion.chunk",
                "created": response.get("created"),
                "model": response.get("model"),
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": word + (" " if index < len(words) - 1 else "")},
                        "finish_reason": None,
                    }
                ],
            }
            self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode("utf-8"))
            self.wfile.flush()
            time.sleep(0.01)

        done_chunk = {
            "id": response.get("id"),
            "object": "chat.completion.chunk",
            "created": response.get("created"),
            "model": response.get("model"),
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }
        self.wfile.write(f"data: {json.dumps(done_chunk)}\n\n".encode("utf-8"))
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


class OpenChimeraAPIServer:
    def __init__(
        self,
        provider: OpenChimeraProvider,
        host: str | None = None,
        port: int | None = None,
        system_status_provider: callable | None = None,
    ):
        self.provider = provider
        self.host = host or get_provider_host()
        self.port = port or get_provider_port()
        self.system_status_provider = system_status_provider
        self.server: _ProviderHTTPServer | None = None
        self.thread: threading.Thread | None = None

    def start(self) -> bool:
        if self.thread is not None:
            return True

        try:
            self.server = _ProviderHTTPServer(
                (self.host, self.port),
                self.provider,
                system_status_provider=self.system_status_provider,
            )
        except OSError as exc:
            LOGGER.exception("Failed to bind OpenChimera API server.")
            return False

        self.thread = threading.Thread(
            target=self.server.serve_forever,
            daemon=True,
            name="OpenChimera-API",
        )
        self.thread.start()
        LOGGER.info("OpenChimera API available at http://%s:%s", self.host, self.port)
        return True

    def stop(self) -> None:
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
        self.thread = None