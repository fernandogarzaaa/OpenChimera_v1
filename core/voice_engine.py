"""
Phase 2: Voice & Audio Engine — TTS, Wake Word Detection, Transcription.

Provides a unified voice interface with:
- Text-to-Speech (TTS) with multiple backend support
- Speech-to-Text (STT / Transcription)
- Wake word detection
- Audio stream management
"""
from __future__ import annotations

import hashlib
import io
import logging
import os
import queue
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums & Config
# ---------------------------------------------------------------------------

class TTSBackend(str, Enum):
    PYTTSX3 = "pyttsx3"
    EDGE_TTS = "edge_tts"
    COQUI = "coqui"
    OPENAI = "openai"
    MOCK = "mock"


class STTBackend(str, Enum):
    WHISPER = "whisper"
    WHISPER_CPP = "whisper_cpp"
    GOOGLE = "google"
    MOCK = "mock"


@dataclass
class VoiceConfig:
    tts_backend: TTSBackend = TTSBackend.MOCK
    stt_backend: STTBackend = STTBackend.MOCK
    voice_id: str = "default"
    language: str = "en-US"
    speech_rate: float = 1.0
    volume: float = 1.0
    wake_words: List[str] = field(default_factory=lambda: ["hey chimera", "chimera"])
    wake_sensitivity: float = 0.7
    audio_sample_rate: int = 16000
    audio_channels: int = 1
    cache_dir: Optional[Path] = None


# ---------------------------------------------------------------------------
# TTS Engine
# ---------------------------------------------------------------------------

@dataclass
class TTSResult:
    text: str
    backend: str
    audio_bytes: Optional[bytes] = None
    audio_path: Optional[Path] = None
    duration_ms: float = 0.0
    success: bool = True
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "backend": self.backend,
            "has_audio": self.audio_bytes is not None or self.audio_path is not None,
            "audio_path": str(self.audio_path) if self.audio_path else None,
            "duration_ms": self.duration_ms,
            "success": self.success,
            "error": self.error,
        }


class TTSEngine:
    """
    Text-to-Speech engine with pluggable backends.
    Falls back to mock/dry-run mode when dependencies are unavailable.
    """

    def __init__(self, config: Optional[VoiceConfig] = None):
        self.config = config or VoiceConfig()
        self._cache: Dict[str, TTSResult] = {}
        self._synthesis_count = 0

    def _cache_key(self, text: str) -> str:
        return hashlib.md5(f"{text}:{self.config.voice_id}:{self.config.speech_rate}".encode()).hexdigest()

    def synthesize(self, text: str, use_cache: bool = True) -> TTSResult:
        """Convert text to speech audio."""
        if not text or not text.strip():
            return TTSResult(text=text, backend=self.config.tts_backend.value, success=False, error="Empty text")
        cache_key = self._cache_key(text)
        if use_cache and cache_key in self._cache:
            return self._cache[cache_key]
        start = time.time()
        result = self._synthesize_with_backend(text)
        result.duration_ms = (time.time() - start) * 1000
        self._synthesis_count += 1
        if use_cache and result.success:
            self._cache[cache_key] = result
        return result

    def _synthesize_with_backend(self, text: str) -> TTSResult:
        backend = self.config.tts_backend
        if backend == TTSBackend.MOCK:
            return self._mock_synthesize(text)
        if backend == TTSBackend.PYTTSX3:
            return self._pyttsx3_synthesize(text)
        if backend == TTSBackend.EDGE_TTS:
            return self._edge_tts_synthesize(text)
        return self._mock_synthesize(text)

    def _mock_synthesize(self, text: str) -> TTSResult:
        """Mock synthesis — returns silence bytes for testing."""
        # Minimal WAV header (44 bytes) + 1 second of silence
        mock_audio = b"RIFF" + b"\x00" * 40
        return TTSResult(
            text=text,
            backend=TTSBackend.MOCK.value,
            audio_bytes=mock_audio,
            success=True,
        )

    def _pyttsx3_synthesize(self, text: str) -> TTSResult:
        try:
            import pyttsx3  # type: ignore
            engine = pyttsx3.init()
            engine.setProperty("rate", int(150 * self.config.speech_rate))
            engine.setProperty("volume", self.config.volume)
            buf = io.BytesIO()
            engine.save_to_file(text, str(buf))
            engine.runAndWait()
            return TTSResult(text=text, backend=TTSBackend.PYTTSX3.value, audio_bytes=buf.getvalue(), success=True)
        except ImportError:
            logger.warning("pyttsx3 not available, falling back to mock")
            return self._mock_synthesize(text)
        except Exception as exc:
            return TTSResult(text=text, backend=TTSBackend.PYTTSX3.value, success=False, error=str(exc))

    def _edge_tts_synthesize(self, text: str) -> TTSResult:
        try:
            import asyncio
            import edge_tts  # type: ignore
            async def _run():
                communicate = edge_tts.Communicate(text, self.config.voice_id or "en-US-JennyNeural")
                buf = io.BytesIO()
                async for chunk in communicate.stream():
                    if chunk["type"] == "audio":
                        buf.write(chunk["data"])
                return buf.getvalue()
            audio_bytes = asyncio.run(_run())
            return TTSResult(text=text, backend=TTSBackend.EDGE_TTS.value, audio_bytes=audio_bytes, success=True)
        except ImportError:
            logger.warning("edge_tts not available, falling back to mock")
            return self._mock_synthesize(text)
        except Exception as exc:
            return TTSResult(text=text, backend=TTSBackend.EDGE_TTS.value, success=False, error=str(exc))

    def save_to_file(self, text: str, output_path: Path) -> TTSResult:
        """Synthesize and save to file."""
        result = self.synthesize(text, use_cache=False)
        if result.success and result.audio_bytes:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(result.audio_bytes)
            result.audio_path = output_path
        return result

    def status(self) -> dict:
        return {
            "backend": self.config.tts_backend.value,
            "voice_id": self.config.voice_id,
            "language": self.config.language,
            "speech_rate": self.config.speech_rate,
            "synthesis_count": self._synthesis_count,
            "cache_entries": len(self._cache),
        }


# ---------------------------------------------------------------------------
# STT / Transcription Engine
# ---------------------------------------------------------------------------

@dataclass
class TranscriptionResult:
    audio_bytes: Optional[bytes]
    text: str
    backend: str
    confidence: float = 1.0
    language: str = "en-US"
    segments: List[dict] = field(default_factory=list)
    duration_ms: float = 0.0
    success: bool = True
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "backend": self.backend,
            "confidence": self.confidence,
            "language": self.language,
            "segments": self.segments,
            "duration_ms": self.duration_ms,
            "success": self.success,
            "error": self.error,
        }


class TranscriptionEngine:
    """
    Speech-to-Text engine with pluggable backends.
    """

    def __init__(self, config: Optional[VoiceConfig] = None):
        self.config = config or VoiceConfig()
        self._transcription_count = 0

    def transcribe(self, audio_bytes: bytes, language: Optional[str] = None) -> TranscriptionResult:
        """Transcribe audio bytes to text."""
        if not audio_bytes:
            return TranscriptionResult(
                audio_bytes=audio_bytes,
                text="",
                backend=self.config.stt_backend.value,
                success=False,
                error="Empty audio",
            )
        start = time.time()
        result = self._transcribe_with_backend(audio_bytes, language or self.config.language)
        result.duration_ms = (time.time() - start) * 1000
        self._transcription_count += 1
        return result

    def transcribe_file(self, audio_path: Path, language: Optional[str] = None) -> TranscriptionResult:
        """Transcribe from audio file."""
        if not audio_path.exists():
            return TranscriptionResult(
                audio_bytes=None,
                text="",
                backend=self.config.stt_backend.value,
                success=False,
                error=f"File not found: {audio_path}",
            )
        audio_bytes = audio_path.read_bytes()
        return self.transcribe(audio_bytes, language)

    def _transcribe_with_backend(self, audio_bytes: bytes, language: str) -> TranscriptionResult:
        backend = self.config.stt_backend
        if backend == STTBackend.MOCK:
            return self._mock_transcribe(audio_bytes, language)
        if backend == STTBackend.WHISPER:
            return self._whisper_transcribe(audio_bytes, language)
        return self._mock_transcribe(audio_bytes, language)

    def _mock_transcribe(self, audio_bytes: bytes, language: str) -> TranscriptionResult:
        """Mock transcription — returns placeholder text."""
        return TranscriptionResult(
            audio_bytes=audio_bytes,
            text="[mock transcription]",
            backend=STTBackend.MOCK.value,
            confidence=1.0,
            language=language,
            segments=[{"start": 0.0, "end": 1.0, "text": "[mock transcription]", "confidence": 1.0}],
            success=True,
        )

    def _whisper_transcribe(self, audio_bytes: bytes, language: str) -> TranscriptionResult:
        try:
            import whisper  # type: ignore
            import tempfile
            import numpy as np
            model = whisper.load_model("base")
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                f.write(audio_bytes)
                tmp_path = f.name
            result = model.transcribe(tmp_path, language=language[:2])
            os.unlink(tmp_path)
            segments = [
                {"start": s["start"], "end": s["end"], "text": s["text"], "confidence": 1.0}
                for s in result.get("segments", [])
            ]
            return TranscriptionResult(
                audio_bytes=audio_bytes,
                text=result.get("text", ""),
                backend=STTBackend.WHISPER.value,
                language=language,
                segments=segments,
                success=True,
            )
        except ImportError:
            logger.warning("whisper not available, falling back to mock")
            return self._mock_transcribe(audio_bytes, language)
        except Exception as exc:
            return TranscriptionResult(
                audio_bytes=audio_bytes,
                text="",
                backend=STTBackend.WHISPER.value,
                success=False,
                error=str(exc),
            )

    def status(self) -> dict:
        return {
            "backend": self.config.stt_backend.value,
            "language": self.config.language,
            "transcription_count": self._transcription_count,
        }


# ---------------------------------------------------------------------------
# Wake Word Detector
# ---------------------------------------------------------------------------

class WakeWordDetector:
    """
    Wake word detection using keyword matching or pluggable model.
    Operates on a rolling audio buffer and triggers callbacks on detection.
    """

    def __init__(self, config: Optional[VoiceConfig] = None):
        self.config = config or VoiceConfig()
        self._callbacks: List[Callable[[str, float], None]] = []
        self._detections: List[dict] = []
        self._listening = False
        self._listen_thread: Optional[threading.Thread] = None

    def add_callback(self, callback: Callable[[str, float], None]) -> None:
        """Register a callback for wake word detection events."""
        self._callbacks.append(callback)

    def detect_in_text(self, text: str) -> Optional[str]:
        """Detect wake word in transcribed text (keyword matching)."""
        text_lower = text.lower().strip()
        for wake_word in self.config.wake_words:
            if wake_word.lower() in text_lower:
                return wake_word
        return None

    def detect_in_audio(self, audio_bytes: bytes, transcriber: Optional[TranscriptionEngine] = None) -> Optional[dict]:
        """Detect wake word in audio by transcribing first."""
        if not transcriber:
            transcriber = TranscriptionEngine(self.config)
        result = transcriber.transcribe(audio_bytes)
        if not result.success:
            return None
        detected_word = self.detect_in_text(result.text)
        if detected_word:
            detection = {
                "wake_word": detected_word,
                "text": result.text,
                "confidence": result.confidence,
                "timestamp": time.time(),
            }
            self._detections.append(detection)
            for cb in self._callbacks:
                try:
                    cb(detected_word, result.confidence)
                except Exception as exc:
                    logger.warning("Wake word callback error: %s", exc)
            return detection
        return None

    def get_detections(self, limit: int = 20) -> List[dict]:
        return list(reversed(self._detections))[:limit]

    def status(self) -> dict:
        return {
            "wake_words": self.config.wake_words,
            "sensitivity": self.config.wake_sensitivity,
            "total_detections": len(self._detections),
            "listening": self._listening,
        }


# ---------------------------------------------------------------------------
# Unified Voice Engine
# ---------------------------------------------------------------------------

class VoiceEngine:
    """
    Unified voice engine combining TTS, STT, and wake word detection.
    Single entry point for all voice functionality.
    """

    def __init__(self, config: Optional[VoiceConfig] = None):
        self.config = config or VoiceConfig()
        self.tts = TTSEngine(config=self.config)
        self.stt = TranscriptionEngine(config=self.config)
        self.wake = WakeWordDetector(config=self.config)
        self._session_id = f"voice-{int(time.time())}"
        self._active = False

    def speak(self, text: str) -> TTSResult:
        """Convert text to speech."""
        return self.tts.synthesize(text)

    def listen(self, audio_bytes: bytes) -> TranscriptionResult:
        """Transcribe audio to text."""
        return self.stt.transcribe(audio_bytes)

    def process_audio(self, audio_bytes: bytes) -> dict:
        """
        Full pipeline: detect wake word, transcribe, return structured result.
        """
        transcription = self.stt.transcribe(audio_bytes)
        wake_detection = None
        if transcription.success:
            wake_detection = self.wake.detect_in_text(transcription.text)
        return {
            "session_id": self._session_id,
            "transcription": transcription.to_dict(),
            "wake_word_detected": wake_detection is not None,
            "wake_word": wake_detection,
            "timestamp": time.time(),
        }

    def status(self) -> dict:
        return {
            "session_id": self._session_id,
            "active": self._active,
            "tts": self.tts.status(),
            "stt": self.stt.status(),
            "wake": self.wake.status(),
            "config": {
                "tts_backend": self.config.tts_backend.value,
                "stt_backend": self.config.stt_backend.value,
                "language": self.config.language,
                "sample_rate": self.config.audio_sample_rate,
            },
        }
