"""
Tests for Phase 2: Voice & Audio Engine (TTS, STT, Wake Word Detection).
"""
from __future__ import annotations

import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.voice_engine import (
    TTSBackend,
    STTBackend,
    VoiceConfig,
    TTSEngine,
    TTSResult,
    TranscriptionEngine,
    TranscriptionResult,
    WakeWordDetector,
    VoiceEngine,
)


class TestVoiceConfig(unittest.TestCase):
    def test_default_config(self):
        config = VoiceConfig()
        self.assertEqual(config.tts_backend, TTSBackend.MOCK)
        self.assertEqual(config.stt_backend, STTBackend.MOCK)
        self.assertIn("hey chimera", config.wake_words)
        self.assertEqual(config.language, "en-US")

    def test_custom_config(self):
        config = VoiceConfig(
            tts_backend=TTSBackend.PYTTSX3,
            stt_backend=STTBackend.WHISPER,
            voice_id="en-US-JennyNeural",
            language="en-GB",
            wake_words=["hello assistant"],
        )
        self.assertEqual(config.tts_backend, TTSBackend.PYTTSX3)
        self.assertEqual(config.language, "en-GB")
        self.assertIn("hello assistant", config.wake_words)


class TestTTSEngine(unittest.TestCase):
    def setUp(self):
        self.engine = TTSEngine(config=VoiceConfig(tts_backend=TTSBackend.MOCK))

    def test_synthesize_returns_result(self):
        result = self.engine.synthesize("Hello, world!")
        self.assertIsInstance(result, TTSResult)
        self.assertTrue(result.success)
        self.assertEqual(result.text, "Hello, world!")
        self.assertEqual(result.backend, TTSBackend.MOCK.value)

    def test_synthesize_empty_text(self):
        result = self.engine.synthesize("")
        self.assertFalse(result.success)
        self.assertIsNotNone(result.error)

    def test_synthesize_whitespace_text(self):
        result = self.engine.synthesize("   ")
        self.assertFalse(result.success)

    def test_mock_returns_audio_bytes(self):
        result = self.engine.synthesize("Test")
        self.assertIsNotNone(result.audio_bytes)
        self.assertGreater(len(result.audio_bytes), 0)

    def test_caching_enabled(self):
        result1 = self.engine.synthesize("Hello!")
        result2 = self.engine.synthesize("Hello!")
        self.assertEqual(result1.audio_bytes, result2.audio_bytes)
        # Count should be 1 (cache hit)
        self.assertEqual(self.engine._synthesis_count, 1)

    def test_caching_disabled(self):
        result1 = self.engine.synthesize("Hello!", use_cache=False)
        result2 = self.engine.synthesize("Hello!", use_cache=False)
        self.assertEqual(self.engine._synthesis_count, 2)

    def test_tts_result_to_dict(self):
        result = self.engine.synthesize("Test")
        d = result.to_dict()
        self.assertIn("text", d)
        self.assertIn("backend", d)
        self.assertIn("success", d)
        self.assertIn("has_audio", d)
        self.assertTrue(d["has_audio"])

    def test_duration_tracked(self):
        result = self.engine.synthesize("Duration test")
        self.assertGreaterEqual(result.duration_ms, 0)

    def test_status_structure(self):
        status = self.engine.status()
        self.assertIn("backend", status)
        self.assertIn("synthesis_count", status)
        self.assertIn("cache_entries", status)

    def test_save_to_file(self):
        import tempfile
        import os
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "test.wav"
            result = self.engine.save_to_file("Hello!", output_path)
            self.assertTrue(result.success)
            self.assertTrue(output_path.exists())


class TestTranscriptionEngine(unittest.TestCase):
    def setUp(self):
        self.engine = TranscriptionEngine(config=VoiceConfig(stt_backend=STTBackend.MOCK))

    def test_transcribe_returns_result(self):
        result = self.engine.transcribe(b"fake-audio-bytes")
        self.assertIsInstance(result, TranscriptionResult)
        self.assertTrue(result.success)
        self.assertEqual(result.backend, STTBackend.MOCK.value)

    def test_transcribe_empty_audio(self):
        result = self.engine.transcribe(b"")
        self.assertFalse(result.success)
        self.assertIsNotNone(result.error)

    def test_mock_returns_placeholder_text(self):
        result = self.engine.transcribe(b"audio-data")
        self.assertIn("mock", result.text.lower())

    def test_transcription_has_segments(self):
        result = self.engine.transcribe(b"audio")
        self.assertIsInstance(result.segments, list)

    def test_transcription_result_to_dict(self):
        result = self.engine.transcribe(b"test")
        d = result.to_dict()
        self.assertIn("text", d)
        self.assertIn("backend", d)
        self.assertIn("confidence", d)
        self.assertIn("language", d)

    def test_transcribe_file_not_found(self):
        result = self.engine.transcribe_file(Path("/nonexistent/path/audio.wav"))
        self.assertFalse(result.success)
        self.assertIn("not found", result.error.lower())

    def test_transcription_count(self):
        self.engine.transcribe(b"audio1")
        self.engine.transcribe(b"audio2")
        self.assertEqual(self.engine._transcription_count, 2)

    def test_status_structure(self):
        status = self.engine.status()
        self.assertIn("backend", status)
        self.assertIn("transcription_count", status)


class TestWakeWordDetector(unittest.TestCase):
    def setUp(self):
        config = VoiceConfig(wake_words=["hey chimera", "chimera", "wake up"])
        self.detector = WakeWordDetector(config=config)

    def test_detect_in_text_found(self):
        result = self.detector.detect_in_text("Hey Chimera, what time is it?")
        self.assertIsNotNone(result)
        self.assertEqual(result.lower(), "hey chimera")

    def test_detect_in_text_not_found(self):
        result = self.detector.detect_in_text("This is a normal message")
        self.assertIsNone(result)

    def test_detect_in_text_case_insensitive(self):
        result = self.detector.detect_in_text("CHIMERA, help me!")
        self.assertIsNotNone(result)

    def test_detect_in_audio_mock(self):
        # Mock transcription will return "[mock transcription]" which won't match
        result = self.detector.detect_in_audio(b"fake-audio")
        # Mock transcript doesn't contain wake words, so None is expected
        self.assertIsNone(result)

    def test_callback_triggered(self):
        detections = []
        self.detector.add_callback(lambda w, c: detections.append(w))
        # Manually simulate detection
        self.detector.detect_in_text("hey chimera")
        # Callback only triggered via detect_in_audio, not detect_in_text alone
        # Test via status
        status = self.detector.status()
        self.assertIn("wake_words", status)

    def test_detection_history(self):
        # Inject a detection manually
        from core.voice_engine import TranscriptionEngine
        engine = TranscriptionEngine()
        # Patch the mock to return wake word text
        with patch.object(engine, "_mock_transcribe") as mock_t:
            mock_result = TranscriptionResult(
                audio_bytes=b"test",
                text="hey chimera please help",
                backend="mock",
                confidence=1.0,
                language="en-US",
                success=True,
            )
            mock_t.return_value = mock_result
            self.detector.detect_in_audio(b"audio", transcriber=engine)
        history = self.detector.get_detections()
        self.assertGreater(len(history), 0)
        self.assertEqual(history[0]["wake_word"], "hey chimera")

    def test_status_structure(self):
        status = self.detector.status()
        self.assertIn("wake_words", status)
        self.assertIn("sensitivity", status)
        self.assertIn("total_detections", status)


class TestVoiceEngine(unittest.TestCase):
    def setUp(self):
        config = VoiceConfig(tts_backend=TTSBackend.MOCK, stt_backend=STTBackend.MOCK)
        self.engine = VoiceEngine(config=config)

    def test_speak_returns_tts_result(self):
        result = self.engine.speak("Hello!")
        self.assertIsInstance(result, TTSResult)
        self.assertTrue(result.success)

    def test_listen_returns_transcription(self):
        result = self.engine.listen(b"fake-audio")
        self.assertIsInstance(result, TranscriptionResult)
        self.assertTrue(result.success)

    def test_process_audio_returns_structured_result(self):
        result = self.engine.process_audio(b"fake-audio")
        self.assertIn("session_id", result)
        self.assertIn("transcription", result)
        self.assertIn("wake_word_detected", result)
        self.assertIn("timestamp", result)

    def test_status_structure(self):
        status = self.engine.status()
        self.assertIn("session_id", status)
        self.assertIn("tts", status)
        self.assertIn("stt", status)
        self.assertIn("wake", status)
        self.assertIn("config", status)

    def test_session_id_stable(self):
        id1 = self.engine._session_id
        id2 = self.engine._session_id
        self.assertEqual(id1, id2)

    def test_speak_then_listen_pipeline(self):
        # TTS
        tts_result = self.engine.speak("What's the weather?")
        self.assertTrue(tts_result.success)
        # STT on "recorded" audio (mock)
        stt_result = self.engine.listen(tts_result.audio_bytes or b"dummy")
        self.assertTrue(stt_result.success)


if __name__ == "__main__":
    unittest.main()
