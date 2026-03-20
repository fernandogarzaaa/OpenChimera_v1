# QUANTUM DIRECTIVE: Hyper-Intelligence Deployment (Phase 5)

## Objective
Implement the 4 core "Hyper-Intelligence" architectural upgrades synthesized from the Deep Research Swarm.

## Swarm Assignments
1. **Validator Swarm (`validator-swarm`)**:
   - Target: `D:\openclaw\scripts\constitutional_validator.py`.
   - Goal: Build the immutable security/logic validator. It must check every code output against our "Constitution" (security rules) before saving.
   
2. **Reasoning Swarm (`reasoning-swarm`)**:
   - Target: `D:\openclaw\scripts\reasoning_wrapper.py`.
   - Goal: Build the System-2 reasoning wrapper. This must wrap LLM inference with a mandatory "Thought Block" generation and a subsequent validation pass.

3. **Router Swarm (`expert-router-swarm`)**:
   - Target: `D:\openclaw\scripts\expert_router.py`.
   - Goal: Build the SMoE (Sparse Mixture of Experts) dynamic router. It must interface with the CHIMERA endpoint, detect intent, and route to the most capable model for that specific task type (e.g., coding vs. reasoning vs. creative).

4. **Checkpoint Swarm (`checkpoint-swarm`)**:
   - Target: `D:\openclaw\scripts\checkpoint_manager.py`.
   - Goal: Implement the persistent state checkpointing for Project Evo. This must save swarm state to the Postgres DB (via MCP) at every major decision checkpoint.

## Coherence Protocol
- All swarms must ensure zero API leaks. 
- All swarms must query the current system state via `localhost:8000/mcp` before executing.
