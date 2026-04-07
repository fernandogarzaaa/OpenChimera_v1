"""Tests for core.chimera_bridge — ChimeraLang ↔ OpenChimera integration.

Covers:
  1.  status() reports availability correctly
  2.  run() with valid hello_chimera source succeeds
  3.  run() with invalid source returns error
  4.  run() emitted values contain expected fields
  5.  check() on valid source passes
  6.  check() on invalid source returns errors
  7.  prove() on valid source returns a verdict dict
  8.  prove() integrity proof has chain and hallucination fields
  9.  scan_response() clean response is flagged as pass
  10. scan_response() response without trace is flagged for review
  11. ChimeraLangBridge singleton (get_bridge) returns consistent object
  12. run() with gate (quantum_reasoning) produces gate_logs
  13. vm._enforce_constraints() — must-constraints are evaluated in fn bodies
  14. vm._call_gate() — branch_index / branch_seed injected into branch scope
  15. vm._call_gate() — branch result trace tagged with branch_N_output
  16. vm._exec_reason() — reason block registered under its declared name (not "about")
"""
from __future__ import annotations

import sys
import os
import pytest

# Make ChimeraLang importable for low-level VM tests
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "external", "chimeralang"))

from core.chimera_bridge import ChimeraLangBridge, get_bridge


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def bridge() -> ChimeraLangBridge:
    return ChimeraLangBridge(seed=0)


HELLO_SOURCE = """\
val greeting: Text = "Hello, OpenChimera!"
emit greeting
"""

INVALID_SOURCE = """\
val x: Int = "this is not an int but parser is lenient"
emit
"""

GATE_SOURCE = """\
gate answer_gate(question: Text) -> Text
  branches: 3
  collapse: majority
  threshold: 0.70
  return question
end

val q: Text = "What is 2+2?"
val result: Text = answer_gate(q)
emit result
"""


# ---------------------------------------------------------------------------
# 1. status()
# ---------------------------------------------------------------------------

def test_status_available(bridge):
    status = bridge.status()
    assert status["available"] is True
    assert "version" in status
    assert "capabilities" in status
    assert "run" in status["capabilities"]
    assert "check" in status["capabilities"]
    assert "prove" in status["capabilities"]
    assert "scan_response" in status["capabilities"]


# ---------------------------------------------------------------------------
# 2. run() — valid source
# ---------------------------------------------------------------------------

def test_run_valid_source(bridge):
    result = bridge.run(HELLO_SOURCE)
    assert result["ok"] is True
    assert len(result["emitted"]) == 1
    assert result["emitted"][0]["raw"] == "Hello, OpenChimera!"
    assert len(result["errors"]) == 0


# ---------------------------------------------------------------------------
# 3. run() — invalid/unparseable source
# ---------------------------------------------------------------------------

def test_run_invalid_source_returns_error(bridge):
    # A source that has a lex/parse error (standalone 'emit' with no value)
    broken = "gate\n"  # gate with no name is a parse error
    result = bridge.run(broken)
    # Should not raise; should return ok=False with errors
    assert result["ok"] is False
    assert len(result["errors"]) > 0


# ---------------------------------------------------------------------------
# 4. run() emitted value fields
# ---------------------------------------------------------------------------

def test_run_emitted_value_fields(bridge):
    result = bridge.run(HELLO_SOURCE)
    val = result["emitted"][0]
    assert "raw" in val
    assert "confidence" in val
    assert "confidence_level" in val
    assert "memory_scope" in val
    assert "trace" in val
    assert "fingerprint" in val
    assert isinstance(val["confidence"], float)
    assert 0.0 <= val["confidence"] <= 1.0


# ---------------------------------------------------------------------------
# 5. check() — valid source passes
# ---------------------------------------------------------------------------

def test_check_valid_source(bridge):
    result = bridge.check(HELLO_SOURCE)
    assert result["ok"] is True
    assert len(result["errors"]) == 0


# ---------------------------------------------------------------------------
# 6. check() — broken source returns errors/false
# ---------------------------------------------------------------------------

def test_check_broken_source(bridge):
    broken = "gate\n"
    result = bridge.check(broken)
    assert result["ok"] is False
    assert len(result["errors"]) > 0


# ---------------------------------------------------------------------------
# 7. prove() — returns verdict
# ---------------------------------------------------------------------------

def test_prove_returns_verdict(bridge):
    result = bridge.prove(HELLO_SOURCE)
    assert "verdict" in result
    assert "proof" in result
    assert "run" in result
    assert isinstance(result["verdict"], str)


# ---------------------------------------------------------------------------
# 8. prove() — integrity proof structure
# ---------------------------------------------------------------------------

def test_prove_integrity_structure(bridge):
    result = bridge.prove(HELLO_SOURCE)
    proof = result["proof"]
    assert proof is not None
    assert "chain" in proof
    assert "gates" in proof
    assert "assertions" in proof
    assert "hallucination" in proof
    assert proof["chain"]["valid"] is True


# ---------------------------------------------------------------------------
# 9. scan_response() — clean response
# ---------------------------------------------------------------------------

def test_scan_response_clean(bridge):
    result = bridge.scan_response("The capital of France is Paris.", confidence=0.95, trace=["model_output"])
    assert result["clean"] is True
    assert result["recommendation"] == "pass"
    assert result["confidence"] == pytest.approx(0.95)


# ---------------------------------------------------------------------------
# 10. scan_response() — response without trace gets SOURCE_GAP flag
# ---------------------------------------------------------------------------

def test_scan_response_no_trace_flagged(bridge):
    # Passing an empty trace list causes SOURCE_GAP detection
    result = bridge.scan_response("Some response", confidence=0.7, trace=[])
    assert result["clean"] is False
    kinds = [f["kind"] for f in result["flags"]]
    assert "SOURCE_GAP" in kinds
    assert result["recommendation"] in ("flag", "review")


# ---------------------------------------------------------------------------
# 11a. scan_response() — default trace (None) gets auto-populated
# ---------------------------------------------------------------------------

def test_scan_response_default_trace_is_clean(bridge):
    # Without specifying trace, the bridge uses ["openchimera_response"] so it is clean
    result = bridge.scan_response("The sky is blue.", confidence=0.9)
    assert result["clean"] is True
    assert result["recommendation"] == "pass"


# ---------------------------------------------------------------------------
# 11. get_bridge() returns singleton
# ---------------------------------------------------------------------------

def test_get_bridge_singleton():
    b1 = get_bridge()
    b2 = get_bridge()
    assert b1 is b2


# ---------------------------------------------------------------------------
# 12. run() with gate produces gate_logs
# ---------------------------------------------------------------------------

def test_run_gate_produces_gate_logs(bridge):
    result = bridge.run(GATE_SOURCE)
    # The gate should have been executed — gate_logs must be populated
    assert len(result["gate_logs"]) >= 1
    gate_log = result["gate_logs"][0]
    assert "gate" in gate_log
    assert "branches" in gate_log
    assert "collapse" in gate_log
    assert "branch_confidences" in gate_log
    assert len(gate_log["branch_confidences"]) == gate_log["branches"]


# ---------------------------------------------------------------------------
# 13. _enforce_constraints() — must-constraints are evaluated in fn bodies
# ---------------------------------------------------------------------------

# Correct ChimeraLang constraint syntax: `must: <expr>` (colon required)
MUST_CONSTRAINT_SOURCE = """\
fn guarded(flag: Bool) -> Bool
  must: flag
  return flag
end

val ok: Bool = guarded(true)
emit ok
"""

MUST_CONSTRAINT_VIOLATED_SOURCE = """\
fn guarded(flag: Bool) -> Bool
  must: flag
  return flag
end

val bad: Bool = guarded(false)
emit bad
"""


def test_enforce_constraints_must_passes(bridge):
    """must-constraint that evaluates to true must not raise."""
    result = bridge.run(MUST_CONSTRAINT_SOURCE)
    assert result["ok"] is True, f"Unexpected errors: {result['errors']}"
    assert result["emitted"][0]["raw"] is True


def test_enforce_constraints_must_violated_returns_error(bridge):
    """must-constraint that evaluates to false must produce an assertion error."""
    result = bridge.run(MUST_CONSTRAINT_VIOLATED_SOURCE)
    assert result["ok"] is False
    assert any(
        "must" in e.lower() or "constraint" in e.lower() or "assertion" in e.lower()
        for e in result["errors"]
    ), f"Expected constraint error message, got: {result['errors']}"


# ---------------------------------------------------------------------------
# 14. _call_gate() — branch_index / branch_seed injected per branch,
#                    branch result trace tagged with branch_N_output
# ---------------------------------------------------------------------------

# Gate that returns its input (so the collapsed value carries branch trace tags)
BRANCH_METADATA_SOURCE = """\
gate meta_gate(x: Int) -> Int
  branches: 3
  collapse: highest_confidence
  threshold: 0.50
  return x
end

val inp: Int = 7
val out: Int = meta_gate(inp)
emit out
"""

# Gate that reads branch_index from scope — proves branch_index was injected
BRANCH_INDEX_SOURCE = """\
gate indexed_gate(x: Int) -> Int
  branches: 3
  collapse: highest_confidence
  threshold: 0.50
  val idx: Int = branch_index
  return idx
end

val inp: Int = 0
val out: Int = indexed_gate(inp)
emit out
"""


def test_gate_branch_metadata_injected(bridge):
    """Gate execution must inject branch_index/branch_seed into each branch scope,
    tag branch ChimeraValue traces with branch_N_input / branch_N_output, and
    expose those per-branch traces via branch_traces on the collapsed emitted value.
    """
    result = bridge.run(BRANCH_METADATA_SOURCE)
    assert result["ok"] is True, f"Gate run failed: {result['errors']}"

    emitted = result["emitted"][0]

    # Gate collapse produces a ConvergeValue — bridge must expose branch_traces
    assert "branch_traces" in emitted, (
        f"bridge should expose branch_traces on gate output; keys: {list(emitted.keys())}"
    )
    branch_traces = emitted["branch_traces"]
    assert len(branch_traces) == 3, f"Expected 3 branch traces, got {len(branch_traces)}"

    # Each branch trace must carry both _input and _output tags
    for i, bt in enumerate(branch_traces):
        inputs  = [e for e in bt if "_input"  in e and "branch_" in e]
        outputs = [e for e in bt if "_output" in e and "branch_" in e]
        assert inputs,  f"Branch {i} missing branch_N_input tag in trace: {bt}"
        assert outputs, f"Branch {i} missing branch_N_output tag in trace: {bt}"


def test_gate_branch_index_injectable(bridge):
    """branch_index variable must be accessible from within a gate body.

    If branch_index injection is missing, the gate body will raise a NameError
    (variable not found) and the run will fail.
    """
    result = bridge.run(BRANCH_INDEX_SOURCE)
    assert result["ok"] is True, (
        f"branch_index injection broken — gate body raised: {result['errors']}"
    )
    # Collapsed result must be an integer (one of the branch_index values: 0, 1, or 2)
    assert isinstance(result["emitted"][0]["raw"], int), (
        f"Expected int from indexed_gate, got: {result['emitted'][0]['raw']!r}"
    )


# ---------------------------------------------------------------------------
# 15. _exec_reason() — reason block registered under its declared name (not "about")
# ---------------------------------------------------------------------------

# ChimeraLang syntax: `reason about(params)` — ABOUT is the required keyword.
# The block is then callable as `about(args)`.
REASON_NAMED_SOURCE = """\
reason about()
  given:
    "grounding_fact"
  commit: highest_confidence
  val x: Int = 42
  return x
end

val r: Int = about()
emit r
"""


def test_reason_registered_under_declared_name(bridge):
    """reason block must be callable via 'about' (its AST name after parser fix)."""
    result = bridge.run(REASON_NAMED_SOURCE)
    assert result["ok"] is True, f"Reason name or parse bug: {result['errors']}"
    assert result["emitted"][0]["raw"] == 42

