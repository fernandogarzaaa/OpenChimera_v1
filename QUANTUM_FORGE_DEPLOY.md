# QUANTUM DIRECTIVE: Hyper-Intelligence Forge (Phase 7)

## Objective
Convert the Research blueprints into active system components.

## Swarm Assignments
1. **Constitutional Forge (`forge-constitutional`)**:
   - Target: `D:\project-evo\sdk\constitutional_validator.py`.
   - Goal: Build the logic that maps "Constitution" rules (e.g., no hardcoded secrets, no insecure I/O) to regex/pattern matching. Integrate this into the `debate_protocol.py` Auditor loop.

2. **Reasoning Forge (`forge-tot-reasoning`)**:
   - Target: `D:\project-evo\sdk\tot_reasoning_orchestrator.py`.
   - Goal: Build a Tree-of-Thought search agent. It must fork 3 concurrent Git worktrees (simulating potential code branches), evaluate each, select the winner, and merge back.

3. **Interpretability Forge (`forge-interpretability`)**:
   - Target: `D:\openclaw\scripts\interpretability_monitor.py`.
   - Goal: Build the Sparse Autoencoder (SAE) monitor for local models. It should output a real-time stream of model "feature activations" (what the model is thinking about) to a new Dashboard panel.

## Coherence Protocol
- All swarms must query `D:\openclaw\RESEARCH_HYPER_INTELLIGENCE.md` before coding.
- Code must pass the `debate_protocol.py` check before final saving.
