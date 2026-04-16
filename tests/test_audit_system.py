"""tests/test_audit_system.py — offline unit tests for the 5-agent audit pipeline.

All tests run without network access, live LLM, uvx, or chimeralang-mcp.
ChimeraClient methods are mocked with AsyncMock throughout.
"""
from __future__ import annotations

import asyncio
import sys
import textwrap
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Skip entire module if pydantic is not installed (dependency not yet in env)
pydantic = pytest.importorskip("pydantic", reason="pydantic not installed")

# Ensure workspace root is on sys.path
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from swarms.audit_system.models import (
    AuditFinding,
    AuditReport,
    ExecutionLog,
    ExecutionRecord,
    OrchestrationReport,
    Recommendation,
    RecommendationSet,
    StageResult,
    TestReport,
    TestResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _finding(
    finding_id: str = "A1-00001",
    file_path: str = "core/foo.py",
    severity: str = "high",
    category: str = "security",
    message: str = "test finding",
    rule_id: str = "PY-SEC-001",
    line: int | None = 10,
) -> AuditFinding:
    return AuditFinding(
        finding_id=finding_id,
        file_path=file_path,
        line=line,
        severity=severity,
        category=category,
        message=message,
        rule_id=rule_id,
    )


def _mock_chimera() -> MagicMock:
    """Return a ChimeraClient mock with safe defaults for all async methods."""
    m = MagicMock()
    m.detect = AsyncMock(return_value={"hallucination_detected": False, "score": 0.0, "strategies_fired": []})
    m.confident = AsyncMock(return_value={"passed": True, "confidence": 0.95})
    m.audit = AsyncMock(return_value={"trust_score": 0.98, "anomalies": []})
    m.prove = AsyncMock(return_value={"proof": "abc123", "valid": True})
    m.gate = AsyncMock(return_value={"passed": True, "confidence": 0.99})
    m.explore = AsyncMock(return_value={"consensus": None, "agreement_score": 1.0, "paths": []})
    m.constrain = AsyncMock(return_value={"satisfied": True, "violations": []})
    m.is_available = MagicMock(return_value=False)
    return m


# ===========================================================================
# TestAuditModels
# ===========================================================================

class TestAuditModels:
    def test_audit_finding_creation(self):
        f = _finding()
        assert f.finding_id == "A1-00001"
        assert f.severity == "high"
        assert f.category == "security"

    def test_audit_report_findings_by_severity(self):
        report = AuditReport(
            run_id="r1", timestamp="2026-01-01T00:00:00Z", workspace="/tmp",
            total_files_scanned=5,
            findings=[
                _finding("f1", severity="critical"),
                _finding("f2", severity="high"),
                _finding("f3", severity="high"),
                _finding("f4", severity="low"),
            ],
        )
        by_sev = report.findings_by_severity()
        assert len(by_sev["critical"]) == 1
        assert len(by_sev["high"]) == 2
        assert len(by_sev["low"]) == 1
        assert len(by_sev["medium"]) == 0

    def test_audit_report_summary_stats(self):
        report = AuditReport(
            run_id="r1", timestamp="2026-01-01T00:00:00Z", workspace="/tmp",
            total_files_scanned=10,
            findings=[_finding("f1", severity="critical"), _finding("f2", severity="info")],
        )
        stats = report.summary_stats()
        assert stats["total"] == 2
        assert stats["files_scanned"] == 10
        assert stats["by_severity"]["critical"] == 1
        assert stats["by_severity"]["info"] == 1

    def test_recommendation_set_by_priority(self):
        rec_set = RecommendationSet(
            run_id="r1",
            recommendations=[
                Recommendation(rec_id="a", priority=3, title="C", description="c",
                                action="fix", confidence=0.9, affected_files=[]),
                Recommendation(rec_id="b", priority=1, title="A", description="a",
                                action="fix", confidence=0.9, affected_files=[]),
                Recommendation(rec_id="c", priority=2, title="B", description="b",
                                action="fix", confidence=0.9, affected_files=[]),
            ],
        )
        ordered = rec_set.by_priority()
        assert [r.priority for r in ordered] == [1, 2, 3]

    def test_execution_log_filters(self):
        log = ExecutionLog(
            run_id="r1",
            records=[
                ExecutionRecord(recommendation_id="a", status="applied", files_changed=["x.py"], diff_summary=""),
                ExecutionRecord(recommendation_id="b", status="skipped", files_changed=[], diff_summary=""),
                ExecutionRecord(recommendation_id="c", status="failed", files_changed=[], diff_summary=""),
            ],
        )
        assert len(log.applied()) == 1
        assert len(log.skipped()) == 1
        assert len(log.failed()) == 1

    def test_execution_log_all_changed_files_deduplication(self):
        log = ExecutionLog(
            run_id="r1",
            records=[
                ExecutionRecord(recommendation_id="a", status="applied",
                                files_changed=["core/foo.py", "core/bar.py"], diff_summary=""),
                ExecutionRecord(recommendation_id="b", status="applied",
                                files_changed=["core/foo.py", "core/baz.py"], diff_summary=""),
            ],
        )
        files = log.all_changed_files()
        assert len(files) == 3  # deduped
        assert "core/foo.py" in files

    def test_stage_result_defaults(self):
        sr = StageResult(stage="audit", status="passed")
        assert sr.trust_score == 1.0
        assert sr.retry_count == 0


# ===========================================================================
# TestChimeraClientFallback
# ===========================================================================

class TestChimeraClientFallback:
    """Tests the fallback path when uvx is unavailable."""

    def setup_method(self):
        from swarms.audit_system.chimera_client import ChimeraClient
        self.client = ChimeraClient()
        # Force unavailable
        self.client._available = False

    def test_is_available_false_when_local_script_missing(self):
        with patch("pathlib.Path.exists", return_value=False):
            from swarms.audit_system.chimera_client import ChimeraClient
            c = ChimeraClient()
            assert c.is_available() is False

    def test_detect_returns_fallback(self):
        result = asyncio.run(self.client.detect("hello world"))
        assert "hallucination_detected" in result
        assert result["hallucination_detected"] is False
        assert result.get("fallback") is True

    def test_confident_returns_fallback_passed(self):
        result = asyncio.run(self.client.confident(0.9))
        assert result.get("passed") is True
        assert result.get("fallback") is True

    def test_audit_returns_trust_score_one(self):
        result = asyncio.run(self.client.audit("test_stage", {}))
        assert result.get("trust_score") == 1.0
        assert result.get("fallback") is True

    def test_prove_returns_local_sha256(self):
        import hashlib
        content = "test content for proof"
        result = asyncio.run(self.client.prove(content))
        expected_proof = hashlib.sha256(content.encode()).hexdigest()
        assert result["proof"] == expected_proof
        assert result["valid"] is True

    def test_gate_respects_condition(self):
        result_true = asyncio.run(self.client.gate(True, 0.9))
        result_false = asyncio.run(self.client.gate(False, 0.1))
        assert result_true.get("passed") is True
        assert result_false.get("passed") is False


# ===========================================================================
# TestAuditAgent
# ===========================================================================

class TestAuditAgent:
    def test_scan_python_security_finds_hardcoded_password(self, tmp_path):
        from swarms.audit_system.agent1_auditor import _scan_python_security
        py_file = tmp_path / "secrets.py"
        py_file.write_text('password = "supersecret"\n')
        findings = _scan_python_security([py_file])
        rule_ids = [f.rule_id for f in findings]
        assert "PY-SEC-004" in rule_ids

    def test_scan_python_security_finds_eval(self, tmp_path):
        from swarms.audit_system.agent1_auditor import _scan_python_security
        py_file = tmp_path / "eval_test.py"
        py_file.write_text("result = eval(user_input)\n")
        findings = _scan_python_security([py_file])
        rule_ids = [f.rule_id for f in findings]
        assert "PY-SEC-001" in rule_ids

    def test_scan_python_security_finds_shell_true(self, tmp_path):
        from swarms.audit_system.agent1_auditor import _scan_python_security
        py_file = tmp_path / "shell_test.py"
        py_file.write_text('subprocess.run(cmd, shell=True)\n')
        findings = _scan_python_security([py_file])
        rule_ids = [f.rule_id for f in findings]
        assert "PY-SEC-003" in rule_ids

    def test_scan_python_quality_finds_bare_except(self, tmp_path):
        from swarms.audit_system.agent1_auditor import _scan_python_quality
        py_file = tmp_path / "bare.py"
        py_file.write_text(textwrap.dedent("""\
            def foo():
                try:
                    pass
                except:
                    pass
        """))
        findings = _scan_python_quality([py_file])
        rule_ids = [f.rule_id for f in findings]
        assert "PY-QUAL-001" in rule_ids

    def test_scan_python_quality_finds_mutable_default(self, tmp_path):
        from swarms.audit_system.agent1_auditor import _scan_python_quality
        py_file = tmp_path / "mutable.py"
        py_file.write_text("def foo(items=[]):\n    pass\n")
        findings = _scan_python_quality([py_file])
        rule_ids = [f.rule_id for f in findings]
        assert "PY-QUAL-002" in rule_ids

    def test_scan_test_coverage_gaps(self, tmp_path):
        from swarms.audit_system.agent1_auditor import _scan_test_coverage_gaps
        core_dir = tmp_path / "core"
        core_dir.mkdir()
        (core_dir / "untested_module.py").write_text("def foo(): pass\n")
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        # No test_untested_module.py created
        findings = _scan_test_coverage_gaps(tmp_path, [])
        messages = [f.message for f in findings]
        assert any("untested_module" in m for m in messages)

    def test_scan_rust_finds_unwrap(self, tmp_path):
        from swarms.audit_system.agent1_auditor import _scan_rust
        rs_file = tmp_path / "lib.rs"
        rs_file.write_text('let val = some_option.unwrap();\n')
        findings = _scan_rust([rs_file])
        rule_ids = [f.rule_id for f in findings]
        assert "RS-QUAL-001" in rule_ids

    def test_audit_agent_run_produces_report(self, tmp_path):
        from swarms.audit_system.agent1_auditor import AuditAgent
        # Create a minimal workspace
        core_dir = tmp_path / "core"
        core_dir.mkdir()
        (core_dir / "module_a.py").write_text('password = "hardcoded"\n')
        agent = AuditAgent(workspace=tmp_path)
        report = agent.run("test-run-001")
        assert report.run_id == "test-run-001"
        assert report.total_files_scanned >= 1
        assert len(report.findings) >= 1
        assert any(f.rule_id == "PY-SEC-004" for f in report.findings)


# ===========================================================================
# TestRecommenderAgent
# ===========================================================================

class TestRecommenderAgent:
    def test_cluster_key_groups_by_category_and_dir(self):
        from swarms.audit_system.agent2_recommender import _cluster_key
        f1 = _finding(file_path="core/foo.py", category="security")
        f2 = _finding(file_path="core/bar.py", category="security")
        f3 = _finding(file_path="swarms/baz.py", category="security")
        assert _cluster_key(f1) == _cluster_key(f2)
        assert _cluster_key(f1) != _cluster_key(f3)

    def test_score_cluster_critical_higher_than_low(self):
        from swarms.audit_system.agent2_recommender import _score_cluster
        critical = [_finding(severity="critical") for _ in range(3)]
        low = [_finding(severity="low") for _ in range(3)]
        assert _score_cluster(critical) > _score_cluster(low)

    def test_action_for_category_mapping(self):
        from swarms.audit_system.agent2_recommender import _action_for_category
        assert _action_for_category("security") == "fix"
        assert _action_for_category("quality") == "refactor"
        assert _action_for_category("dependency") == "update_dep"
        assert _action_for_category("dead_code") == "delete"
        assert _action_for_category("test_gap") == "add_test"

    def test_recommender_empty_report_returns_empty_set(self):
        from swarms.audit_system.agent2_recommender import RecommenderAgent
        agent = RecommenderAgent(chimera=_mock_chimera())
        report = AuditReport(
            run_id="r1", timestamp="2026-01-01T00:00:00Z",
            workspace="/tmp", total_files_scanned=0,
        )
        result = agent.run("r1", report)
        assert result.run_id == "r1"
        assert isinstance(result.recommendations, list)

    def test_recommender_produces_sorted_recommendations(self):
        from swarms.audit_system.agent2_recommender import RecommenderAgent
        chimera = _mock_chimera()
        agent = RecommenderAgent(chimera=chimera)
        report = AuditReport(
            run_id="r2", timestamp="2026-01-01T00:00:00Z",
            workspace="/tmp", total_files_scanned=3,
            findings=[
                _finding("f1", category="security", severity="critical", file_path="core/a.py"),
                _finding("f2", category="test_gap", severity="low", file_path="core/b.py"),
            ],
        )
        result = agent.run("r2", report)
        if len(result.recommendations) >= 2:
            priorities = [r.priority for r in result.recommendations]
            assert priorities == sorted(priorities)


# ===========================================================================
# TestExecutorAgent
# ===========================================================================

class TestExecutorAgent:
    def test_dry_run_does_not_write_files(self, tmp_path):
        from swarms.audit_system.agent3_executor import ExecutorAgent
        py_file = tmp_path / "secrets.py"
        py_file.write_text('password = "topsecret"\n')
        chimera = _mock_chimera()
        agent = ExecutorAgent(workspace=tmp_path, chimera=chimera, dry_run=True)
        rec = Recommendation(
            rec_id="r1", priority=1, title="Fix secret",
            description="hardcoded password", action="fix",
            confidence=0.95, affected_files=[str(py_file)],
        )
        rec_set = RecommendationSet(run_id="t1", recommendations=[rec], chimera_validated=True)
        log = agent.run("t1", rec_set)
        assert len(log.records) == 1
        assert log.records[0].status == "skipped"
        # File must be unchanged
        assert py_file.read_text() == 'password = "topsecret"\n'

    def test_apply_security_fix_replaces_credential(self, tmp_path):
        from swarms.audit_system.agent3_executor import ExecutorAgent
        py_file = tmp_path / "secrets.py"
        py_file.write_text('password = "topsecret"\n')
        chimera = _mock_chimera()
        agent = ExecutorAgent(workspace=tmp_path, chimera=chimera, dry_run=False)
        rec = Recommendation(
            rec_id="r1", priority=1, title="Fix secret",
            description="hardcoded password", action="fix",
            confidence=0.95, affected_files=[str(py_file)],
        )
        rec_set = RecommendationSet(run_id="t1", recommendations=[rec], chimera_validated=True)
        agent.run("t1", rec_set)
        content = py_file.read_text()
        assert "os.getenv" in content
        assert '"topsecret"' not in content

    def test_generate_test_stub_creates_file(self, tmp_path):
        from swarms.audit_system.agent3_executor import ExecutorAgent
        core_dir = tmp_path / "core"
        core_dir.mkdir()
        module_file = core_dir / "mymodule.py"
        module_file.write_text("def foo(): pass\n")
        chimera = _mock_chimera()
        agent = ExecutorAgent(workspace=tmp_path, chimera=chimera, dry_run=False)
        rec = Recommendation(
            rec_id="r1", priority=1, title="Add test",
            description="missing test", action="add_test",
            confidence=0.95, affected_files=[str(module_file)],
        )
        rec_set = RecommendationSet(run_id="t1", recommendations=[rec], chimera_validated=True)
        agent.run("t1", rec_set)
        stub = tmp_path / "tests" / "test_mymodule_stub.py"
        assert stub.exists()
        content = stub.read_text()
        assert "def test_mymodule_imports" in content

    def test_protected_file_skipped(self, tmp_path):
        from swarms.audit_system.agent3_executor import ExecutorAgent
        chimera = _mock_chimera()
        agent = ExecutorAgent(workspace=tmp_path, chimera=chimera, dry_run=False)
        rec = Recommendation(
            rec_id="r1", priority=1, title="Edit config",
            description="edit runtime", action="fix",
            confidence=0.95,
            affected_files=[str(tmp_path / "config" / "runtime_profile.json")],
        )
        rec_set = RecommendationSet(run_id="t1", recommendations=[rec], chimera_validated=True)
        log = agent.run("t1", rec_set)
        assert log.records[0].status == "skipped"


# ===========================================================================
# TestTesterAgent
# ===========================================================================

class TestTesterAgent:
    def test_parse_pytest_stdout_three_passed_one_failed(self):
        from swarms.audit_system.agent4_tester import _parse_pytest_stdout
        output = "3 passed, 1 failed in 2.34s"
        result = _parse_pytest_stdout(output, "suite_a")
        assert result.passed == 3
        assert result.failed == 1
        assert result.gate_passed is False

    def test_parse_pytest_stdout_all_passed(self):
        from swarms.audit_system.agent4_tester import _parse_pytest_stdout
        output = "10 passed in 1.23s"
        result = _parse_pytest_stdout(output, "suite_b")
        assert result.passed == 10
        assert result.failed == 0
        assert result.gate_passed is True

    def test_detect_regressions_empty_when_all_pass(self):
        from swarms.audit_system.agent4_tester import TesterAgent
        agent = TesterAgent(chimera=_mock_chimera())
        results = [TestResult(suite="s1", passed=5, failed=0, gate_passed=True)]
        regressions = agent._detect_regressions(results)
        assert regressions == []

    def test_detect_regressions_includes_failing_suite(self):
        from swarms.audit_system.agent4_tester import TesterAgent
        agent = TesterAgent(chimera=_mock_chimera())
        results = [
            TestResult(suite="s1", passed=2, failed=1, gate_passed=False,
                       errors=["FAILED tests/test_foo.py::test_bar"]),
        ]
        regressions = agent._detect_regressions(results)
        assert len(regressions) == 1
        assert "s1" in regressions[0]

    def test_smoke_test_skips_when_no_run_py(self, tmp_path):
        from swarms.audit_system.agent4_tester import TesterAgent
        agent = TesterAgent(workspace=tmp_path, chimera=_mock_chimera())
        results, notes = agent._smoke_test_entry_points()
        assert any("not found" in n.lower() for n in notes)


# ===========================================================================
# TestOrchestratorStateMachine
# ===========================================================================

class TestOrchestratorStateMachine:
    def _make_orchestrator(self, tmp_path):
        from swarms.audit_system.agent5_orchestrator import OrchestratorAgent
        agent = OrchestratorAgent(
            workspace=tmp_path,
            chimera=_mock_chimera(),
            dry_run=True,
            skip_execute=True,
            skip_tests=True,
        )
        return agent

    def test_run_produces_orchestration_report(self, tmp_path):
        """Full pipeline completes and returns OrchestrationReport."""
        orchestrator = self._make_orchestrator(tmp_path)
        # Create minimal workspace so AuditAgent doesn't crash
        (tmp_path / "core").mkdir()
        (tmp_path / "tests").mkdir()
        report = asyncio.run(orchestrator.run("test-run-orch"))
        assert report.run_id == "test-run-orch"
        assert report.overall_verdict in ("success", "partial", "failed", "aborted")

    def test_artifacts_directory_created(self, tmp_path):
        orchestrator = self._make_orchestrator(tmp_path)
        (tmp_path / "core").mkdir()
        asyncio.run(orchestrator.run("test-run-artifacts"))
        run_dir = tmp_path / "artifacts" / "audit_runs" / "test-run-artifacts"
        assert run_dir.exists()
        assert (run_dir / "audit_report.json").exists()

    def test_hallucination_detected_triggers_redirect(self, tmp_path):
        """When chimera_detect reports a hallucination, retry counter increments."""
        from swarms.audit_system.agent5_orchestrator import OrchestratorAgent, StageAbortedError
        chimera = _mock_chimera()
        # Always report hallucination so all retries exhausted
        chimera.detect = AsyncMock(return_value={
            "hallucination_detected": True, "score": 0.9,
            "strategies_fired": ["semantic"],
        })
        orchestrator = OrchestratorAgent(
            workspace=tmp_path,
            chimera=chimera,
            dry_run=True,
            skip_execute=True,
            skip_tests=True,
        )
        (tmp_path / "core").mkdir()
        report = asyncio.run(orchestrator.run("test-hallucination"))
        # Should be aborted after retries exhausted
        assert report.overall_verdict == "aborted"
        assert len(orchestrator._hallucination_events) > 0

    def test_trust_chain_grows_across_stages(self, tmp_path):
        orchestrator = self._make_orchestrator(tmp_path)
        (tmp_path / "core").mkdir()
        asyncio.run(orchestrator.run("test-trust-chain"))
        # Should have at least one entry in trust chain (audit stage)
        assert len(orchestrator._trust_chain) >= 1

    def test_skip_execute_skips_executor_stage(self, tmp_path):
        from swarms.audit_system.agent5_orchestrator import OrchestratorAgent
        orchestrator = OrchestratorAgent(
            workspace=tmp_path,
            chimera=_mock_chimera(),
            dry_run=True,
            skip_execute=True,
            skip_tests=True,
        )
        (tmp_path / "core").mkdir()
        report = asyncio.run(orchestrator.run("test-skip-exec"))
        stage_names = [s.stage for s in report.stages]
        assert "execute" not in stage_names

    def test_overall_verdict_success_when_all_pass(self, tmp_path):
        orchestrator = self._make_orchestrator(tmp_path)
        (tmp_path / "core").mkdir()
        report = asyncio.run(orchestrator.run("test-success"))
        # With mocked chimera (all pass) and skip_execute + skip_tests, should succeed
        assert report.overall_verdict in ("success", "partial")
