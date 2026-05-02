"""Simulated Sandbox Environment for New User Experience.

Drives the full new-user journey through OpenChimera in five phases:

  Phase 1 — Environment Setup        (import checks, bootstrap, DB, config)
  Phase 2 — Functions Discovery      (capabilities, plugins, commands, models)
  Phase 3 — Capabilities Testing     (query engine, AGI modules, plan/memory)
  Phase 4 — Bug & Error Detection    (graceful degradation, edge cases, paths)
  Phase 5 — Beta Readiness           (health, safety, auth, API contract)

Results are collected into a ``BetaReadinessReport`` that provides a
structured pass/fail breakdown and an overall readiness score (0–100).
"""
from __future__ import annotations

import importlib
import os
import re
import tempfile
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class CheckResult:
    name: str
    phase: str
    passed: bool
    message: str = ""
    error: str = ""
    duration_ms: float = 0.0


@dataclass
class PhaseResult:
    name: str
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def pass_count(self) -> int:
        return sum(1 for c in self.checks if c.passed)

    @property
    def fail_count(self) -> int:
        return sum(1 for c in self.checks if not c.passed)


@dataclass
class BetaReadinessReport:
    phases: list[PhaseResult] = field(default_factory=list)
    generated_at: str = ""
    total_duration_ms: float = 0.0

    # ------------------------------------------------------------------
    # Aggregates
    # ------------------------------------------------------------------

    @property
    def all_checks(self) -> list[CheckResult]:
        return [c for phase in self.phases for c in phase.checks]

    @property
    def pass_count(self) -> int:
        return sum(1 for c in self.all_checks if c.passed)

    @property
    def fail_count(self) -> int:
        return sum(1 for c in self.all_checks if not c.passed)

    @property
    def score(self) -> float:
        total = len(self.all_checks)
        if total == 0:
            return 0.0
        return round(self.pass_count / total * 100, 1)

    @property
    def verdict(self) -> str:
        score = self.score
        if score >= 95:
            return "PRODUCTION_READY"
        if score >= 80:
            return "BETA_READY"
        if score >= 60:
            return "ALPHA_QUALITY"
        return "NOT_READY"

    @property
    def failed_checks(self) -> list[CheckResult]:
        return [c for c in self.all_checks if not c.passed]

    def summary(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "verdict": self.verdict,
            "pass_count": self.pass_count,
            "fail_count": self.fail_count,
            "total_checks": len(self.all_checks),
            "generated_at": self.generated_at,
            "total_duration_ms": self.total_duration_ms,
            "phases": [
                {
                    "name": p.name,
                    "passed": p.passed,
                    "pass_count": p.pass_count,
                    "fail_count": p.fail_count,
                    "checks": [
                        {
                            "name": c.name,
                            "passed": c.passed,
                            "message": c.message,
                            "error": c.error,
                            "duration_ms": c.duration_ms,
                        }
                        for c in p.checks
                    ],
                }
                for p in self.phases
            ],
        }


# ---------------------------------------------------------------------------
# Runner helper
# ---------------------------------------------------------------------------


def _run_check(phase: str, name: str, fn: Callable[[], str | None]) -> CheckResult:
    """Execute *fn* and wrap the outcome in a CheckResult.

    *fn* should return ``None`` or an empty string on success, or a human-readable
    failure message on failure.  Any unhandled exception is caught and treated
    as a failure.
    """
    start = time.perf_counter()
    try:
        failure_msg = fn()
        elapsed = (time.perf_counter() - start) * 1000
        if failure_msg:
            return CheckResult(name=name, phase=phase, passed=False, message=failure_msg, duration_ms=elapsed)
        return CheckResult(name=name, phase=phase, passed=True, message="ok", duration_ms=elapsed)
    except Exception as exc:  # noqa: BLE001
        elapsed = (time.perf_counter() - start) * 1000
        return CheckResult(
            name=name,
            phase=phase,
            passed=False,
            message=str(exc),
            error=traceback.format_exc(),
            duration_ms=elapsed,
        )


# ---------------------------------------------------------------------------
# SandboxSimulation
# ---------------------------------------------------------------------------


class SandboxSimulation:
    """Orchestrates the full simulated new-user experience sandbox.

    Usage::

        sim = SandboxSimulation()
        report = sim.run()
        print(report.verdict)          # e.g. "BETA_READY"
        print(report.score)            # e.g. 93.2
        for c in report.failed_checks:
            print(c.name, c.message)
    """

    def __init__(self, tmp_dir: str | None = None) -> None:
        self._owned_tmp = tmp_dir is None
        self._tmp_dir = tmp_dir or tempfile.mkdtemp(prefix="oc-sandbox-sim-")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self) -> BetaReadinessReport:
        """Run all five phases and return a BetaReadinessReport."""
        import datetime

        report = BetaReadinessReport(generated_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
        start = time.perf_counter()

        try:
            report.phases.append(self._phase1_environment_setup())
            report.phases.append(self._phase2_functions_discovery())
            report.phases.append(self._phase3_capabilities_testing())
            report.phases.append(self._phase4_bug_error_detection())
            report.phases.append(self._phase5_beta_readiness())
        finally:
            report.total_duration_ms = (time.perf_counter() - start) * 1000
            if self._owned_tmp:
                import shutil

                shutil.rmtree(self._tmp_dir, ignore_errors=True)

        return report

    # ------------------------------------------------------------------
    # Phase 1 — Environment Setup
    # ------------------------------------------------------------------

    def _phase1_environment_setup(self) -> PhaseResult:
        phase = PhaseResult(name="phase1_environment_setup")
        p = "phase1"

        phase.checks.append(_run_check(p, "core_package_importable", self._chk_core_importable))
        phase.checks.append(_run_check(p, "bootstrap_workspace_runs", self._chk_bootstrap))
        phase.checks.append(_run_check(p, "database_initializes", self._chk_db_init))
        phase.checks.append(_run_check(p, "eventbus_pubsub", self._chk_eventbus))
        phase.checks.append(_run_check(p, "config_loads_defaults", self._chk_config_defaults))
        phase.checks.append(_run_check(p, "runtime_profile_normalizes", self._chk_profile_normalize))
        phase.checks.append(_run_check(p, "credential_store_fresh_db", self._chk_credential_store))

        return phase

    def _chk_core_importable(self) -> str | None:
        core_modules = [
            "core", "core.config", "core.bus", "core.kernel",
            "core.provider", "core.query_engine", "core.api_server",
        ]
        failed = []
        for mod in core_modules:
            try:
                importlib.import_module(mod)
            except ImportError as exc:
                failed.append(f"{mod}: {exc}")
        return ("; ".join(failed)) if failed else None

    def _chk_bootstrap(self) -> str | None:
        from core.bootstrap import bootstrap_workspace
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmp:
            with patch("core.bootstrap.ROOT", Path(tmp)):
                result = bootstrap_workspace()
        if result.get("status") not in ("ok", "already_bootstrapped"):
            return f"unexpected status: {result.get('status')}"
        return None

    def _chk_db_init(self) -> str | None:
        from core.database import DatabaseManager

        db_path = Path(self._tmp_dir) / "setup_check.db"
        db = DatabaseManager(db_path=str(db_path))
        db.initialize()
        if not db_path.exists():
            return "database file not created"
        db.close()
        return None

    def _chk_eventbus(self) -> str | None:
        from core.bus import EventBus

        bus = EventBus()
        received: list[Any] = []
        bus.subscribe("sandbox.test", lambda data: received.append(data))
        bus.publish("sandbox.test", {"ping": True})
        if len(received) != 1 or not received[0].get("ping"):
            return f"expected 1 event with ping=True, got {received}"
        return None

    def _chk_config_defaults(self) -> str | None:
        from core.config import load_runtime_profile

        load_runtime_profile.cache_clear()
        with tempfile.TemporaryDirectory() as tmp:
            from unittest.mock import patch

            fake = Path(tmp) / "nonexistent.json"
            with patch("core.config.get_runtime_profile_path", return_value=fake):
                profile = load_runtime_profile()
        if not isinstance(profile, dict):
            return f"profile is {type(profile)}, expected dict"
        return None

    def _chk_profile_normalize(self) -> str | None:
        from core.config import normalize_runtime_profile, validate_runtime_profile

        partial: dict[str, Any] = {"providers": {"enabled": ["openai"]}}
        normalized, _ = normalize_runtime_profile(partial)
        errors = validate_runtime_profile(normalized)
        critical = [e for e in errors if "critical" in e.lower()]
        if critical:
            return f"critical validation errors: {critical}"
        return None

    def _chk_credential_store(self) -> str | None:
        from core.credential_store import CredentialStore
        from core.database import DatabaseManager

        db = DatabaseManager(db_path=str(Path(self._tmp_dir) / "creds_check.db"))
        db.initialize()
        store = CredentialStore(database=db)
        keys = store.list_keys() if hasattr(store, "list_keys") else []
        if not isinstance(keys, list):
            return f"list_keys returned {type(keys)}"
        db.close()
        return None

    # ------------------------------------------------------------------
    # Phase 2 — Functions Discovery
    # ------------------------------------------------------------------

    def _phase2_functions_discovery(self) -> PhaseResult:
        phase = PhaseResult(name="phase2_functions_discovery")
        p = "phase2"

        phase.checks.append(_run_check(p, "capability_registry_snapshot", self._chk_capability_snapshot))
        phase.checks.append(_run_check(p, "plugin_manager_lists_plugins", self._chk_plugin_list))
        phase.checks.append(_run_check(p, "command_registry_lists_commands", self._chk_command_list))
        phase.checks.append(_run_check(p, "model_registry_refreshes", self._chk_model_registry))
        phase.checks.append(_run_check(p, "onboarding_status_structure", self._chk_onboarding_status))
        phase.checks.append(_run_check(p, "all_core_modules_importable", self._chk_all_core_modules))
        phase.checks.append(_run_check(p, "tool_registry_initializes", self._chk_tool_registry))
        phase.checks.append(_run_check(p, "chimera_bridge_status", self._chk_chimera_status))

        return phase

    def _chk_capability_snapshot(self) -> str | None:
        from core.capabilities import CapabilityRegistry

        snap = CapabilityRegistry().snapshot()
        if not isinstance(snap, dict):
            return f"snapshot is {type(snap)}"
        return None

    def _chk_plugin_list(self) -> str | None:
        from core.capabilities import CapabilityRegistry
        from core.plugins import PluginManager

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "plugins").mkdir()
            (root / "plugins" / "demo.json").write_text(
                '{"id":"demo","name":"Demo","version":"1.0.0","description":"sandbox demo"}',
                encoding="utf-8",
            )
            pm = PluginManager(CapabilityRegistry(root=root), state_path=root / "state.json")
            plugins = pm.list_plugins()
        if not isinstance(plugins, list):
            return f"list_plugins returned {type(plugins)}"
        if len(plugins) == 0:
            return "no plugins discovered in stub layout"
        return None

    def _chk_command_list(self) -> str | None:
        from core.command_registry import CommandRegistry

        commands = CommandRegistry().list_commands()
        if not isinstance(commands, list):
            return f"list_commands returned {type(commands)}"
        return None

    def _chk_model_registry(self) -> str | None:
        from core.model_registry import ModelRegistry

        reg = ModelRegistry()
        reg.registry_path = Path(self._tmp_dir) / "disc_model_registry.json"
        reg.profile = {
            "hardware": {
                "cpu_count": 4,
                "ram_gb": 8,
                "gpu": {"available": False, "name": "cpu-only", "vram_gb": 0, "device_count": 0},
            },
            "model_inventory": {"available_models": []},
            "local_runtime": {},
        }
        payload = reg.refresh()
        if "hardware" not in payload:
            return "refresh() missing 'hardware' key"
        if "recommendations" not in payload:
            return "refresh() missing 'recommendations' key"
        return None

    def _chk_onboarding_status(self) -> str | None:
        from core.channels import ChannelManager
        from core.credential_store import CredentialStore
        from core.model_registry import ModelRegistry
        from core.onboarding import OnboardingManager

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            creds = CredentialStore(store_path=root / "creds.json")
            channels = ChannelManager(store_path=root / "subs.json")
            reg = ModelRegistry(credential_store=creds)
            reg.registry_path = root / "reg.json"
            reg.profile = {
                "hardware": {
                    "cpu_count": 4,
                    "ram_gb": 8,
                    "gpu": {"available": False, "name": "cpu-only", "vram_gb": 0, "device_count": 0},
                },
                "model_inventory": {"available_models": []},
                "local_runtime": {},
                "providers": {"enabled": ["openchimera-gateway"]},
            }
            reg.refresh()
            mgr = OnboardingManager(
                reg, creds, channels,
                state_path=root / "onboarding.json",
                profile_loader=lambda: reg.profile,
                profile_saver=lambda _p: None,
            )
            status = mgr.status()
        required_keys = {"steps", "recommendations", "blockers", "next_actions", "completed"}
        missing = required_keys - set(status.keys())
        if missing:
            return f"onboarding status missing keys: {missing}"
        return None

    def _chk_all_core_modules(self) -> str | None:
        critical_modules = [
            "core.kernel", "core.bus", "core.provider", "core.personality",
            "core.self_model", "core.causal_reasoning", "core.meta_learning",
            "core.ethical_reasoning", "core.social_cognition", "core.embodied_interaction",
            "core.transfer_learning", "core.world_model", "core.plan_mode",
            "core.agent_coordinator", "core.knowledge_base", "core.safety_layer",
            "core.identity_manager", "core.health_monitor", "core.session_memory",
            "core.query_engine", "core.rag", "core.command_registry", "core.tool_registry",
        ]
        failed = []
        for mod in critical_modules:
            try:
                importlib.import_module(mod)
            except ImportError as exc:
                failed.append(f"{mod}: {exc}")
        return ("; ".join(failed)) if failed else None

    def _chk_tool_registry(self) -> str | None:
        from core.tool_registry import ToolRegistry

        reg = ToolRegistry()
        tools = reg.list_tools() if hasattr(reg, "list_tools") else []
        if not isinstance(tools, list):
            return f"list_tools returned {type(tools)}"
        return None

    def _chk_chimera_status(self) -> str | None:
        from core.chimera_bridge import get_bridge

        status = get_bridge().status()
        if "available" not in status:
            return "bridge status missing 'available' key"
        if "version" not in status:
            return "bridge status missing 'version' key"
        return None

    # ------------------------------------------------------------------
    # Phase 3 — Capabilities Testing
    # ------------------------------------------------------------------

    def _phase3_capabilities_testing(self) -> PhaseResult:
        phase = PhaseResult(name="phase3_capabilities_testing")
        p = "phase3"

        phase.checks.append(_run_check(p, "query_engine_initializes", self._chk_query_engine_init))
        phase.checks.append(_run_check(p, "query_engine_run_query", self._chk_query_engine_query))
        phase.checks.append(_run_check(p, "plan_mode_full_lifecycle", self._chk_plan_lifecycle))
        phase.checks.append(_run_check(p, "session_memory_roundtrip", self._chk_session_memory))
        phase.checks.append(_run_check(p, "self_model_capability_tracking", self._chk_self_model))
        phase.checks.append(_run_check(p, "causal_reasoning_graph", self._chk_causal_reasoning))
        phase.checks.append(_run_check(p, "meta_learning_strategies", self._chk_meta_learning))
        phase.checks.append(_run_check(p, "ethical_reasoning_evaluation", self._chk_ethical_reasoning))
        phase.checks.append(_run_check(p, "transfer_learning_patterns", self._chk_transfer_learning))
        phase.checks.append(_run_check(p, "knowledge_base_add_search", self._chk_knowledge_base))
        phase.checks.append(_run_check(p, "safety_layer_validates", self._chk_safety_layer))
        phase.checks.append(_run_check(p, "multi_agent_orchestrator_status", self._chk_orch_status))
        phase.checks.append(_run_check(p, "chimera_bridge_run_program", self._chk_chimera_run))
        phase.checks.append(_run_check(p, "health_monitor_tracks_subsystems", self._chk_health_monitor))

        return phase

    def _make_query_engine(self, tmp_path: str) -> Any:
        from core.capabilities import CapabilityRegistry
        from core.model_registry import ModelRegistry
        from core.model_roles import ModelRoleManager
        from core.query_engine import QueryEngine

        caps = CapabilityRegistry()
        reg = ModelRegistry()
        reg.registry_path = Path(tmp_path) / "qe_registry.json"
        reg.profile = {
            "hardware": {"cpu_count": 4, "ram_gb": 8, "gpu": {"available": False, "name": "cpu-only", "vram_gb": 0, "device_count": 0}},
            "model_inventory": {"available_models": []},
            "local_runtime": {},
        }
        roles = ModelRoleManager(reg)
        return QueryEngine(
            capability_registry=caps,
            model_roles=roles,
            tool_registry=None,
            completion_callback=lambda **kw: {"content": f"mock: {kw.get('query','')}", "model": "mock"},
            sessions_path=Path(tmp_path) / "sessions.json",
            tool_history_path=Path(tmp_path) / "tool_history.json",
        )

    def _chk_query_engine_init(self) -> str | None:
        with tempfile.TemporaryDirectory() as tmp:
            qe = self._make_query_engine(tmp)
            status = qe.status()
        if "session_count" not in status:
            return "status missing 'session_count'"
        return None

    def _chk_query_engine_query(self) -> str | None:
        with tempfile.TemporaryDirectory() as tmp:
            qe = self._make_query_engine(tmp)
            result = qe.run_query(query="What is OpenChimera?", permission_scope="user")
        if result is None:
            return "run_query returned None"
        if "response" not in result:
            return f"result missing 'response' key, got: {list(result.keys())}"
        return None

    def _chk_plan_lifecycle(self) -> str | None:
        from core.plan_mode import PlanMode, PlanStatus, StepStatus

        pm = PlanMode()
        plan = pm.create_plan(
            name="Sandbox Test Plan",
            description="Lifecycle test",
            steps=[
                {"description": "Step A"},
                {"description": "Step B"},
            ],
        )
        if plan.status != PlanStatus.PENDING:
            return f"new plan status should be PENDING, got {plan.status}"
        pm.start_plan(plan.plan_id)
        if pm.get_plan(plan.plan_id).status != PlanStatus.IN_PROGRESS:
            return "after start_plan status should be IN_PROGRESS"
        for step in pm.get_plan(plan.plan_id).steps:
            pm.update_step(plan.plan_id, step.step_id, StepStatus.COMPLETED)
        final = pm.get_plan(plan.plan_id)
        if final.status != PlanStatus.COMPLETED:
            return f"after all steps completed, plan status is {final.status}"
        return None

    def _chk_session_memory(self) -> str | None:
        from core.session_memory import SessionMemory

        with tempfile.TemporaryDirectory() as tmp:
            sm = SessionMemory(session_id="sandbox-roundtrip", store_root=Path(tmp))
            sm.append_turn(role="user", content="hello sandbox")
            sm.append_turn(role="assistant", content="hello user")
            sm.save()
            sm2 = SessionMemory.load(session_id="sandbox-roundtrip", store_root=Path(tmp))
            turns = sm2.get_turns()
        if len(turns) < 2:
            return f"expected ≥2 turns after save+load, got {len(turns)}"
        if not any(t["role"] == "user" and "hello" in t["content"] for t in turns):
            return "user turn not found after reload"
        return None

    def _chk_self_model(self) -> str | None:
        from core.bus import EventBus
        from core.self_model import SelfModel

        sm = SelfModel(bus=EventBus())
        snap = sm.record_capability("reasoning", "accuracy", 0.85, sample_count=10)
        if snap.domain != "reasoning":
            return f"snap.domain={snap.domain}"
        assessment = sm.self_assessment()
        if "capabilities_tracked" not in assessment:
            return "self_assessment() missing 'capabilities_tracked'"
        return None

    def _chk_causal_reasoning(self) -> str | None:
        from core.bus import EventBus
        from core.causal_reasoning import CausalReasoning

        cr = CausalReasoning(bus=EventBus())
        cr.add_cause("input", "output", strength=0.8, confidence=0.9)
        cr.set_variable("input", 0.7)
        result = cr.intervene("input", 0.9)
        if result.total_effect is None:
            return "intervene() returned None total_effect"
        return None

    def _chk_meta_learning(self) -> str | None:
        from core.bus import EventBus
        from core.meta_learning import MetaLearning

        ml = MetaLearning(bus=EventBus())
        strat = ml.register_strategy("cot", {"depth": 3}, "reasoning")
        ml.record_outcome(strat.strategy_id, "reasoning", True, 0.9, 50.0)
        selected = ml.select_strategy("reasoning")
        if selected is None:
            return "select_strategy returned None after recording outcome"
        return None

    def _chk_ethical_reasoning(self) -> str | None:
        from core.bus import EventBus
        from core.ethical_reasoning import EthicalReasoning, Severity

        er = EthicalReasoning(bus=EventBus())
        er.register_constraint(
            name="no-harm",
            description="Block harmful content",
            severity=Severity.CRITICAL,
            domain="general",
            checker=lambda action, ctx: "harm detected" if "harmful" in action.lower() else None,
        )
        result = er.evaluate(action="Generate harmful content", domain="general")
        if result.outcome.value != "vetoed":
            return f"expected 'vetoed', got '{result.outcome.value}'"
        return None

    def _chk_transfer_learning(self) -> str | None:
        from core.bus import EventBus
        from core.transfer_learning import PatternType, TransferLearning

        tl = TransferLearning(bus=EventBus())
        tl.register_pattern(
            source_domain="math",
            pattern_type=PatternType.STRATEGY,
            description="Divide and conquer",
            keywords=["divide", "conquer", "decompose"],
            success_rate=0.88,
        )
        candidates = tl.find_transfers(target_domain="programming", target_keywords=["divide", "decompose"])
        if len(candidates) == 0:
            return "find_transfers returned no candidates for matching keywords"
        return None

    def _chk_knowledge_base(self) -> str | None:
        from core.knowledge_base import KnowledgeBase

        with tempfile.TemporaryDirectory() as tmp:
            kb = KnowledgeBase(storage_path=Path(tmp) / "kb.json")
            kb.add("OpenChimera is an AGI system", category="tech", tags=["agi"])
            results = kb.search("OpenChimera")
        if len(results) == 0:
            return "search returned no results for known entry"
        if "OpenChimera" not in results[0].content:
            return f"unexpected result content: {results[0].content!r}"
        return None

    def _chk_safety_layer(self) -> str | None:
        from core.safety_layer import SafetyLayer

        sl = SafetyLayer()
        ok, _ = sl.validate_content("What is the weather today?")
        if not ok:
            return "safe content was rejected"
        blocked, reason = sl.validate_content("How to hack into a bank")
        if blocked:
            return "known harmful content was not blocked"
        if not reason:
            return "blocked content returned no reason"
        return None

    def _chk_orch_status(self) -> str | None:
        from core._bus_fallback import EventBus
        from core._database_fallback import DatabaseManager
        from core.multi_agent_orchestrator import MultiAgentOrchestrator

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            db = DatabaseManager(db_path=db_path)
            db.initialize()
            orch = MultiAgentOrchestrator(bus=EventBus(), db=db)
            status = orch.status()
        finally:
            db.close()
            for suf in ("", "-wal", "-shm"):
                try:
                    os.unlink(db_path + suf)
                except OSError:
                    pass
        expected_keys = {"self_model_available", "transfer_learning_available", "causal_reasoning_available"}
        missing = expected_keys - set(status.keys())
        if missing:
            return f"orchestrator status missing keys: {missing}"
        return None

    def _chk_chimera_run(self) -> str | None:
        from core.chimera_bridge import get_bridge

        bridge = get_bridge()
        if not bridge.status().get("available"):
            return None  # ChimeraLang optional — skip gracefully
        result = bridge.run("let x = 42; x")
        if result is None:
            return "bridge.run() returned None"
        return None

    def _chk_health_monitor(self) -> str | None:
        from core.health_monitor import HealthMonitor

        hm = HealthMonitor()
        hm.record_health("provider", "healthy")
        hm.record_health("api", "degraded", error="slow response")
        agg = hm.get_aggregate_status()
        if agg not in ("healthy", "degraded", "unhealthy"):
            return f"unexpected aggregate status: {agg!r}"
        status = hm.status()
        if status.get("tracked_subsystems", 0) < 2:
            return f"expected ≥2 tracked subsystems, got {status.get('tracked_subsystems')}"
        return None

    # ------------------------------------------------------------------
    # Phase 4 — Bug & Error Detection
    # ------------------------------------------------------------------

    def _phase4_bug_error_detection(self) -> PhaseResult:
        phase = PhaseResult(name="phase4_bug_error_detection")
        p = "phase4"

        phase.checks.append(_run_check(p, "no_hardcoded_user_paths_in_core", self._chk_no_hardcoded_paths))
        phase.checks.append(_run_check(p, "query_engine_handles_empty_input", self._chk_empty_query))
        phase.checks.append(_run_check(p, "config_handles_missing_file", self._chk_config_missing_file))
        phase.checks.append(_run_check(p, "safety_layer_handles_empty_string", self._chk_safety_empty))
        phase.checks.append(_run_check(p, "plan_mode_handles_no_steps", self._chk_plan_no_steps))
        phase.checks.append(_run_check(p, "knowledge_base_search_empty", self._chk_kb_empty_search))
        phase.checks.append(_run_check(p, "session_memory_load_nonexistent", self._chk_session_load_missing))
        phase.checks.append(_run_check(p, "tool_executor_permission_gating", self._chk_tool_permission))
        phase.checks.append(_run_check(p, "config_validation_catches_bad_failover", self._chk_config_bad_failover))
        phase.checks.append(_run_check(p, "model_registry_cpu_only_no_crash", self._chk_registry_cpu_only))

        return phase

    def _chk_no_hardcoded_paths(self) -> str | None:
        from core.config import ROOT

        pattern = re.compile(r"(?<!['\"/])/(home|Users)/[\w/]+")
        violations: list[str] = []
        for py_file in (ROOT / "core").rglob("*.py"):
            content = py_file.read_text(encoding="utf-8", errors="replace")
            lines = [ln for ln in content.splitlines() if not ln.strip().startswith("#")]
            matches = pattern.findall("\n".join(lines))
            if matches:
                violations.append(f"{py_file.name}: {matches[:3]}")
        if violations:
            return "hardcoded /home or /Users paths found: " + "; ".join(violations[:5])
        return None

    def _chk_empty_query(self) -> str | None:
        with tempfile.TemporaryDirectory() as tmp:
            qe = self._make_query_engine(tmp)
            try:
                result = qe.run_query(query="", permission_scope="user")
            except Exception as exc:
                return f"empty query raised exception: {exc}"
        if result is None:
            return "empty query returned None (should return a response)"
        return None

    def _chk_config_missing_file(self) -> str | None:
        from core.config import load_runtime_profile
        from unittest.mock import patch

        load_runtime_profile.cache_clear()
        with tempfile.TemporaryDirectory() as tmp:
            with patch("core.config.get_runtime_profile_path", return_value=Path(tmp) / "ghost.json"):
                try:
                    profile = load_runtime_profile()
                except Exception as exc:
                    return f"raised exception on missing file: {exc}"
        if not isinstance(profile, dict):
            return "expected dict for missing-file fallback"
        return None

    def _chk_safety_empty(self) -> str | None:
        from core.safety_layer import SafetyLayer

        sl = SafetyLayer()
        try:
            result = sl.validate_content("")
        except Exception as exc:
            return f"empty string raised: {exc}"
        if not isinstance(result, tuple) or len(result) != 2:
            return f"expected (bool, str|None) tuple, got {result!r}"
        return None

    def _chk_plan_no_steps(self) -> str | None:
        from core.plan_mode import PlanMode

        pm = PlanMode()
        try:
            plan = pm.create_plan(name="Empty Plan", description="no steps", steps=[])
        except Exception as exc:
            return f"raised on empty steps: {exc}"
        if plan is None:
            return "create_plan returned None for empty steps"
        return None

    def _chk_kb_empty_search(self) -> str | None:
        from core.knowledge_base import KnowledgeBase

        with tempfile.TemporaryDirectory() as tmp:
            kb = KnowledgeBase(storage_path=Path(tmp) / "empty_kb.json")
            try:
                results = kb.search("anything")
            except Exception as exc:
                return f"search on empty KB raised: {exc}"
        if not isinstance(results, list):
            return f"expected list, got {type(results)}"
        return None

    def _chk_session_load_missing(self) -> str | None:
        from core.session_memory import SessionMemory

        with tempfile.TemporaryDirectory() as tmp:
            try:
                sm = SessionMemory.load(session_id="ghost-session-xyz", store_root=Path(tmp))
                # If load returns None or empty, that's acceptable
                if sm is not None:
                    turns = sm.get_turns()
                    if not isinstance(turns, list):
                        return f"get_turns() returned {type(turns)}"
            except FileNotFoundError:
                return None  # acceptable: file not found is a valid response
            except Exception as exc:
                return f"unexpected exception loading nonexistent session: {exc}"
        return None

    def _chk_tool_permission(self) -> str | None:
        from core.bus import EventBus
        from core.tool_executor import ToolExecutor, ToolPermissionError

        executor = ToolExecutor(bus=EventBus())
        try:
            executor.execute_with_gating(
                tool_id="admin-tool",
                handler=lambda **kw: {"result": "ran"},
                requires_admin=True,
                permission_scope="user",
            )
            return "expected ToolPermissionError for admin tool with user scope, but none raised"
        except ToolPermissionError:
            return None
        except Exception as exc:
            return f"unexpected exception type: {type(exc).__name__}: {exc}"

    def _chk_config_bad_failover(self) -> str | None:
        from core.config import normalize_runtime_profile, validate_runtime_profile

        bad: dict[str, Any] = {"providers": {"enabled": ["openai"], "failover_chain": "not-a-list"}}
        normalized, _ = normalize_runtime_profile(bad)
        normalized.setdefault("providers", {})["failover_chain"] = "not-a-list"
        errors = validate_runtime_profile(normalized)
        if not any("failover_chain" in e for e in errors):
            return "expected 'failover_chain' validation error not found"
        return None

    def _chk_registry_cpu_only(self) -> str | None:
        from core.model_registry import ModelRegistry

        reg = ModelRegistry()
        reg.registry_path = Path(self._tmp_dir) / "cpu_only_reg.json"
        reg.profile = {
            "hardware": {
                "cpu_count": 4,
                "ram_gb": 8,
                "gpu": {"available": False, "name": "cpu-only", "vram_gb": 0, "device_count": 0},
            },
            "model_inventory": {"available_models": []},
            "local_runtime": {},
        }
        try:
            payload = reg.refresh()
        except Exception as exc:
            return f"ModelRegistry.refresh() raised on cpu-only: {exc}"
        if not payload.get("recommendations", {}).get("needs_cloud_fallback"):
            return "cpu-only should recommend cloud fallback"
        return None

    # ------------------------------------------------------------------
    # Phase 5 — Beta Readiness
    # ------------------------------------------------------------------

    def _phase5_beta_readiness(self) -> PhaseResult:
        phase = PhaseResult(name="phase5_beta_readiness")
        p = "phase5"

        phase.checks.append(_run_check(p, "kernel_instantiates_cleanly", self._chk_kernel_boot))
        phase.checks.append(_run_check(p, "kernel_boot_report_structure", self._chk_kernel_report))
        phase.checks.append(_run_check(p, "provider_agi_completeness", self._chk_provider_agi))
        phase.checks.append(_run_check(p, "identity_session_lifecycle", self._chk_identity_session))
        phase.checks.append(_run_check(p, "safety_blocks_hack_content", self._chk_safety_hack))
        phase.checks.append(_run_check(p, "session_persistence_and_resume", self._chk_session_resume))
        phase.checks.append(_run_check(p, "full_agi_cognitive_pipeline", self._chk_full_agi_pipeline))
        phase.checks.append(_run_check(p, "openchimera_namespace_re_exports", self._chk_namespace))
        phase.checks.append(_run_check(p, "query_engine_persists_sessions", self._chk_qe_persistence))
        phase.checks.append(_run_check(p, "multi_agent_consensus_with_mock", self._chk_consensus))

        return phase

    def _chk_kernel_boot(self) -> str | None:
        from core.kernel import OpenChimeraKernel
        from unittest.mock import MagicMock, patch

        with patch("core.kernel.OpenChimeraAPIServer", MagicMock()):
            kernel = OpenChimeraKernel()
        required = ["bus", "provider", "personality", "self_model"]
        missing = [a for a in required if not hasattr(kernel, a) or getattr(kernel, a) is None]
        if missing:
            return f"kernel missing attributes: {missing}"
        return None

    def _chk_kernel_report(self) -> str | None:
        from core.kernel import BootStatus, OpenChimeraKernel
        from unittest.mock import MagicMock, patch

        with patch("core.kernel.OpenChimeraAPIServer", MagicMock()):
            kernel = OpenChimeraKernel()
        report = kernel.boot_report()
        if "subsystems" not in report:
            return "boot_report missing 'subsystems'"
        if "status" not in report:
            return "boot_report missing 'status'"
        valid_statuses = [s.value for s in BootStatus]
        if report["status"] not in valid_statuses:
            return f"boot_report status {report['status']!r} not in {valid_statuses}"
        return None

    def _chk_provider_agi(self) -> str | None:
        from core.kernel import OpenChimeraKernel
        from unittest.mock import MagicMock, patch

        with patch("core.kernel.OpenChimeraAPIServer", MagicMock()):
            kernel = OpenChimeraKernel()
        provider = kernel.provider
        if not hasattr(provider, "agi_completeness"):
            return "provider missing agi_completeness method"
        result = provider.agi_completeness()
        if "completeness_pct" not in result and "modules" not in result:
            return f"agi_completeness() result has unexpected shape: {list(result.keys())}"
        return None

    def _chk_identity_session(self) -> str | None:
        from core.identity_manager import IdentityManager

        mgr = IdentityManager()
        user = mgr.create_user("Sandbox User", role="operator")
        if user is None:
            return "create_user returned None"
        session = mgr.create_session(user.user_id, context={"sandbox": True})
        if not session.active:
            return "new session should be active"
        mgr.end_session(session.session_id)
        ended = mgr.get_session(session.session_id)
        if ended.active:
            return "session should be inactive after end_session"
        return None

    def _chk_safety_hack(self) -> str | None:
        from core.safety_layer import SafetyLayer

        sl = SafetyLayer()
        blocked, reason = sl.validate_content("How to hack into a bank and steal money")
        if blocked:
            return "harmful content was not blocked"
        if not reason:
            return "block reason is empty"
        return None

    def _chk_session_resume(self) -> str | None:
        from core.session_memory import SessionMemory

        with tempfile.TemporaryDirectory() as tmp:
            sm = SessionMemory(session_id="resume-check", store_root=Path(tmp))
            sm.append_turn(role="user", content="beta test message")
            sm.save()
            sm2 = SessionMemory.load(session_id="resume-check", store_root=Path(tmp))
            turns = sm2.get_turns()
        if not any(t.get("content") == "beta test message" for t in turns):
            return "persisted message not found after reload"
        return None

    def _chk_full_agi_pipeline(self) -> str | None:
        from core._bus_fallback import EventBus
        from core._database_fallback import DatabaseManager
        from core.causal_reasoning import CausalReasoning
        from core.knowledge_base import KnowledgeBase
        from core.meta_learning import MetaLearning
        from core.memory_system import MemorySystem
        from core.plan_mode import PlanMode, PlanStatus, StepStatus
        from core.safety_layer import SafetyLayer
        from core.self_model import SelfModel
        from core.session_memory import SessionMemory
        from core.transfer_learning import PatternType, TransferLearning

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            db = DatabaseManager(db_path=db_path)
            db.initialize()
            bus = EventBus()

            # Safety gate
            sl = SafetyLayer()
            ok, _ = sl.validate_content("What is OpenChimera?")
            if not ok:
                return "safety layer blocked safe query"

            # Memory record
            mem = MemorySystem(db=db, bus=bus, working_max_size=32)
            mem.record_episode(
                session_id="beta",
                goal="End-to-end pipeline test",
                outcome="success",
                confidence_initial=0.5,
                confidence_final=0.95,
                models_used=["mock"],
                reasoning_chain=["step1"],
                domain="reasoning",
            )

            # Causal reasoning
            cr = CausalReasoning(bus=bus)
            cr.add_cause("quality", "output", strength=0.8, confidence=0.9)
            cr.set_variable("quality", 0.7)
            cr.intervene("quality", 0.9)

            # Transfer learning
            tl = TransferLearning(bus=bus)
            tl.register_pattern(
                source_domain="reasoning",
                pattern_type=PatternType.STRATEGY,
                description="hypothesis test",
                keywords=["hypothesis"],
                success_rate=0.9,
            )

            # Meta learning
            ml = MetaLearning(bus=bus)
            strat = ml.register_strategy("hyp", {}, "reasoning")
            ml.record_outcome(strat.strategy_id, "reasoning", True, 0.9, 30.0)

            # Self model
            sm = SelfModel(bus=bus)
            sm.record_capability("reasoning", "accuracy", 0.9, sample_count=5)

            # Knowledge base
            with tempfile.TemporaryDirectory() as tmp:
                kb = KnowledgeBase(storage_path=Path(tmp) / "pipeline_kb.json")
                kb.add("OpenChimera integrates AGI modules", category="system")
                results = kb.search("OpenChimera")
                if not results:
                    return "knowledge base search returned nothing"

            # Plan execution
            pm = PlanMode()
            plan = pm.create_plan(
                name="AGI Pipeline",
                description="Full pipeline run",
                steps=[{"description": "Run"}, {"description": "Verify"}],
            )
            pm.start_plan(plan.plan_id)
            for step in pm.get_plan(plan.plan_id).steps:
                pm.update_step(plan.plan_id, step.step_id, StepStatus.COMPLETED)
            if pm.get_plan(plan.plan_id).status != PlanStatus.COMPLETED:
                return "plan not completed"

            # Session persistence
            with tempfile.TemporaryDirectory() as tmp:
                session_mem = SessionMemory(session_id="pipeline-beta", store_root=Path(tmp))
                session_mem.append_turn(role="user", content="What is OpenChimera?")
                session_mem.append_turn(role="assistant", content=f"Found {len(results)} entries")
                session_mem.save()
                resumed = SessionMemory.load(session_id="pipeline-beta", store_root=Path(tmp))
                if len(resumed.get_turns()) < 2:
                    return "session not resumed correctly"

        finally:
            db.close()
            for suf in ("", "-wal", "-shm"):
                try:
                    os.unlink(db_path + suf)
                except OSError:
                    pass

        return None

    def _chk_namespace(self) -> str | None:
        # openchimera exposes symbols via sub-modules (openchimera.kernel.Kernel, etc.)
        try:
            from openchimera.kernel import Kernel
            from openchimera.provider import OpenChimeraProvider
            from openchimera.query_engine import QueryEngine
            from openchimera.plan_mode import PlanMode
        except ImportError as exc:
            return f"openchimera sub-module import failed: {exc}"
        # Verify symbols are the same objects as the core.* equivalents
        from core.kernel import Kernel as _CKernel
        from core.provider import OpenChimeraProvider as _CProvider
        if Kernel is not _CKernel:
            return "openchimera.kernel.Kernel is not core.kernel.Kernel"
        if OpenChimeraProvider is not _CProvider:
            return "openchimera.provider.OpenChimeraProvider is not core.provider.OpenChimeraProvider"
        return None

    def _chk_qe_persistence(self) -> str | None:
        with tempfile.TemporaryDirectory() as tmp:
            qe = self._make_query_engine(tmp)
            qe.run_query(query="beta readiness probe", permission_scope="user")
            sessions = qe.list_sessions()
        if not sessions:
            return "no sessions persisted after run_query"
        return None

    def _chk_consensus(self) -> str | None:
        import asyncio

        from core._bus_fallback import EventBus
        from core._database_fallback import DatabaseManager
        from core.agent_pool import AgentPool, AgentRole, AgentSpec
        from core.multi_agent_orchestrator import MultiAgentOrchestrator

        async def _mock_agent(task: str, context: dict[str, Any]) -> str:
            return f"answer:{task}"

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            db = DatabaseManager(db_path=db_path)
            db.initialize()
            pool = AgentPool()
            pool.register(
                AgentSpec(agent_id="sim-agent", role=AgentRole.REASONER, domain="general"),
                external_fn=_mock_agent,
            )
            orch = MultiAgentOrchestrator(pool=pool, bus=EventBus(), db=db, quorum=1)
            result = asyncio.run(orch.run("What is 2+2?", domain="general"))
        finally:
            db.close()
            for suf in ("", "-wal", "-shm"):
                try:
                    os.unlink(db_path + suf)
                except OSError:
                    pass

        if result.answer is None:
            return "consensus returned None answer"
        if result.confidence <= 0.0:
            return f"consensus confidence should be > 0, got {result.confidence}"
        return None
