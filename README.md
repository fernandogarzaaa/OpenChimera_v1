# OpenChimera v2

**OpenChimera v2** is a next-generation agentic orchestration runtime. It unifies a blazing-fast Rust TUI, a modern Python AI runtime with the latest model providers, native MCP tooling, RAG, skills, and deep integration with the AXIOM / EVE / ADAM cognitive stack.

> 🎯 **Assessment ready** — one-liner install, zero assumptions, works out of the box.

---

## ✨ What's New in v2

| Feature | v1 | v2 |
|---|---|---|
| **TUI** | None | Ratatui-powered real-time terminal UI |
| **Providers** | OpenAI only | OpenAI, Anthropic, Google, Groq, Ollama |
| **Tool Calling** | Basic | Full JSON-schema tool registry + execution |
| **MCP** | Registry only | Full MCP client with stdio/HTTP |
| **RAG** | None | ChromaDB + sentence-transformers |
| **Cognitive Stack** | External references | Native AXIOM/EVE/ADAM bridge |
| **Install** | Multi-step manual | One-liner PowerShell |
| **Architecture** | Monolithic Python | Rust + Python + TypeScript monorepo |

---

## 🚀 One-Liner Install (PowerShell)

```powershell
irm https://raw.githubusercontent.com/fernandogarzaaa/OpenChimera_v2/main/install.ps1 | iex
```

Or clone and run locally:

```powershell
git clone https://github.com/fernandogarzaaa/OpenChimera_v2.git
cd OpenChimera_v2
.\install.ps1
```

The installer will:
1. Check Python 3.11+ and Rust
2. Create a virtual environment
3. Install all Python dependencies
4. Build the Rust TUI
5. Build the TypeScript dashboard (if Node is present)
6. Bootstrap a local config file

---

## 🖥️ Quick Start

### 1. Configure providers

Edit `config/local.yaml` and add your API keys:

```yaml
providers:
  openai:
    enabled: true
    api_key: "sk-..."
  anthropic:
    enabled: true
    api_key: "sk-ant-..."
```

Or use environment variables:

```powershell
$env:OPENCHIMERA_PROVIDERS__OPENAI__API_KEY = "sk-..."
```

### 2. Start the API server

```powershell
.venv\Scripts\openchimera serve
```

The server runs at `http://127.0.0.1:7870` with auto-generated docs at `/docs`.

### 3. Launch the TUI

```powershell
# Live mode (connects to running server)
.\target\release\openchimera.exe

# Demo mode (simulated data for offline demo)
.\target\release\openchimera.exe --demo
```

### 4. Run diagnostics

```powershell
.venv\Scripts\openchimera doctor
```

---

## 🏗️ Architecture

```
openchimera/
├── crates/
│   ├── chimera-core/      # Shared Rust types
│   ├── chimera-tui/       # Ratatui terminal UI
│   └── chimera-bridge/    # Rust-Python bridge types
├── python/openchimera/
│   ├── api/routes.py      # FastAPI v2 surface
│   ├── providers/         # OpenAI, Anthropic, Google, Groq, Ollama
│   ├── tools/registry.py  # Built-in + extensible tool registry
│   ├── mcp/client.py      # MCP stdio client
│   ├── cognitive/bridge.py# AXIOM / EVE / ADAM integration
│   ├── agent.py           # Agent orchestrator
│   └── rag/engine.py      # RAG pipeline
├── typescript/dashboard/  # Vite + React web dashboard
└── config/
    ├── default.yaml       # Safe defaults
    └── local.yaml         # Your local overrides (gitignored)
```

---

## 🧠 Cognitive Stack Integration

OpenChimera v2 natively integrates the unified cognitive architecture:

- **AXIOM** — Long-term memory, grounding, and drift evaluation. Recall prior decisions before acting, remember conventions after fixing bugs.
- **EVE** — Simulated-human UX validation. Predict and validate interfaces before building.
- **ADAM** — Persistent cognitive substrate. Genome state, belief tracking, skill lifecycle, and governed evolution.

The cognitive bridge attempts to connect to the local MCP gateway (`127.0.0.1:8788`) and surfaces status in both the API and the TUI.

---

## 🔌 API Surface (v2)

| Method | Route | Description |
|---|---|---|
| GET | `/health` | Liveness probe |
| GET | `/api/v2/status` | Full system status |
| GET | `/api/v2/providers` | Provider health list |
| GET | `/api/v2/agents` | Active agent list |
| POST | `/api/v2/agents/spawn` | Spawn a new agent |
| POST | `/api/v2/query` | Chat completion with optional tool execution |
| GET | `/api/v2/tools` | List registered tools |
| POST | `/api/v2/tools/execute` | Execute a tool by ID |
| GET | `/api/v2/cognitive/status` | AXIOM / EVE / ADAM status |

---

## 🛠️ Built-in Tools

| Tool | Category | Admin |
|---|---|---|
| `browser.fetch` | web | No |
| `github.search_code` | integration | No |
| `file.read` | filesystem | No |
| `shell.exec` | system | Yes |
| `rag.query` | retrieval | No |
| `axiom.recall` | cognitive | No |
| `eve.predict_ux` | cognitive | No |
| `adam.genome` | cognitive | No |

---

## ⌨️ TUI Keybindings

| Key | Action |
|---|---|
| `Tab` / `l` | Next tab |
| `Shift+Tab` / `h` | Previous tab |
| `1`–`7` | Jump to tab |
| `/` | Quick query |
| `i` | Input mode |
| `↑` / `↓` | Scroll lists |
| `Ctrl+C` / `q` | Quit |

---

## 🧪 Development

```powershell
# Run Python tests
.venv\Scripts\pytest python/tests -q

# Run Rust checks
cd crates/chimera-tui
cargo check

# Run dashboard dev server
cd typescript/dashboard
npm run dev
```

---

## 📜 License

MIT — see [LICENSE](LICENSE).
