#!/usr/bin/env python3
"""OpenChimera Self-Evolution Cycle.

Invoked by the self-evolution GitHub Actions workflow every 24 hours.
This script:
  1. Reads the evolution memory log to avoid duplicate cycles.
  2. Collects a snapshot/summary of the current repository state for review.
  3. Queries GitHub Copilot (via the GitHub Models API) for actionable
     self-improvement suggestions based on that summary.
  4. Writes the generated report/artifacts for the workflow run.
  5. Appends an unsigned entry to the evolution memory log so the next
     scheduled run knows not to repeat the cycle within 23 h.
  6. Writes the evolution branch name and cycle ID to ``$GITHUB_OUTPUT``
     so the caller workflow can create a pull request with the artefacts.

Environment variables (injected by the workflow):
  GITHUB_TOKEN         — personal/actions token with repo + models scope
  GITHUB_REPOSITORY    — e.g. "fernandogarzaaa/OpenChimera_v1"
  GITHUB_SHA           — current HEAD commit SHA
  GITHUB_RUN_ID        — workflow run identifier
  EVOLUTION_MEMORY_PATH — path to evolution-memory.json (optional)
  GITHUB_OUTPUT        — path to the GitHub Actions output file (set
                         automatically by Actions; omitted in local runs)

Scope
-----
The evolution cycle inspects the **entire repository** in its current checked-
out state.  Specifically it looks at:

* **Python source & test files** — counts, module names, and the active
  ``core/`` module surface area.
* **EvolutionEngine internal state** — episodic memory (DPO pairs, preference
  dataset size, model fitness scores, threshold adaptation history).
* **Evolution memory log** — ```.github/evolution-memory.json``` — records
  which cycles have already run, preventing double-execution within 23 h.
* **GitHub Copilot / Models API** — receives the health snapshot above and
  returns ranked, actionable self-improvement suggestions.

Sources
-------
1. File-system walk of the repository (``pathlib.Path.rglob``).
2. ``core.evolution.EvolutionEngine`` (DPO pairs from
   ``core.memory.episodic.EpisodicMemory`` → SQLite via
   ``core._database_fallback.DatabaseManager``).
3. GitHub Models REST API (``https://models.inference.ai.azure.com``) using the
   ``GITHUB_TOKEN`` Bearer credential.

Limitations
-----------
* **No code generation / automatic patch application.** The cycle produces
  *recommendations* and a human-readable report.  A pull request is opened so
  that human reviewers can evaluate and merge suggested changes.
* **DPO pairs require episodic memory entries.** On a fresh deployment with no
  prior ``EpisodicMemory`` records the ``EvolutionEngine`` will produce zero
  pairs and zero dataset entries; the LoRA adapter registration step is skipped.
* **Copilot API requires a valid token.** Without ``GITHUB_TOKEN`` (or when the
  token lacks the ``models: read`` scope) Copilot insights are skipped and
  replaced with a placeholder message.
* **23-hour loop guard.** If the last cycle ran fewer than 23 hours ago the
  script exits cleanly without executing a second cycle.  This prevents
  runaway evolution triggered by back-to-back workflow retries.
* **Shallow clone awareness.** The health snapshot reflects only files visible
  in the current checkout; it does not analyse git history.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
# Ensure log timestamps use UTC so the trailing "Z" designator is accurate.
logging.Formatter.converter = time.gmtime
log = logging.getLogger("self_evolution_cycle")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
MEMORY_PATH = Path(
    os.environ.get("EVOLUTION_MEMORY_PATH", ".github/evolution-memory.json")
)
if not MEMORY_PATH.is_absolute():
    MEMORY_PATH = REPO_ROOT / MEMORY_PATH

# 23 h guard — 1 h shorter than the 24 h cron schedule to absorb scheduling
# jitter (GitHub Actions can fire a few minutes late) while still preventing
# genuine double-runs within the same day.
MIN_CYCLE_INTERVAL_SECONDS = 23 * 3600
MEMORY_MAX_CYCLES = 90  # keep last 90 entries in the log

# GitHub Models endpoint (provides Copilot / GPT-4o access with a standard token)
COPILOT_API_URL = "https://models.inference.ai.azure.com/chat/completions"
COPILOT_MODEL = "gpt-4o"

# ---------------------------------------------------------------------------
# Memory log helpers
# ---------------------------------------------------------------------------


def load_memory() -> dict[str, Any]:
    """Load the evolution memory log, returning a default structure on error."""
    if MEMORY_PATH.exists():
        try:
            return json.loads(MEMORY_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            log.warning("Memory log contains invalid JSON (%s) — starting fresh.", exc)
        except OSError as exc:
            log.warning("Could not read memory log (%s) — starting fresh.", exc)
    return {"schema_version": 1, "last_cycle_timestamp": 0, "cycles": []}


def save_memory(data: dict[str, Any]) -> None:
    """Persist the evolution memory log atomically."""
    data["cycles"] = data.get("cycles", [])[-MEMORY_MAX_CYCLES:]
    MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = MEMORY_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(MEMORY_PATH)
    log.info("Memory log updated → %s", MEMORY_PATH)


def check_loop_guard(memory: dict[str, Any]) -> bool:
    """Return True if it is safe to proceed (last cycle was > MIN_CYCLE_INTERVAL_SECONDS ago)."""
    last_ts = float(memory.get("last_cycle_timestamp", 0))
    elapsed = time.time() - last_ts
    if elapsed < MIN_CYCLE_INTERVAL_SECONDS:
        log.warning(
            "Loop guard triggered — last cycle ran %.1f h ago (minimum gap: %.1f h). Skipping.",
            elapsed / 3600,
            MIN_CYCLE_INTERVAL_SECONDS / 3600,
        )
        return False
    return True


# ---------------------------------------------------------------------------
# System health summary (lightweight — avoids heavy import chain)
# ---------------------------------------------------------------------------


def build_health_summary() -> dict[str, Any]:
    """Return a lightweight summary of the repository's current state."""
    summary: dict[str, Any] = {
        "repo_root": str(REPO_ROOT),
        "python_version": sys.version.split()[0],
        "timestamp": time.time(),
    }

    # Count Python source files and test files
    py_files = list(REPO_ROOT.rglob("*.py"))
    test_files = [f for f in py_files if f.name.startswith("test_")]
    summary["source_file_count"] = len(py_files)
    summary["test_file_count"] = len(test_files)

    # Collect recent memory cycles for trend analysis
    memory = load_memory()
    summary["evolution_cycles_recorded"] = len(memory.get("cycles", []))
    summary["last_evolution_timestamp"] = memory.get("last_cycle_timestamp", 0)

    # Collect core module names as a capability fingerprint
    core_dir = REPO_ROOT / "core"
    if core_dir.is_dir():
        core_modules = sorted(
            f.stem for f in core_dir.glob("*.py") if not f.name.startswith("_")
        )
        summary["core_modules"] = core_modules
        summary["core_module_count"] = len(core_modules)

    return summary


# ---------------------------------------------------------------------------
# OpenChimera evolution engine (thin wrapper — avoids importing the full stack)
# ---------------------------------------------------------------------------


def run_evolution_engine() -> dict[str, Any]:
    """Run the EvolutionEngine cycle if the module is importable."""
    try:
        # Add repo root to sys.path so core modules resolve correctly
        if str(REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(REPO_ROOT))

        from core._bus_fallback import EventBus  # type: ignore[import]
        from core._database_fallback import DatabaseManager  # type: ignore[import]
        from core.evolution import EvolutionEngine  # type: ignore[import]

        bus = EventBus()
        db = DatabaseManager()
        engine = EvolutionEngine(db=db, bus=bus)
        result = engine.evolution_cycle()
        summary = engine.summary()
        log.info(
            "EvolutionEngine cycle complete — pairs=%d, adapter=%s",
            len(result.get("pairs", [])),
            result.get("adapter_id", "n/a"),
        )
        return {"status": "ok", "cycle": result, "summary": summary}
    except ImportError as exc:
        log.warning("EvolutionEngine not importable (missing dependency): %s", exc)
        return {"status": "skipped", "reason": f"ImportError: {exc}"}
    except Exception as exc:  # noqa: BLE001
        log.warning("EvolutionEngine cycle failed unexpectedly: %s", exc)
        return {"status": "skipped", "reason": str(exc)}


# ---------------------------------------------------------------------------
# GitHub Copilot (GitHub Models API) integration
# ---------------------------------------------------------------------------


def query_copilot(prompt: str, token: str) -> str:
    """Call the GitHub Models API with *prompt* and return the reply text."""
    payload = json.dumps(
        {
            "model": COPILOT_MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are the brain of OpenChimera, an autonomous AGI platform. "
                        "Your role is to analyze the system's current state and propose "
                        "concrete, safe, incremental self-improvements. Focus on code "
                        "quality, test coverage gaps, documentation, and architectural "
                        "hardening. Be concise and actionable."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "max_tokens": 1024,
            "temperature": 0.3,
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        COPILOT_API_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return body["choices"][0]["message"]["content"].strip()
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        log.warning("Copilot API HTTP error %d: %s", exc.code, body_text[:400])
        return f"[Copilot unavailable — HTTP {exc.code}]"
    except urllib.error.URLError as exc:
        log.warning("Copilot API network error: %s", exc.reason)
        return f"[Copilot unavailable — network error: {exc.reason}]"
    except json.JSONDecodeError as exc:
        log.warning("Copilot API returned invalid JSON: %s", exc)
        return "[Copilot unavailable — invalid JSON response]"
    except Exception as exc:  # noqa: BLE001
        log.warning("Copilot API unexpected error: %s", exc)
        return f"[Copilot unavailable — {exc}]"


def build_copilot_prompt(health: dict[str, Any], engine_result: dict[str, Any]) -> str:
    """Compose the prompt sent to GitHub Copilot."""
    lines = [
        "## OpenChimera Self-Evolution Audit",
        "",
        f"- Python version: {health['python_version']}",
        f"- Source files: {health.get('source_file_count', '?')}",
        f"- Test files:   {health.get('test_file_count', '?')}",
        f"- Core modules: {health.get('core_module_count', '?')} ({', '.join(health.get('core_modules', [])[:10])}…)",
        f"- Evolution cycles logged: {health.get('evolution_cycles_recorded', 0)}",
        "",
        "## EvolutionEngine result",
        f"- Status: {engine_result.get('status')}",
    ]
    if engine_result.get("status") == "ok":
        cycle = engine_result.get("cycle", {})
        lines += [
            f"- DPO pairs generated: {len(cycle.get('pairs', []))}",
            f"- Dataset size: {cycle.get('dataset_size', 0)}",
            f"- Adapter registered: {cycle.get('adapter_id', 'none')}",
        ]
        recs = cycle.get("recommendations", [])
        if recs:
            lines.append("- Recommendations from EvolutionEngine:")
            for rec in recs[:5]:
                if isinstance(rec, dict):
                    model = rec.get("model", "unknown")
                    action = rec.get("action", "unknown")
                    reason = rec.get("reason", "")
                    lines.append(f"  • [{action.upper()}] {model}: {reason}")
                else:
                    lines.append(f"  • {rec}")
    else:
        lines.append(f"- Skipped reason: {engine_result.get('reason', '')}")

    lines += [
        "",
        "Based on this audit, list the top 3–5 concrete, safe self-improvement actions "
        "OpenChimera should take in its next evolution cycle. Format as a numbered list.",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Write evolution insights to a markdown report
# ---------------------------------------------------------------------------


_SCOPE_AND_LIMITATIONS = """\
## Scope & Limitations

**Scope — what this cycle inspects:**
- All Python source and test files visible in the current repository checkout.
- `core/` module surface area (module count and names).
- `EvolutionEngine` internal state: episodic memory DPO pairs, preference
  dataset size, model fitness scores, and threshold adaptation history.
- Evolution memory log (`.github/evolution-memory.json`) for trend analysis.
- GitHub Copilot / Models API response with ranked improvement suggestions.

**Sources:**
1. File-system walk of the repository (`pathlib.Path.rglob`).
2. `core.evolution.EvolutionEngine` → `core.memory.episodic.EpisodicMemory`
   → SQLite via `core._database_fallback.DatabaseManager`.
3. GitHub Models REST API (`https://models.inference.ai.azure.com`) using the
   `GITHUB_TOKEN` Bearer credential.

**Limitations:**
- **No automatic code changes.** The cycle produces recommendations and a
  human-readable report only.  The companion workflow opens a pull request so
  human reviewers can evaluate and merge suggested changes.
- **DPO pairs require prior episodic memory entries.** On a fresh deployment
  with no `EpisodicMemory` records the engine produces zero pairs and skips
  LoRA adapter registration.
- **Copilot API requires a valid token.** Without `GITHUB_TOKEN` (or when the
  token lacks `models: read` scope) Copilot insights are replaced with a
  placeholder.
- **23-hour loop guard.** A second cycle started within 23 hours of the
  previous one exits immediately to prevent runaway evolution.
- **Shallow clone awareness.** Health metrics reflect only files in the current
  checkout; git history is not analysed.
"""


def write_insights_report(
    cycle_id: int,
    health: dict[str, Any],
    engine_result: dict[str, Any],
    copilot_insights: str,
) -> Path:
    """Write a human-readable Markdown report for this cycle."""
    reports_dir = REPO_ROOT / "data" / "evolution_reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / f"cycle_{cycle_id:04d}.md"

    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    content = f"""# OpenChimera Self-Evolution Cycle {cycle_id}

**Timestamp:** {ts}  
**Run ID:** {os.environ.get("GITHUB_RUN_ID", "local")}  
**Commit:** {os.environ.get("GITHUB_SHA", "unknown")[:8]}

## System Health Snapshot

| Metric | Value |
|--------|-------|
| Python version | {health["python_version"]} |
| Source files | {health.get("source_file_count", "?")} |
| Test files | {health.get("test_file_count", "?")} |
| Core modules | {health.get("core_module_count", "?")} |
| Previous cycles | {health.get("evolution_cycles_recorded", 0)} |

## EvolutionEngine

**Status:** `{engine_result.get("status")}`

{_engine_section(engine_result)}

## GitHub Copilot Insights (Brain)

{copilot_insights}

{_SCOPE_AND_LIMITATIONS}
---
*Generated automatically by the OpenChimera Self-Evolution workflow.*
"""
    report_path.write_text(content, encoding="utf-8")
    log.info("Insights report written → %s", report_path)

    # Prune old reports so the directory doesn't grow without bound.
    # Keep the same number of reports as the memory log cap (MEMORY_MAX_CYCLES).
    _prune_old_reports(reports_dir, keep=MEMORY_MAX_CYCLES)

    return report_path


def _prune_old_reports(reports_dir: Path, keep: int) -> None:
    """Delete the oldest cycle_NNNN.md files, retaining at most *keep* files."""
    existing = sorted(reports_dir.glob("cycle_*.md"))
    to_delete = existing[: max(0, len(existing) - keep)]
    for old in to_delete:
        try:
            old.unlink()
            log.info("Pruned old report: %s", old.name)
        except OSError as exc:
            log.warning("Could not prune %s: %s", old, exc)


def _engine_section(engine_result: dict[str, Any]) -> str:
    if engine_result.get("status") != "ok":
        return f"Skipped: {engine_result.get('reason', 'unknown')}"
    cycle = engine_result.get("cycle", {})
    recs = cycle.get("recommendations", [])
    lines = [
        f"- DPO pairs: {len(cycle.get('pairs', []))}",
        f"- Dataset size: {cycle.get('dataset_size', 0)}",
        f"- Adapter: `{cycle.get('adapter_id', 'none')}`",
    ]
    if recs:
        lines.append("\n**Recommendations:**")
        for rec in recs:
            if isinstance(rec, dict):
                model = rec.get("model", "unknown")
                action = rec.get("action", "unknown")
                reason = rec.get("reason", "")
                lines.append(f"- **[{action.upper()}]** `{model}`: {reason}")
            else:
                lines.append(f"- {rec}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# GitHub Actions output helpers
# ---------------------------------------------------------------------------


def write_github_outputs(cycle_id: int, branch_name: str) -> None:
    """Write cycle metadata to ``$GITHUB_OUTPUT`` for use by the caller workflow.

    Sets the following step outputs:
    * ``cycle_id``    — integer cycle number (e.g. ``5``)
    * ``branch_name`` — git branch the workflow should push artefacts to
                        (e.g. ``evo/cycle-0005``)

    When ``$GITHUB_OUTPUT`` is not set (local / non-Actions run) this function
    is a no-op so the script can be executed locally without side effects.
    """
    github_output = os.environ.get("GITHUB_OUTPUT", "")
    if not github_output:
        log.debug("GITHUB_OUTPUT not set — skipping Actions output.")
        return
    try:
        with open(github_output, "a", encoding="utf-8") as fh:
            fh.write(f"cycle_id={cycle_id}\n")
            fh.write(f"branch_name={branch_name}\n")
        log.info(
            "GitHub Actions outputs written: cycle_id=%d, branch_name=%s",
            cycle_id,
            branch_name,
        )
    except OSError as exc:
        log.warning("Could not write to GITHUB_OUTPUT (%s): %s", github_output, exc)



def main() -> int:
    log.info("=== OpenChimera Self-Evolution Cycle starting ===")

    # 1. Load memory log
    memory = load_memory()

    # 2. Loop guard
    if not check_loop_guard(memory):
        log.info("Cycle skipped by loop guard. Exiting cleanly.")
        return 0

    # 3. Collect system health
    log.info("Collecting system health snapshot…")
    health = build_health_summary()

    # 4. Run the EvolutionEngine
    log.info("Running EvolutionEngine cycle…")
    engine_result = run_evolution_engine()

    # 5. Query GitHub Copilot for insights
    token = os.environ.get("GITHUB_TOKEN", "")
    if token:
        log.info("Querying GitHub Copilot for self-improvement insights…")
        prompt = build_copilot_prompt(health, engine_result)
        copilot_insights = query_copilot(prompt, token)
        log.info("Copilot response received (%d chars).", len(copilot_insights))
    else:
        copilot_insights = "[GITHUB_TOKEN not set — Copilot insights skipped]"
        log.warning("GITHUB_TOKEN not set; skipping Copilot query.")

    # 6. Determine next cycle ID
    existing_cycles = memory.get("cycles", [])
    last_cycle = existing_cycles[-1] if existing_cycles else {}
    last_cycle_id = last_cycle.get("cycle_id", 0) if isinstance(last_cycle, dict) else 0
    cycle_id = last_cycle_id + 1

    # 7. Write insights report
    report_path = write_insights_report(cycle_id, health, engine_result, copilot_insights)

    # 8. Update memory log
    now = time.time()
    entry: dict[str, Any] = {
        "cycle_id": cycle_id,
        "timestamp": now,
        "iso_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
        "run_id": os.environ.get("GITHUB_RUN_ID", "local"),
        "sha": os.environ.get("GITHUB_SHA", "unknown")[:8],
        "engine_status": engine_result.get("status"),
        "report": str(report_path.relative_to(REPO_ROOT)),
        "copilot_available": bool(token) and not copilot_insights.startswith("["),
    }
    if engine_result.get("status") == "ok":
        cycle_data = engine_result["cycle"]
        entry["dpo_pairs"] = len(cycle_data.get("pairs", []))
        entry["adapter_id"] = cycle_data.get("adapter_id")

    memory["last_cycle_timestamp"] = now
    memory.setdefault("cycles", []).append(entry)
    save_memory(memory)

    # 9. Expose cycle metadata to the GitHub Actions workflow so it can
    #    create a pull request with the generated artefacts.
    branch_name = f"evo/cycle-{cycle_id:04d}"
    write_github_outputs(cycle_id, branch_name)

    log.info("=== Cycle %d complete. Report: %s ===", cycle_id, report_path)
    log.info("Evolution branch: %s", branch_name)

    # Print a summary to stdout (captured by the workflow log)
    print("\n" + "=" * 60)
    print(f"OpenChimera Self-Evolution — Cycle {cycle_id}")
    print("=" * 60)
    print(copilot_insights)
    print("=" * 60 + "\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
