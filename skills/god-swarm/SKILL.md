---
name: god-swarm
description: Meta-orchestrator that creates and manages other swarms on demand. Use when the user presents complex, multi-domain objectives that require coordinated effort across multiple specialized swarms. Automatically analyzes requirements, selects optimal swarm composition, spawns sub-swarms, monitors execution, and coordinates handoffs. Examples: "Build a SaaS product with auth and docs", "Research competitors and implement features", "Launch product with marketing and infrastructure".
---

# God Swarm

The God Swarm is your supreme orchestrator. It doesn't do the work—it assembles the perfect teams to do it.

## When to Use This Skill

Use God Swarm when:
- The objective spans multiple domains (e.g., build feature AND write docs AND create marketing)
- You're unsure which swarm(s) to deploy
- Multiple swarms need coordination with dependencies
- The objective is novel and requires custom swarm composition
- Existing approaches failed and replanning is needed

## Core Agents

| Agent | Role |
|-------|------|
| **Omniscient** | Analyzes requirements deeply |
| **Architect** | Designs swarm topology |
| **Demiurge** | Spawns sub-swarms |
| **Chronos** | Monitors all activity |
| **Arbiter** | Resolves conflicts |
| **Scribe** | Keeps shared context |

## Activation

When user presents a complex objective:

1. **Acknowledge** — "Activating God Swarm to orchestrate this objective."

2. **Spawn Omniscient** — Analyze requirements
   ```python
   sessions_spawn(
       task="You are OMNISCIENT... [objective details]",
       label="god-omniscient",
       mode="session"
   )
   ```

3. **Spawn Architect** — Design topology based on Omniscient output

4. **Spawn Demiurge** — Create sub-swarms per architecture

5. **Spawn Chronos** — Monitor all activity

6. **Deliver** — Aggregate results and present to user

## Swarm Selection Matrix

| Objective Contains... | Deploy |
|-----------------------|--------|
| "build", "implement", "feature" | Feature Forge |
| "research", "analyze" | Deep Research |
| "legacy", "refactor" | Code Archaeology |
| "content", "blog", "marketing" | Content Studio |
| "down", "outage", "incident" | Incident Response |
| "security", "audit" | Security Audit |
| "document", "wiki" | Knowledge Synthesis |
| "deploy", "pipeline", "infra" | DevOps Pipeline |
| "design", "UI" | Design System |
| "data", "ETL" | Data Engineering |
| "API" | API Crafting |
| Multiple domains | Composite (God Swarm coordinates) |

## Composite Patterns

### Sequential
```
Deep Research → [findings] → Feature Forge
```

### Parallel
```
├→ Feature Forge (product)
├→ Content Studio (marketing)
└→ Knowledge Synthesis (docs)
```

### Nested
```
God Swarm
└─ Code Archaeology (per service)
   └─ Feature Forge (rewrite)
```

## Workflow

```
User Objective
     ↓
Omniscient (analyze)
     ↓
Architect (design)
     ↓
Demiurge (spawn)
     ↓
Chronos (monitor)
     ↓
Results
```

## Commands

### Check God Swarm Status
```python
subagents(action="list")
```

### Send Message to God Swarm Agent
```python
sessions_send(
    sessionKey="god-omniscient",
    message="Status update?"
)
```

### Terminate God Swarm
```python
subagents(action="kill", target="god-")
```

## Registry

Track active God Swarms in:
`D:\openclaw\swarms\registry\god-swarm-active.yaml`

## Full Documentation

- Architecture: `D:\openclaw\swarms\GOD_SWARM.md`
- Usage Guide: `D:\openclaw\swarms\GOD_SWARM_GUIDE.md`
- Base Swarms: `D:\openclaw\swarms\SWARM_ARCHITECTURES.md`
