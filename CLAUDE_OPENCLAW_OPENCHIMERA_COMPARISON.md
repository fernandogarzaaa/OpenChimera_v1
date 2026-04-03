# OpenClaw + Claude Code + OpenChimera Comparison

## Executive summary

The strongest path is not to merge the three systems wholesale.

OpenChimera should remain the runtime core.
OpenClaw should contribute local-first multi-model orchestration patterns.
Claude Code should contribute the agent-facing capability model: commands, tools, MCP, skills, memory, and session control.

That produces a system with:

- OpenClaw-style model modularity and local routing
- Claude-Code-style tool and workflow depth
- OpenChimera-native control plane, safety model, subsystem bridges, and identity

This is a credible path to a much stronger operator system. It is not a meaningful engineering basis for claiming AGI. The measurable target is a more capable, modular, self-improving local orchestration runtime.

## Current strengths by source

### OpenClaw strengths

- Multi-model local routing with priority ordering, health checks, and failover patterns
- Pragmatic support for heterogeneous providers: local llama.cpp, Ollama, brokered remote models, and fallback catalogs
- Experimental consensus patterns across multiple local models
- Broad modular sprawl with many adjacent projects and sub-systems already explored

### Claude Code strengths

- Deep command surface with explicit command, tool, skill, plugin, and MCP layers
- Strong query/session architecture centered on a persistent query engine
- Rich tool orchestration model with permission checks, deferred tools, tool search, and structured results
- Mature MCP integration including transport handling, auth flows, tools, commands, and resources
- Strong operator UX around model selection, plan mode, memory, plugins, skills, remote/session flows, and agent coordination

### OpenChimera strengths

- Clean Python-native runtime shell with kernel, provider, API server, observability, onboarding, resilience, and job queue
- Local-first packaging and install model that can run from source and degrade safely
- Existing integration bridges for AETHER, WRAITH, Project Evo, MiniMind, Aegis, and Ascension-related surfaces
- Existing identity and subsystem layer for your quantum engine, ascension engine, and other transplanted creations
- Better publication hygiene than OpenClaw and a more coherent control plane than the sourcemap reconstruction

## Recommended ownership model

### Keep OpenChimera as the spine

OpenChimera should own:

- process lifecycle
- API surface
- auth and credentials
- observability
- durable jobs
- runtime health
- onboarding
- external subsystem supervision
- install and packaging

### Import from OpenClaw selectively

Adopt these ideas, but reimplement them in OpenChimera-native contracts:

- model capability metadata
- local endpoint health scoring
- routing by task type
- local-first failover chains
- optional multi-model consensus for expensive reasoning paths
- modular provider activation and deactivation

Do not import OpenClaw as-is:

- hard-coded secrets
- workstation-coupled paths
- ad hoc scripts as runtime contracts
- uncontrolled architecture sprawl

### Import from Claude Code selectively

Adopt these ideas, but do not treat the sourcemap repo as trusted upstream:

- query-engine centric session model
- explicit separation of commands, tools, skills, plugins, and agents
- MCP as a first-class extension bus
- tool permission gating and tool discoverability
- memory as an explicit runtime primitive
- model selection as a user-visible and system-visible concern
- plan mode, structured execution phases, and richer operator UX

Do not import blindly:

- Anthropic-specific service assumptions
- internal/reconstructed product wiring
- anything that depends on undocumented private backends

## Target merged architecture

### Layer 1: Runtime kernel

OpenChimera kernel remains the supervisor for:

- provider runtime
- API server
- local models
- MiniMind
- autonomy scheduler
- channels
- external subsystem bridges

### Layer 2: Model and reasoning fabric

This should combine OpenClaw and OpenChimera ideas:

- OpenChimera model registry remains the catalog spine
- local LLM manager remains the managed-process and route-memory spine
- add stronger task routing classes from OpenClaw patterns: fast, general, code, reasoning, consensus, retrieval-heavy, tool-heavy
- add optional advisor and fallback model roles inspired by Claude Code's model handling
- add explicit quality tiers per model rather than only priority order

### Layer 3: Capability fabric

This is the biggest missing Claude-Code-like area.

OpenChimera should grow a formal capability model with these distinct concepts:

- Commands: user-invoked workflows
- Tools: low-level executable primitives
- Skills: reusable prompt-backed or workflow-backed capabilities
- MCP servers: external capability providers
- Agents: bounded worker processes or sub-runtimes
- Plugins: installable bundles of skills, tools, MCP config, and policies

Right now OpenChimera has pieces of this, but not the clean separation.

### Layer 4: Memory and session fabric

OpenChimera should adopt a more explicit memory/session model:

- session memory
- user memory
- repo memory
- task snapshots
- tool execution history
- operator state and resumability

This is a major Claude-Code advantage and would materially improve continuity and autonomous task execution.

### Layer 5: Your proprietary subsystem layer

This is where OpenChimera differentiates from both OpenClaw and Claude Code.

OpenChimera should remain the sole home of:

- quantum engine
- ascension engine
- Aegis workflows
- Project Evo bridging
- AETHER and WRAITH orchestration
- your custom autonomy behavior
- your modified reasoning and identity system

Those should not be bolted on as random legacy extras. They should be formal first-class managed subsystems behind stable contracts.

## Gap analysis

### What OpenChimera already has

- kernel supervision
- provider abstraction
- model registry
- local model manager
- onboarding
- browser surface
- multimodal surface
- job queue
- observability
- resilience
- integration audit
- Aegis and Ascension bridges
- external runtime supervision

### What OpenChimera still lacks relative to the merged target

- first-class command system
- first-class tool registry
- first-class skill system
- first-class plugin system
- first-class MCP server management UX and runtime integration depth
- richer session state and resume semantics
- explicit query engine abstraction
- explicit role separation between main model, fast model, advisor model, and fallback model
- stronger multi-model consensus and deliberation orchestration

### What should be discarded from the source systems

- OpenClaw secrets and unsafe defaults
- OpenClaw path coupling and unbounded sprawl
- reconstructed Claude-Code product assumptions that require Anthropic infrastructure
- any AGI/hyper-intelligence framing as a release criterion

## Recommended build sequence

### Phase 1: Capability architecture

Implement in OpenChimera:

- tool registry
- command registry
- skill registry
- plugin manifest format
- MCP adapter layer

### Phase 2: Query engine

Add an OpenChimera-native query engine that owns:

- conversation turns
- memory hydration
- model choice
- tool choice
- permission context
- agent spawning
- structured results

### Phase 3: Model-role expansion

Expand the current routing layer into explicit roles:

- main loop model
- fast model
- code model
- reasoning model
- advisor model
- consensus ensemble
- fallback model

### Phase 4: Subsystem formalization

Turn the custom engines into first-class managed services with contracts for:

- health
- capability description
- invocation
- state snapshot
- auditability
- permission boundaries

### Phase 5: Operator UX

Add user-facing surfaces for:

- model selection
- command discovery
- skill discovery
- MCP server management
- task resume
- memory inspection
- plugin installation

## Success criteria

The merged system is successful if OpenChimera becomes:

- the stable runtime and packaging surface
- the host for your proprietary engines and modifications
- a local-first multi-model orchestrator
- a Claude-Code-like capability platform for tools, skills, MCP, and agents
- a reproducible operator system that can be installed, extended, and supervised safely

It is not successful merely because it is larger or more ambitious.

## Bottom line

The correct synthesis is:

- OpenClaw for model modularity and experimental routing patterns
- Claude Code for capability architecture and operator ergonomics
- OpenChimera for the real runtime, integration spine, and your custom intelligence stack

That combination can produce a substantially more capable system than any one of the three alone.
The right target is a stronger local orchestration platform with compound reasoning, rich tool use, and managed subsystem intelligence, not an unsupported AGI claim.