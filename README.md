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

- Runtime status: `GET /v1/runtime/status`
- Start configured local models: `POST /v1/runtime/start`
- Stop managed local models: `POST /v1/runtime/stop`
- Harness port status: `GET /v1/harness/status`
- Autonomy status: `GET /v1/autonomy/status`
- Start autonomy scheduler: `POST /v1/autonomy/start`
- Stop autonomy scheduler: `POST /v1/autonomy/stop`
- Run one autonomy job: `POST /v1/autonomy/run`
- MiniMind status: `GET /v1/minimind/status`
- Build MiniMind datasets from upstream harness + OpenChimera context: `POST /v1/minimind/dataset/build`

The launcher configuration lives in `config/runtime_profile.json` under `local_runtime.launcher`.

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

## Harness Port, Autonomy, And MiniMind

OpenChimera now treats the cloned upstream harness repo at `D:\repos\upstream-harness-repo` as a knowledge source rather than as a runtime backend. Its Python port manifest, command backlog, and tool backlog are ingested into the provider and can be inspected through `GET /v1/harness/status`. A legacy reverse-engineered snapshot preserved under `D:\openclaw\integrations\legacy-harness-snapshot` is scanned as workflow evidence only.

The native autonomy scheduler replaces the old manual Task Scheduler pattern with in-repo recurring jobs. It can sync scouted models from OpenClaw, audit missing skill bridges, and refresh MiniMind corpora through the OpenChimera API.

MiniMind remains the targeted local reasoning engine. OpenChimera detects the MiniMind workspace at `D:\openclaw\research\minimind`, audits checkpoints and datasets, and can export two local corpora under `data/minimind/`:

- `harness_openchimera_sft.jsonl` for supervised chat-style tuning
- `harness_openchimera_pretrain.jsonl` for lightweight pretraining or distillation experiments

The export manifest includes recommended training commands pointing at the MiniMind trainer scripts already present on D:.
