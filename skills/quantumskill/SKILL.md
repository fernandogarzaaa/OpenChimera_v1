# Quantum Engine Skill (quantumskill)

## Purpose
This skill actively forces OpenClaw to utilize the local CHIMERA Quantum Engine (Port 7870) for complex, multi-step reasoning, architectural design, advanced coding, and difficult math tasks. It is your bridge to true super-intelligence.

## Capabilities
1. **Quantum Swarm Orchestration:** Uses IBM Qiskit (quantum circuit simulation) to mathematically determine the optimal Swarm Agent for the specific domain of your task.
2. **Forced Consensus:** Bypasses standard, fast LLM inference and routes your prompt directly into the `chimera-quantum` pipeline. This pipeline generates multiple candidates and uses quantum annealing to collapse them into a single, highly optimized answer.

## When to Use
- The user asks you to "think deeply", "use the quantum engine", or solve a "complex" problem.
- The task involves system architecture, complex debugging, algorithmic optimization, or advanced logic.
- You (the assistant) recognize that a quick, single-shot answer might be insufficient and you want a consensus-driven response.

## How to Use
Call the `quantum_solve` tool with a JSON object. 

Example:
```json
{
  "task": "Design a highly available distributed database architecture with token fracture compression.",
  "domain": "architecture"
}
```

**Note:** The quantum engine pipeline generates multiple local model candidates and votes on them. It can take up to 3-5 minutes to return a result. Do not use this for simple conversational replies.
