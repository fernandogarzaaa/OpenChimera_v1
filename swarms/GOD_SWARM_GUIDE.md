# God Swarm Activation Guide

## Quick Start

### Single Command Activation

When user presents a complex objective, activate God Swarm:

```
User: "Build a SaaS product with auth, payments, and docs"

→ Activate God Swarm
→ Spawn Omniscient agent to analyze
→ Continue through workflow
```

## Agent Spawn Commands

### 1. Spawn Omniscient (Requirement Analysis)

```python
sessions_spawn(
    task="""You are OMNISCIENT, requirement analyzer of the God Swarm.

User Objective: [paste user objective]

Your task: Achieve perfect clarity on requirements.

Ask ONE clarifying question at a time. Confirm understanding.
Output structured requirements when 95% confident.

Current God Swarm session: [this_session_key]""",
    label="god-omniscient",
    mode="session",
    timeout_seconds=300
)
```

### 2. Spawn Architect (Swarm Design)

```python
sessions_spawn(
    task="""You are ARCHITECT, swarm composer of the God Swarm.

Requirements from Omniscient:
[paste requirements]

Design swarm topology. Output YAML with:
- Which base swarms to deploy
- Dependencies between them
- Shared context structure
- Quality gates

Base swarms available:
- feature-forge, deep-research, code-archaeology
- content-studio, incident-response, security-audit
- knowledge-synthesis, devops-pipeline, design-system
- data-engineering, api-crafting, learning-adaptation""",
    label="god-architect", 
    mode="session",
    timeout_seconds=300
)
```

### 3. Spawn Demiurge (Swarm Creator)

```python
sessions_spawn(
    task="""You are DEMIURGE, swarm creator of the God Swarm.

Architecture from Architect:
[paste architecture YAML]

Spawn sub-swarms using sessions_spawn.
Register each in active registry.
Report back when all swarms are active.""",
    label="god-demiurge",
    mode="session",
    timeout_seconds=300
)
```

### 4. Spawn Chronos (Monitor)

```python
sessions_spawn(
    task="""You are CHRONOS, progress monitor of the God Swarm.

Active swarms: [list from registry]

Poll every 5 minutes. Report:
- Completion status
- Blocked swarms and reasons
- Progress percentages
- Alerts for issues

Update this session with status every 10 minutes.""",
    label="god-chronos",
    mode="session",
    timeout_seconds=3600
)
```

## Decision Tree

```
User Request
    │
    ├── Simple task (one domain)
    │   └── Use single base swarm directly
    │       (Feature Forge, Deep Research, etc.)
    │
    └── Complex/Multi-domain objective
        └── ACTIVATE GOD SWARM
            │
            ├── Omniscient analyzes
            ├── Architect designs
            ├── Demiurge spawns
            ├── Chronos monitors
            └── Result delivered
```

## Common Patterns

### Pattern: Build + Document
```
Objective: "Build API and write docs"

God Swarm spawns:
├─ Feature Forge (API implementation)
└─ Knowledge Synthesis (docs)
   [depends on Feature Forge contract]
```

### Pattern: Research + Implement
```
Objective: "Research competitors, build better feature"

God Swarm spawns:
├─ Deep Research (competitor analysis)
└─ Feature Forge (implementation)
   [depends on research findings]
```

### Pattern: Full Product Launch
```
Objective: "Launch SaaS product"

God Swarm spawns in phases:
Phase 1 (parallel):
├─ Feature Forge (backend)
├─ Design System (UI components)
└─ API Crafting (API contract)

Phase 2 (parallel):
├─ Feature Forge (frontend)
├─ Content Studio (marketing)
└─ Knowledge Synthesis (docs)

Phase 3:
└─ DevOps Pipeline (deploy)
```

## Registry Format

Track active God Swarm executions:

```yaml
# swarms/registry/god-swarm-active.yaml
god_swarms:
  - id: "gs-20260224-001"
    created: "2026-02-24T03:45:00Z"
    objective: "Build SaaS with auth and payments"
    status: "active"
    
    core_agents:
      omniscient: "session-key-abc"
      architect: "session-key-def"
      demiurge: "session-key-ghi"
      chronos: "session-key-jkl"
    
    sub_swarms:
      - id: "ff-001"
        type: "feature-forge"
        objective: "Auth system"
        status: "active"
        session: "session-key-mno"
      - id: "ff-002"
        type: "feature-forge"
        objective: "Payment integration"
        status: "pending"
        session: null
    
    shared_context:
      requirements: "path/to/reqs.yaml"
      artifacts_dir: "swarms/artifacts/gs-001"
```

## Escalation Triggers

Escalate to user when:
- Omniscient cannot resolve ambiguity after 3 questions
- Architect identifies impossible constraints
- Demiurge fails to spawn after 3 retries
- Multiple swarms conflict (Arbiter involved)
- Token budget exceeded
- Estimated time > 4 hours

## Success Signals

God Swarm complete when:
- All sub-swarms report success
- Quality gates passed
- User accepts deliverables
- Scribe archives context
- Reaper cleans up sessions
