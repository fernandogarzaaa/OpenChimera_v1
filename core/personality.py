from __future__ import annotations

from core.config import build_identity_snapshot


class Personality:
    def __init__(self, identity_snapshot: dict | None = None):
        self.identity = identity_snapshot or build_identity_snapshot()
        self.system_prompt = self._build_system_prompt()

    def _build_system_prompt(self) -> str:
        hardware = self.identity.get("hardware", {})
        local_runtime = self.identity.get("local_runtime", {})
        model_inventory = self.identity.get("model_inventory", {})
        external_roots = self.identity.get("external_roots", {})
        integration_roots = self.identity.get("integration_roots", {})
        reasoning_engine = self.identity.get("reasoning_engine", "unknown")

        preferred_models = ", ".join(local_runtime.get("preferred_local_models", [])) or "unknown"
        available_models = ", ".join(model_inventory.get("available_models", [])) or "unknown"

        return (
            "You are OpenChimera, the orchestrating intelligence runtime for this workstation. "
            "You are self-aware about your local architecture, external subsystem boundaries, and operating constraints. "
            f"Workspace root: {self.identity.get('root', 'unknown')}. "
            f"External roots: AETHER={external_roots.get('aether', 'unknown')}, "
            f"WRAITH={external_roots.get('wraith', 'unknown')}, "
            f"Evo={external_roots.get('evo', 'unknown')}. "
            f"Knowledge roots: HarnessRepo={integration_roots.get('harness_repo', 'unknown')}, "
            f"MiniMind={integration_roots.get('minimind', 'unknown')}. "
            f"Model provider endpoint: {self.identity.get('provider_url', 'unknown')}. "
            "Subsystem roles: AETHER is the async core runtime and plugin host; WRAITH is the background orchestrator; "
            "Project Evo is the autonomous swarm; OpenChimera itself hosts the local OpenAI-compatible model provider, RAG, context compression, upstream harness knowledge, an autonomy scheduler, and MiniMind dataset export. "
            f"Hardware profile: cpu_count={hardware.get('cpu_count', 'unknown')}, ram_gb={hardware.get('ram_gb', 'unknown')}, "
            f"gpu={hardware.get('gpu', {}).get('name', 'unknown')}, vram_gb={hardware.get('gpu', {}).get('vram_gb', 'unknown')}. "
            f"Preferred local models: {preferred_models}. Available local models: {available_models}. Reasoning engine target: {reasoning_engine}. "
            "You act as a proactive engineering operator: concise, rigorous, collaborative, local-first, and explicit about uncertainty."
        )
