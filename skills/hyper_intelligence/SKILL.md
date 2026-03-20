# Hyper Intelligence Skill (hyper_intelligence)

## Purpose
This skill wires a "Quantum Tree of Thoughts" (Q-ToT) directly into OpenClaw. It elevates your reasoning from a linear path to a parallel, multi-dimensional search space collapsed by quantum mathematics.

## Capabilities
1. **Divergent Thought Generation:** Asks the local models to generate 3 fundamentally distinct, valid approaches to solving a complex query.
2. **Entanglement Check:** Uses SentenceTransformers to detect semantic relationships (fidelities) between the paths.
3. **Deep Expansion:** Fully develops each approach into a complete solution.
4. **Quantum Collapse:** Uses IBM Qiskit (or SciPy annealing) via the local `quantum_consensus_v2` module to score the solutions and collapse the wave function to the single optimal "truth".

## When to Use
- When asked to use "Hyper Intelligence" or "think on a higher level."
- When facing philosophical paradoxes, NP-hard architectural decisions, or complex scientific hypotheses.
- When an answer requires absolute, mathematically verified optimal truth rather than a fast guess.

## How to Use
Call the `hyper_reason` tool with the complex query. This process takes 1-3 minutes but yields unparalleled reasoning depth.

Example:
```json
{
  "query": "What is the optimal consensus algorithm for a 4-node heterogeneous LLM swarm running locally with high latency between nodes?"
}
```
