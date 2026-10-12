"""Security regression tests for the ``code.execute`` / ``shell.exec`` tools.

Before the Oct 2026 audit fix, ``code.execute`` ran model code with ``exec()``
and the real builtins (``__import__('os')`` escaped the "sandbox"), and
``shell.exec`` ran ``shell=True`` with the full parent environment (provider API
keys) and no approval. These tests pin the fixed behaviour.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON_PACKAGE_PATH = REPO_ROOT / "python"
SANDBOX_PATH = PYTHON_PACKAGE_PATH / "openchimera" / "tools" / "sandbox.py"

# ``openchimera`` at the repo root is the legacy package, so load the v2 sandbox
# module straight from its file (it has no package-internal imports).
_spec = importlib.util.spec_from_file_location("_oc_tool_sandbox", SANDBOX_PATH)
sb = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(sb)

IS_WINDOWS = os.name == "nt"


# ── Static policy ────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "code, fragment",
    [
        ("__import__('os').system('id')", "__import__"),
        ("import os", "Import of 'os'"),
        ("import os.path", "Import of 'os.path'"),
        ("from os import path", "Import from 'os'"),
        ("import importlib", "Import of 'importlib'"),
        ("import subprocess", "Import of 'subprocess'"),
        ("import socket", "Import of 'socket'"),
        ("import ctypes", "Import of 'ctypes'"),
        ("import sys", "Import of 'sys'"),
        ("import logging", "Import of 'logging'"),
        ("from . import x", "Relative imports"),
        ("from statistics import sys", "name 'sys'"),
        ("from random import _os", "name '_os'"),
        ("import random\nrandom._os.system('id')", "attribute '_os'"),
        ("import statistics\nstatistics.sys", "attribute 'sys'"),
        ("().__class__.__base__.__subclasses__()", "is blocked"),
        ("print(__builtins__)", "__builtins__"),
        ("g = (i for i in [1])\ng.gi_frame", "attribute 'gi_frame'"),
        ("x = 1\nmatch x:\n    case object(__class__=c):\n        pass", "attribute '__class__'"),
        ("def f(:\n  pass", "Syntax error"),
    ],
)
def test_static_check_blocks_escapes(code: str, fragment: str) -> None:
    error = sb.check_python_code(code)
    assert error is not None, code
    assert fragment in error


@pytest.mark.parametrize(
    "code",
    [
        "import math\nprint(math.sqrt(16))",
        "from collections import Counter\nprint(Counter('aab'))",
        "import json, re, itertools",
        "class A:\n    def __init__(self):\n        self.v = 1\nprint(A().v)",
        "x = 1\nmatch x:\n    case int(real=r):\n        print(r)",
        "_ = 3\nprint(_)",
    ],
)
def test_static_check_allows_plain_code(code: str) -> None:
    assert sb.check_python_code(code) is None


# ── Out-of-process execution ─────────────────────────────────────────────────

def test_python_runs_and_returns_stdout() -> None:
    result = sb.run_python_sandboxed("import math\nprint(math.sqrt(16))")
    assert result["returncode"] == 0, result
    assert result["stdout"].strip() == "4.0"
    assert "error" not in result


def test_import_os_escape_is_refused_before_running() -> None:
    result = sb.run_python_sandboxed("__import__('os').system('echo PWNED')")
    assert result["returncode"] == -1
    assert "blocked" in result["error"]
    assert "PWNED" not in result["stdout"]


def test_runtime_import_hook_blocks_even_without_static_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """Second layer: if the AST check were bypassed, the import hook still refuses."""
    monkeypatch.setattr(sb, "check_python_code", lambda code: None)
    result = sb.run_python_sandboxed("print(__import__('os').getcwd())")
    assert result["returncode"] == 1, result
    assert "ImportError" in result["error"]
    assert "blocked in sandbox" in result["error"]
    result = sb.run_python_sandboxed("import math\nprint(math.pi > 3)")
    assert result["stdout"].strip() == "True"


@pytest.mark.parametrize("name", ["open", "eval", "exec", "getattr", "compile", "globals", "vars", "input"])
def test_dangerous_builtins_are_absent(name: str) -> None:
    result = sb.run_python_sandboxed(f"{name}")
    assert result["returncode"] == 1, result
    assert "NameError" in result["error"]


def test_child_environment_is_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-should-not-leak")
    monkeypatch.setenv("OPENCHIMERA_API__AUTH__TOKEN", "tok-should-not-leak")
    env = sb.sandbox_env()
    assert "OPENAI_API_KEY" not in env
    assert "OPENCHIMERA_API__AUTH__TOKEN" not in env
    if not IS_WINDOWS:
        assert env == {}


def test_child_process_receives_sandbox_env_and_tempdir(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}
    real_run = subprocess.run

    def spy(argv, **kwargs):
        seen.update(kwargs)
        seen["argv"] = argv
        return real_run(argv, **kwargs)

    monkeypatch.setattr(sb.subprocess, "run", spy)
    monkeypatch.setenv("GITHUB_TOKEN", "ghp-should-not-leak")
    result = sb.run_python_sandboxed("print('ok')", timeout=7)
    assert result["stdout"].strip() == "ok"
    assert seen["env"] == sb.sandbox_env()
    assert "GITHUB_TOKEN" not in seen["env"]
    assert seen["timeout"] == 7
    assert seen["argv"][:3] == [sys.executable, "-I", "-S"]
    assert "openchimera-sandbox-" in str(seen["cwd"])
    assert str(seen["cwd"]) != os.getcwd()
    assert "print('ok')" not in " ".join(seen["argv"])  # code goes via stdin
    cfg = json.loads(seen["input"])
    assert "open" not in cfg["builtins"] and "__import__" not in cfg["builtins"]
    assert "os" not in cfg["modules"]


def test_wall_clock_timeout() -> None:
    result = sb.run_python_sandboxed("while True:\n    pass", timeout=2, cpu_seconds=30)
    assert result["returncode"] != 0
    assert "error" in result


@pytest.mark.skipif(IS_WINDOWS, reason="resource limits are POSIX-only")
def test_cpu_limit_kills_busy_loop() -> None:
    result = sb.run_python_sandboxed("while True:\n    pass", timeout=30, cpu_seconds=1)
    assert result["returncode"] != 0
    assert "timed out" not in result.get("error", "")


@pytest.mark.skipif(IS_WINDOWS or sys.platform == "darwin", reason="RLIMIT_AS is enforced on Linux")
def test_memory_limit() -> None:
    result = sb.run_python_sandboxed("x = bytearray(512 * 1024 * 1024)\nprint('allocated')", memory_mb=128)
    assert result["returncode"] != 0
    assert "allocated" not in result["stdout"]
    assert "MemoryError" in result["error"]


def test_output_is_truncated() -> None:
    result = sb.run_python_sandboxed("print('a' * 50000)")
    assert len(result["stdout"]) == sb.MAX_STDOUT


def test_failing_code_reports_error() -> None:
    result = sb.run_python_sandboxed("print('before')\n1/0")
    assert result["returncode"] == 1
    assert result["stdout"].strip() == "before"
    assert result["error"] == "ZeroDivisionError: division by zero"


# ── Shell helpers ────────────────────────────────────────────────────────────

def test_scrubbed_env_drops_secrets() -> None:
    source = {
        "PATH": "/usr/bin",
        "HOME": "/home/u",
        "OPENAI_API_KEY": "sk-1",
        "ANTHROPIC_API_KEY": "sk-2",
        "GITHUB_TOKEN": "ghp",
        "AWS_SECRET_ACCESS_KEY": "aws",
        "DB_PASSWORD": "pw",
        "OPENCHIMERA_API__AUTH__TOKEN": "t",
        "UNRELATED": "x",
        "FOO": "bar",
        "MY_API_KEY": "k",
    }
    assert sb.scrubbed_env(source) == {"PATH": "/usr/bin", "HOME": "/home/u"}
    assert sb.scrubbed_env(source, passthrough=["FOO", "MY_API_KEY"]) == {
        "PATH": "/usr/bin",
        "HOME": "/home/u",
        "FOO": "bar",
    }


@pytest.mark.parametrize(
    "name, sensitive",
    [
        ("OPENAI_API_KEY", True), ("github_token", True), ("CLIENT_SECRET", True),
        ("PGPASSWORD", True), ("GOOGLE_APPLICATION_CREDENTIALS", True),
        ("HF_AUTH", True), ("SESSION_ID", True), ("PRIVATE_PEM", True),
        ("OPENCHIMERA_SERVER__PORT", True), ("PATH", False), ("HOME", False),
        ("LANG", False), ("MY_OPENCHIMERA_X", False),
    ],
)
def test_sensitive_env_names(name: str, sensitive: bool) -> None:
    assert sb.is_sensitive_env_name(name) is sensitive


@pytest.mark.skipif(IS_WINDOWS, reason="POSIX shlex rules")
def test_split_command_does_not_interpret_shell_syntax() -> None:
    assert sb.split_command('echo "a b"; rm -rf /') == ["echo", "a b;", "rm", "-rf", "/"]
    assert sb.split_command("cat x | sh") == ["cat", "x", "|", "sh"]


def test_program_name() -> None:
    assert sb.program_name(["/usr/bin/git", "status"]) == "git"
    assert sb.program_name(["ls"]) == "ls"
    assert sb.program_name([]) == ""


# ── ToolRegistry integration (runs in a subprocess with the v2 package path) ─

_REGISTRY_SCRIPT = r'''
import asyncio, json, os, sys, tempfile
from openchimera.config import Settings, ToolsConfig
from openchimera.tools.registry import ToolRegistry

IS_WIN = os.name == "nt"
os.environ["OPENAI_API_KEY"] = "sk-test-leak-123"
os.environ["OPENCHIMERA_SECRET_THING"] = "oc-leak-456"
out = {}

async def main():
    work = tempfile.mkdtemp()
    marker = os.path.join(work, "marker")
    cmd = "touch " + marker

    # 1. default: denied, nothing runs (also for code.execute bash)
    reg = ToolRegistry(Settings())
    r = await reg.execute("shell.exec", {"command": cmd})
    out["default_denied"] = bool(r.get("denied")) and not os.path.exists(marker)
    r = await reg.execute("code.execute", {"code": cmd, "language": "bash"})
    out["bash_denied"] = bool(r.get("denied")) and not os.path.exists(marker)
    r = ToolRegistry(None)
    r = await r.execute("shell.exec", {"command": cmd})
    out["none_settings_denied"] = bool(r.get("denied"))

    # 2. approval callback
    calls = []
    def deny(tool_id, argv):
        calls.append((tool_id, argv)); return False
    r = await ToolRegistry(Settings(), approval_callback=deny).execute("shell.exec", {"command": cmd})
    out["cb_deny"] = bool(r.get("denied")) and calls == [("shell.exec", ["touch", marker])]
    r = await ToolRegistry(Settings(), approval_callback=lambda t, a: "yes").execute("shell.exec", {"command": cmd})
    out["cb_truthy_not_true_denied"] = bool(r.get("denied"))
    seen = []
    async def approve(tool_id, argv):
        seen.append(tool_id); return True
    reg_cb = ToolRegistry(Settings(), approval_callback=approve)
    if not IS_WIN:
        r = await reg_cb.execute("code.execute", {"code": cmd, "language": "bash"})
        out["cb_async_approve"] = r.get("returncode") == 0 and os.path.exists(marker) and seen == ["code.execute"]

    # 3. allowlist + env scrub + no shell interpretation
    s = Settings(tools=ToolsConfig(shell_allowlist=["env", "echo"]))
    reg = ToolRegistry(s)
    if not IS_WIN:
        r = await reg.execute("shell.exec", {"command": "env"})
        out["env_ok"] = r.get("returncode") == 0 and "PATH=" in r["stdout"]
        out["env_no_leak"] = "sk-test-leak" not in r["stdout"] and "oc-leak" not in r["stdout"]
        target = os.path.join(work, "out.txt")
        r = await reg.execute("shell.exec", {"command": "echo hi > " + target})
        out["no_redirect"] = r["stdout"].strip() == "hi > " + target and not os.path.exists(target)
        r = await reg.execute("shell.exec", {"command": "touch " + marker + "2"})
        out["not_allowlisted_denied"] = bool(r.get("denied")) and not os.path.exists(marker + "2")
        r = await ToolRegistry(Settings(tools=ToolsConfig(allow_shell=True))).execute(
            "shell.exec", {"command": "touch " + marker + "3"})
        out["allow_shell"] = r.get("returncode") == 0 and os.path.exists(marker + "3")
        r = await ToolRegistry(Settings(tools=ToolsConfig(allow_shell=True))).execute(
            "shell.exec", {"command": "definitely-not-a-program-xyz"})
        out["missing_program"] = "not found" in r.get("error", "")
    r = await reg.execute("shell.exec", {"command": "   "})
    out["empty_rejected"] = "non-empty" in r.get("error", "")
    r = await reg.execute("shell.exec", {"command": "echo 'unterminated"})
    out["bad_quote_rejected"] = "parse" in r.get("error", "") if not IS_WIN else True

    # 4. python sandbox through the registry
    reg = ToolRegistry(Settings())
    r = await reg.execute("code.execute", {"code": "__import__('os').system('echo PWNED')"})
    out["py_escape_blocked"] = "blocked" in r.get("error", "") and "PWNED" not in r.get("stdout", "")
    r = await reg.execute("code.execute", {"code": "print(1 + 1)"})
    out["py_ok"] = r.get("stdout", "").strip() == "2" and r.get("returncode") == 0
    r = await reg.execute("code.execute", {"code": "print(open)"})
    out["py_no_open"] = r.get("returncode") == 1 and "NameError" in r.get("error", "")
    r = await ToolRegistry(Settings(tools=ToolsConfig(python_enabled=False))).execute(
        "code.execute", {"code": "print(1)"})
    out["py_disabled"] = "disabled" in r.get("error", "")
    r = await reg.execute("code.execute", {"code": "print(1)", "language": "javascript"})
    out["lang_unsupported"] = "not supported" in r.get("error", "")

asyncio.run(main())
print(json.dumps(out))
'''


def test_registry_shell_and_python_policy() -> None:
    env = {k: v for k, v in os.environ.items() if not k.startswith("OPENCHIMERA_")}
    env["PYTHONPATH"] = str(PYTHON_PACKAGE_PATH)
    proc = subprocess.run(
        [sys.executable, "-c", _REGISTRY_SCRIPT],
        cwd=Path(tempfile.gettempdir()),
        env=env,
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    failed = [k for k, v in out.items() if v is not True]
    assert not failed, out
    expected = {
        "default_denied", "bash_denied", "none_settings_denied", "cb_deny",
        "cb_truthy_not_true_denied", "empty_rejected", "bad_quote_rejected",
        "py_escape_blocked", "py_ok", "py_no_open", "py_disabled", "lang_unsupported",
    }
    if not IS_WINDOWS:
        expected |= {
            "cb_async_approve", "env_ok", "env_no_leak", "no_redirect",
            "not_allowlisted_denied", "allow_shell", "missing_program",
        }
    assert expected <= set(out), sorted(expected - set(out))
