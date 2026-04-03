from __future__ import annotations

import json
import tempfile
import unittest
import wave
from pathlib import Path

from core.multimodal_service import MultimodalService


PNG_1X1_BASE64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9s0nX7sAAAAASUVORK5CYII="


class MultimodalServiceTests(unittest.TestCase):
    def test_transcribe_records_history(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = MultimodalService(
                artifact_root=Path(temp_dir) / "artifacts",
                history_path=Path(temp_dir) / "media_sessions.json",
            )
            result = service.transcribe(audio_text="OpenChimera status update", language="en")
            self.assertEqual(result["transcript"], "OpenChimera status update")
            history = json.loads((Path(temp_dir) / "media_sessions.json").read_text(encoding="utf-8"))
            self.assertEqual(history[-1]["action"], "transcribe")

    def test_synthesize_writes_wav_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = MultimodalService(
                artifact_root=Path(temp_dir) / "artifacts",
                history_path=Path(temp_dir) / "media_sessions.json",
            )
            if service.status()["backends"]["synthesize"]["available"]:
                result = service.synthesize("Daily briefing ready.")
                artifact = Path(result["artifact"]["path"])
                self.assertTrue(artifact.exists())
                with wave.open(str(artifact), "rb") as wav_file:
                    self.assertGreater(wav_file.getnframes(), 0)
            else:
                with self.assertRaises(NotImplementedError):
                    service.synthesize("Daily briefing ready.")

    def test_understand_image_returns_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = MultimodalService(
                artifact_root=Path(temp_dir) / "artifacts",
                history_path=Path(temp_dir) / "media_sessions.json",
            )
            if service.status()["backends"]["understand_image"]["available"]:
                result = service.understand_image(prompt="Describe this image", image_base64=PNG_1X1_BASE64)
                self.assertEqual(result["metadata"]["mime_type"], "image/png")
                self.assertEqual(result["metadata"]["width"], 1)
                self.assertTrue(result["summary"])
            else:
                with self.assertRaises(NotImplementedError):
                    service.understand_image(prompt="Describe this image", image_base64=PNG_1X1_BASE64)

    def test_generate_image_writes_svg_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = MultimodalService(
                artifact_root=Path(temp_dir) / "artifacts",
                history_path=Path(temp_dir) / "media_sessions.json",
            )
            if service.status()["backends"]["generate_image"]["available"]:
                result = service.generate_image(prompt="Winged lion logo study", width=640, height=480, style="brand")
                artifact = Path(result["artifact"]["path"])
                self.assertTrue(artifact.exists())
                self.assertEqual(artifact.suffix.lower(), ".png")
                self.assertGreater(artifact.stat().st_size, 0)
            else:
                with self.assertRaises(NotImplementedError):
                    service.generate_image(prompt="Winged lion logo study", width=640, height=480, style="brand")


if __name__ == "__main__":
    unittest.main()