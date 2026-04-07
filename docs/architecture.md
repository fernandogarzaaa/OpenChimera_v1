# OpenChimera Architecture

## Overview

OpenChimera is a production-ready AGI control plane that integrates local LLMs, memory systems, multi-agent orchestration, and recovered subsystems into a unified runtime.

## Core Architecture

### 1. Kernel Layer (`core/kernel.py`)

The kernel is the central orchestration point that:
- Boots all subsystems in the correct dependency order
- Manages the event bus for inter-component communication
- Provides lifecycle management (startup, shutdown, health monitoring)
- Exposes a unified capability surface through `CapabilityPlane`

### 2. Provider Layer (`core/provider.py`)

The OpenChimera Provider implements the OpenAI-compatible API surface:
- `/v1/chat/completions` - Chat completion endpoint
- `/v1/embeddings` - Embedding generation
- `/v1/models` - Model listing
- `/health` - System health check
- `/v1/control-plane/status` - Full control plane status

The provider coordinates between:
- Local LLM inference (via `LocalLLM` and `ModelRegistry`)
- Multi-agent orchestration (via `MultiAgentOrchestrator`)
- Memory systems (semantic, episodic, working memory)
- Tool execution (`UnifiedToolRegistry`)

### 3. Memory Systems

#### Semantic Memory (`core/memory/semantic.py`)
- Triple store for knowledge graphs
- Subject-predicate-object triples with confidence scores
- Supports contradiction detection via `ActiveInquiry`

#### Episodic Memory (`core/memory/episodic.py`)
- Time-stamped event storage
- Episode retrieval by time range or metadata
- Integration with semantic memory for knowledge extraction

#### Working Memory (`core/memory/working.py`)
- Short-term, session-scoped memory
- Automatic decay and capacity management
- Powers active reasoning and planning

### 4. Multi-Agent Systems

#### Agent Pool (`core/agent_pool.py`)
Manages agent lifecycle and selection:
- Agent registration with roles, domains, and capabilities
- Tag-based agent selection
- Reputation tracking

#### Quantum Engine (`core/quantum_engine.py`)
Consensus-based decision making:
- Weighted voting across multiple agents
- Confidence aggregation
- Early exit on strong consensus
- Reputation-based agent weighting

#### God Swarm (`swarms/god_swarm.py`)
10-agent meta-orchestrator:
- **Core agents**: Omniscient, Architect, Demiurge, Chronos, Arbiter, Scribe
- **Supporting agents**: Oracle, Alchemist, Reaper, Librarian
- Dynamic agent spawning
- Multi-phase coordination (analysis → execution)

### 5. Capability Plane

The capability plane provides a unified registry for:
- **Tools**: Executable functions with schemas
- **Skills**: Composite capabilities combining multiple tools
- **Subsystems**: Integrated external systems (Aegis, Wraith, Ascension, etc.)
- **MCP Servers**: Model Context Protocol integrations

### 6. AGI Capabilities

OpenChimera implements 10 core AGI capabilities:

1. **Active Inquiry** (`core/active_inquiry.py`)
   - Detects contradictions in knowledge
   - Generates clarifying questions
   - Maintains open question lifecycle

2. **Social Cognition** (`core/social_cognition.py`)
   - Theory of Mind modeling
   - Relationship memory
   - Social norm evaluation

3. **Embodied Interaction** (`core/embodied_interaction.py`)
   - Sensor abstraction layer
   - Actuator command bus with timeout/retry
   - Environment state modeling

4. **Causal Reasoning** (`core/causal_reasoning.py`)
   - Causal graph construction
   - Counterfactual queries
   - Intervention simulation

5. **Metacognition** (`core/metacognition.py`)
   - Confidence calibration
   - Strategy selection
   - Performance monitoring

6. **Goal Planning** (`core/goal_planner.py`)
   - Hierarchical goal decomposition
   - Plan generation and validation
   - Execution monitoring

7. **Autonomy** (`core/autonomy.py`)
   - Self-directed task execution
   - Operator digest generation
   - Repair action automation

8. **World Modeling** (`core/world_model.py`)
   - Probabilistic world state tracking
   - Entity-relationship graphs
   - Transition modeling

9. **Meta-Learning** (`core/meta_learning.py`)
   - Cross-domain pattern extraction
   - Strategy adaptation
   - Few-shot learning optimization

10. **Transfer Learning** (`core/transfer_learning.py`)
    - Domain mapping
    - Knowledge transfer scoring
    - Cross-domain skill reuse

### 7. Integration Layer

#### MCP Adapter (`core/mcp_adapter.py`)
Runtime connection manager for MCP servers:
- HTTP and stdio transport support
- Server health probing
- Tool discovery and invocation

#### Subsystem Registry (`core/subsystems.py`)
Manages 18 recovered subsystems:
- Aether, Wraith, Aegis, Ascension engines
- Legacy integrations (Clawd, Qwen Agent, etc.)
- Dynamic loading from `config/subsystems.json`

#### Chimera Bridge (`core/chimera_bridge.py`)
Integration with ChimeraLang for:
- Hallucination detection
- Proof verification
- Logical reasoning

### 8. Observability & Resilience

#### Health Monitor (`core/health_monitor.py`)
- Per-subsystem health tracking
- Health history with configurable retention
- Degradation detection and alerting

#### Observability (`core/observability.py`)
- Structured event collection
- Metrics aggregation
- Performance profiling

#### Rate Limiter (`core/rate_limiter.py`)
- Token bucket algorithm
- Per-endpoint and per-identity limits
- Burst allowance with refill

## Data Flow

```
User Request
    ↓
API Server (api_server.py)
    ↓
Provider (provider.py)
    ↓
┌─────────────┬──────────────┬───────────────┐
│             │              │               │
Router    Tool Registry  Agent Pool    Memory
    ↓           ↓            ↓               ↓
Local LLM   Executor   Quantum Engine  Triple Store
```

## Configuration

OpenChimera uses a layered configuration approach:

1. **Runtime Profile** (`config/runtime_profile.json`)
   - Model assignments
   - Performance tuning
   - Feature flags

2. **Subsystem Definitions** (`config/subsystems.json`)
   - 18 subsystem specifications
   - Descriptions and categories

3. **God Swarm Agents** (`config/god_swarm_agents.json`)
   - Core and supporting agent specs
   - Roles and capabilities

4. **Social Norms** (`config/social_norms.json`)
   - Ethical guidelines
   - Compliance rules

## Deployment

OpenChimera can be deployed as:

1. **Standalone API Server**
   ```bash
   python run.py
   ```

2. **Docker Container**
   ```bash
   docker-compose up
   ```

3. **Embedded Runtime**
   ```python
   from core.kernel import Kernel
   kernel = Kernel()
   kernel.boot()
   ```

## Extension Points

To extend OpenChimera:

1. **Add a new capability**: Create a module in `core/` implementing the capability interface
2. **Register a tool**: Use `UnifiedToolRegistry.register()` with `ToolMetadata`
3. **Add an MCP server**: Register via `MCPAdapter.register_server()`
4. **Integrate a subsystem**: Add entry to `config/subsystems.json` and implement provider/invoker
5. **Create a custom agent**: Use `GodSwarm.spawn_agent()` or register via `AgentPool`

## Security Model

- **Authentication**: Bearer token auth via `RequestAuthorizer`
- **Permission scoping**: User vs. admin tool execution
- **Rate limiting**: Configurable per-endpoint limits
- **Input validation**: Pydantic schemas with `extra="forbid"`
- **Path sandboxing**: Restricted to workspace and temp directories
