# Legacy Integrations

OpenChimera can inspect or supervise optional external workspaces, but those workspaces are not required for a clean source install.

## Integration Model

OpenChimera treats connected systems in one of three ways:

- first-class managed runtimes when lifecycle control exists inside the OpenChimera kernel
- evidence-only compatibility sources when only files, manifests, or archived workflows are available
- unsupported when a workspace exists but does not match the expected layout or safety rules

## Optional External Roots

The runtime profile can point at these optional roots:

- external orchestration services such as AETHER, WRAITH, and Project Evo
- historical CHIMERA and AppForge-adjacent runtimes such as Clawd Hybrid RTX and Qwen-Agent
- mobile and operator surfaces such as Aegis Mobile / gateway and Project Seraph
- MiniMind reasoning and training workspace
- upstream harness Python-port workspace
- legacy workflow snapshot roots used for compatibility evidence only
- Aegis and Ascension-related workspaces

## Setting Up Optional Subsystems

`python run.py status` will show `not installed (optional)` for AETHER, WRAITH, Evo,
and Aegis when their repos are absent. This is normal for a fresh install — the core
runtime and Ascension subsystem operate fully without them.

To enable any optional subsystem clone (or symlink) its repository into the `external/`
directory, then restart OpenChimera:

```bash
# AETHER — adaptive operator intelligence stack
git clone <aether-repo-url> external/aether

# WRAITH — stealth/mutation analysis engine
git clone <wraith-repo-url> external/wraith

# Project Evo — evolutionary algorithm subsystem
git clone <evo-repo-url> external/evo

# Aegis — mobile gateway / control plane
git clone <aegis-repo-url> external/aegis-mobile
```

Alternatively, override any root via an environment variable before starting:

```bash
AETHER_ROOT=/my/custom/aether python run.py serve
```

Or set the path permanently in `config/runtime_profile.local.json`:

```json
{
  "integrations": {
    "aether": "/my/custom/aether",
    "wraith": "/my/custom/wraith"
  }
}
```

If a subsystem repo is not publicly available, OpenChimera continues to operate in
full degraded-acceptable mode: all core APIs, Ascension, the God Swarm, the audit
pipeline, and chimeralang-mcp integration work without them.

## Memory-Recovered Integrations

OpenChimera now preserves historically important integrations recovered from the OpenClaw memory corpus even when they are not yet first-class runtime bridges.

These include:

- Project Seraph
- RuView / RuVector / RuFlo tri-core architecture
- Clawd Hybrid RTX
- Qwen-Agent bridge
- Context-Hub and related recovered integration stacks
- Hitchhiker reasoning-shim protocol
- Prometheus research surface
- AETHER operator stack lineage
- Aegis Core control-plane lineage

ABO cluster and the CCTV / Imou vision work are preserved as private archival history only. They are intentionally excluded from the managed subsystem inventory and open-source onboarding flow.

These public-facing legacy surfaces appear in the integration audit and managed subsystem inventory as memory-recovered context so prior work is not silently lost.

Other recovered architecture patterns are treated as roadmap inputs for internal OpenChimera evolution rather than as first-class integrations until they have a concrete runtime surface.

## Repository Policy

Machine-specific paths belong in `config/runtime_profile.local.json` or another private profile referenced through `OPENCHIMERA_RUNTIME_PROFILE`.

The committed `config/runtime_profile.json` should remain generic and publishable.
