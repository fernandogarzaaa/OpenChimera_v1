# OpenChimera — Quick Start

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

Open **http://127.0.0.1:7870/docs** in your browser — you're done!

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

## What works out of the box

| Feature | Works without config |
|---|---|
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
