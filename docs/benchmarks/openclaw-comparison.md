# OpenChimera vs OpenClaw Comparison

This report compares OpenChimera against OpenClaw for user-priority axes:

- Capability
- Reliability
- Autonomy

## OpenClaw Baseline (Code-Evidence)

- Gateway-centric persistent multi-channel architecture.
- Plugin-extensible ecosystem and device-node orchestration.
- Mature CI lanes including live tests and perf-budget checks.

## OpenChimera Positioning

- Emphasis on cognitive depth and local-first AGI runtime modules:
  - deliberation/causal reasoning/world modeling,
  - metacognition/safety/reliability hardening,
  - autonomy scheduling + long-horizon planning.

## Measured Result Source

Authoritative benchmark artifact:

- `artifacts/benchmarks/superiority-report.json`

Gate command:

- `python scripts/benchmarks/gate.py`

## Decision Rule

OpenChimera is considered superior on selected axes only if:

1. The benchmark scorecard reports `overall_ok = true`.
2. Axis thresholds in `docs/agi/true-agi-contract.md` are all satisfied.
3. No benchmark suite regresses during the integrated gate.
