"""ChimeraLang CLI — parse, check, and run .chimera programs.

Usage:
  chimera run    <file>   Execute a .chimera program
  chimera check  <file>   Type-check without executing
  chimera lex    <file>   Dump token stream
  chimera parse  <file>   Dump AST
  chimera prove  <file>   Run + generate integrity report
"""

from __future__ import annotations

import io
import json
import sys
import time
from pathlib import Path

# Ensure stdout can handle Unicode box-drawing characters on Windows
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from chimera.detect import HallucinationDetector
from chimera.integrity import IntegrityEngine
from chimera.lexer import Lexer, LexError
from chimera.parser import ParseError, Parser
from chimera.type_checker import TypeChecker
from chimera.vm import ChimeraVM


def _read_source(path_str: str) -> str:
    p = Path(path_str)
    if not p.exists():
        print(f"chimera: error: file not found: {p}", file=sys.stderr)
        sys.exit(1)
    if p.suffix != ".chimera":
        print(f"chimera: warning: expected .chimera extension, got '{p.suffix}'", file=sys.stderr)
    return p.read_text(encoding="utf-8")


def _lex(source: str, filename: str = "<stdin>"):
    lexer = Lexer(source, filename)
    return lexer.tokenize()


def _parse(source: str, filename: str = "<stdin>"):
    tokens = _lex(source, filename)
    parser = Parser(tokens)
    return parser.parse()


def cmd_lex(path: str) -> None:
    """Dump the token stream."""
    source = _read_source(path)
    try:
        tokens = _lex(source, path)
        for tok in tokens:
            print(f"{tok.span.line:4d}:{tok.span.col:<3d}  {tok.kind.name:<24s} {tok.value!r}")
    except LexError as e:
        print(f"chimera: lex error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_parse(path: str) -> None:
    """Dump the AST as indented repr."""
    source = _read_source(path)
    try:
        program = _parse(source, path)
        for decl in program.declarations:
            _print_node(decl, indent=0)
    except (LexError, ParseError) as e:
        print(f"chimera: parse error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_check(path: str) -> None:
    """Type-check a .chimera file."""
    source = _read_source(path)
    try:
        program = _parse(source, path)
    except (LexError, ParseError) as e:
        print(f"chimera: parse error: {e}", file=sys.stderr)
        sys.exit(1)

    checker = TypeChecker()
    result = checker.check(program)

    for w in result.warnings:
        print(f"  warning: {w}")
    for e in result.errors:
        print(f"  ERROR: {e}")
    if result.ok:
        print(f"chimera: {path} — type check PASSED")
    else:
        print(f"chimera: {path} — type check FAILED ({len(result.errors)} error(s))")
        sys.exit(1)


def cmd_run(path: str, *, show_trace: bool = False) -> None:
    """Execute a .chimera program."""
    source = _read_source(path)
    try:
        program = _parse(source, path)
    except (LexError, ParseError) as e:
        print(f"chimera: parse error: {e}", file=sys.stderr)
        sys.exit(1)

    vm = ChimeraVM()
    result = vm.execute(program)

    if result.emitted:
        for val in result.emitted:
            conf_str = f"{val.confidence.value:.2f}"
            print(f"  emit: {val.raw}  [confidence={conf_str}]")

    if show_trace and result.trace:
        print("\n— Reasoning Trace —")
        for entry in result.trace:
            print(f"  {entry}")

    if result.errors:
        print("\n— Errors —")
        for e in result.errors:
            print(f"  {e}")
        sys.exit(1)

    print(
        f"\nchimera: {path} — executed in {result.duration_ms:.1f}ms"
        f" (assertions: {result.assertions_passed} passed, {result.assertions_failed} failed)"
    )


def cmd_prove(path: str) -> None:
    """Execute + full integrity report."""
    source = _read_source(path)
    try:
        program = _parse(source, path)
    except (LexError, ParseError) as e:
        print(f"chimera: parse error: {e}", file=sys.stderr)
        sys.exit(1)

    # Execute
    vm = ChimeraVM()
    exec_result = vm.execute(program)

    # Hallucination scan
    detector = HallucinationDetector()
    detection = detector.full_scan(exec_result.gate_logs, exec_result.emitted)

    # Integrity report
    engine = IntegrityEngine()
    report = engine.certify(exec_result, detection, source)

    # Print report
    print("═══════════════════════════════════════════════")
    print("        CHIMERALANG INTEGRITY REPORT           ")
    print("═══════════════════════════════════════════════")
    print(report.to_json())
    print("═══════════════════════════════════════════════")
    print(f"  Verdict: {report.verdict}")
    print("═══════════════════════════════════════════════")


def _print_node(node: object, indent: int) -> None:
    prefix = "  " * indent
    name = type(node).__name__
    print(f"{prefix}{name}", end="")
    if hasattr(node, "name"):
        print(f" ({node.name})", end="")  # type: ignore[attr-defined]
    if hasattr(node, "description"):
        print(f' ("{node.description}")', end="")  # type: ignore[attr-defined]
    print()
    for attr in ("params", "body", "declarations", "then_body", "else_body"):
        children = getattr(node, attr, None)
        if isinstance(children, list):
            for child in children:
                _print_node(child, indent + 1)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

USAGE = """\
ChimeraLang v0.1.0 — A programming language for AI cognition

Usage:
  chimera run   <file.chimera>   Execute a program
  chimera check <file.chimera>   Type-check only
  chimera lex   <file.chimera>   Dump token stream
  chimera parse <file.chimera>   Dump AST
  chimera prove <file.chimera>   Run + integrity report

Options:
  --trace   Show reasoning trace (with run)
  --help    Show this message
"""


def main() -> None:
    args = sys.argv[1:]
    if not args or "--help" in args or "-h" in args:
        print(USAGE)
        sys.exit(0)

    cmd = args[0]
    rest = args[1:]
    trace = "--trace" in rest
    positional = [a for a in rest if not a.startswith("--")]

    if not positional:
        print(f"chimera: '{cmd}' requires a file argument", file=sys.stderr)
        sys.exit(1)

    filepath = positional[0]

    commands = {
        "run": lambda: cmd_run(filepath, show_trace=trace),
        "check": lambda: cmd_check(filepath),
        "lex": lambda: cmd_lex(filepath),
        "parse": lambda: cmd_parse(filepath),
        "prove": lambda: cmd_prove(filepath),
    }

    handler = commands.get(cmd)
    if handler is None:
        print(f"chimera: unknown command '{cmd}'", file=sys.stderr)
        print(USAGE)
        sys.exit(1)

    handler()


if __name__ == "__main__":
    main()
