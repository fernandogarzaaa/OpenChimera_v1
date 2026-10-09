# Changelog

All notable changes to OpenChimera will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **DRY Improvements**: Extracted shared `ToolExecutor` helper from tool_registry.py and tool_runtime.py
- **DRY Improvements**: Extracted shared MCP entry normalization into `mcp_normalization.py`
- **Configuration Externalization**: Moved 18-subsystem list from hardcoded to `config/subsystems.json` with dynamic loading
- **Configuration Externalization**: Extracted GodSwarm agent specs to `config/god_swarm_agents.json`
- **REST Endpoints**: Added `GET /api/v1/inquiry/pending` for listing pending inquiry questions
- **REST Endpoints**: Added `POST /api/v1/inquiry/{id}/resolve` for resolving inquiry questions
- **REST Endpoints**: Added `GET /api/v1/health` using HealthMonitor for detailed health status
- **GodSwarm Enhancement**: Added uniqueness check on agent_id in GodSwarm.spawn_agent()
- **Embodied Interaction Enhancement**: Added timeout handling and retry logic for actuator commands
- **Social Cognition Enhancement**: Improved SocialCognition.evaluate() to use word embedding similarity (character n-gram cosine similarity) instead of simple keyword matching
- **Type Safety**: Improved type hints throughout ActiveInquiry, removing Optional/List/Dict imports in favor of modern union syntax
- **Documentation**: Created `docs/architecture.md` with comprehensive system architecture documentation
- **Documentation**: Created `docs/api-reference.md` with full API endpoint reference
- **Documentation**: Created `docs/development.md` with development workflow and contribution guidelines

### Changed
- **Tool Execution**: Unified tool execution patterns using shared ToolExecutor for permission gating, timing, and event emission
- **MCP Normalization**: Consolidated MCP server entry normalization logic into single reusable helper
- **Subsystem Loading**: Changed subsystem registry from hardcoded list to dynamic JSON-based configuration
- **GodSwarm Initialization**: Updated GodSwarm to load agent specs from config with fallback to defaults
- **ActiveInquiry Type Hints**: Modernized type annotations to use PEP 604 union syntax (e.g., `str | None` instead of `Optional[str]`)

### Fixed
- **Runtime Tool Execution**: Previously stubbed RuntimeToolRegistry.execute() now fully functional using ToolExecutor
- **Actuator Timeout Handling**: ActuatorInterface.issue_command() now properly handles timeouts and retries

### Security
- Pydantic schemas already use `extra="forbid"` for strict validation (verified as existing feature)
- All key models enforce input validation with cross-field validators where appropriate

## [0.1.0] - 2026-04-14

### Added

#### Core Runtime
- **OpenAI-compatible API server** on `http://127.0.0.1:7870` with full OpenAPI documentation at `/docs` and `/openapi.json`
- **Local-first kernel** (`core/kernel.py`) with boot sequence, event bus subscriptions, and graceful shutdown
- **OpenChimera CLI** (`openchimera` entry point) with commands: `bootstrap`, `doctor`, `config`, `onboard`, `capabilities`, `tools`, `query`, `sessions`, `memory`, `model-roles`, `plugins`, `subsystems`, `mcp`, `briefing`, `autonomy`, `jobs`, `status`, `serve`
- **Docker support** with `Dockerfile` and `docker-compose.yml` for containerized deployments
- **Windows Task Scheduler deployment** via `scripts/install-openchimera-task.ps1` for persistent background service

#### Multi-Agent Audit Pipeline
- **Multi-agent audit pipeline** (`run_audit.py`) with 5 specialized audit agents and chimeralang-mcp integration
- **GodSwarm meta-orchestrator** (`swarms/`) with 10 specialized agents for parallel task execution
- **Multi-Agent Orchestrator** (`core/multi_agent_orchestrator.py`) with role-based dispatch (`AgentRole`: Reasoner, Creative, Critic, Specialist, etc.)
- **Cognitive enrichment pipeline** — post-consensus stage integrating Self-Model, Transfer Learning, Causal Reasoning, Meta-Learning, Ethical Reasoning, Social Cognition, and Embodied Interaction

#### Recursive Intelligence Loop (10 Subsystems)
- **Memory System** (`core/memory/`) — episodic (SQL + embeddings), semantic (NetworkX graph), and working (LRU) memory with unified facade
- **Deliberation Engine** (`core/deliberation.py`) — hypothesis/contradiction graph with max-flow consensus and Jaccard cross-check
- **HTN Goal Planner** (`core/goal_planner.py`) — CRUD goals with decomposition, dependencies, and Kahn topological sort
- **Evolution Engine** (`core/evolution.py`) — DPO training pair generation with 0.85 cosine similarity gate and domain fitness tracking
- **Metacognition Engine** (`core/metacognition.py`) — Expected Calibration Error (ECE), overconfidence ratio, and domain drift detection
- **Self-Model** (`core/self_model.py`) — capability snapshots, health heartbeats, and self-assessment for introspective monitoring
- **Transfer Learning** (`core/transfer_learning.py`) — cross-domain pattern registry, keyword overlap matching, and domain profile analytics
- **Causal Reasoning** (`core/causal_reasoning.py`) — directed causal graph, do-calculus interventions, and counterfactual simulation
- **Meta-Learning** (`core/meta_learning.py`) — strategy registry, adaptive parameter tuning, regime shift detection, and exploration–exploitation balance
- **Ethical Reasoning** (`core/ethical_reasoning.py`) — constraint registry, domain-scoped evaluation, audit trail, and configurable guardrails
- **Embodied Interaction** (`core/embodied_interaction.py`) — sensor abstraction, actuator command bus, environment state, and body-schema
- **Social Cognition** (`core/social_cognition.py`) — Theory of Mind, relationship memory, social context tracking, and norm compliance evaluation

#### Quantum Consensus Engine
- **Quantum Consensus Engine** (`core/quantum_engine.py`) — async-first weighted multi-agent voting with speculative gather and early-exit on quorum
- **Speculative gather** — returns as soon as quorum + early-exit confidence is met, cancelling stragglers
- **Weighted voting** — per-agent reputation via exponential moving average, updated on feedback
- **Destructive interference** — contradicting high-weight groups reduce winner confidence
- **Domain-aware reputation** — scores keyed by `(agent_id, domain)` with general-domain fallback
- **Embedding similarity** — optional sentence-transformers cosine similarity for soft dedup (thread-safe lazy singleton)
- **Persistence** — optional reputation persistence to SemanticMemory with auto-save every 10 updates
- **ConsensusProfiler** — built-in p50/p95 latency, avg confidence, early-exit %, and contradiction counts

#### MCP Integration
- **MCP (Model Context Protocol) adapter** for external agent tool-call protocol
- **Root `.mcp.json` manifest** declaring `openchimera-local` stdio server
- **MCP registry** (`data/mcp_registry.json`) with health-state persistence in `data/mcp_health_state.json`
- **Hosted MCP endpoint** at `/mcp` (GET for descriptor, POST for tool invocations)
- **MCP CLI commands**: `openchimera mcp --serve`, `--registry`, `--register`, `--unregister`, `--probe`, `--resources`, `--prompts`

#### ChimeraLang Bridge
- **ChimeraLang bridge** (`core/chimera_bridge.py` / `openchimera.chimera_bridge`) — logical reasoning language integration
- Accessible via `from openchimera.chimera_bridge import ChimeraLangBridge`

#### Autonomy Scheduler
- **Scheduled autonomy jobs**: `discover_free_models`, `sync_scouted_models`, `learn_fallback_rankings`, `check_degradation_chains`, `run_self_audit`, `preview_self_repair`, `dispatch_operator_digest`
- **Autonomy artifact retention** — configurable `max_history_entries` and `max_age_days` for pruning
- **Operator alerts** — severe findings emit `system/autonomy/alert` channel events for Slack/Discord/webhook subscribers
- **Non-destructive diagnostics** — `GET /v1/autonomy/diagnostics`, `/artifacts/history`, `/artifacts/get`, `/operator-digest` are all read-only
- **Preview repair** — `POST /v1/autonomy/preview-repair` generates repair plans without applying them

#### Observability and Operations
- **Structured JSONL runtime logs** at `logs/openchimera-runtime.jsonl` with request correlation
- **Health monitoring** — `/health` and `/v1/system/readiness` endpoints
- **Restrictive HTTP security headers** — `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`, HSTS on HTTPS
- **Rate limiting and authentication** — `OPENCHIMERA_API_TOKEN` and `OPENCHIMERA_ADMIN_TOKEN`
- **Optional TLS** — configurable via runtime profile or environment variables
- **Event bus** for inter-component communication
- **Capability plane** for unified tool/skill/subsystem registry
- **Operator channels** with delivery history and webhook/Slack/Discord/Telegram support
- **Durable operator jobs** with status tracking, filtering, cancellation, and replay

#### Configuration and Security
- **Sanitized default runtime profile** (`config/runtime_profile.json`) — publishable defaults only
- **Local override workflow** (`config/runtime_profile.local.json`) — machine-specific paths and credentials stay out of the repo
- **Fast-fail validation** — fails on enabled auth without a token, enabled TLS without cert paths, or cloud provider enabled but not preferred
- **Localhost-only default binding** — `OPENCHIMERA_ALLOW_INSECURE_BIND=1` required for non-loopback without auth

#### Python Namespace
- **`openchimera` package namespace** — `Kernel`, `OpenChimeraProvider`, `QueryEngine`, `QuantumEngine`, `MultiAgentOrchestrator`, `AgentPool`, `AgentSpec`, `AgentRole`, `MemorySystem`, `SessionMemory`, `ChimeraLangBridge`, `OpenChimeraAPIServer`

#### Testing and CI
- **Comprehensive test suite** — 2,600+ tests covering all subsystems
- **GitHub Actions** — `python-ci.yml` (Windows + Ubuntu validation gate) and `deploy.yml` (sdist/wheel build + GitHub release on version tag)
- **Quality gate scripts** — `scripts/run-quality-gate.sh` and `scripts/run-quality-gate.ps1`

### Infrastructure
- Python 3.11+ requirement
- Core dependencies: `networkx`, `numpy`, `psutil`, `pydantic>=2.12`
- Optional `redis` extra for distributed state
- Dev dependencies: `build`, `pytest-asyncio`, `wheel`, `pip-tools`

[Unreleased]: https://github.com/fernandogarzaaa/OpenChimera_v1/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/fernandogarzaaa/OpenChimera_v1/releases/tag/v0.1.0
