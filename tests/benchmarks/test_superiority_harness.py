from __future__ import annotations

from scripts.benchmarks.scorecard import evaluate_scorecard


def test_scorecard_thresholds_pass_case():
    axis_results = {
        "capability": [{"ok": True}],
        "reliability": [{"ok": True}],
        "autonomy": [{"ok": True}],
    }
    score = evaluate_scorecard(axis_results)
    assert score["overall_ok"] is True
    assert score["axes"]["capability"]["meets_threshold"] is True


def test_scorecard_thresholds_fail_case():
    axis_results = {
        "capability": [{"ok": True}],
        "reliability": [{"ok": False}],
        "autonomy": [{"ok": True}],
    }
    score = evaluate_scorecard(axis_results)
    assert score["overall_ok"] is False
    assert score["axes"]["reliability"]["meets_threshold"] is False
