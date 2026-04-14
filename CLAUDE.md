# OpenChimera — AI Assistant Guide (CLAUDE.md)

Reference for AI assistants (Claude Code and others) working on this codebase.

---

## Project Overview

**OpenChimera** is a local-first AGI orchestration runtime. It exposes an OpenAI-compatible REST
API on `http://127.0.0.1:7870` and coordinates ten interlocking cognitive subsystems (the
"recursive intelligence loop") including quantum consensus, multi-agent orchestration, episodic
memory, goal planning, and ethical reasoning. MIT licensed, Python 3.11+.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Primary language | Python 3.11+ |
| HTTP API | FastAPI + Uvicorn (`core/api_server.py`) |
| Data validation | Pydantic v2 (`core/schemas.py`) |
| Database | SQLite3 — Rust backend (`chimera_core.db`) with Python fallback |
| Semantic memory graph | NetworkX |
| Native extensions | Rust / PyO3 / Maturin (`chimera-core/`) — router, event bus, DB, FIM |
| Embeddings / local models | sentence-transformers, Transformers, torch (all optional) |
| LLM providers | OpenAI SDK, OpenRouter, Ollama, llama-server |
| Distributed rate limiting | Redis (optional, via `OPENCHIMERA_REDIS_URL`) |

---

## Repository Structure

```
core/               # ~110 Python modules — ALL runtime subsystems live here
chimera-core/       # Rust extension (PyO3/Maturin) — router, bus, DB, FIM daemon
skills/             # 200+ composable AI skills; each has a SKILL.md spec
swarms/             # GodSwarm multi-agent definitions and YAML registries
tests/              # 2600+ tests — unit, integration, e2e, benchmarks
config/             # Runtime profiles, subsystem registry, agent specs
docs/               # Architecture, API reference, AGI contracts
scripts/            # QA/CI scripts, quantum sim verifier, self-evolution cycle
run.py              # Main entry point — CLI dispatcher + release validation
pyproject.toml      # Python packaging and console_scripts entry point
Cargo.toml          # Rust workspace root
```

---

## Essential Commands

```bash
# --- Development setup ---
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pip install -e .
openchimera bootstrap
cp config/runtime_profile.local.example.json config/runtime_profile.local.json
# Edit runtime_profile.local.json for your machine — NEVER commit this file

# --- Run server ---
python run.py serve          # http://127.0.0.1:7870

# --- Test ---
python -m pytest tests/ --ignore=tests/test_local_llm_quality.py -q
python -m pytest tests/ --cov=core --cov-fail-under=60   # CI gate
python run.py validate                                     # full release gate (same as CI)
python scripts/quantum_sim_verify.py                      # consensus simulation

# --- Code quality ---
ruff check .
ruff format .
python -m pre_commit run --all-files

# --- Rust extension (optional) ---
cd chimera-core && maturin develop     # build in-place for development
cargo test -p chimera-core             # expects 19 passed

# --- Docker ---
docker-compose up --build -d
```

---

## Testing Rules

- **Framework**: pytest + pytest-asyncio for async tests (`@pytest.mark.asyncio`)
- **Coverage**: 80% target for new code; CI enforces **60% minimum** on the `core/` package
- **Excluded from CI**: `tests/test_local_llm_quality.py` (requires live models)
- **Suite runtime**: ~45 seconds; 2 expected skips on non-Windows
- New feature → new tests. PRs without tests will not be merged.
- `tests/test_agi_complete_loop.py` validates all 10 AGI capabilities end-to-end; do not break it.

---

## Code Style & Conventions

- **Formatter/Linter**: Ruff — `ruff check .` + `ruff format .` before every commit
- **Type hints**: Mandatory on all functions; use `from __future__ import annotations`
- **Docstrings**: Required for all public APIs
- **Imports**: No wildcard imports; ordered standard → third-party → local
- **Logging**: Per-module loggers — `LOGGER = logging.getLogger(__name__)`
- **Immutability discipline**: Never mutate shared runtime objects in place in async code.
  Always produce new state. This prevents race conditions across the async runtime.
- **Pydantic v2**: All API request/response models are defined in `core/schemas.py`
- **Error handling**: Explicit exception types with informative messages
- **Rust**: Follow `rustfmt` conventions inside `chimera-core/`

---

## Commit Message Format

[Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <short description>

[optional body]

[optional footer: Closes #123]
```

Allowed types: `feat`, `fix`, `docs`, `test`, `chore`, `refactor`, `perf`, `ci`

```
feat(skills): add graph-traversal skill for autonomy plane
fix(rag): handle empty embedding response gracefully
test(quantum): add consensus round-trip regression test
docs: update architecture guide for MCP integration
```

---

## Architecture Patterns

**Event-driven**: Components communicate via `EventBus` (`core/bus.py`) — do not couple them
directly. Use pub/sub.

**Graceful degradation**: `core/kernel.py` wraps optional subsystems in try/except at boot.
If Rust extensions are missing, Python fallbacks activate transparently. Never break the boot path.

**Configuration injection**: Major components receive a config/profile object at init — do not
reach into global state.

**Planes architecture**: Core operations flow through four planes:
- `core/inference_plane.py` — model routing and prompt strategy
- `core/consensus_plane.py` — consensus protocol orchestration
- `core/autonomy_plane.py` — self-directed background work
- `core/skills_plane.py` — composable skill execution

**Quantum consensus**: Multi-agent voting lives in `core/quantum_engine.py`. Any change here
**must** be verified with `python scripts/quantum_sim_verify.py`.

**Rust fallbacks**: Code using `chimera_core.*` must always be wrapped with try/except and a
pure-Python fallback path.

---

## Critical Files

| File | Role |
|------|------|
| `run.py` | CLI entry point (all `openchimera` subcommands) |
| `core/kernel.py` | Boots all subsystems in dependency order |
| `core/api_server.py` | FastAPI server — all REST routes, auth, rate limiting |
| `core/provider.py` | OpenAI-compatible provider, multi-model routing |
| `core/quantum_engine.py` | Quantum consensus engine — change with caution |
| `core/config.py` | Configuration loading — env vars, profiles, defaults |
| `core/schemas.py` | All Pydantic data models for API contracts |
| `core/bus.py` | EventBus — inter-component pub/sub |
| `core/database.py` | DB wrapper (Rust or Python backend) |
| `core/autonomy.py` | Autonomy scheduler — background jobs, self-repair |
| `core/memory_system.py` | Memory facade (episodic, semantic, working) |
| `core/migrations/*.sql` | Database schema migrations — applied in numbered order |
| `config/runtime_profile.json` | Published safe defaults |
| `config/runtime_profile.local.json` | Machine-specific overrides — **gitignored, never commit** |
| `config/subsystems.json` | 18-subsystem dynamic registry |
| `.github/workflows/python-ci.yml` | CI pipeline definition |

---

## Configuration System

Layered precedence (highest wins):

1. Environment variables
2. `config/runtime_profile.local.json` (gitignored, machine-specific)
3. `config/runtime_profile.json` (published safe defaults)
4. Hardcoded defaults in `core/config.py`

**Key env vars**:

| Variable | Default | Purpose |
|----------|---------|---------|
| `OPENCHIMERA_HOST` | `127.0.0.1` | Bind address |
| `OPENCHIMERA_PORT` | `7870` | API port |
| `OPENCHIMERA_API_TOKEN` | *(empty)* | Bearer token — empty disables auth |
| `OPENCHIMERA_LOG_LEVEL` | `INFO` | DEBUG/INFO/WARNING/ERROR |
| `OPENCHIMERA_REDIS_URL` | *(empty)* | Enables distributed rate limiting |
| `OPENAI_API_KEY` | — | OpenAI provider |
| `OPENROUTER_API_KEY` | — | OpenRouter provider |
| `HUGGINGFACEHUB_API_TOKEN` | — | HuggingFace Hub |
| `AETHER_ROOT` / `WRAITH_ROOT` / `EVO_ROOT` | — | Optional external subsystem roots |

See `.env.example` for the full list of ~40 documented variables.

---

## Security Practices

- **No secrets in git**: API keys, tokens, and passwords belong in `.env` (gitignored) or
  `config/runtime_profile.local.json` (gitignored). Use `.env.example` as the template.
- **Bandit**: Security scanner runs in CI. Config in `.bandit`. Documented exceptions exist for
  B310 (urllib with validated URLs), B608 (parameterized SQL), and B101 (type-narrowing asserts).
- **pip-audit**: CVE scans run against `requirements-prod.lock` in CI with `--strict`.
- **Non-root Docker**: Container runs as `openchimera` user.
- **Credential isolation**: Provider API keys are stored in the `credentials` DB table via
  `core/credential_store.py`, never in source files.

---

## Adding Skills

1. Create `skills/<skill-name>/` directory
2. Add a `SKILL.md` spec (purpose, inputs, outputs, examples)
3. Add the skill implementation
4. Register the skill in `core/skill_registry.py` if it needs to be auto-discovered
5. Add tests in `tests/`

---

## CI/CD Pipeline

Main workflow: `.github/workflows/python-ci.yml`

**Jobs** (sequential):

| Job | What runs |
|-----|-----------|
| `test` (Ubuntu + Windows) | pip-audit, pre-commit (Linux), `run.py validate`, quantum sim, pytest 60% coverage, AGI integration tests |
| `full-discovery` | Complete test sweep via `run.py validate --pattern test_*.py` |
| `build` | `python -m build` — sdist + wheel |
| `smoke-install` | Installs wheel, runs `bootstrap`, `doctor`, `status`, `backup create` |

All `test` and `full-discovery` jobs must pass before merge.

---

## Common Pitfalls

- **Never mutate shared runtime objects** in async code — always produce new state
- **Never change `core/quantum_engine.py`** without running `scripts/quantum_sim_verify.py`
- **Never commit `config/runtime_profile.local.json`** — it is gitignored intentionally
- **Never skip `ruff` formatting** — pre-commit will reject the commit
- **Never break the kernel boot order** in `core/kernel.py` — subsystems have dependencies
- **Never add wildcard imports** (`from module import *`)
- **Always wrap `chimera_core.*` imports** in try/except with a pure-Python fallback
- **Always include `SKILL.md`** when adding a new skill to `skills/`
- **Always use `@pytest.mark.asyncio`** for async test functions
