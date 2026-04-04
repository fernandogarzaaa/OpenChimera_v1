# Contributing to OpenChimera

Welcome, and thank you for your interest in contributing to OpenChimera — a local-first, open-source AI orchestration runtime built around quantum consensus, skills composition, and swarm-scale operator workflows.

Every bug report, documentation improvement, plugin, or feature strengthens the ecosystem. This guide explains how to contribute effectively.

---

## Ways to Contribute

| Type | Where to start |
|------|----------------|
| Bug report | [Open a bug report](.github/ISSUE_TEMPLATE/bug_report.md) |
| Feature request | [Open a feature request](.github/ISSUE_TEMPLATE/feature_request.md) |
| Documentation | Edit any `.md` file and open a PR |
| Skills / Plugins | Add a skill under `skills/` or a plugin under `plugins/` |
| Tests | Add or improve tests under `tests/` |
| Rust core | Improve `chimera-core/` (see Rust setup below) |

---

## Development Setup

### 1. Fork and clone

```bash
git clone https://github.com/<your-username>/OpenChimera_v1.git
cd OpenChimera_v1
```

### 2. Create a virtual environment

```bash
python -m venv .venv
# Windows
.venv\Scripts\Activate.ps1
# Linux / macOS
source .venv/bin/activate
```

### 3. Install in editable mode with dev dependencies

```bash
pip install -e ".[dev]"
```

### 4. Bootstrap local state

```bash
openchimera bootstrap
```

Copy the example local runtime override and edit it for your machine (never commit this file):

```bash
cp config/runtime_profile.local.example.json config/runtime_profile.local.json
```

### 5. Rust components (optional)

If you are working on the low-level consensus core in `chimera-core/`:

```bash
cd chimera-core
cargo build
```

Rust 1.75+ is recommended. The Python runtime does not require the Rust build to function.

---

## Running Tests

Run the curated test suite (excludes live-model quality tests):

```bash
python -m pytest tests/ --ignore=tests/test_local_llm_quality.py
```

Run the quantum consensus verification:

```bash
python scripts/quantum_sim_verify.py
```

Run the full release validation gate (same as CI):

```bash
python run.py validate
```

Coverage target is **80%** for all new code paths. A new feature without tests will not be merged.

---

## Code Style

- **Python**: formatted with [`ruff`](https://docs.astral.sh/ruff/). Run `ruff check .` and `ruff format .` before committing.
- **Shared state**: never mutate shared runtime objects in place — always produce new state (immutability discipline prevents race conditions in the async runtime).
- **Rust**: follow standard `rustfmt` conventions inside `chimera-core/`.
- **Secrets**: never commit tokens, passwords, or API keys. Use `config/runtime_profile.local.json` or environment variables.

---

## Commit Message Format

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <short description>

[optional body]

[optional footer: Closes #123]
```

Allowed types: `feat`, `fix`, `docs`, `test`, `chore`, `refactor`, `perf`, `ci`.

Examples:

```
feat(skills): add graph-traversal skill for autonomy plane
fix(rag): handle empty embedding response gracefully
docs: add contributing guide
test(quantum): add consensus round-trip regression test
```

---

## Pull Request Process

1. Fork the repository and create a feature branch from `main`:
   ```bash
   git checkout -b feat/my-feature
   ```
2. Make your changes, add tests, and ensure all checks pass locally.
3. Open a PR against `main`. Fill in the [PR template](.github/pull_request_template.md) completely.
4. A maintainer will review. Address feedback before requesting re-review.
5. Once approved, the PR will be squash-merged into `main`.

---

## Architecture Notes

When contributing, keep these runtime layers in mind:

- **QuantumEngine / consensus plane** (`core/quantum_engine.py`, `core/consensus_plane.py`): Probabilistic consensus model. Changes here require `quantum_sim_verify.py` to pass.
- **Skills plane** (`core/skills_plane.py`, `skills/`): Composable skill definitions. New skills should include a `SKILL.md` spec.
- **Swarms runtime** (`swarms/`): Multi-agent coordination layer. Side effects must be idempotent.
- **Inference plane** (`core/inference_plane.py`): Model routing and prompt strategy. Adaptive fallback logic lives here.
- **MCP server** (`core/mcp_server.py`): Tool-call protocol surface exposed to external agents.

---

## Recognition

All contributors are listed in [AUTHORS.md](AUTHORS.md). The full commit history is the canonical record — your name will appear there as soon as your PR is merged.
