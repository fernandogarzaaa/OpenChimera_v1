import os
import shutil

skills = {
    "agent-browser-skill": "Browser automation and agentic web navigation skill. Use this to allow the agent to control headless browsers, scrape dynamic sites, and perform web UI interactions autonomously.",
    "claude-skills-repo": "Manage, sync, and audit the local repository of Claude-compatible agent skills. Use for version control and mass-updates of skill definitions.",
    "codebuff-repo": "Integration with Codebuff for advanced autonomous coding, codebase refactoring, and AI-driven development workflows.",
    "voltagent-skills": "VoltAgent skill integration. Provides high-speed task execution and hardware-level agentic routines.",
    "hftbacktest": "High-frequency trading and market-making backtesting tool supporting Level-2/3 data. Use for algo-trading strategy validation and quantitative analysis.",
    "agentic-seek": "A fully local Manus-style AI agent that performs web browsing and coding without API costs. Use for zero-cost autonomous research and local dev tasks."
}

base_dir = r"D:\openclaw\skills"

template = """# {name}

## Description
{desc}

## Usage
When the user requests tasks related to {name}, utilize the tools and scripts provided in this directory. This skill provides the context and execution environment necessary to leverage these capabilities autonomously.

## Requirements
- Local execution environment configured for {name}.
- Follow OpenClaw standard operating procedures for agentic tool use.
"""

for name, desc in skills.items():
    skill_dir = os.path.join(base_dir, name)
    os.makedirs(skill_dir, exist_ok=True)
    
    # Fix nested directories if they exist from the previous init_skill.py run
    nested_dir = os.path.join(skill_dir, name)
    if os.path.exists(nested_dir):
        shutil.rmtree(nested_dir, ignore_errors=True)
        
    path = os.path.join(skill_dir, "SKILL.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(template.format(name=name, desc=desc))
    print(f"Generated properly formatted SKILL.md at: {path}")

