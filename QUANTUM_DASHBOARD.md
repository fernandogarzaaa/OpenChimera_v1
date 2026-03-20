# QUANTUM DIRECTIVE: Ecosystem Visualization Dashboard

## Objective
Build a real-time React/Vite visualization dashboard inside the existing AppForge project (`D:\appforge-main\appforge`). This dashboard will monitor and display the metrics of our new Quantum Ecosystem.

## Key Metrics to Visualize
1. **Hardware State (VRAM Balancer):** Display current VRAM usage vs Capacity (6GB RTX 2060).
2. **CHIMERA Router:** Display the currently active LLM, priority status, and fallback registry (from `chimera_free_fallbacks.json`).
3. **Swarm Intelligence (Project Evo):** Show active Git Worktrees, recent MCP Database operations, and Debate Protocol consensus logs.

## Execution Steps for Feature Forge Swarm
1. Navigate to `D:\appforge-main\appforge\src\`.
2. Create a new component `QuantumDashboard.tsx` (or `.jsx`).
3. Use modern UI libraries (Tailwind, standard React hooks) to mock or fetch these data points. 
4. If real endpoints aren't fully exposed via CORS yet, create a realistic simulation interval that mimics the output of `vram_balancer.py` and `auto_llm_scout.py`.
5. Mount the component into the main `App.tsx` or router so it is visible at `http://localhost:5173/dashboard`.