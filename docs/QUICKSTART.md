# OpenChimera Quickstart

A practical, plain-language walkthrough of what OpenChimera is and how to run
it. Every command below was run against the current build; sample output is
real.

## What it is, in one paragraph

OpenChimera is a **local-first orchestration runtime**. You run one Python
process that exposes an **OpenAI-compatible HTTP API** on
`http://127.0.0.1:7870`, plus a `openchimera` command-line tool. It routes
requests to local models (and, optionally, cloud providers), and adds
retrieval (RAG), tool/skill execution, operator jobs, browser actions, and MCP
server discovery on top. You bring the model; OpenChimera is the gateway and
control plane around it.

## Is it "finished"? What "degraded" means

The runtime itself is functional and tested — it boots, serves the API, and
passes its release validation suite. What it does **not** ship is a model: out
of the box there is no local `llama-server` binary and no model files, so
`doctor` reports **degraded** and generation calls have nothing to run against.
That is expected. Add a model (below) and the degraded warnings clear. Think
"works, bring your own model," not "unfinished."

## 1. Install

```bash
# From a clone of the repo:
python -m venv .venv
source .venv/bin/activate          # Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements-prod.lock
pip install -e .                   # provides the `openchimera` command
```

`openchimera` and `python run.py` are the same entry point — use either.

## 2. First-time setup

```bash
openchimera setup        # bootstraps local state (data/ dirs, seed config) + diagnostics
```

It prints next steps. Two more inspection commands are useful immediately:

```bash
openchimera doctor       # install/config diagnostics + what's missing
openchimera status       # runtime status snapshot
```

`doctor` will list things like "llama-server executable not found" and "no
local GGUF model assets" — that is the model gap from the section above, not a
broken install.

## 3. Add a model (clears "degraded")

OpenChimera runs GGUF models through a local `llama-server`. Point it at a
model file you already have:

```bash
openchimera onboard --register-local-model-path /path/to/model.gguf \
                    --register-local-model-id my-model
```

You can also configure cloud providers (OpenAI, etc.) and other options with
`openchimera onboard` and `openchimera configure`.

## 4. Start the server

```bash
openchimera serve        # boots the API on http://127.0.0.1:7870 (Ctrl+C to stop)
```

Check it from another shell:

```bash
curl http://127.0.0.1:7870/health
```

```json
{
  "status": "degraded",
  "name": "openchimera",
  "base_url": "http://127.0.0.1:7870",
  "components": {"local_llm": false, "rag": true, "router": true, "autonomy": true},
  "healthy_models": 0,
  "known_models": 4
}
```

(`status` becomes `ok` once a model is registered and healthy.)

List the models the gateway knows about — this endpoint is OpenAI-compatible:

```bash
curl http://127.0.0.1:7870/v1/models
```

## 5. Call it like the OpenAI API

Once a model is healthy, point any OpenAI-compatible client at the base URL:

```bash
curl http://127.0.0.1:7870/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "my-model", "messages": [{"role": "user", "content": "Hello"}]}'
```

Or use the CLI without writing HTTP:

```bash
openchimera query "Summarize the runtime status"
```

## Authentication (for non-local use)

Auth is **off by default** because the server binds to loopback for local use.
If you expose it beyond localhost, enable token auth — the server refuses to
bind to a non-loopback address without it. Set:

```bash
export OPENCHIMERA_API_TOKEN=your-user-token
export OPENCHIMERA_ADMIN_TOKEN=your-admin-token
```

Then send `Authorization: Bearer <token>`. Admin-only routes (and admin tools)
require the admin token; the scope is bound to the token, never to the request
body.

## The CLI at a glance

`openchimera <command>` — the commands you'll actually use first:

| Command | What it does |
|---|---|
| `setup` | One-step first-time setup: bootstrap + diagnostics + next steps |
| `serve` | Boot the runtime and API server on `127.0.0.1:7870` |
| `doctor` | Install/config diagnostics; tells you what's missing |
| `status` | Runtime status snapshot |
| `onboard` | Register a local model, add cloud keys, set preferences |
| `configure` | Configure capabilities, cloud API keys, remote channels |
| `query` | Run a query through the query engine from the terminal |
| `capabilities` | Inspect registered commands / tools / skills / plugins / mcp |
| `skills` | Discover or inspect registered skills |
| `tools` | Inspect or execute runtime tools |
| `config` | Show a safe (secret-free) runtime configuration snapshot |
| `validate` | Run the canonical release validation suite |

Run `openchimera <command> --help` for the flags on any of them.

## Where things live

- `core/` — the runtime: API server, provider/router, query engine, RAG,
  capability/skill/tool registries, subsystems.
- `skills/` — the skill library discovered at startup (each `SKILL.md` is one
  skill).
- `config/runtime_profile.local.json` — your machine-specific overrides
  (tokens, model paths, TLS). Local-only; keep secrets here, not in the repo.
- `run.py` — the CLI entry point (`openchimera`).

## Troubleshooting

- **`doctor` says degraded / `local_llm: false`** — no model registered yet.
  See step 3.
- **Generation returns nothing / model "offline"** — `llama-server` isn't
  running or the GGUF path is wrong; re-check `openchimera onboard`.
- **Refuses to start on a non-loopback host** — set
  `OPENCHIMERA_API_TOKEN` + `OPENCHIMERA_ADMIN_TOKEN` (see Authentication), or
  bind to `127.0.0.1` for local use.
