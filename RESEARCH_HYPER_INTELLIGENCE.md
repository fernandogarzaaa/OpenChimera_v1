# RESEARCH_HYPER_INTELLIGENCE.md

## Overview
This document synthesizes core architectural patterns for "Hyper-Intelligence" cognitive simulation, designed for local deployment within the CHIMERA ecosystem.

## 1. Chain of Thought (CoT)
- **Concept:** LLMs generate superior results when forced to articulate intermediate reasoning steps before final output.
- **Local Implementation:** 
  - Mandatory "Reasoning Block": Enforce a system prompt structure requiring a `<thought>` tag for every complex request.
  - Verification: Use a secondary "Critic" agent to ensure the reasoning in the `<thought>` block logically supports the final answer.

## 2. System-2 Reasoning
- **Concept:** Moving beyond intuitive, fast ("System-1") responses to deliberate, analytical, and constraint-based reasoning ("System-2").
- **Local Implementation:**
  - "Audit/Critic" Loop: Adopt a two-pass architecture. Pass 1 generates an answer; Pass 2 (a specialized Auditor agent) reviews the answer against defined truth criteria and safety/correctness constraints.
  - Decision Extraction: Use the 'Board Meeting' protocol to force consensus from multiple specialized 'C-suite' agents before finalizing a strategic direction.

## 3. Sparse Mixture of Experts (SMoE)
- **Concept:** Scaling model capability by selectively activating only relevant sub-networks (experts) rather than the entire parameter set.
- **Local Implementation:**
  - Dynamic Agent Routing: Replace 'Broadcast' models with 'Router' models. The primary intelligence should be a Router Agent that assesses the input and routes it exclusively to the relevant specialized Agent/Skill (e.g., `code-archaeology` for code, `security-audit` for threat detection).
  - Skill Registry: Maintain a robust registry of available agents to minimize latency and focus context window allocation.

## 4. Agentic Reasoning Loops
- **Concept:** Recurrent state management where agents iteratively assess progress towards a goal, modify plans, and update memory.
- **Local Implementation:**
  - Decision Checkpoint Architecture: Agents should be architected to perform a "State Evaluation" phase after every major action. If the state is not closer to the objective, the agent must invoke a "Replan" function rather than blindly continuing.
  - Memory Persistence: Use `MEMORY.md` as the authoritative source of truth for the loop to prevent context drift across iterations.
  - Loop Constraint: Define a maximum recursion depth/step-count for all agentic loops to prevent resource exhaustion.
