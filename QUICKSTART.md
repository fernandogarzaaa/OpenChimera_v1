# OpenChimera — Quick Start

## 🚀 One-Liner Install (Recommended)

**Windows (PowerShell):**

```powershell
irm https://raw.githubusercontent.com/fernandogarzaaa/OpenChimera_v1/main/install.ps1 | iex
```

**Linux/macOS (bash):**

```bash
curl -fsSL https://raw.githubusercontent.com/fernandogarzaaa/OpenChimera_v1/main/install.sh | bash
```

This will set up a virtual environment, install dependencies, and print next steps. To run OpenChimera after install:

```bash
# Activate your environment (Linux/macOS)
source .venv/bin/activate
# or (Windows)
.\.venv\Scripts\Activate.ps1

# Start OpenChimera
python run.py
```

For onboarding:

```bash
python run.py onboard
```

---

Get running in **three steps**. No Docker, no cloud accounts, no GPU required.

---

## Prerequisites

- **Python 3.11+** — [download here](https://www.python.org/downloads/) (check "Add Python to PATH" on Windows)
- A terminal with internet access for the initial install

---

## Setup (one command)

### Windows (PowerShell)

```powershell
git clone https://github.com/fernandogarzaaa/OpenChimera_v1.git openchimera
cd openchimera
.\setup.ps1
```

### macOS / Linux

```bash
git clone https://github.com/fernandogarzaaa/OpenChimera_v1.git openchimera
cd openchimera
bash setup.sh
```

The setup script automatically creates a virtual environment, installs all
dependencies, bootstraps workspace state, and runs diagnostics.

---

## Start the server

```bash
# Activate the virtual environment (once per terminal session)
# Windows:
.venv\Scripts\Activate.ps1

# macOS / Linux:
source .venv/bin/activate

# Start OpenChimera
openchimera serve
```

Open [http://127.0.0.1:7870/docs](http://127.0.0.1:7870/docs) in your browser — you're done!

---

## Verify it's alive

From a second terminal (keep the server running):

```bash
curl http://127.0.0.1:7870/health
```

Or via the CLI:

```bash
openchimera status
```

---

## Optional: connect a local AI model

Install [Ollama](https://ollama.ai), then:

```bash
ollama pull gemma3:4b
# Restart openchimera serve — it auto-detects Ollama
openchimera query --text "hello world"
```

---

## Manual setup (advanced)

If you prefer to run each step yourself instead of using the setup script:

```bash
git clone https://github.com/fernandogarzaaa/OpenChimera_v1.git openchimera
cd openchimera

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\Activate.ps1

pip install -e .
openchimera setup                  # bootstrap + diagnostics in one step
openchimera serve
```

---

## Production install

For a pinned, repeatable production deployment install from `requirements-prod.txt`
instead of `pip install -e .`:

```bash
# 1. Create and activate a fresh virtual environment
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\Activate.ps1

# 2. Install all pinned production dependencies
pip install -r requirements-prod.txt

# 3. Install OpenChimera itself (non-editable)
pip install .

# 4. Bootstrap workspace state
python run.py bootstrap

# 5. Verify
python run.py status
python run.py doctor --production
```

### Environment variables

Copy `.env.example` to `.env` and set any values you need (all are optional — the
runtime has safe defaults for everything):

```bash
cp .env.example .env
# Edit .env — at minimum set OPENCHIMERA_API_TOKEN for network-exposed deployments
```

OpenChimera does **not** auto-load `.env` files. Export variables in your shell,
systemd unit (`EnvironmentFile=`), or Docker Compose `env_file:` block.

### Connecting a local LLM

The API server starts and responds to health checks without any model configured.
To enable actual LLM inference:

```bash
# Option A: Ollama (easiest, free)
# Install from https://ollama.ai, then:
ollama pull gemma3:4b
# OpenChimera auto-detects Ollama at localhost:11434 on next restart.

# Option B: llama-server (llama.cpp)
# Set llama_server_path in config/runtime_profile.local.json.

# Option C: Cloud provider
# Set OPENAI_API_KEY or equivalent in .env or your shell.
```

### What "degraded" status means

`python run.py status` will show **degraded** on a fresh install because the four
optional subsystems (AETHER, WRAITH, Evo, Aegis) are separate repositories not
bundled with this repo. The core API, Ascension swarm, God Swarm, audit pipeline,
and chimeralang-mcp integration all work normally in this state.
See [LEGACY_INTEGRATIONS.md](LEGACY_INTEGRATIONS.md) for setup instructions.

---

## What works out of the box

| Feature | Works without config |
| --- | --- |
| `openchimera serve` | Yes — API starts in degraded-but-alive mode |
| `openchimera status` | Yes — local snapshot |
| `openchimera doctor` | Yes — checks config health |
| `openchimera capabilities` | Yes — shows detected tools/skills |
| `/health` + `/docs` | Yes |
| Local query routing | Requires Ollama or llama-server |
| Cloud model routing | Requires provider API key |

---

## Add a local override config

Machine-specific settings go in a gitignored file:

```bash
cp config/runtime_profile.local.example.json config/runtime_profile.local.json
# Edit the copy — set llama_server_path, API keys, etc.
```

---

## Running the tests

```bash
pip install -r requirements-dev.txt
python -m pytest tests/ -q
```

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
