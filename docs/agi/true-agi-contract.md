# OpenChimera True AGI Contract

This contract defines the minimum measurable standard for claiming "True AGI progress"
in OpenChimera and the threshold for superiority on selected axes against OpenClaw.

## Priority Axes

- Capability
- Reliability
- Autonomy

## Operational Definition

OpenChimera qualifies as "true AGI progress" when it can:

1. Solve novel multi-domain tasks end-to-end.
2. Maintain calibrated confidence under uncertainty.
3. Execute long-horizon goals with low operator intervention.

## KPI Thresholds

### Capability

- Metric: Capability pass rate over OOD/composite benchmark slice.
- Source tests:
  - `tests/benchmarks/test_capability_regression.py`
  - `tests/test_agi_complete_loop.py`
- Threshold:
  - `pass_rate >= 0.95` (required)

### Reliability

- Metrics:
  - Reliability pass rate on fault-injection/guardrail slice.
  - Calibration quality (ECE) from metacognition report.
- Source tests:
  - `tests/benchmarks/test_reliability_regression.py`
  - `tests/test_resilience.py`
  - `tests/test_phase2_self_awareness.py`
- Thresholds:
  - `pass_rate >= 0.98` (required)
  - `ece <= 0.10` for benchmark fixture workloads (required)

### Autonomy

- Metrics:
  - Long-horizon decomposition/replanning benchmark pass rate.
  - Intervention avoidance rate from planner metrics.
- Source tests:
  - `tests/benchmarks/test_autonomy_regression.py`
  - `tests/test_autonomy.py`
  - `tests/test_goal_planner.py`
- Thresholds:
  - `pass_rate >= 0.95` (required)
  - `intervention_avoidance_rate >= 0.70` on benchmark fixtures (required)

## Superiority Claim Policy

OpenChimera can be claimed superior on selected user-priority axes only when:

1. All required thresholds above pass in a single benchmark run.
2. No integrated gate regression is detected in capability/reliability/autonomy suites.
3. A comparison report is generated at:
   - `docs/benchmarks/openclaw-comparison.md`
   - `artifacts/benchmarks/superiority-report.json`

## Execution Command

Run:

`python scripts/benchmarks/gate.py`

This command is the canonical release gate for this contract.
