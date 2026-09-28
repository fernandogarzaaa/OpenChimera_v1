# Lint and type-check scope

OpenChimera currently has two Python surfaces:

1. `python/openchimera/` — the installable package shipped by `pyproject.toml`.
2. Root-level `core/`, `openchimera/`, and integration workspaces — legacy/source-runtime compatibility modules and upstream snapshots that are still covered by tests but are not the wheel package selected by Hatch.

The configured release lint/type gates are scoped to maintained release inputs and exclude or per-file-ignore objectively invalid or legacy-noisy paths:

- `external/**`: third-party/upstream snapshots with duplicate module names.
- `skills/**`: bundled skill examples, fixtures, and generated templates.
- `artifacts/**`, `data/**`, `dist/**`, `build/**`, `node_modules/**`: generated/runtime/build outputs.
- Root `core/`, root `openchimera/`, `run.py`, `scripts/`, `services/`, `swarms/`, `transport/`, `utils/`, and historical broad tests are still exercised by deterministic pytest shards, but they contain pre-existing style/type debt and duplicate namespace concerns. They are excluded/per-file-ignored from the release lint/type gate until a separate cleanup can be reviewed safely.

This scope is not a claim that legacy code has no debt. Repository-wide legacy lint/type cleanup remains in the roadmap; tests continue to exercise the root source runtime and compatibility namespace.
