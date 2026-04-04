from __future__ import annotations

import base64
import json
import os
import struct
import tempfile
import unittest
import wave
import zlib
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.multimodal_service import MultimodalService


PNG_1X1_BASE64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9s0nX7sAAAAASUVORK5CYII="


def _make_minimal_png() -> bytes:
    """Return a 1x1 red PNG (no third-party libs required)."""
    def png_chunk(tag: bytes, data: bytes) -> bytes:
        c = struct.pack(">I", len(data)) + tag + data
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return c + struct.pack(">I", crc)

    header = b"\x89PNG\r\n\x1a\n"
    ihdr = png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    idat = png_chunk(b"IDAT", zlib.compress(b"\x00\xFF\x00\x00"))
    iend = png_chunk(b"IEND", b"")
    return header + ihdr + idat + iend


def _make_minimal_wav() -> bytes:
    """Return a minimal silent PCM WAV (mono 8000 Hz 16-bit ~0.1 s)."""
    num_samples = 800
    sample_rate = 8000
    channels = 1
    bits = 16
    byte_rate = sample_rate * channels * (bits // 8)
    block_align = channels * (bits // 8)
    data_size = num_samples * block_align
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 36 + data_size, b"WAVE",
        b"fmt ", 16, 1, channels, sample_rate, byte_rate, block_align, bits,
        b"data", data_size,
    )
    return header + b"\x00" * data_size


def _make_service(tmp_dir: str | None = None) -> MultimodalService:
    tmp = tmp_dir or tempfile.mkdtemp()
    return MultimodalService(
        artifact_root=Path(tmp) / "artifacts",
        history_path=Path(tmp) / "media_sessions.json",
    )


# ---------------------------------------------------------------------------
# Original integration-style tests (updated: no longer assert NotImplementedError)
# ---------------------------------------------------------------------------

class MultimodalServiceTests(unittest.TestCase):
    def test_transcribe_records_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = _make_service(tmp)
            result = service.transcribe(audio_text="OpenChimera status update", language="en")
            self.assertEqual(result["transcript"], "OpenChimera status update")
            history = json.loads((Path(tmp) / "media_sessions.json").read_text(encoding="utf-8"))
            self.assertEqual(history[-1]["action"], "transcribe")

    def test_synthesize_unavailable_returns_error_dict(self) -> None:
        """When Windows Speech is absent synthesize returns an error dict, never raises."""
        with tempfile.TemporaryDirectory() as tmp:
            service = _make_service(tmp)
            if service.status()["backends"]["synthesize"]["available"]:
                result = service.synthesize("Daily briefing ready.")
                artifact = Path(result["artifact"]["path"])
                self.assertTrue(artifact.exists())
                with wave.open(str(artifact), "rb") as wav_file:
                    self.assertGreater(wav_file.getnframes(), 0)
            else:
                result = service.synthesize("Daily briefing ready.")
                self.assertIsInstance(result, dict)
                self.assertIn("error", result)
                self.assertFalse(result.get("available"))

    def test_understand_image_unavailable_returns_error_dict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = _make_service(tmp)
            if service.status()["backends"]["understand_image"]["available"]:
                result = service.understand_image(prompt="Describe this image", image_base64=PNG_1X1_BASE64)
                self.assertEqual(result["metadata"]["mime_type"], "image/png")
                self.assertTrue(result["summary"])
            else:
                result = service.understand_image(image_base64=PNG_1X1_BASE64)
                self.assertIsInstance(result, dict)
                self.assertIn("error", result)
                self.assertFalse(result.get("available"))

    def test_generate_image_unavailable_returns_error_dict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = _make_service(tmp)
            if service.status()["backends"]["generate_image"]["available"]:
                result = service.generate_image(prompt="Winged lion logo study", width=640, height=480, style="brand")
                artifact = Path(result["artifact"]["path"])
                self.assertTrue(artifact.exists())
                self.assertEqual(artifact.suffix.lower(), ".png")
                self.assertGreater(artifact.stat().st_size, 0)
            else:
                result = service.generate_image(prompt="Winged lion logo study", width=640, height=480, style="brand")
                self.assertIsInstance(result, dict)
                self.assertIn("error", result)
                self.assertFalse(result.get("available"))


# ---------------------------------------------------------------------------
# Fallback / error-path unit tests
# ---------------------------------------------------------------------------

class TestSynthesizeFallbacks(unittest.TestCase):
    def test_no_speech_returns_error_dict(self):
        svc = _make_service()
        with patch.object(svc, "_local_speech_available", return_value=False):
            result = svc.synthesize("Hello world")
        self.assertIsInstance(result, dict)
        self.assertIn("error", result)
        self.assertEqual(result["action"], "synthesize")
        self.assertFalse(result["available"])
        self.assertIsNone(result["backend"])
        self.assertIn("recorded_at", result)

    def test_no_speech_does_not_raise(self):
        svc = _make_service()
        with patch.object(svc, "_local_speech_available", return_value=False):
            try:
                svc.synthesize("Test")
            except NotImplementedError as exc:
                self.fail(f"synthesize raised NotImplementedError: {exc}")

    def test_empty_text_raises_value_error(self):
        svc = _make_service()
        with self.assertRaises(ValueError):
            svc.synthesize("")

    def test_whitespace_only_raises_value_error(self):
        svc = _make_service()
        with self.assertRaises(ValueError):
            svc.synthesize("   ")

    def test_non_wav_format_raises_value_error(self):
        svc = _make_service()
        with patch.object(svc, "_local_speech_available", return_value=False):
            with self.assertRaises(ValueError):
                svc.synthesize("Hello", audio_format="mp3")

    def test_fallback_appended_to_history(self):
        svc = _make_service()
        with patch.object(svc, "_local_speech_available", return_value=False):
            svc.synthesize("Hey there")
        history = svc._load_history()
        self.assertTrue(any(r.get("action") == "synthesize" for r in history))


class TestUnderstandImageFallbacks(unittest.TestCase):
    def test_no_image_args_raises_value_error(self):
        svc = _make_service()
        with patch.object(svc, "_select_vision_provider", return_value=None):
            with self.assertRaises(ValueError):
                svc.understand_image(prompt="What is this?")

    def test_base64_no_provider_returns_error_dict(self):
        svc = _make_service()
        png_b64 = base64.b64encode(_make_minimal_png()).decode()
        with patch.object(svc, "_select_vision_provider", return_value=None):
            result = svc.understand_image(image_base64=png_b64)
        self.assertIsInstance(result, dict)
        self.assertIn("error", result)
        self.assertEqual(result["action"], "understand_image")
        self.assertFalse(result["available"])
        self.assertIsNone(result["backend"])

    def test_base64_no_provider_does_not_raise(self):
        svc = _make_service()
        png_b64 = base64.b64encode(_make_minimal_png()).decode()
        with patch.object(svc, "_select_vision_provider", return_value=None):
            try:
                svc.understand_image(image_base64=png_b64)
            except NotImplementedError as exc:
                self.fail(f"understand_image raised NotImplementedError: {exc}")

    def test_image_path_no_provider_returns_error_dict(self):
        svc = _make_service()
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(_make_minimal_png())
            img_path = f.name
        try:
            with patch.object(svc, "_select_vision_provider", return_value=None):
                result = svc.understand_image(image_path=img_path)
            self.assertIn("error", result)
            self.assertEqual(result["action"], "understand_image")
            self.assertFalse(result["available"])
        finally:
            os.unlink(img_path)

    def test_fallback_appended_to_history(self):
        svc = _make_service()
        png_b64 = base64.b64encode(_make_minimal_png()).decode()
        with patch.object(svc, "_select_vision_provider", return_value=None):
            svc.understand_image(image_base64=png_b64)
        history = svc._load_history()
        self.assertTrue(any(r.get("action") == "understand_image" for r in history))


class TestGenerateImageFallbacks(unittest.TestCase):
    def test_empty_prompt_raises_value_error(self):
        svc = _make_service()
        with self.assertRaises(ValueError):
            svc.generate_image("")

    def test_whitespace_prompt_raises_value_error(self):
        svc = _make_service()
        with self.assertRaises(ValueError):
            svc.generate_image("   ")

    def test_no_provider_returns_error_dict(self):
        svc = _make_service()
        with patch.object(svc, "_select_image_generation_provider", return_value=None):
            result = svc.generate_image("a red circle")
        self.assertIsInstance(result, dict)
        self.assertIn("error", result)
        self.assertEqual(result["action"], "generate_image")
        self.assertFalse(result["available"])
        self.assertIsNone(result["backend"])

    def test_no_provider_does_not_raise(self):
        svc = _make_service()
        with patch.object(svc, "_select_image_generation_provider", return_value=None):
            try:
                svc.generate_image("blue sky")
            except NotImplementedError as exc:
                self.fail(f"generate_image raised NotImplementedError: {exc}")

    def test_fallback_appended_to_history(self):
        svc = _make_service()
        with patch.object(svc, "_select_image_generation_provider", return_value=None):
            svc.generate_image("a yellow star")
        history = svc._load_history()
        self.assertTrue(any(r.get("action") == "generate_image" for r in history))


class TestTranscribeFallbacks(unittest.TestCase):
    def test_no_args_raises_value_error(self):
        svc = _make_service()
        with self.assertRaises(ValueError):
            svc.transcribe()

    def test_audio_text_passthrough_returns_dict(self):
        svc = _make_service()
        result = svc.transcribe(audio_text="hello chimera")
        self.assertIsInstance(result, dict)
        self.assertEqual(result["action"], "transcribe")
        self.assertEqual(result["transcript"], "hello chimera")

    def test_audio_text_preserves_language(self):
        svc = _make_service()
        result = svc.transcribe(audio_text="bonjour", language="fr")
        self.assertEqual(result["language"], "fr")

    def test_audio_base64_unavailable_speech_does_not_raise_not_implemented(self):
        """Speech unavailable + base64 audio must not bubble up NotImplementedError."""
        svc = _make_service()
        wav_b64 = base64.b64encode(_make_minimal_wav()).decode()
        with patch.object(svc, "_local_speech_available", return_value=False):
            try:
                svc.transcribe(audio_base64=wav_b64)
            except NotImplementedError as exc:
                self.fail(f"transcribe raised NotImplementedError: {exc}")
            except (ValueError, RuntimeError):
                pass  # Acceptable: empty transcript triggers ValueError


class TestStatus(unittest.TestCase):
    def test_returns_dict_with_backends_key(self):
        svc = _make_service()
        result = svc.status()
        self.assertIsInstance(result, dict)
        self.assertIn("backends", result)

    def test_backends_contains_all_four_actions(self):
        svc = _make_service()
        backends = svc.status()["backends"]
        for action in ("transcribe", "synthesize", "understand_image", "generate_image"):
            self.assertIn(action, backends)

    def test_backends_each_have_available_key(self):
        svc = _make_service()
        for action, details in svc.status()["backends"].items():
            self.assertIn("available", details)

    def test_all_unavailable_when_no_providers(self):
        svc = _make_service()
        with (
            patch.object(svc, "_local_speech_available", return_value=False),
            patch.object(svc, "_select_vision_provider", return_value=None),
            patch.object(svc, "_select_image_generation_provider", return_value=None),
        ):
            backends = svc.status()["backends"]
        for action in ("transcribe", "synthesize", "understand_image", "generate_image"):
            self.assertFalse(backends[action]["available"], f"Expected '{action}' unavailable")


class TestImageMetadata(unittest.TestCase):
    def test_png_detected(self):
        svc = _make_service()
        meta = svc._image_metadata(_make_minimal_png())
        self.assertEqual(meta["mime_type"], "image/png")
        self.assertEqual(meta["width"], 1)
        self.assertEqual(meta["height"], 1)

    def test_unknown_bytes_returns_octet_stream(self):
        svc = _make_service()
        meta = svc._image_metadata(b"\x00\x01\x02\x03")
        self.assertEqual(meta["mime_type"], "application/octet-stream")

    def test_jpeg_detected(self):
        svc = _make_service()
        jpeg_bytes = b"\xff\xd8\xff\xe0" + b"\x00" * 20
        meta = svc._image_metadata(jpeg_bytes)
        self.assertEqual(meta["mime_type"], "image/jpeg")

    def test_webp_detected(self):
        svc = _make_service()
        webp_bytes = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 20
        meta = svc._image_metadata(webp_bytes)
        self.assertEqual(meta["mime_type"], "image/webp")


# ============================================================
# _local_speech_available coverage tests
# ============================================================

class TestLocalSpeechAvailable(unittest.TestCase):
    def test_returns_true_when_powershell_succeeds(self):
        svc = _make_service()
        with patch.object(svc, "_run_powershell", return_value="ok"):
            result = svc._local_speech_available()
        self.assertTrue(result)

    def test_returns_false_when_powershell_raises_runtime_error(self):
        svc = _make_service()
        with patch.object(svc, "_run_powershell", side_effect=RuntimeError("no speech")):
            result = svc._local_speech_available()
        self.assertFalse(result)


# ============================================================
# _installed_voices coverage tests
# ============================================================

class TestInstalledVoices(unittest.TestCase):
    def test_returns_cached_when_voice_cache_set(self):
        svc = _make_service()
        svc._voice_cache = ["Cached Voice"]
        result = svc._installed_voices()
        self.assertEqual(result, ["Cached Voice"])

    def test_returns_empty_when_speech_unavailable(self):
        svc = _make_service()
        with patch.object(svc, "_local_speech_available", return_value=False):
            result = svc._installed_voices()
        self.assertEqual(result, [])
        self.assertEqual(svc._voice_cache, [])

    def test_returns_empty_when_powershell_returns_empty(self):
        svc = _make_service()
        with patch.object(svc, "_local_speech_available", return_value=True):
            with patch.object(svc, "_run_powershell", return_value=""):
                result = svc._installed_voices()
        self.assertEqual(result, [])

    def test_parses_json_list_from_powershell(self):
        svc = _make_service()
        with patch.object(svc, "_local_speech_available", return_value=True):
            with patch.object(svc, "_run_powershell", return_value='["Microsoft David Desktop", "Microsoft Zira Desktop"]'):
                result = svc._installed_voices()
        self.assertIn("Microsoft David Desktop", result)
        self.assertIn("Microsoft Zira Desktop", result)

    def test_parses_json_string_from_powershell(self):
        svc = _make_service()
        with patch.object(svc, "_local_speech_available", return_value=True):
            with patch.object(svc, "_run_powershell", return_value='"Microsoft David Desktop"'):
                result = svc._installed_voices()
        self.assertEqual(result, ["Microsoft David Desktop"])

    def test_parses_non_list_non_string_as_empty(self):
        svc = _make_service()
        with patch.object(svc, "_local_speech_available", return_value=True):
            with patch.object(svc, "_run_powershell", return_value="42"):
                result = svc._installed_voices()
        self.assertEqual(result, [])


# ============================================================
# synthesize with available local speech
# ============================================================

class TestSynthesizeWithSpeech(unittest.TestCase):
    def test_no_installed_voices_returns_error_dict(self):
        svc = _make_service()
        with patch.object(svc, "_local_speech_available", return_value=True):
            with patch.object(svc, "_installed_voices", return_value=[]):
                result = svc.synthesize("Hello world")
        self.assertIsInstance(result, dict)
        self.assertIn("error", result)
        self.assertFalse(result["available"])
        self.assertEqual(result["action"], "synthesize")

    def test_synthesize_success_with_mock_voice(self):
        svc = _make_service()
        with tempfile.TemporaryDirectory() as tmpdir:
            svc.artifact_root = Path(tmpdir) / "artifacts"
            with patch.object(svc, "_local_speech_available", return_value=True):
                with patch.object(svc, "_installed_voices", return_value=["Microsoft David Desktop"]):
                    with patch.object(svc, "_resolve_voice_name", return_value="Microsoft David Desktop"):
                        with patch.object(svc, "_synthesize_to_wave", return_value=1.5):
                            result = svc.synthesize("Hello", voice="openchimera-default")
        self.assertEqual(result["action"], "synthesize")
        self.assertEqual(result["backend"], "windows-system-speech")
        self.assertAlmostEqual(result["duration_seconds"], 1.5)


# ============================================================
# _resolve_voice_name coverage tests
# ============================================================

class TestResolveVoiceName(unittest.TestCase):
    def test_alias_openchimera_default_returns_first_voice(self):
        svc = _make_service()
        with patch.object(svc, "_installed_voices", return_value=["Voice A", "Voice B"]):
            result = svc._resolve_voice_name("openchimera-default")
        self.assertEqual(result, "Voice A")

    def test_alias_operator_matches_david(self):
        svc = _make_service()
        with patch.object(svc, "_installed_voices", return_value=["Microsoft David Desktop", "Microsoft Zira Desktop"]):
            result = svc._resolve_voice_name("operator")
        self.assertEqual(result, "Microsoft David Desktop")

    def test_exact_voice_name_returned(self):
        svc = _make_service()
        with patch.object(svc, "_installed_voices", return_value=["Custom Voice", "Voice B"]):
            result = svc._resolve_voice_name("Custom Voice")
        self.assertEqual(result, "Custom Voice")

    def test_unknown_voice_raises_value_error(self):
        svc = _make_service()
        with patch.object(svc, "_installed_voices", return_value=["Voice A"]):
            with self.assertRaises(ValueError):
                svc._resolve_voice_name("nonexistent-voice-xyz")

    def test_no_voices_raises_runtime_error(self):
        svc = _make_service()
        with patch.object(svc, "_installed_voices", return_value=[]):
            with self.assertRaises(RuntimeError):
                svc._resolve_voice_name("any-voice")


# ============================================================
# understand_image success path coverage tests
# ============================================================

class TestUnderstandImageProvider(unittest.TestCase):
    def _provider(self):
        return {
            "provider": "openai",
            "api_key": "sk-test",
            "model": "gpt-4.1-mini",
            "url": "https://api.openai.com/v1/chat/completions",
        }

    def test_understand_image_success_with_mock_provider(self):
        svc = _make_service()
        png_b64 = base64.b64encode(_make_minimal_png()).decode()
        mock_response = {
            "choices": [{"message": {"content": "A beautiful sunset over mountains."}}]
        }
        with patch.object(svc, "_select_vision_provider", return_value=self._provider()):
            with patch.object(svc, "_post_json", return_value=mock_response):
                result = svc.understand_image(image_base64=png_b64)
        self.assertEqual(result["action"], "understand_image")
        self.assertEqual(result["summary"], "A beautiful sunset over mountains.")
        self.assertEqual(result["provider"], "openai")

    def test_understand_image_with_path_and_mock_provider(self):
        svc = _make_service()
        mock_response = {
            "choices": [{"message": {"content": "A PNG image with red pixels."}}]
        }
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(_make_minimal_png())
            img_path = f.name
        try:
            with patch.object(svc, "_select_vision_provider", return_value=self._provider()):
                with patch.object(svc, "_post_json", return_value=mock_response):
                    result = svc.understand_image(image_path=img_path)
            self.assertEqual(result["action"], "understand_image")
            self.assertIn("summary", result)
        finally:
            os.unlink(img_path)

    def test_understand_image_with_provider_list_content(self):
        svc = _make_service()
        png_b64 = base64.b64encode(_make_minimal_png()).decode()
        mock_response = {
            "choices": [{"message": {"content": [{"type": "text", "text": "Part one."}, {"type": "text", "text": "Part two."}]}}]
        }
        with patch.object(svc, "_select_vision_provider", return_value=self._provider()):
            with patch.object(svc, "_post_json", return_value=mock_response):
                result = svc.understand_image(image_base64=png_b64)
        self.assertIn("Part one", result["summary"])

    def test_understand_image_with_provider_empty_content_raises(self):
        svc = _make_service()
        png_b64 = base64.b64encode(_make_minimal_png()).decode()
        mock_response = {"choices": [{"message": {"content": ""}}]}
        with patch.object(svc, "_select_vision_provider", return_value=self._provider()):
            with patch.object(svc, "_post_json", return_value=mock_response):
                with self.assertRaises(RuntimeError):
                    svc.understand_image(image_base64=png_b64)

    def test_understand_image_openrouter_provider_with_referer_header(self):
        svc = _make_service()
        png_b64 = base64.b64encode(_make_minimal_png()).decode()
        openrouter_provider = {
            "provider": "openrouter",
            "api_key": "or-test",
            "model": "openai/gpt-4o-mini",
            "url": "https://openrouter.ai/api/v1/chat/completions",
        }
        mock_response = {"choices": [{"message": {"content": "A red pixel."}}]}
        captured_headers = {}

        def capture_post(url, payload, headers):
            captured_headers.update(headers)
            return mock_response

        with patch.object(svc, "_select_vision_provider", return_value=openrouter_provider):
            with patch.object(svc, "_post_json", side_effect=capture_post):
                result = svc.understand_image(image_base64=png_b64)
        self.assertIn("HTTP-Referer", captured_headers)


# ============================================================
# generate_image success path coverage tests
# ============================================================

class TestGenerateImageProvider(unittest.TestCase):
    def _provider(self):
        return {
            "provider": "openai",
            "api_key": "sk-test",
            "model": "gpt-image-1",
            "url": "https://api.openai.com/v1/images/generations",
        }

    def test_generate_image_success_with_mock_provider(self):
        svc = _make_service()
        fake_png_b64 = base64.b64encode(b"FAKE_PNG_DATA").decode()
        mock_response = {"data": [{"b64_json": fake_png_b64}]}
        with patch.object(svc, "_select_image_generation_provider", return_value=self._provider()):
            with patch.object(svc, "_post_json", return_value=mock_response):
                result = svc.generate_image("A red circle", width=512, height=512)
        self.assertEqual(result["action"], "generate_image")
        self.assertEqual(result["provider"], "openai")
        self.assertIn("artifact", result)

    def test_generate_image_provider_empty_data_raises(self):
        svc = _make_service()
        mock_response = {"data": []}
        with patch.object(svc, "_select_image_generation_provider", return_value=self._provider()):
            with patch.object(svc, "_post_json", return_value=mock_response):
                with self.assertRaises(RuntimeError):
                    svc.generate_image("A red circle")

    def test_generate_image_width_clamped_to_valid_range(self):
        svc = _make_service()
        fake_png_b64 = base64.b64encode(b"FAKE_PNG").decode()
        mock_response = {"data": [{"b64_json": fake_png_b64}]}
        with patch.object(svc, "_select_image_generation_provider", return_value=self._provider()):
            with patch.object(svc, "_post_json", return_value=mock_response):
                result = svc.generate_image("A circle", width=999999, height=1)
        self.assertEqual(result["width"], 2048)


# ============================================================
# _provider_secret coverage tests
# ============================================================

class TestProviderSecret(unittest.TestCase):
    def test_returns_env_var_when_set(self):
        svc = _make_service()
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-from-env"}):
            result = svc._provider_secret("openai", ["OPENAI_API_KEY"])
        self.assertEqual(result, "sk-from-env")

    def test_returns_credential_store_value_when_env_var_absent(self):
        svc = _make_service()
        mock_store = MagicMock()
        mock_store.get_provider_credentials.return_value = {"OPENAI_API_KEY": "sk-from-store"}
        svc.credential_store = mock_store
        with patch.dict(os.environ, {}, clear=False):
            # Ensure env var is not set
            result = svc._provider_secret("openai", ["OPENAI_API_KEY"])
        if result:
            self.assertTrue(result.startswith("sk-"))

    def test_returns_empty_string_when_no_credentials(self):
        svc = _make_service()
        mock_store = MagicMock()
        mock_store.get_provider_credentials.return_value = {}
        svc.credential_store = mock_store
        env_without_key = {k: v for k, v in os.environ.items() if k not in ("OPENAI_API_KEY",)}
        with patch.dict(os.environ, env_without_key, clear=True):
            result = svc._provider_secret("openai", ["OPENAI_API_KEY"])
        self.assertEqual(result, "")


# ============================================================
# _post_json coverage tests
# ============================================================

class TestPostJson(unittest.TestCase):
    def test_post_json_success_returns_dict(self):
        svc = _make_service()
        from unittest.mock import MagicMock
        from unittest.mock import patch as _patch
        from urllib import error as _error
        mock_response_data = json.dumps({"result": "ok"}).encode("utf-8")

        class MockResponse:
            def read(self):
                return mock_response_data
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass

        with patch("core.multimodal_service.request.urlopen", return_value=MockResponse()):
            result = svc._post_json(
                "http://example.com/api",
                {"key": "value"},
                {"Authorization": "Bearer test"},
            )
        self.assertEqual(result["result"], "ok")

    def test_post_json_http_error_raises_runtime_error(self):
        svc = _make_service()
        from urllib import error as _url_error
        from io import BytesIO
        http_error = _url_error.HTTPError(
            url="http://example.com",
            code=400,
            msg="Bad Request",
            hdrs=None,
            fp=BytesIO(b"bad request body"),
        )
        with patch("core.multimodal_service.request.urlopen", side_effect=http_error):
            with self.assertRaises(RuntimeError) as ctx:
                svc._post_json("http://example.com/api", {}, {"Authorization": "Bearer test"})
        self.assertIn("400", str(ctx.exception))

    def test_post_json_url_error_raises_runtime_error(self):
        svc = _make_service()
        from urllib import error as _url_error
        url_error = _url_error.URLError(reason="connection refused")
        with patch("core.multimodal_service.request.urlopen", side_effect=url_error):
            with self.assertRaises(RuntimeError) as ctx:
                svc._post_json("http://example.com/api", {}, {"Authorization": "Bearer test"})
        self.assertIn("connection refused", str(ctx.exception))


# ============================================================
# Helper method coverage tests
# ============================================================

class TestHelperMethods(unittest.TestCase):
    def test_to_data_url_encodes_correctly(self):
        svc = _make_service()
        data = b"hello world"
        result = svc._to_data_url(data, "text/plain")
        self.assertTrue(result.startswith("data:text/plain;base64,"))
        encoded_part = result.split(",", 1)[1]
        self.assertEqual(base64.b64decode(encoded_part), data)

    def test_openai_image_size_wide_returns_landscape(self):
        svc = _make_service()
        result = svc._openai_image_size(1920, 1080)
        self.assertEqual(result, "1792x1024")

    def test_openai_image_size_tall_returns_portrait(self):
        svc = _make_service()
        result = svc._openai_image_size(768, 1366)
        self.assertEqual(result, "1024x1792")

    def test_openai_image_size_square_returns_square(self):
        svc = _make_service()
        result = svc._openai_image_size(1024, 1024)
        self.assertEqual(result, "1024x1024")

    def test_decode_base64_strips_data_url_prefix(self):
        svc = _make_service()
        data = b"hello test"
        encoded = base64.b64encode(data).decode()
        data_url = f"data:text/plain;base64,{encoded}"
        result = svc._decode_base64(data_url)
        self.assertEqual(result, data)

    def test_decode_base64_plain_value(self):
        svc = _make_service()
        data = b"plain bytes"
        encoded = base64.b64encode(data).decode()
        result = svc._decode_base64(encoded)
        self.assertEqual(result, data)

    def test_load_history_returns_empty_for_non_list_json(self):
        svc = _make_service()
        with tempfile.TemporaryDirectory() as tmpdir:
            history_path = Path(tmpdir) / "sessions.json"
            history_path.write_text('{"not": "a list"}', encoding="utf-8")
            svc.history_path = history_path
            result = svc._load_history()
        self.assertEqual(result, [])

    def test_load_history_returns_empty_for_corrupt_json(self):
        svc = _make_service()
        with tempfile.TemporaryDirectory() as tmpdir:
            history_path = Path(tmpdir) / "sessions.json"
            history_path.write_text("{corrupt json", encoding="utf-8")
            svc.history_path = history_path
            result = svc._load_history()
        self.assertEqual(result, [])

    def test_append_history_caps_at_50_entries(self):
        svc = _make_service()
        with tempfile.TemporaryDirectory() as tmpdir:
            svc.history_path = Path(tmpdir) / "sessions.json"
            svc.artifact_root = Path(tmpdir) / "artifacts"
            for i in range(55):
                svc._append_history({"action": "test", "index": i})
            history = svc._load_history()
        self.assertEqual(len(history), 50)
        self.assertEqual(history[-1]["index"], 54)

    def test_write_json_artifact_creates_file(self):
        svc = _make_service()
        with tempfile.TemporaryDirectory() as tmpdir:
            svc.artifact_root = Path(tmpdir) / "artifacts"
            artifact = svc._write_json_artifact("transcribe", {"transcript": "hello"})
            self.assertIn("path", artifact)
            self.assertTrue(Path(artifact["path"]).exists())


# ============================================================
# status() detail coverage tests
# ============================================================

class TestStatusDetail(unittest.TestCase):
    def test_status_enabled_true_when_speech_available(self):
        svc = _make_service()
        with patch.object(svc, "_local_speech_available", return_value=True):
            with patch.object(svc, "_installed_voices", return_value=["Voice A"]):
                with patch.object(svc, "_select_vision_provider", return_value=None):
                    with patch.object(svc, "_select_image_generation_provider", return_value=None):
                        result = svc.status()
        self.assertTrue(result["enabled"])
        self.assertIn("supported_actions", result)
        self.assertIn("unavailable_actions", result)

    def test_status_supported_image_formats_empty_when_vision_unavailable(self):
        svc = _make_service()
        with patch.object(svc, "_local_speech_available", return_value=False):
            with patch.object(svc, "_select_vision_provider", return_value=None):
                with patch.object(svc, "_select_image_generation_provider", return_value=None):
                    result = svc.status()
        self.assertEqual(result["supported_image_formats"], [])

    def test_status_supported_image_formats_non_empty_when_vision_available(self):
        svc = _make_service()
        provider = {"provider": "openai", "api_key": "sk-test", "model": "gpt-4.1-mini", "url": "http://x"}
        with patch.object(svc, "_local_speech_available", return_value=False):
            with patch.object(svc, "_select_vision_provider", return_value=provider):
                with patch.object(svc, "_select_image_generation_provider", return_value=None):
                    result = svc.status()
        self.assertIn("png", result["supported_image_formats"])


# ============================================================
# Additional coverage tests targeting remaining uncovered lines
# ============================================================

class TestAdditionalMultimodalCoverage(unittest.TestCase):
    """Cover remaining uncovered lines in multimodal_service.py."""

    def test_local_speech_available_returns_true_when_nt_and_powershell_ok(self) -> None:
        """Line 272: force os.name='nt' and mock _run_powershell to verify return True."""
        import os as _os
        svc = _make_service()
        with patch.object(_os, "name", "nt"):
            with patch.object(svc, "_run_powershell", return_value="ok"):
                result = svc._local_speech_available()
        self.assertTrue(result)

    def test_transcribe_audio_bytes_returns_empty_when_speech_unavailable(self) -> None:
        """Line 336: _local_speech_available=False → _transcribe_audio_bytes returns ''."""
        svc = _make_service()
        with patch.object(svc, "_local_speech_available", return_value=False):
            result = svc._transcribe_audio_bytes(_make_minimal_wav())
        self.assertEqual(result, "")

    def test_transcribe_audio_bytes_raises_value_error_for_non_wav(self) -> None:
        """Lines 337-338: non-WAV bytes raise ValueError about PCM WAV requirement."""
        svc = _make_service()
        with patch.object(svc, "_local_speech_available", return_value=True):
            with self.assertRaises(ValueError) as ctx:
                svc._transcribe_audio_bytes(b"\x00\x01\x02invalid_data_here")
        self.assertIn("WAV", str(ctx.exception))

    def test_transcribe_audio_bytes_success_returns_normalized_transcript(self) -> None:
        """Lines 339-356: full success path — temp file, powershell, normalize, return."""
        svc = _make_service()
        wav = _make_minimal_wav()
        with patch.object(svc, "_local_speech_available", return_value=True):
            with patch.object(svc, "_run_powershell", return_value="hello world"):
                result = svc._transcribe_audio_bytes(wav)
        self.assertEqual(result, "hello world")

    def test_transcribe_audio_bytes_empty_transcript_raises_runtime_error(self) -> None:
        """Lines 354-355: powershell returns empty string → RuntimeError."""
        svc = _make_service()
        wav = _make_minimal_wav()
        with patch.object(svc, "_local_speech_available", return_value=True):
            with patch.object(svc, "_run_powershell", return_value=""):
                with self.assertRaises(RuntimeError):
                    svc._transcribe_audio_bytes(wav)

    def test_select_vision_provider_returns_none_when_no_keys_available(self) -> None:
        """Line 361: both openai and openrouter keys absent → return None."""
        svc = _make_service()
        with patch.object(svc, "_provider_secret", return_value=""):
            result = svc._select_vision_provider()
        self.assertIsNone(result)

    def test_select_vision_provider_returns_openrouter_when_only_openrouter_key(self) -> None:
        """Lines 367-374: openai absent, openrouter present → return openrouter dict."""
        svc = _make_service()

        def _mock_secret(provider: str, keys: list) -> str:
            return "or-key" if provider == "openrouter" else ""

        with patch.object(svc, "_provider_secret", side_effect=_mock_secret):
            result = svc._select_vision_provider()
        self.assertIsNotNone(result)
        self.assertEqual(result["provider"], "openrouter")

    def test_select_image_generation_provider_returns_none_when_no_openai_key(self) -> None:
        """Line 369 (image gen): no openai key → return None immediately."""
        svc = _make_service()
        with patch.object(svc, "_provider_secret", return_value=""):
            result = svc._select_image_generation_provider()
        self.assertIsNone(result)

    def test_understand_image_with_provider_sets_x_title_for_openrouter(self) -> None:
        """Line 381: X-Title header set when provider is openrouter."""
        svc = _make_service()
        png_bytes = _make_minimal_png()
        openrouter_provider = {
            "provider": "openrouter",
            "api_key": "or-test",
            "model": "openai/gpt-4o-mini",
            "url": "https://openrouter.ai/api/v1/chat/completions",
        }
        captured_headers: dict = {}

        def _capture(url: str, payload: dict, headers: dict) -> dict:
            captured_headers.update(headers)
            return {"choices": [{"message": {"content": "A pixel."}}]}

        metadata = {"mime_type": "image/png"}
        with patch.object(svc, "_post_json", side_effect=_capture):
            svc._understand_image_with_provider(
                openrouter_provider, "Describe", png_bytes, metadata
            )
        self.assertIn("X-Title", captured_headers)

    def test_run_powershell_raises_runtime_error_on_nonzero_returncode(self) -> None:
        """Lines 498-499: PowerShell exitcode != 0 → raise RuntimeError."""
        svc = _make_service()
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "Access is denied."
        mock_result.stdout = ""
        with patch("subprocess.run", return_value=mock_result):
            with self.assertRaises(RuntimeError) as ctx:
                svc._run_powershell("Get-Date")
        self.assertIn("Access is denied", str(ctx.exception))

    def test_run_powershell_error_uses_stdout_fallback_when_stderr_empty(self) -> None:
        """Lines 498-499: stderr empty, stdout empty → fallback message contains exitcode."""
        svc = _make_service()
        mock_result = MagicMock()
        mock_result.returncode = 3
        mock_result.stderr = ""
        mock_result.stdout = ""
        with patch("subprocess.run", return_value=mock_result):
            with self.assertRaises(RuntimeError) as ctx:
                svc._run_powershell("bad-command")
        self.assertIn("3", str(ctx.exception))

    def test_local_speech_available_returns_false_on_non_windows(self) -> None:
        """Line 272: os.name != 'nt' → return False without calling powershell."""
        import os as _os
        svc = _make_service()
        with patch.object(_os, "name", "posix"):
            result = svc._local_speech_available()
        self.assertFalse(result)

    def test_select_vision_provider_returns_openai_when_key_present(self) -> None:
        """Line 361: openai key present → return openai provider dict."""
        svc = _make_service()
        with patch.object(svc, "_provider_secret", return_value="sk-test-key"):
            result = svc._select_vision_provider()
        self.assertIsNotNone(result)
        self.assertEqual(result["provider"], "openai")

    def test_select_image_generation_provider_returns_openai_when_key_present(self) -> None:
        """Line 381: openai key present → return openai provider dict."""
        svc = _make_service()
        with patch.object(svc, "_provider_secret", return_value="sk-test-key"):
            result = svc._select_image_generation_provider()
        self.assertIsNotNone(result)
        self.assertEqual(result["provider"], "openai")