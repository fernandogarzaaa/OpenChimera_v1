# Contributing to OpenChimera

Welcome, and thank you for your interest in contributing to OpenChimera — a local-first, open-source AI orchestration runtime built around quantum consensus, skills composition, and swarm-scale operator workflows.

Every bug report, documentation improvement, plugin, or feature strengthens the ecosystem. This guide explains how to contribute effectively.

---

## Project Values

OpenChimera is built around three core values that guide every contribution decision:

- **Local-first** — the control plane stays on your machine. No telemetry, no forced cloud dependencies.
- **Privacy** — secrets never enter committed files. Users own their data and credentials.
- **Open weights** — the project is designed to work with openly licensed local models and openly auditable code.

Contributions that conflict with these values (e.g., adding mandatory cloud telemetry, committing tokens, or requiring proprietary model access) will not be accepted.

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

### 4. Install pre-commit hooks

```bash
pre-commit install
```

This installs hooks that run Black, ruff, and mypy automatically before each commit.

### 5. Bootstrap local state

```bash
openchimera bootstrap
```

Copy the example local runtime override and edit it for your machine (never commit this file):

```bash
cp config/runtime_profile.local.example.json config/runtime_profile.local.json
```

### 6. Rust components (optional)

If you are working on the low-level consensus core in `chimera-core/`:

```bash
cd chimera-core
cargo build
```

Rust 1.75+ is recommended. The Python runtime does not require the Rust build to function.

---

## Code Style

- **Formatting**: formatted with [`black`](https://black.readthedocs.io/). Run `black .` before committing.
- **Linting**: [`ruff`](https://docs.astral.sh/ruff/) for fast linting. Run `ruff check .` and `ruff format .` before committing.
- **Type checking**: [`mypy`](https://mypy.readthedocs.io/) for static type analysis. Run `mypy core/` to check the core package.
- **Shared state**: never mutate shared runtime objects in place — always produce new state (immutability discipline prevents race conditions in the async runtime).
- **Rust**: follow standard `rustfmt` conventions inside `chimera-core/`.
- **Secrets**: never commit tokens, passwords, or API keys. Use `config/runtime_profile.local.json` or environment variables.

Run all style checks together:

```bash
black --check .
ruff check .
mypy core/
```

---

## Branch Naming Convention

Use a consistent prefix so branches are easy to categorize:

| Prefix | Use for |
|--------|---------|
| `feat/` | New features |
| `fix/` | Bug fixes |
| `docs/` | Documentation changes |
| `test/` | Adding or improving tests |
| `chore/` | Maintenance, dependency updates, tooling |
| `refactor/` | Code restructuring without functional change |
| `perf/` | Performance improvements |
| `ci/` | CI/CD pipeline changes |

Examples: `feat/streaming-consensus`, `fix/rag-empty-embedding`, `docs/quickstart-linux`

---

## Commit Message Convention

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

## Running Tests

Run the full test suite:

```bash
pytest tests/ -q
```

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

## Pull Request Process

1. Fork the repository and create a feature branch from `main` using the branch naming convention above:
   ```bash
   git checkout -b feat/my-feature
   ```
2. Make your changes, add tests, and ensure all checks pass locally.
3. Open a PR against `main`. Fill in the [PR template](.github/PULL_REQUEST_TEMPLATE.md) completely.
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

## Code of Conduct

This project follows the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md). By participating, you agree to uphold it. Report violations to `security@openchimera.ai`.

---

## Recognition

All contributors are listed in [AUTHORS.md](AUTHORS.md). The full commit history is the canonical record — your name will appear there as soon as your PR is merged.
