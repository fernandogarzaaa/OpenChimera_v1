from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from core.aegis_service import AegisService
from core.ascension_service import AscensionService
from core.local_llm import LocalLLMManager
from core.minimind_service import MiniMindService


class AdvancedCapabilityTests(unittest.TestCase):
    def test_aegis_preview_scans_targets_without_mutating(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "test_demo.py").write_text("print('ok')\n", encoding="utf-8")
            service = AegisService()
            service.available = True

            result = service.run_workflow(target_project=str(root), preview=True)

            self.assertEqual(result["status"], "preview")
            self.assertEqual(result["debt_count"], 1)
            self.assertTrue((root / "test_demo.py").exists())

    def test_ascension_deliberation_falls_back_to_local_llm(self) -> None:
        minimind = MiniMindService()
        minimind.reasoning_completion = MagicMock(return_value={"content": "", "model": "minimind", "error": "low quality"})
        llm_manager = LocalLLMManager()
        llm_manager.get_ranked_models = MagicMock(return_value=["llama-3.2-3b"])
        llm_manager.chat_completion = MagicMock(
            return_value={"content": "Use a stronger runtime bridge and better discovery.", "model": "llama-3.2-3b"}
        )
        service = AscensionService(llm_manager, minimind)

        result = service.deliberate("How should OpenChimera surpass OpenClaw?", perspectives=["architect"])

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["perspectives"][0]["model"], "llama-3.2-3b")
        self.assertIn("Consensus:", result["consensus"])


if __name__ == "__main__":
    unittest.main()