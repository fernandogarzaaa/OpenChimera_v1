from __future__ import annotations

import base64
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib import error, request

from core.config import ROOT
from core.credential_store import CredentialStore
from core.transactions import atomic_write_json


class MultimodalService:
    def __init__(
        self,
        artifact_root: Path | None = None,
        history_path: Path | None = None,
        credential_store: CredentialStore | None = None,
    ):
        self.artifact_root = artifact_root or (ROOT / "sandbox" / "artifacts" / "media")
        self.history_path = history_path or (ROOT / "data" / "media_sessions.json")
        self.credential_store = credential_store or CredentialStore()
        self._voice_cache: list[str] | None = None

    def status(self) -> dict[str, Any]:
        history = self._load_history()
        backends = self._build_backend_status()
        supported_actions = [name for name, details in backends.items() if details.get("available")]
        unavailable_actions = {
            name: str(details.get("reason", "Unavailable"))
            for name, details in backends.items()
            if not details.get("available")
        }
        return {
            "enabled": bool(supported_actions),
            "artifact_root": str(self.artifact_root),
            "history_path": str(self.history_path),
            "recent_sessions": history[-10:],
            "supported_actions": supported_actions,
            "supported_voices": list(backends.get("synthesize", {}).get("voices", [])),
            "supported_image_formats": ["png", "jpeg", "webp"] if backends.get("understand_image", {}).get("available") else [],
            "unavailable_actions": unavailable_actions,
            "backends": backends,
        }

    def transcribe(self, audio_text: str = "", audio_base64: str = "", language: str = "en") -> dict[str, Any]:
        normalized_text = self._normalize_text(audio_text)
        decoded_size = 0
        source = "text-input"
        backend = "passthrough"
        if audio_base64:
            decoded = self._decode_base64(audio_base64)
            decoded_size = len(decoded)
            normalized_text = self._transcribe_audio_bytes(decoded)
            source = "audio-base64"
            backend = "windows-system-speech"
        if not normalized_text:
            raise ValueError("Transcription requires audio_text or audio_base64")

        artifact = self._write_json_artifact(
            "transcribe",
            {
                "transcript": normalized_text,
                "language": language,
                "audio_bytes": decoded_size,
                "source": source,
                "backend": backend,
            },
        )
        record = {
            "action": "transcribe",
            "language": language,
            "transcript": normalized_text,
            "source": source,
            "backend": backend,
            "artifact": artifact,
            "recorded_at": int(time.time()),
        }
        self._append_history(record)
        return record

    def synthesize(self, text: str, voice: str = "openchimera-default", audio_format: str = "wav", sample_rate_hz: int = 16000) -> dict[str, Any]:
        normalized_text = self._normalize_text(text)
        if not normalized_text:
            raise ValueError("Synthesis requires non-empty text")
        if audio_format.lower() != "wav":
            raise ValueError("Only wav output is supported")
        if not self._local_speech_available():
            raise NotImplementedError("Speech synthesis is unavailable. Windows System.Speech is required.")

        self.artifact_root.mkdir(parents=True, exist_ok=True)
        artifact_path = self.artifact_root / f"synthesize-{int(time.time() * 1000)}.wav"
        resolved_voice = self._resolve_voice_name(voice)
        duration_seconds = self._synthesize_to_wave(artifact_path, normalized_text, resolved_voice)
        record = {
            "action": "synthesize",
            "voice": resolved_voice,
            "format": "wav",
            "character_count": len(normalized_text),
            "duration_seconds": duration_seconds,
            "sample_rate_hz": sample_rate_hz,
            "backend": "windows-system-speech",
            "artifact": {"path": str(artifact_path)},
            "recorded_at": int(time.time()),
        }
        self._append_history(record)
        return record

    def understand_image(self, prompt: str = "", image_path: str = "", image_base64: str = "") -> dict[str, Any]:
        if not image_path and not image_base64:
            raise ValueError("Image understanding requires image_path or image_base64")

        image_bytes = b""
        source = "base64"
        resolved_path = ""
        if image_path:
            path = Path(image_path)
            image_bytes = path.read_bytes()
            resolved_path = str(path)
            source = "path"
        else:
            image_bytes = self._decode_base64(image_base64)

        metadata = self._image_metadata(image_bytes)
        normalized_prompt = self._normalize_text(prompt) or "Describe the image."
        provider = self._select_vision_provider()
        if provider is None:
            raise NotImplementedError(
                "Image understanding is unavailable. Configure OPENAI_API_KEY or OPENROUTER_API_KEY for a real vision backend."
            )
        summary, provider_name, model_name = self._understand_image_with_provider(provider, normalized_prompt, image_bytes, metadata)
        artifact = self._write_json_artifact(
            "understand_image",
            {
                "prompt": normalized_prompt,
                "source": source,
                "resolved_path": resolved_path,
                "metadata": metadata,
                "summary": summary,
                "provider": provider_name,
                "model": model_name,
            },
        )
        record = {
            "action": "understand_image",
            "prompt": normalized_prompt,
            "summary": summary,
            "metadata": metadata,
            "provider": provider_name,
            "model": model_name,
            "artifact": artifact,
            "recorded_at": int(time.time()),
        }
        self._append_history(record)
        return record

    def generate_image(self, prompt: str, width: int = 1024, height: int = 1024, style: str = "schematic") -> dict[str, Any]:
        normalized_prompt = self._normalize_text(prompt)
        if not normalized_prompt:
            raise ValueError("Image generation requires a prompt")
        width = max(256, min(int(width), 2048))
        height = max(256, min(int(height), 2048))
        provider = self._select_image_generation_provider()
        if provider is None:
            raise NotImplementedError(
                "Image generation is unavailable. Configure OPENAI_API_KEY for a real image generation backend."
            )

        self.artifact_root.mkdir(parents=True, exist_ok=True)
        artifact_path = self.artifact_root / f"generate-image-{int(time.time() * 1000)}.png"
        provider_name, model_name = self._generate_image_with_provider(provider, normalized_prompt, width, height, style, artifact_path)
        record = {
            "action": "generate_image",
            "prompt": normalized_prompt,
            "style": style,
            "width": width,
            "height": height,
            "format": "png",
            "provider": provider_name,
            "model": model_name,
            "artifact": {"path": str(artifact_path)},
            "recorded_at": int(time.time()),
        }
        self._append_history(record)
        return record

    def _normalize_text(self, text: str) -> str:
        return " ".join(str(text or "").strip().split())

    def _decode_base64(self, value: str) -> bytes:
        cleaned = str(value).strip()
        if "," in cleaned and cleaned.startswith("data:"):
            cleaned = cleaned.split(",", 1)[1]
        return base64.b64decode(cleaned, validate=False)

    def _image_metadata(self, image_bytes: bytes) -> dict[str, Any]:
        if image_bytes.startswith(b"\x89PNG\r\n\x1a\n") and len(image_bytes) >= 24:
            width = int.from_bytes(image_bytes[16:20], "big")
            height = int.from_bytes(image_bytes[20:24], "big")
            return {"mime_type": "image/png", "width": width, "height": height, "byte_size": len(image_bytes)}
        if image_bytes.startswith(b"\xff\xd8"):
            return {"mime_type": "image/jpeg", "width": 0, "height": 0, "byte_size": len(image_bytes)}
        if image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP":
            return {"mime_type": "image/webp", "width": 0, "height": 0, "byte_size": len(image_bytes)}
        return {"mime_type": "application/octet-stream", "width": 0, "height": 0, "byte_size": len(image_bytes)}

    def _build_backend_status(self) -> dict[str, dict[str, Any]]:
        local_speech = self._local_speech_available()
        voices = self._installed_voices() if local_speech else []
        vision_provider = self._select_vision_provider()
        image_provider = self._select_image_generation_provider()
        return {
            "transcribe": {
                "available": local_speech,
                "backend": "windows-system-speech" if local_speech else None,
                "reason": None if local_speech else "Windows System.Speech recognition is not available.",
            },
            "synthesize": {
                "available": local_speech,
                "backend": "windows-system-speech" if local_speech else None,
                "voices": ["openchimera-default", "operator", "briefing", *voices] if local_speech else [],
                "reason": None if local_speech else "Windows System.Speech synthesis is not available.",
            },
            "understand_image": {
                "available": vision_provider is not None,
                "backend": None if vision_provider is None else vision_provider["provider"],
                "reason": None if vision_provider is not None else "Configure OPENAI_API_KEY or OPENROUTER_API_KEY for a real vision backend.",
            },
            "generate_image": {
                "available": image_provider is not None,
                "backend": None if image_provider is None else image_provider["provider"],
                "reason": None if image_provider is not None else "Configure OPENAI_API_KEY for a real image generation backend.",
            },
        }

    def _local_speech_available(self) -> bool:
        if os.name != "nt":
            return False
        try:
            self._run_powershell("Add-Type -AssemblyName System.Speech; 'ok'")
        except RuntimeError:
            return False
        return True

    def _installed_voices(self) -> list[str]:
        if self._voice_cache is not None:
            return list(self._voice_cache)
        if not self._local_speech_available():
            self._voice_cache = []
            return []
        raw = self._run_powershell(
            "Add-Type -AssemblyName System.Speech; "
            "$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            "$names = @($synth.GetInstalledVoices() | ForEach-Object { $_.VoiceInfo.Name }); "
            "$synth.Dispose(); $names | ConvertTo-Json -Compress"
        )
        if not raw:
            self._voice_cache = []
            return []
        parsed = json.loads(raw)
        if isinstance(parsed, str):
            self._voice_cache = [parsed]
        elif isinstance(parsed, list):
            self._voice_cache = [str(item) for item in parsed]
        else:
            self._voice_cache = []
        return list(self._voice_cache)

    def _resolve_voice_name(self, requested_voice: str) -> str:
        voices = self._installed_voices()
        if not voices:
            raise NotImplementedError("Speech synthesis is unavailable. No Windows voices are installed.")
        normalized = self._normalize_text(requested_voice).lower()
        aliases = {
            "openchimera-default": voices[0],
            "operator": next((voice for voice in voices if "david" in voice.lower()), voices[0]),
            "briefing": next((voice for voice in voices if "zira" in voice.lower()), voices[0]),
        }
        if normalized in aliases:
            return aliases[normalized]
        for voice in voices:
            if voice.lower() == normalized:
                return voice
        raise ValueError(f"Unsupported voice '{requested_voice}'. Available voices: {', '.join(voices)}")

    def _synthesize_to_wave(self, artifact_path: Path, text: str, voice: str) -> float:
        started_at = time.perf_counter()
        escaped_text = self._powershell_literal(text)
        escaped_voice = self._powershell_literal(voice)
        escaped_path = self._powershell_literal(str(artifact_path))
        self._run_powershell(
            "$ErrorActionPreference='Stop'; "
            "Add-Type -AssemblyName System.Speech; "
            f"$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer; $synth.SelectVoice('{escaped_voice}'); "
            f"$synth.SetOutputToWaveFile('{escaped_path}'); $synth.Speak('{escaped_text}'); $synth.Dispose()"
        )
        return round(time.perf_counter() - started_at, 3)

    def _transcribe_audio_bytes(self, audio_bytes: bytes) -> str:
        if not self._local_speech_available():
            raise NotImplementedError("Speech transcription is unavailable. Windows System.Speech recognition is required.")
        if len(audio_bytes) < 12 or audio_bytes[:4] != b"RIFF" or audio_bytes[8:12] != b"WAVE":
            raise ValueError("Speech transcription currently supports PCM WAV input only.")
        with tempfile.NamedTemporaryFile(prefix="openchimera-stt-", suffix=".wav", delete=False) as temp_audio:
            temp_audio.write(audio_bytes)
            temp_path = Path(temp_audio.name)
        try:
            escaped_path = self._powershell_literal(str(temp_path))
            transcript = self._run_powershell(
                "$ErrorActionPreference='Stop'; "
                "Add-Type -AssemblyName System.Speech; "
                "$engine = New-Object System.Speech.Recognition.SpeechRecognitionEngine; "
                "$engine.LoadGrammar((New-Object System.Speech.Recognition.DictationGrammar)); "
                f"$engine.SetInputToWaveFile('{escaped_path}'); "
                "$result = $engine.Recognize(); if ($null -eq $result) { '' } else { $result.Text }"
            )
        finally:
            temp_path.unlink(missing_ok=True)
        normalized = self._normalize_text(transcript)
        if not normalized:
            raise RuntimeError("Speech recognition completed without a usable transcription.")
        return normalized

    def _select_vision_provider(self) -> dict[str, str] | None:
        openai_key = self._provider_secret("openai", ["OPENAI_API_KEY"])
        if openai_key:
            return {
                "provider": "openai",
                "api_key": openai_key,
                "model": os.getenv("OPENCHIMERA_VISION_MODEL", "gpt-4.1-mini"),
                "url": "https://api.openai.com/v1/chat/completions",
            }
        openrouter_key = self._provider_secret("openrouter", ["OPENROUTER_API_KEY"])
        if openrouter_key:
            return {
                "provider": "openrouter",
                "api_key": openrouter_key,
                "model": os.getenv("OPENCHIMERA_OPENROUTER_VISION_MODEL", "openai/gpt-4o-mini"),
                "url": "https://openrouter.ai/api/v1/chat/completions",
            }
        return None

    def _select_image_generation_provider(self) -> dict[str, str] | None:
        openai_key = self._provider_secret("openai", ["OPENAI_API_KEY"])
        if not openai_key:
            return None
        return {
            "provider": "openai",
            "api_key": openai_key,
            "model": os.getenv("OPENCHIMERA_IMAGE_MODEL", "gpt-image-1"),
            "url": "https://api.openai.com/v1/images/generations",
        }

    def _understand_image_with_provider(
        self,
        provider: dict[str, str],
        prompt: str,
        image_bytes: bytes,
        metadata: dict[str, Any],
    ) -> tuple[str, str, str]:
        data_url = self._to_data_url(image_bytes, str(metadata.get("mime_type") or "application/octet-stream"))
        payload = {
            "model": provider["model"],
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ],
        }
        headers = {"Authorization": f"Bearer {provider['api_key']}"}
        if provider["provider"] == "openrouter":
            headers["HTTP-Referer"] = "https://openchimera.local"
            headers["X-Title"] = "OpenChimera"
        response_payload = self._post_json(provider["url"], payload, headers)
        choices = response_payload.get("choices", []) if isinstance(response_payload, dict) else []
        message = choices[0].get("message", {}) if choices else {}
        content = message.get("content", "")
        if isinstance(content, list):
            text_parts = [str(item.get("text", "")) for item in content if isinstance(item, dict)]
            content = "\n".join(part for part in text_parts if part)
        summary = self._normalize_text(str(content))
        if not summary:
            raise RuntimeError(f"{provider['provider']} vision backend returned an empty response.")
        return summary, provider["provider"], provider["model"]

    def _generate_image_with_provider(
        self,
        provider: dict[str, str],
        prompt: str,
        width: int,
        height: int,
        style: str,
        artifact_path: Path,
    ) -> tuple[str, str]:
        size = self._openai_image_size(width, height)
        payload = {
            "model": provider["model"],
            "prompt": f"{prompt}\nStyle guidance: {style}",
            "size": size,
            "response_format": "b64_json",
        }
        response_payload = self._post_json(
            provider["url"],
            payload,
            {"Authorization": f"Bearer {provider['api_key']}"},
        )
        data = response_payload.get("data", []) if isinstance(response_payload, dict) else []
        if not data or not isinstance(data[0], dict) or not data[0].get("b64_json"):
            raise RuntimeError("OpenAI image generation returned no image payload.")
        image_bytes = base64.b64decode(str(data[0]["b64_json"]))
        artifact_path.write_bytes(image_bytes)
        return provider["provider"], provider["model"]

    def _provider_secret(self, provider_id: str, candidate_keys: list[str]) -> str:
        for key in candidate_keys:
            value = os.getenv(key, "").strip()
            if value:
                return value
        stored = self.credential_store.get_provider_credentials(provider_id)
        for key in candidate_keys:
            value = str(stored.get(key, "")).strip()
            if value:
                return value
        return ""

    def _post_json(self, url: str, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        request_headers = {"Content-Type": "application/json", **headers}
        req = request.Request(url, data=body, headers=request_headers, method="POST")
        try:
            with request.urlopen(req, timeout=90) as response:
                return json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"Media backend request failed with HTTP {exc.code}: {detail[:400]}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"Media backend request failed: {exc.reason}") from exc

    def _to_data_url(self, payload: bytes, mime_type: str) -> str:
        encoded = base64.b64encode(payload).decode("ascii")
        return f"data:{mime_type};base64,{encoded}"

    def _openai_image_size(self, width: int, height: int) -> str:
        ratio = width / max(height, 1)
        if ratio >= 1.2:
            return "1792x1024"
        if ratio <= 0.84:
            return "1024x1792"
        return "1024x1024"

    def _run_powershell(self, script: str) -> str:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
        if result.returncode != 0:
            error_message = (result.stderr or result.stdout).strip() or f"powershell exited with {result.returncode}"
            raise RuntimeError(error_message)
        return (result.stdout or "").strip()

    def _powershell_literal(self, value: str) -> str:
        return str(value).replace("'", "''")

    def _write_json_artifact(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        artifact_path = self.artifact_root / f"{action}-{int(time.time() * 1000)}.json"
        atomic_write_json(artifact_path, {"action": action, "payload": payload, "created_at": int(time.time())})
        return {"path": str(artifact_path)}

    def _load_history(self) -> list[dict[str, Any]]:
        if not self.history_path.exists():
            return []
        try:
            raw = json.loads(self.history_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
        return raw if isinstance(raw, list) else []

    def _append_history(self, record: dict[str, Any]) -> None:
        history = self._load_history()
        history.append(record)
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self.history_path, history[-50:])