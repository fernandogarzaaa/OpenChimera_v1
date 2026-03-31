# OpenChimera

OpenChimera is the local orchestration shell that composes multiple D: drive runtimes into one system and now hosts its own local model provider.

## Runtime Topology

- `AETHER`: async event bus, plugin host, and immune-system style evolution loop
- `WRAITH`: day/night background orchestration
- `Project Evo`: autonomous swarm execution
- `OpenChimera Provider`: in-repo OpenAI-compatible local model provider, RAG, and context compression on `http://127.0.0.1:7870`
- `Autonomy Scheduler`: native recurring jobs for model-registry sync, skill audit, and MiniMind dataset refresh

## Native Local Model Runtime

OpenChimera now contains its own llama.cpp process control layer. It can manage the configured local model endpoints directly instead of assuming they were started by OpenClaw.

It also keeps a small persistent route-memory file at `data/local_llm_route_memory.json` so model selection can adapt over time based on successful completions, failures, and low-quality output rejections. Recent outcomes are weighted more heavily than stale ones so one bad run does not permanently poison a model.

Local llama.cpp requests are also prompt-shaped by model family: smaller/faster models receive a flattened plain-text instruction block, while larger chat-capable models keep chat structure with extra output-style guidance.

Prompt shaping now learns per model and query type from live traffic. The route-memory file stores prompt-strategy outcomes, so models can start with the strategy that has actually been succeeding instead of always using the static family default.

Chat completion responses now include an `openchimera` metadata block with routing/debug fields such as `query_type`, `attempted_models`, `route_reason`, `prompt_strategy`, and `prompt_strategies_tried` so live prompt behavior and same-model recovery attempts are inspectable without reading logs.

- Runtime status: `GET /v1/runtime/status`
- Model registry status: `GET /v1/model-registry/status`
- Refresh model registry: `POST /v1/model-registry/refresh`
- Hardware-aware onboarding status: `GET /v1/onboarding/status`
- Advanced integration audit: `GET /v1/integrations/status`
- Aegis bridge status: `GET /v1/aegis/status`
- Safe Aegis workflow preview or execution: `POST /v1/aegis/run`
- Ascension consensus status: `GET /v1/ascension/status`
- Ascension multi-perspective deliberation: `POST /v1/ascension/deliberate`
- Daily operator briefing: `GET /v1/briefings/daily`
- Start configured local models: `POST /v1/runtime/start`
- Stop managed local models: `POST /v1/runtime/stop`
- Harness port status: `GET /v1/harness/status`
- Autonomy status: `GET /v1/autonomy/status`
- Start autonomy scheduler: `POST /v1/autonomy/start`
- Stop autonomy scheduler: `POST /v1/autonomy/stop`
- Run one autonomy job: `POST /v1/autonomy/run`
- MiniMind status: `GET /v1/minimind/status`
- Build MiniMind datasets from upstream harness + OpenChimera context: `POST /v1/minimind/dataset/build`
- Start MiniMind reasoning server: `POST /v1/minimind/server/start`
- Stop MiniMind reasoning server: `POST /v1/minimind/server/stop`
- Start MiniMind training job: `POST /v1/minimind/training/start`
- Stop MiniMind training job: `POST /v1/minimind/training/stop`

The launcher configuration lives in `config/runtime_profile.json` under `local_runtime.launcher`.

OpenChimera also now maintains a modular provider and model catalog under `data/model_registry.json`. It merges the runtime profile with a curated local/cloud model inventory, produces hardware-aware local-model recommendations during onboarding, and emits an AirLLM-inspired MiniMind optimization profile tuned for constrained-memory training and inference.

The model registry now also merges in synced scouted models from `data/autonomy/scouted_models_registry.json` and can optionally pull remote discovery sources defined in `config/runtime_profile.json`, which moves it closer to OpenClaw-style live provider catalogs instead of a static list.

## Running

From `D:\OpenChimera`:

```powershell
python run.py
```

`run.py` will:

- resolve external repo roots from D: defaults or environment overrides
- start AETHER when available, otherwise fall back to a local OpenChimera runtime
- start WRAITH and Project Evo when their repos are available
- start the native OpenChimera API server and publish provider health into the runtime event stream
- start file-integrity monitoring for OpenChimera state files

To start local llama.cpp endpoints through OpenChimera itself after boot:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:7870/v1/runtime/start -Body '{}' -ContentType 'application/json'
```

## Environment Overrides

- `AETHER_ROOT`
- `WRAITH_ROOT`
- `EVO_ROOT`
- `OPENCHIMERA_HOST`
- `OPENCHIMERA_PORT`

Defaults:

- `AETHER_ROOT=D:\Project AETHER`
- `WRAITH_ROOT=D:\Project Wraith`
- `EVO_ROOT=D:\project-evo`
- `OPENCHIMERA_HOST=127.0.0.1`
- `OPENCHIMERA_PORT=7870`

## Identity and Local State

The runtime profile in `config/runtime_profile.json` is used to build OpenChimera's local identity context, including hardware, preferred models, and local endpoint routing. Local state files such as `chimera_kb.json`, `rag_storage.json`, and `memory/evo_memory.json` are watched by the FIM daemon and indexed into the native provider.

The onboarding surface uses the detected hardware profile to recommend local models first, then cloud fallbacks when the box is underpowered. The model catalog is intentionally modular so provider/model configuration can be swapped out later without rebuilding the core provider.

## Harness Port, Autonomy, And MiniMind

OpenChimera now treats the cloned upstream harness repo at `D:\repos\upstream-harness-repo` as a knowledge source rather than as a runtime backend. Its Python port manifest, command backlog, and tool backlog are ingested into the provider and can be inspected through `GET /v1/harness/status`. A legacy reverse-engineered snapshot preserved under `D:\openclaw\integrations\legacy-harness-snapshot` is scanned as workflow evidence only.

The native autonomy scheduler replaces the old manual Task Scheduler pattern with in-repo recurring jobs. It can sync scouted models from OpenClaw, audit missing skill bridges, and refresh MiniMind corpora through the OpenChimera API.

MiniMind remains the targeted local reasoning engine. OpenChimera detects the MiniMind workspace at `D:\openclaw\research\minimind`, audits checkpoints and datasets, can start and stop the MiniMind OpenAI-compatible server, can launch background training jobs, and can export two local corpora under `data/minimind/`:

- `harness_openchimera_sft.jsonl` for supervised chat-style tuning
- `harness_openchimera_pretrain.jsonl` for lightweight pretraining or distillation experiments

The export manifest includes recommended training commands pointing at the MiniMind trainer scripts already present on D:. Runtime state is also persisted under `data/minimind/minimind_runtime_manifest.json` and `data/minimind/minimind_training_jobs.json`.

OpenChimera now also exposes two higher-order operator capabilities: a safe Aegis bridge for remediation previews and an Ascension Engine for multi-perspective deliberation across MiniMind and local models. The daily briefing endpoint composes runtime health, onboarding guidance, recent events, and integration gaps into one operator-facing snapshot.

The advanced integration audit now reports first-class runtime coverage for AETHER, WRAITH, Project Evo, and detected evidence for quantum, ascension, and Aegis-related work present on D:. That audit is exposed over the provider API so missing bridges are visible without manual repository spelunking.
