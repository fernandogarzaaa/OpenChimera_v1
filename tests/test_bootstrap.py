from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import bootstrap


class BootstrapTests(unittest.TestCase):
    def test_bootstrap_creates_missing_workspace_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            report = bootstrap.bootstrap_workspace(root=root)

            self.assertEqual(report["status"], "ok")
            self.assertTrue((root / "logs").exists())
            self.assertTrue((root / "data" / "minimind").exists())
            self.assertTrue((root / "chimera_kb.json").exists())
            self.assertTrue((root / "rag_storage.json").exists())
            self.assertTrue((root / "config" / "runtime_profile.json").exists())
