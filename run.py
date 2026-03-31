from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from core.kernel import OpenChimeraKernel


def main() -> None:
    workspace_root = Path(__file__).resolve().parent
    os.chdir(workspace_root)
    workspace_root_str = str(workspace_root)
    if workspace_root_str not in sys.path:
        sys.path.insert(0, workspace_root_str)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.info("Starting OpenChimera from %s", workspace_root)
    kernel = OpenChimeraKernel()
    try:
        kernel.boot()
    except KeyboardInterrupt:
        logging.info("Stopping OpenChimera...")
        kernel.shutdown()


if __name__ == "__main__":
    main()