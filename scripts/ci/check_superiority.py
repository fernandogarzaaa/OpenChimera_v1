from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "artifacts" / "benchmarks" / "superiority-report.json"


def main() -> int:
    if not REPORT.exists():
        print("Missing superiority report artifact:", REPORT)
        return 2
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    ok = bool(payload.get("scorecard", {}).get("overall_ok"))
    print("superiority_overall_ok =", ok)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
