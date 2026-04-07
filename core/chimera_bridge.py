"""ChimeraLang Bridge — integrates ChimeraLang into the OpenChimera runtime.

ChimeraLang (https://github.com/fernandogarzaaa/ChimeraLang) is a programming
language for AI cognition with probabilistic types, quantum consensus gates,
hallucination detection, and cryptographic integrity proofs.

This module bridges those capabilities into OpenChimera's existing services:

* ``ChimeraLangBridge.run(source)``        — execute a .chimera program
* ``ChimeraLangBridge.check(source)``      — static type-check without running
* ``ChimeraLangBridge.prove(source)``      — run + produce a full integrity report
* ``ChimeraLangBridge.scan_response(...)`` — gate an LLM response through
                                             ChimeraLang's hallucination detector
* ``ChimeraLangBridge.status()``           — version / availability status

The bridge does **not** break existing OpenChimera behaviour; all methods are
opt-in and return structured dicts that can be serialised to JSON directly.
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path
from typing import Any

_LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Ensure the embedded ChimeraLang package is importable.
# ---------------------------------------------------------------------------
_CHIMERA_ROOT = Path(__file__).parent.parent / "external" / "chimeralang"
if str(_CHIMERA_ROOT) not in sys.path:
    sys.path.insert(0, str(_CHIMERA_ROOT))

try:
    from chimera.detect import DetectionReport, HallucinationDetector
    from chimera.integrity import ChainBuilder, IntegrityEngine
    from chimera.lexer import LexError, Lexer
    from chimera.parser import ParseError, Parser
    from chimera.type_checker import TypeChecker
    from chimera.types import ChimeraValue, Confidence, MemoryScope
    from chimera.vm import ChimeraVM

    _AVAILABLE = True
except Exception as _import_err:  # pragma: no cover – environment problem
    _LOGGER.warning("ChimeraLang unavailable: %s", _import_err)
    _AVAILABLE = False


# ---------------------------------------------------------------------------
# Public bridge helpers
# ---------------------------------------------------------------------------

def _lex_and_parse(source: str, filename: str = "<chimera>"):
    """Tokenise *source* and return a parsed Program AST."""
    tokens = Lexer(source, filename).tokenize()
    return Parser(tokens).parse()


def _chimera_value_to_dict(val: "ChimeraValue") -> dict[str, Any]:
    """Serialise a ChimeraLang runtime value to a plain dict."""
    return {
        "raw": val.raw,
        "confidence": val.confidence.value,
        "confidence_level": val.confidence.level.name,
        "memory_scope": val.memory_scope.name,
        "trace": list(val.trace),
        "fingerprint": val.fingerprint,
    }


def _detection_report_to_dict(report: "DetectionReport") -> dict[str, Any]:
    """Serialise a HallucinationDetector report to a plain dict."""
    return {
        "clean": report.clean,
        "values_scanned": report.values_scanned,
        "gates_scanned": report.gates_scanned,
        "flags": [
            {
                "kind": f.kind.name,
                "severity": f.severity,
                "description": f.description,
                "evidence": dict(f.evidence),
            }
            for f in report.flags
        ],
    }


# ---------------------------------------------------------------------------
# ChimeraLangBridge
# ---------------------------------------------------------------------------

class ChimeraLangBridge:
    """Top-level integration point between ChimeraLang and OpenChimera."""

    def __init__(self, seed: int | None = None) -> None:
        self._seed = seed

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        """Return availability and version info."""
        if not _AVAILABLE:
            return {"available": False, "reason": "ChimeraLang package failed to import"}
        try:
            import chimera as _ch  # noqa: PLC0415
            version = getattr(_ch, "__version__", "unknown")
        except Exception:
            version = "unknown"
        return {
            "available": True,
            "version": version,
            "capabilities": ["run", "check", "prove", "scan_response"],
            "source": "external/chimeralang",
        }

    def run(self, source: str, *, filename: str = "<chimera>") -> dict[str, Any]:
        """Execute a ChimeraLang program and return structured results.

        Args:
            source:   Raw ChimeraLang source text.
            filename: Optional name used in error messages.

        Returns:
            A dict with keys: ``ok``, ``emitted``, ``trace``, ``gate_logs``,
            ``assertions_passed``, ``assertions_failed``, ``errors``,
            ``duration_ms``.
        """
        self._require_available()
        try:
            program = _lex_and_parse(source, filename)
        except (LexError, ParseError) as exc:
            return {"ok": False, "errors": [str(exc)], "emitted": [], "trace": [],
                    "gate_logs": [], "assertions_passed": 0, "assertions_failed": 0,
                    "duration_ms": 0.0}

        vm = ChimeraVM(seed=self._seed)
        result = vm.execute(program)
        return {
            "ok": len(result.errors) == 0,
            "emitted": [_chimera_value_to_dict(v) for v in result.emitted],
            "trace": list(result.trace),
            "gate_logs": list(result.gate_logs),
            "assertions_passed": result.assertions_passed,
            "assertions_failed": result.assertions_failed,
            "errors": list(result.errors),
            "duration_ms": result.duration_ms,
        }

    def check(self, source: str, *, filename: str = "<chimera>") -> dict[str, Any]:
        """Type-check a ChimeraLang program without executing it.

        Returns:
            A dict with keys: ``ok``, ``errors``, ``warnings``.
        """
        self._require_available()
        try:
            program = _lex_and_parse(source, filename)
        except (LexError, ParseError) as exc:
            return {"ok": False, "errors": [str(exc)], "warnings": []}

        checker = TypeChecker()
        tc_result = checker.check(program)
        return {
            "ok": tc_result.ok,
            "errors": list(tc_result.errors),
            "warnings": list(tc_result.warnings),
        }

    def prove(self, source: str, *, filename: str = "<chimera>") -> dict[str, Any]:
        """Execute a ChimeraLang program and produce a full integrity report.

        The report includes:
        * Merkle-chain reasoning proof
        * Gate consensus certificates
        * Hallucination scan results
        * Cryptographic verdict

        Returns:
            A dict containing ``run`` (same as :meth:`run`) and ``proof``
            (the serialised :class:`chimera.integrity.IntegrityReport`).
        """
        self._require_available()
        try:
            program = _lex_and_parse(source, filename)
        except (LexError, ParseError) as exc:
            return {
                "ok": False,
                "errors": [str(exc)],
                "run": None,
                "proof": None,
            }

        vm = ChimeraVM(seed=self._seed)
        exec_result = vm.execute(program)

        detector = HallucinationDetector()
        detection = detector.full_scan(exec_result.gate_logs, exec_result.emitted)

        engine = IntegrityEngine()
        report = engine.certify(exec_result, detection, source)

        run_summary = {
            "ok": len(exec_result.errors) == 0,
            "emitted": [_chimera_value_to_dict(v) for v in exec_result.emitted],
            "assertions_passed": exec_result.assertions_passed,
            "assertions_failed": exec_result.assertions_failed,
            "errors": list(exec_result.errors),
            "duration_ms": exec_result.duration_ms,
        }

        return {
            "ok": report.verdict.startswith("PASS"),
            "verdict": report.verdict,
            "run": run_summary,
            "proof": report.to_dict(),
            "hallucination": _detection_report_to_dict(detection),
        }

    def scan_response(
        self,
        response_text: str,
        confidence: float = 0.8,
        trace: list[str] | None = None,
    ) -> dict[str, Any]:
        """Gate an OpenChimera LLM response through ChimeraLang's hallucination detector.

        This wraps the plain-text *response_text* in a ChimeraValue and runs it
        through :class:`chimera.detect.HallucinationDetector`.  The response is
        not executed as ChimeraLang source — it is scanned as a runtime value.

        Args:
            response_text: Raw string response from the model.
            confidence:    Confidence score to attach (0.0–1.0).  Default 0.8.
            trace:         Optional provenance trace entries.

        Returns:
            A dict with keys: ``clean``, ``confidence``, ``flags``,
            ``recommendation``.
        """
        self._require_available()
        value = ChimeraValue(
            raw=response_text,
            confidence=Confidence(value=max(0.0, min(1.0, confidence)), source="openchimera"),
            memory_scope=MemoryScope.EPHEMERAL,
            trace=trace if trace is not None else ["openchimera_response"],
        )
        detector = HallucinationDetector()
        report = DetectionReport()
        detector.scan_value(value, report)

        recommendation = (
            "pass" if report.clean
            else "flag" if any(f.severity >= 0.8 for f in report.flags)
            else "review"
        )

        return {
            "clean": report.clean,
            "confidence": confidence,
            "flags": [
                {
                    "kind": f.kind.name,
                    "severity": f.severity,
                    "description": f.description,
                }
                for f in report.flags
            ],
            "recommendation": recommendation,
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _require_available(self) -> None:
        if not _AVAILABLE:
            raise RuntimeError(
                "ChimeraLang is not available. "
                "Ensure external/chimeralang/chimera/ exists and is importable."
            )


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_bridge: ChimeraLangBridge | None = None


def get_bridge() -> ChimeraLangBridge:
    """Return the module-level ChimeraLangBridge singleton."""
    global _bridge
    if _bridge is None:
        _bridge = ChimeraLangBridge()
    return _bridge
