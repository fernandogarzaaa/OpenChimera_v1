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
        input_tags  = [e for e in bt if "_input"  in e and "branch_" in e]
        output_tags = [e for e in bt if "_output" in e and "branch_" in e]
        assert input_tags,  f"Branch {i} missing branch_N_input tag in trace: {bt}"
        assert output_tags, f"Branch {i} missing branch_N_output tag in trace: {bt}"


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


# ---------------------------------------------------------------------------
# 16. for loop — iteration over a list
# ---------------------------------------------------------------------------

FOR_LOOP_SOURCE = """\
val items: List<Int> = [10, 20, 30]
for n in items
  emit n
end
"""


def test_for_loop_emits_each_element(bridge):
    """for loop must iterate over list elements and emit each one."""
    result = bridge.run(FOR_LOOP_SOURCE)
    assert result["ok"] is True, f"for-loop run failed: {result['errors']}"
    assert len(result["emitted"]) == 3
    raws = [e["raw"] for e in result["emitted"]]
    assert raws == [10, 20, 30]


FOR_LOOP_MULTI_SOURCE = """\
val labels: List<Text> = ["a", "b", "c"]
for item in labels
  emit item
end
"""


def test_for_loop_runs_without_error(bridge):
    """for loop over a valid non-empty list must not produce errors."""
    result = bridge.run(FOR_LOOP_MULTI_SOURCE)
    assert result["ok"] is True, f"for-loop failed: {result['errors']}"
    assert len(result["emitted"]) == 3


FOR_LOOP_NON_LIST_SOURCE = """\
val not_a_list: Int = 42
for x in not_a_list
  emit x
end
emit not_a_list
"""


def test_for_loop_non_list_is_skipped(bridge):
    """for loop over a non-list value must be silently skipped (trace warning)."""
    result = bridge.run(FOR_LOOP_NON_LIST_SOURCE)
    assert result["ok"] is True, f"Expected graceful skip: {result['errors']}"
    # Only the final 'emit not_a_list' should fire since the loop is skipped
    assert len(result["emitted"]) == 1
    assert result["emitted"][0]["raw"] == 42
    warning_found = any("not a list" in t.lower() or "skipping" in t.lower() for t in result["trace"])
    assert warning_found, f"Expected skip warning in trace: {result['trace']}"


# ---------------------------------------------------------------------------
# 17. match expression — pattern dispatch
# ---------------------------------------------------------------------------

MATCH_SOURCE = """\
val x: Int = 2
val label: Text = match x
  1 => return "one"
  2 => return "two"
  _ => return "other"
end
emit label
"""


def test_match_dispatches_to_correct_arm(bridge):
    """match expression must evaluate to the body of the first matching arm."""
    result = bridge.run(MATCH_SOURCE)
    assert result["ok"] is True, f"match run failed: {result['errors']}"
    assert len(result["emitted"]) == 1
    assert result["emitted"][0]["raw"] == "two"


MATCH_WILDCARD_SOURCE = """\
val x: Int = 99
val label: Text = match x
  1 => return "one"
  _ => return "wildcard"
end
emit label
"""


def test_match_wildcard_arm_catches_unmatched(bridge):
    """wildcard arm (_) must match when no other arm matches."""
    result = bridge.run(MATCH_WILDCARD_SOURCE)
    assert result["ok"] is True, f"match wildcard failed: {result['errors']}"
    assert result["emitted"][0]["raw"] == "wildcard"


MATCH_NO_MATCH_SOURCE = """\
val x: Int = 5
val r: Int = match x
  1 => return "one"
  2 => return "two"
end
emit r
"""


def test_match_no_matching_arm_returns_none(bridge):
    """match with no matching arm and no wildcard must return None gracefully."""
    result = bridge.run(MATCH_NO_MATCH_SOURCE)
    assert result["ok"] is True, f"match no-match failed: {result['errors']}"
    assert result["emitted"][0]["raw"] is None


# ---------------------------------------------------------------------------
# 18. map literal — {key: value, ...}
# ---------------------------------------------------------------------------

MAP_LITERAL_SOURCE = """\
val m: Map<Text, Int> = {"alpha": 1, "beta": 2}
emit m
"""


def test_map_literal_emits_dict(bridge):
    """map literal {k: v, ...} must produce a dict as the emitted raw value."""
    result = bridge.run(MAP_LITERAL_SOURCE)
    assert result["ok"] is True, f"map literal failed: {result['errors']}"
    assert len(result["emitted"]) == 1
    raw = result["emitted"][0]["raw"]
    assert isinstance(raw, dict), f"Expected dict, got: {type(raw).__name__}"
    assert raw == {"alpha": 1, "beta": 2}


MAP_LITERAL_EMPTY_SOURCE = """\
val m: Map<Text, Int> = {}
emit m
"""


def test_map_literal_empty(bridge):
    """empty map literal {} must produce an empty dict."""
    result = bridge.run(MAP_LITERAL_EMPTY_SOURCE)
    assert result["ok"] is True, f"empty map failed: {result['errors']}"
    assert result["emitted"][0]["raw"] == {}


# ---------------------------------------------------------------------------
# 19. assert with message
# ---------------------------------------------------------------------------

ASSERT_MESSAGE_SOURCE = """\
val ok: Bool = true
assert ok, "value must be true"
emit ok
"""

ASSERT_MESSAGE_FAIL_SOURCE = """\
val bad: Bool = false
assert bad, "custom failure message"
emit bad
"""


def test_assert_with_message_passes(bridge):
    """assert with a message string must pass when condition is true."""
    result = bridge.run(ASSERT_MESSAGE_SOURCE)
    assert result["ok"] is True, f"assert with message failed: {result['errors']}"
    assert result["assertions_passed"] == 1


def test_assert_with_message_surfaces_message_on_failure(bridge):
    """assert with a message string must surface the custom message in errors."""
    result = bridge.run(ASSERT_MESSAGE_FAIL_SOURCE)
    assert result["ok"] is False
    assert any("custom failure message" in e for e in result["errors"]), (
        f"Custom message not found in errors: {result['errors']}"
    )


# ---------------------------------------------------------------------------
# 20. gate fallback — ProvisionalValue when below threshold
# ---------------------------------------------------------------------------

# Gate with a threshold of 1.0 (impossible to meet with noisy branches) to
# reliably trigger the fallback path.
FALLBACK_GATE_SOURCE = """\
gate strict_gate(x: Int) -> Int
  branches: 3
  collapse: majority
  threshold: 1.0
  fallback: escalate
  return x
end

val r: Int = strict_gate(5)
emit r
"""


def test_gate_fallback_returns_provisional_when_below_threshold(bridge):
    """When gate consensus is below threshold, the result must be a ProvisionalValue
    (memory_scope == PROVISIONAL) and its trace must contain the fallback label."""
    result = bridge.run(FALLBACK_GATE_SOURCE)
    assert result["ok"] is True, f"gate fallback failed: {result['errors']}"
    assert len(result["emitted"]) == 1
    emitted = result["emitted"][0]
    assert emitted["memory_scope"] == "PROVISIONAL", (
        f"Expected PROVISIONAL scope on below-threshold gate result, got: {emitted['memory_scope']}"
    )
    assert any("fallback" in t for t in emitted["trace"]), (
        f"Expected 'fallback:...' entry in trace, got: {emitted['trace']}"
    )


def test_gate_logs_include_threshold_met_flag(bridge):
    """Gate logs must include threshold_met boolean to indicate whether consensus passed."""
    result = bridge.run(FALLBACK_GATE_SOURCE)
    assert result["ok"] is True
    assert len(result["gate_logs"]) >= 1
    log = result["gate_logs"][0]
    assert "threshold_met" in log, f"threshold_met missing from gate_log: {log}"
    assert log["threshold_met"] is False  # threshold=1.0 is impossible to meet


# ---------------------------------------------------------------------------
# 21. version bump — ChimeraLang 0.2.0
# ---------------------------------------------------------------------------

def test_chimera_version_is_0_2_0(bridge):
    """ChimeraLang version must be 0.2.0 after the upgrade."""
    status = bridge.status()
    assert status["version"] == "0.2.0", (
        f"Expected ChimeraLang v0.2.0, got: {status['version']!r}"
    )


def test_status_capabilities_include_new_features(bridge):
    """status() capabilities must include the new v0.2.0 language features."""
    status = bridge.status()
    caps = status["capabilities"]
    assert "for_loops" in caps, f"for_loops missing from capabilities: {caps}"
    assert "match_expressions" in caps, f"match_expressions missing: {caps}"
    assert "map_literals" in caps, f"map_literals missing: {caps}"

