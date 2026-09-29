# Lint and type-check scope

OpenChimera currently has two Python surfaces:

1. `python/openchimera/` — the installable package shipped by `pyproject.toml`.
2. Root-level `core/`, `openchimera/`, and integration workspaces — legacy/source-runtime compatibility modules and upstream snapshots that are still covered by tests but are not the wheel package selected by Hatch.

The configured release lint/type gates are scoped to maintained release inputs and exclude or per-file-ignore objectively invalid or legacy-noisy paths:

- `external/**`: third-party/upstream snapshots with duplicate module names.
- `skills/**`: bundled skill examples, fixtures, and generated templates.
- `artifacts/**`, `data/**`, `dist/**`, `build/**`, `node_modules/**`: generated/runtime/build outputs.
- Root `core/`, root `openchimera/`, `run.py`, `run_audit.py`, `scripts/`, `services/`, `swarms/`, `transport/`, `utils/`, `dist_sim/` are covered by the release **ruff** gate (graduated after mechanical cleanup: import hygiene, dead-code removal, narrowly-scoped `noqa` only for intentional sys.path bootstraps, availability probes, and one documented re-export).
- Historical broad tests (`tests/**`) are covered by the release **ruff** gate as well (graduated after a dedicated hygiene pass: import sorting, unused-variable cleanup preserving call semantics, `noqa` only for availability probes, sys.path bootstraps, and `__future__`-annotation false positives).
- The release **mypy** gate stays scoped to the installable package (`python/openchimera/`); legacy type debt (largely untyped defs) remains roadmap.

This scope is not a claim that legacy code has no debt. Repository-wide legacy lint/type cleanup remains in the roadmap; tests continue to exercise the root source runtime and compatibility namespace.
