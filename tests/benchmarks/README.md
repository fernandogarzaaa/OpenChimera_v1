# Benchmark Suite

This folder contains benchmark-oriented regression tests for AGI progress axes.

## Files

- `test_capability_regression.py`: cross-domain/OOD reasoning and transfer checks
- `test_reliability_regression.py`: calibration and safety hardening checks
- `test_autonomy_regression.py`: long-horizon planning/replanning/intervention checks
- `test_superiority_harness.py`: harness and scorecard contract checks

## Run Benchmarks

Use the benchmark runner:

`python scripts/benchmarks/run_superiority_bench.py`

## Run Gate

Use the integrated AGI superiority gate:

`python scripts/benchmarks/gate.py`
