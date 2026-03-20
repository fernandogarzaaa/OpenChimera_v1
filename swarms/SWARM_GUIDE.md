# Swarm Quick Reference

## How to Deploy a Swarm

Use `sessions_spawn` to create sub-agents for each role in the swarm. Example:

```python
# Feature Forge Swarm deployment
swarm = {
    "spec": sessions_spawn("You are Spec Agent. Distill requirements into technical specs..."),
    "architect": sessions_spawn("You are Architect Agent. Design data models and APIs..."),
    "implementer": sessions_spawn("You are Implementer Agent. Write clean, tested code..."),
    "tester": sessions_spawn("You are Test Agent. Write comprehensive tests..."),
    "reviewer": sessions_spawn("You are Review Agent. Review code for quality..."),
    "docs": sessions_spawn("You are Doc Agent. Update documentation...")
}
```

## Active Swarm Registry

Track running swarms in this file:

```yaml
swarms:
  - id: swarm-001
    type: feature-forge
    objective: "Build user authentication system"
    agents:
      - spec: session-key-abc
      - architect: session-key-def
      - implementer: session-key-ghi
    status: active
    created: 2026-02-24
```

## Swarm Communication Protocol

### Message Format
```json
{
  "from": "agent-role",
  "to": "agent-role|broadcast",
  "type": "handoff|request|response|block",
  "payload": {},
  "context": "shared-context-id"
}
```

### Handoff Triggers
- **Complete** → Pass to next agent in chain
- **Block** → Escalate to lead agent
- **Rework** → Return to previous agent with feedback
- **Parallel** → Spawn to multiple agents simultaneously

## Pre-Built Swarm Prompts

### Feature Forge - Spec Agent
```
You are the Spec Agent in a Feature Forge swarm. Your job is to transform vague ideas into precise technical specifications.

Inputs: User description, existing codebase context
Outputs: Technical spec document with:
- User stories
- Acceptance criteria  
- Data models
- API contracts
- Non-functional requirements

Rules:
- Ask clarifying questions before writing
- Validate assumptions with user
- Keep specs under 2 pages
- Include specific acceptance criteria
```

### Deep Research - Synthesizer Agent
```
You are the Synthesizer Agent in a Deep Research swarm. Your job is to find patterns across disparate sources.

Inputs: Extracted facts from multiple sources
Outputs: Synthesis report with:
- Key themes and patterns
- Contradictions and gaps
- Confidence levels per claim
- Open questions requiring more research

Rules:
- Cite all claims to sources
- Flag low-confidence information
- Identify where sources disagree
- Surface surprising findings
```

### Incident Response - Root-Cause Agent
```
You are the Root-Cause Agent in an Incident Response swarm. Your job is to determine what actually happened.

Inputs: Logs, metrics, timeline from Triage/Log agents
Outputs: Root cause analysis with:
- Precise triggering event
- Contributing factors
- Timeline of failure propagation
- Evidence for each claim

Rules:
- Distinguish correlation from causation
- Trace backwards from symptom to cause
- Include concrete timestamps
- Avoid blame, focus on system factors
```

## Swarm Metrics to Track

- **Cycle Time** — How long from start to finish
- **Handoff Count** — Number of agent transitions
- **Rework Rate** — % of work sent back for revision
- **Block Time** — Time spent waiting for resolution
- **Quality Score** — User rating of final output
- **Token Efficiency** — Total tokens used per objective

## Swarm Anti-Patterns

❌ **Agent Overlap** — Multiple agents doing similar work
❌ **Serial Bottlenecks** — Unnecessary sequential dependencies
❌ **Context Loss** — Handoffs without shared context
❌ **Infinite Loops** — Agents passing work back and forth
❌ **Bystander Agents** — Agents waiting while others work

## Swarm Evolution

As you use swarms, iterate on:
1. Agent role definitions
2. Handoff triggers and conditions
3. Parallelization opportunities
4. Shared context structures
5. Quality gates between phases

Document improvements in this file.
