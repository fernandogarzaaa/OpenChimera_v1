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
"""
from __future__ import annotations

import pytest

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
