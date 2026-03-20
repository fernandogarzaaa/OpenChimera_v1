# Codebuff - Autonomous Local Development Swarm

Codebuff leverages the **Swarm V3** architecture in CHIMERA to provide autonomous, high-performance local development capabilities. It uses a collective of specialized agents (Researcher, Writer, Coder, Reviewer) to handle complex engineering tasks.

## 🚀 Capabilities

### 1. `codebuff-build`
**Mode:** Hierarchical
**Agents:** Manager → Researcher → Coder → Reviewer
**Use when:** Building a new feature from scratch, implementing a complex component, or starting a new project.

### 2. `codebuff-fix`
**Mode:** Sequential
**Agents:** Researcher → Coder → Reviewer
**Use when:** Debugging an issue, fixing a known bug, or refactoring a specific function.

### 3. `codebuff-review`
**Mode:** Parallel
**Agents:** Reviewer (Multiple instances)
**Use when:** Performing a deep security or performance audit, or reviewing a large Pull Request.

## 🛠️ Usage

To use Codebuff, send a POST request to the CHIMERA Swarm V3 endpoint on port 7870.

### Example: Building a new feature
```bash
curl -X POST http://localhost:7870/swarm/v3/execute \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "hierarchical",
    "tasks": [
      {
        "id": "research",
        "description": "Analyze the requirements for a new auth system using JWT",
        "priority": "HIGH"
      },
      {
        "id": "implementation",
        "description": "Implement the JWT auth system in python",
        "dependencies": ["research"],
        "priority": "CRITICAL"
      },
      {
        "id": "review",
        "description": "Review the implemented auth system for security flaws",
        "dependencies": ["implementation"],
        "priority": "HIGH"
      }
    ]
  }'
```

### Example: Fixing a bug
```bash
curl -X POST http://localhost:7870/swarm/v3/execute \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "sequential",
    "tasks": [
      {
        "description": "Locate the cause of the 500 error in the /login endpoint",
        "assigned_agent": "researcher"
      },
      {
        "description": "Apply the fix to the detected issue",
        "assigned_agent": "coder"
      }
    ]
  }'
```

## 🧠 State Persistence (Checkpoints)

Codebuff automatically saves checkpoints at every step. If an execution is interrupted, you can resume it using the `checkpoint_id`.

**Resume execution:**
```bash
curl -X POST http://localhost:7870/swarm/v3/resume?checkpoint_id=YOUR_CHECKPOINT_ID
```

## 📋 Status Tracking
Monitor the progress of your Codebuff swarm:
```bash
curl http://localhost:7870/swarm/v3/status
```

---

*Note: Codebuff runs entirely on your local CHIMERA infrastructure. No external API keys are required.*
