# OpenChimera v2

> **Agentic orchestration runtime** — Rust TUI, 17+ modern AI providers, computer use, cognitive stack (AXIOM/EVE/ADAM), and one-liner install.

[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://python.org)
[![Rust](https://img.shields.io/badge/rust-1.80%2B-orange)](https://rust-lang.org)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

---

## 🚀 One-Liner Install

### Windows (PowerShell)
```powershell
iwr -useb https://raw.githubusercontent.com/fernandogarzaaa/OpenChimera_v1/main/install.ps1 | iex
```

### macOS / Linux / WSL
```bash
curl -fsSL https://raw.githubusercontent.com/fernandogarzaaa/OpenChimera_v1/main/install.sh | bash
```

### Manual (Python)
```bash
git clone https://github.com/fernandogarzaaa/OpenChimera_v1.git
cd OpenChimera_v1
pip install -e ".[all]"
openchimera onboard
```

---

## ⚡ Quick Start

```bash
# Interactive setup wizard
openchimera onboard

# Run diagnostics
openchimera doctor

# Start the API server
openchimera serve

# Launch the Rust TUI
openchimera tui

# One-off query (no server needed)
openchimera ask "What is the capital of France?" --provider openai

# Check status
openchimera status
```

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Rust TUI  ←→  Python FastAPI  ←→  17+ AI Providers         │
│                     ↓                                        │
│     Tools · MCP · RAG · Cognitive (AXIOM/EVE/ADAM)         │
│                     ↓                                        │
│        TypeScript Dashboard (Vite + React)                   │
└─────────────────────────────────────────────────────────────┘
```

| Layer | Tech | What it does |
|---|---|---|
| **Rust TUI** | Ratatui | Real-time terminal UI with provider health, agent status, cognitive monitoring |
| **Python Runtime** | FastAPI + Click | API server, CLI, agent orchestration, tool execution |
| **Providers** | 17 adapters | OpenAI, Anthropic, Google, Groq, Ollama, DeepSeek, Mistral, Cohere, Azure, Together, Fireworks, xAI, Perplexity, OpenRouter, Bedrock, Cerebras, AI21 |
| **Tools** | 25+ built-in | Browser automation, computer use (screenshot/click/type), shell exec, file ops, code sandbox, GitHub, web search, RAG, cognitive tools, godmode |
| **Cognitive** | AXIOM/EVE/ADAM | Memory + grounding, UX validation, cognitive substrate with genome evolution |
| **Dashboard** | Vite + React | Real-time monitoring at `http://localhost:3000` |

---

## 🔧 Configuration

### Environment Variables

Set API keys as environment variables (recommended for security):

```powershell
# Windows PowerShell
$env:OPENAI_API_KEY = "sk-..."
$env:ANTHROPIC_API_KEY = "sk-ant-..."
$env:GROQ_API_KEY = "gsk_..."
```

```bash
# macOS / Linux
export OPENAI_API_KEY="sk-..."
export ANTHROPIC_API_KEY="sk-ant-..."
export GROQ_API_KEY="gsk_..."
```

### Config Files

Layered YAML configuration:
- `config/default.yaml` — Base config (checked in)
- `config/local.yaml` — Your local overrides (gitignored)
- `OPENCHIMERA_CONFIG` env var — Custom config path

```yaml
# config/local.yaml
providers:
  openai:
    enabled: true
    api_key: "${OPENAI_API_KEY}"
    default_model: "gpt-4o"
  anthropic:
    enabled: true
    api_key: "${ANTHROPIC_API_KEY}"
```

---

## 🧠 Cognitive Stack

OpenChimera v2 integrates the owner's cognitive architecture:

- **AXIOM** — Long-term memory + grounding. Auto-recalls past decisions before re-deriving.
- **EVE** — Simulated-human UX validation. Predicts UX outcomes before building.
- **ADAM** — Persistent cognitive substrate. Genome evolution, beliefs, skills lifecycle.

```bash
# Activate godmode (full cognitive loop)
# The AI can tool-call godmode.activate to use cognitive tools

# Via API
POST /api/v2/tools/execute
{
  "tool_id": "godmode.activate",
  "arguments": {"action": "recall", "query": "What did we decide about auth?"}
}
```

---

## 🖥️ Computer Use

Browser automation and desktop control:

```bash
# Navigate and screenshot
POST /api/v2/tools/execute
{
  "tool_id": "browser.navigate",
  "arguments": {"url": "https://example.com"}
}

# Take desktop screenshot
POST /api/v2/tools/execute
{
  "tool_id": "computer.screenshot",
  "arguments": {}
}
```

---

## 📊 Dashboard

```bash
cd typescript/dashboard
npm install
npm run dev
# Opens at http://localhost:3000
```

---

## 🛠️ Development

```bash
# Python
pip install -e ".[all,dev]"
pytest

# Rust
cd crates/chimera-tui
cargo build --release

# TypeScript
cd typescript/dashboard
npm install
npm run dev
```

---

## 📜 License

MIT © Fernando Garza
