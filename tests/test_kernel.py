from __future__ import annotations

import unittest
from unittest.mock import MagicMock
from unittest.mock import patch

from core.kernel import OpenChimeraKernel


class KernelStartupTests(unittest.TestCase):
    def test_boot_fails_fast_when_api_server_does_not_start(self) -> None:
        fake_provider = MagicMock()
        fake_provider.start = MagicMock()
        fake_provider.stop = MagicMock()

        with (
            patch("core.kernel.build_identity_snapshot", return_value={"supervision": {}}),
            patch("core.kernel.get_watch_files", return_value=[]),
            patch("core.kernel.Personality"),
            patch("core.kernel.OpenChimeraProvider", return_value=fake_provider),
            patch("core.kernel.OpenChimeraAPIServer") as api_server_cls,
        ):
            api_server_cls.return_value.start.return_value = False
            kernel = OpenChimeraKernel()

            with self.assertRaises(RuntimeError):
                kernel.boot(run_forever=False)

        fake_provider.start.assert_called_once()
        fake_provider.stop.assert_called_once()


if __name__ == "__main__":
    unittest.main()