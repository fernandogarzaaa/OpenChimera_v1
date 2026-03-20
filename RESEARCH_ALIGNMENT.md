# RESEARCH_ALIGNMENT.md - Constitutional AI & RLAIF Pipeline for Project Evo

## Executive Summary
This design implements a local, resource-efficient alignment framework for Project Evo. Given our hardware constraints (RTX 2060), we prioritize **Inference-Time Constitutional Alignment (ITCA)** over resource-intensive fine-tuning.

## Architecture: The "Critique-Revise" Loop

Instead of training a Reward Model, we utilize a specialized "Critique Agent" (or an ensemble of agents) to act as the Reinforcement Signal in real-time.

### 1. The System Constitution
A central Markdown file (`D:\openclaw\CONSTITUTION.md`) containing ranked principles.
- **Example Principles:**
    - "Modular over monolithic: Break large functions into atomic units."
    - "Security First: Never output hardcoded credentials."
    - "Conciseness: Avoid verbose explanations unless explicitly requested."

### 2. Pipeline Stages

#### Stage A: Actor Execution
The main agent/swarm executes the task (e.g., generating code).

#### Stage B: Constitutional Critique (RLAIF Trigger)
A separate, lightweight agent (the "Judge") reviews the Actor's output against the Constitution.
- **Input:** Actor Output + Task Context + Constitution Principles.
- **Output:** A Critique Report (violations, suggestions, compliance score 0-1).

#### Stage C: Revision/Selection (The RLAIF Logic)
- **If Score < Threshold:** Trigger Revision. The Actor receives the Critique Report as feedback and attempts to regenerate.
- **If Score >= Threshold:** Pass output to user/next step.

### 3. Feedback Evolution (Long-term)
Every critique is logged to `D:\openclaw\logs\alignment.jsonl`.
- We use this data to identify patterns:
    - *Which agents violate which principles most often?*
    - *Update agent system prompts to proactively address frequent violations.*

## Implementation Plan for Project Evo
1. **Bootstrap Constitution:** Create `D:\openclaw\CONSTITUTION.md`.
2. **Critique Agent Utility:** Create a Python utility (in `skills/alignment/judge.py`) that performs the evaluation.
3. **Integration:** Update the main orchestrator to wrap task completion calls with an `alignment_check` function.
4. **Monitoring:** Build a small dashboard (or CLI output) tracking the "Average Compliance Score" for agent runs.

## Next Steps
- Implement `skills/alignment/judge.py`.
- Define the initial `CONSTITUTION.md` ruleset.
- Test the "Critique-Revision" loop on a complex coding task.
