# Evo Orchestrator: God Swarm Protocol

This skill defines the 'God Swarm' protocol, instructing OpenClaw on how to orchestrate Project Evo. The God Swarm is the meta-orchestrator that delegates complex multi-agent tasks to the Project Evo swarm backend.

## Trigger Conditions
Use this skill when:
- The user requests to run a complex, multi-agent task that requires specialized swarms.
- The user explicitly mentions "God Swarm", "Project Evo", or "run swarm".
- A task is too large for a single agent and requires parallel execution by specialized agents (e.g., Feature Forge, Deep Research, etc.).

## Execution Strategy
To orchestrate Project Evo and trigger a swarm execution, use the `exec` tool to run the swarm bot script.

### Command
```powershell
python D:\project-evo\swarm_bot.py --run
```

### Passing Context
When executing the swarm, you can pass context or specific instructions to the swarm by providing arguments to the script, depending on the current capabilities of `swarm_bot.py`. Always ensure that the task context is well-defined before delegating to the God Swarm.

## Swarm Capabilities
Project Evo supports various specialized swarms orchestrated by the God Swarm:
- **Feature Forge**: Build features end-to-end.
- **Deep Research**: Research reports & synthesis.
- **Code Archaeology**: Legacy code understanding.
- **Content Studio**: Multi-format content.
- **Incident Response**: Production incidents.
- **Security Audit**: Security assessments.
- **Knowledge Synthesis**: Documentation & wikis.
- **DevOps Pipeline**: CI/CD & infrastructure.
- **Design System**: UI/UX consistency.
- **Data Engineering**: Data pipelines.
- **API Crafting**: API design & maintenance.
- **Learning & Adaptation**: Performance improvement.

## Error Handling
If the execution fails, check the output of the `python` command for errors. Ensure that the Python environment is correctly set up and that `D:\project-evo\swarm_bot.py` exists.