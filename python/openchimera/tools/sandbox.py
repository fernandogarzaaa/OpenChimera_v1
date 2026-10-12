"""Out-of-process execution helpers for the ``code.execute`` and ``shell.exec`` tools.

Python code from a model is never ``exec()``-ed inside the OpenChimera process.
It runs in a separate interpreter (``python -I -S``) with:

* an empty environment (no API keys, no ``OPENCHIMERA_*`` settings),
* a fresh temporary working directory,
* restricted builtins (no ``open``, ``__import__``, ``eval``, ``exec``,
  ``getattr`` ...) and an import hook that only allows a small set of
  pure-computation standard-library modules,
* a static check that rejects dunder names, private (``_x``) attribute access,
  frame/generator internals and access to module attributes such as ``.os``,
* CPU, memory, file-size and process limits (POSIX ``resource``; on Windows only
  the wall-clock timeout applies),
* a wall-clock timeout.

This is defence in depth, not a security boundary equivalent to a container or
VM. Do not expose ``code.execute`` to untrusted users without OS-level isolation.

Shell commands run without a shell (``shlex.split`` argv list), with a scrubbed
environment, and only when the operator has allowed it (see ``ToolsConfig``).
"""

from __future__ import annotations

import ast
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from typing import Any

# ── Python sandbox policy ────────────────────────────────────────────────────

#: Modules named explicitly in error messages. Never importable.
BLOCKED_MODULES: frozenset[str] = frozenset({
    "os", "sys", "subprocess", "socket", "ctypes", "importlib", "builtins",
    "shutil", "pathlib", "io", "multiprocessing", "threading", "signal", "pty",
    "posix", "nt", "resource", "gc", "inspect", "code", "codeop", "runpy",
    "pickle", "marshal", "shelve", "tempfile", "glob", "asyncio", "select",
    "selectors", "mmap", "urllib", "http", "ftplib", "smtplib", "ssl",
    "webbrowser", "platform", "sysconfig", "site", "types", "_thread",
})

#: Pure-computation stdlib modules user code may import (root package name).
ALLOWED_MODULES: frozenset[str] = frozenset({
    "math", "cmath", "random", "statistics", "decimal", "fractions", "numbers",
    "json", "re", "string", "textwrap", "unicodedata", "difflib",
    "itertools", "functools", "operator", "collections", "heapq", "bisect",
    "array", "copy", "pprint", "enum", "dataclasses", "typing",
    "datetime", "time", "calendar", "zoneinfo",
    "hashlib", "hmac", "base64", "binascii", "uuid", "secrets", "struct",
    "csv",
})

#: Attribute names that lead from ordinary objects to the interpreter
#: internals (frames, globals) or to modules re-exported by allowed modules.
BLOCKED_ATTRIBUTES: frozenset[str] = BLOCKED_MODULES | frozenset({
    "modules", "gi_frame", "gi_code", "cr_frame", "cr_code", "ag_frame",
    "ag_code", "f_globals", "f_locals", "f_builtins", "f_back", "f_code",
    "tb_frame", "tb_next", "func_globals", "mro",
})

SAFE_BUILTINS: tuple[str, ...] = (
    "abs", "all", "any", "ascii", "bin", "bool", "bytearray", "bytes",
    "callable", "chr", "classmethod", "complex", "dict", "divmod", "enumerate",
    "filter", "float", "format", "frozenset", "hasattr", "hash", "hex", "id",
    "int", "isinstance", "issubclass", "iter", "len", "list", "map", "max",
    "min", "next", "object", "oct", "ord", "pow", "print", "property", "range",
    "repr", "reversed", "round", "set", "slice", "sorted", "staticmethod",
    "str", "sum", "super", "tuple", "type", "zip",
    "True", "False", "None", "NotImplemented", "Ellipsis",
    "BaseException", "Exception", "ArithmeticError", "AssertionError",
    "AttributeError", "EOFError", "FloatingPointError", "ImportError",
    "IndexError", "KeyError", "LookupError", "MemoryError",
    "ModuleNotFoundError", "NameError", "NotImplementedError", "OverflowError",
    "RecursionError", "RuntimeError", "StopIteration", "StopAsyncIteration",
    "TypeError", "UnicodeError", "UnicodeDecodeError", "UnicodeEncodeError",
    "ValueError", "ZeroDivisionError", "Warning",
    "UserWarning", "DeprecationWarning", "RuntimeWarning",
    "__build_class__",
)

DEFAULT_TIMEOUT_S = 10
DEFAULT_CPU_S = 5
DEFAULT_MEMORY_MB = 256
DEFAULT_FILE_SIZE_MB = 1
MAX_STDOUT = 10_000
MAX_STDERR = 5_000


def check_python_code(code: str) -> str | None:
    """Static policy check. Returns an error message, or ``None`` if allowed."""
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return f"Syntax error: {exc}"
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root not in ALLOWED_MODULES:
                    return f"Import of '{alias.name}' is blocked in sandbox"
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                return "Relative imports are blocked in sandbox"
            root = (node.module or "").split(".")[0]
            if root not in ALLOWED_MODULES:
                return f"Import from '{node.module}' is blocked in sandbox"
            for alias in node.names:
                if alias.name.startswith("_") or alias.name in BLOCKED_ATTRIBUTES:
                    return f"Import of name '{alias.name}' is blocked in sandbox"
        elif isinstance(node, ast.Name):
            if node.id.startswith("__"):
                return f"Use of name '{node.id}' is blocked in sandbox"
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("_") or node.attr in BLOCKED_ATTRIBUTES:
                return f"Access to attribute '{node.attr}' is blocked in sandbox"
        elif isinstance(node, ast.MatchClass):
            for attr in node.kwd_attrs:
                if attr.startswith("_") or attr in BLOCKED_ATTRIBUTES:
                    return f"Access to attribute '{attr}' is blocked in sandbox"
    return None


# The runner is executed with ``python -I -S -c``; it reads its config from stdin
# so the user code never appears on the command line.
_RUNNER = r'''
import json, sys
_cfg = json.loads(sys.stdin.read())
try:
    import resource as _r
    def _lim(name, value):
        res = getattr(_r, name, None)
        if res is None:
            return
        try:
            _r.setrlimit(res, (value, value))
        except (ValueError, OSError):
            pass
    _lim("RLIMIT_CPU", _cfg["cpu"])
    _lim("RLIMIT_AS", _cfg["mem"])
    _lim("RLIMIT_FSIZE", _cfg["fsize"])
    _lim("RLIMIT_NPROC", 0)
    _lim("RLIMIT_CORE", 0)
except ImportError:
    pass
import builtins as _b
_allowed = frozenset(_cfg["modules"])
_real_import = _b.__import__
def _guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    if level or name.split(".")[0] not in _allowed:
        raise ImportError("Import of %r is blocked in sandbox" % (name,))
    return _real_import(name, globals, locals, fromlist, level)
_ns_builtins = {k: getattr(_b, k) for k in _cfg["builtins"] if hasattr(_b, k)}
_ns_builtins["__import__"] = _guarded_import
_code = compile(_cfg["code"], "<sandbox>", "exec")
_ns = {"__builtins__": _ns_builtins, "__name__": "__sandbox__"}
del _cfg
try:
    sys.stdin.close()
except Exception:
    pass
try:
    exec(_code, _ns)
except SystemExit:
    raise
except BaseException as _exc:
    sys.stderr.write("%s: %s\n" % (type(_exc).__name__, _exc))
    sys.stdout.flush()
    sys.exit(1)
'''


def sandbox_env() -> dict[str, str]:
    """Environment for the sandboxed interpreter: empty except what Windows needs to boot."""
    env: dict[str, str] = {}
    if os.name == "nt":
        for key in ("SYSTEMROOT", "SystemRoot"):
            if key in os.environ:
                env[key] = os.environ[key]
    return env


def run_python_sandboxed(
    code: str,
    *,
    timeout: float = DEFAULT_TIMEOUT_S,
    cpu_seconds: int = DEFAULT_CPU_S,
    memory_mb: int = DEFAULT_MEMORY_MB,
    file_size_mb: int = DEFAULT_FILE_SIZE_MB,
) -> dict[str, Any]:
    """Check and run ``code`` in a separate restricted interpreter."""
    error = check_python_code(code)
    if error:
        return {"error": error, "returncode": -1, "stdout": "", "stderr": ""}
    cfg = {
        "code": code,
        "cpu": int(cpu_seconds),
        "mem": int(memory_mb) * 1024 * 1024,
        "fsize": int(file_size_mb) * 1024 * 1024,
        "modules": sorted(ALLOWED_MODULES),
        "builtins": list(SAFE_BUILTINS),
    }
    with tempfile.TemporaryDirectory(prefix="openchimera-sandbox-") as workdir:
        try:
            proc = subprocess.run(
                [sys.executable, "-I", "-S", "-c", _RUNNER],
                input=json.dumps(cfg),
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=workdir,
                env=sandbox_env(),
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return {
                "error": f"Code timed out after {timeout}s",
                "returncode": -1,
                "stdout": _text(exc.stdout)[:MAX_STDOUT],
                "stderr": _text(exc.stderr)[:MAX_STDERR],
            }
    result: dict[str, Any] = {
        "stdout": proc.stdout[:MAX_STDOUT],
        "stderr": proc.stderr[:MAX_STDERR],
        "returncode": proc.returncode,
    }
    if proc.returncode != 0:
        result["error"] = (proc.stderr.strip().splitlines() or [f"exit code {proc.returncode}"])[-1][:500]
    return result


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)


# ── Shell policy ─────────────────────────────────────────────────────────────

#: Variables passed to shell commands by default (if present).
BASE_ENV_KEYS: tuple[str, ...] = (
    "PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TERM", "TMPDIR", "TZ", "USER",
    # Windows needs these to start most programs.
    "SYSTEMROOT", "SystemRoot", "COMSPEC", "PATHEXT", "WINDIR", "TEMP", "TMP",
    "USERPROFILE",
)

_SENSITIVE = re.compile(
    r"KEY|TOKEN|SECRET|PASSW|CREDENTIAL|AUTH|COOKIE|SESSION|PRIVATE|^OPENCHIMERA_",
    re.IGNORECASE,
)


def is_sensitive_env_name(name: str) -> bool:
    return bool(_SENSITIVE.search(name))


def scrubbed_env(
    source: Mapping[str, str] | None = None,
    passthrough: list[str] | tuple[str, ...] = (),
) -> dict[str, str]:
    """Minimal environment for shell commands; never includes secret-looking names."""
    src = os.environ if source is None else source
    env: dict[str, str] = {}
    for key in (*BASE_ENV_KEYS, *passthrough):
        if key in src and not is_sensitive_env_name(key):
            env[key] = src[key]
    return env


def split_command(command: str) -> list[str]:
    """Split a command string into argv without invoking a shell."""
    return shlex.split(command, posix=os.name != "nt")


def program_name(argv: list[str]) -> str:
    base = os.path.basename(argv[0]) if argv else ""
    if os.name == "nt" and base.lower().endswith(".exe"):
        base = base[:-4]
    return base
