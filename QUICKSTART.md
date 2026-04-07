# OpenChimera — Quick Start

This guide shows what actually works when you clone the repo and install from source.
Every command below runs without API keys, paid accounts, or external services.

---

## Requirements

- **Python 3.11 or later** (3.12+ recommended)
- A terminal with internet access for initial `pip install`
- That's it — no Docker, no cloud accounts, no GPU required for the basic runtime

---

## Five-minute setup

```bash
# 1. Clone and enter the repo
git clone https://github.com/fernandogarzaaa/OpenChimera_v1.git openchimera
cd openchimera

# 2. Create a virtual environment and install
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\Activate.ps1

# 3. Install all production dependencies
pip install -r requirements-prod.lock

# 4. Install OpenChimera in editable mode
pip install -e .

# 5. Bootstrap missing local state (creates data/ dirs, seed JSON)
openchimera bootstrap

# 6. Run the diagnostics check
openchimera doctor

# 7. Start the runtime (Ctrl+C to stop)
openchimera serve
```

The server starts on `http://127.0.0.1:7870` by default (loopback only).

---

## Verify it's alive

From a second terminal (keep the server running):

```bash
# Activate the same virtual environment
source .venv/bin/activate          # Windows: .venv\Scripts\Activate.ps1

# Health ping
curl http://127.0.0.1:7870/health

# Readiness breakdown
curl http://127.0.0.1:7870/v1/system/readiness

# OpenAPI contract
curl http://127.0.0.1:7870/openapi.json | python -m json.tool | head -40
```

Or via the CLI:

```bash
openchimera status --json
```

---

## What runs out of the box

| Feature | Works without config |
|---|---|
| `openchimera doctor` | Yes — checks config, not services |
| `openchimera status` | Yes — local snapshot, no server needed |
| `openchimera bootstrap` | Yes — creates missing dirs and state |
| `openchimera capabilities` | Yes — shows locally detected tools/skills |
| `openchimera serve` | Yes — API starts in degraded-but-alive mode |
| `/health` + `/v1/system/readiness` | Yes |
| `/openapi.json` + `/docs` | Yes |
| Local query routing | Requires Ollama or a llama-server binary |
| Cloud model routing | Requires provider API key in runtime profile |
| MiniMind reasoning | Requires MiniMind weights |

---

## Add a local model with Ollama

If you have [Ollama](https://ollama.ai) installed:

```bash
ollama pull gemma3:4b        # or any model you prefer
# Ollama runs at http://127.0.0.1:11434 automatically

openchimera serve            # OpenChimera detects Ollama and routes to it
openchimera query --text "hello world"
```

---

## Add a local override config

Machine-specific settings go in a local-only file that is gitignored:

```bash
cp config/runtime_profile.local.example.json config/runtime_profile.local.json
# Edit the copy — set llama_server_path, API keys, etc.
```

The runtime merges this file on top of the committed defaults at startup.

---

## Running the tests

```bash
# Install dev dependencies (includes pytest, coverage, pre-commit)
pip install -r requirements-dev.txt

# Run the full test suite (2467 tests, ~40 seconds)
python -m pytest tests/ -q
```

Expected output: **2467 passed, 2 skipped** in under one minute on any modern machine.

---

## Diagnostics for common problems

```bash
# Check configuration health
openchimera doctor

# Check production-readiness (WAL mode, auth, TLS, migrations, bind safety)
openchimera doctor --production

# Print the effective sanitized config (no secret values)
openchimera config --json
```

---

## What's next

- [README.md](README.md) — Full feature reference, API surface, and configuration guide
- [SECURITY.md](SECURITY.md) — Security expectations and reporting process
- [LEGACY_INTEGRATIONS.md](LEGACY_INTEGRATIONS.md) — Optional external integrations (AETHER, MiniMind, etc.)
- `.env.example` — All supported environment variables with documentation
- `config/runtime_profile.local.example.json` — Example local config overlay
