"""The packaged AgentOrchestrator feeds tool results back to the model."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON_PACKAGE_PATH = REPO_ROOT / "python"


def _run(code: str) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("OPENCHIMERA_")}
    env["PYTHONPATH"] = str(PYTHON_PACKAGE_PATH)
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(tempfile.gettempdir()),
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )


_SCRIPTED_PROVIDER = """
import asyncio, json, os, tempfile
from openchimera.agent import AgentOrchestrator
from openchimera.config import Settings
from openchimera.providers.manager import OpenAICompatibleProvider
from openchimera.tools.registry import ToolRegistry

class Scripted(OpenAICompatibleProvider):
    name = 'openai'
    def __init__(self):
        super().__init__(api_key='x', default_model='scripted')
        self.calls = []
    async def chat(self, messages, model=None, tools=None, **kw):
        self.calls.append({'messages': [dict(m) for m in messages], 'tools': tools})
        if len(self.calls) == 1:
            return {'text': '', 'tool_calls': [{'id': 'call_1', 'type': 'function',
                    'function': {'name': 'file__list', 'arguments': json.dumps({'path': DIR})}}]}
        tool_msg = messages[-1]
        assert tool_msg['role'] == 'tool' and tool_msg['tool_call_id'] == 'call_1', messages
        return {'text': 'Saw: ' + tool_msg['content'], 'tool_calls': []}

class PM:
    def __init__(self, p): self.p = p
    def get(self, name): return self.p
    def get_default(self): return self.p

DIR = tempfile.mkdtemp()
open(os.path.join(DIR, 'hello.txt'), 'w').write('hi')
prov = Scripted()
orch = AgentOrchestrator(PM(prov), ToolRegistry(Settings()))
"""


def test_tool_results_are_sent_back_and_final_answer_returned() -> None:
    code = _SCRIPTED_PROVIDER + """
out = asyncio.run(orch.query('list it', provider=None, model=None, execute_tools=True))
assert out['tools'] == ['file.list'], out
assert 'hello.txt' in out['text'], out
assert len(prov.calls) == 2
names = [t['function']['name'] for t in prov.calls[0]['tools']]
import re
assert all(re.fullmatch(r'[A-Za-z0-9_-]{1,64}', n) for n in names), names
assert 'file__list' in names
"""
    result = _run(code)
    assert result.returncode == 0, result.stdout + result.stderr


def test_without_tools_flag_the_model_is_called_once() -> None:
    code = _SCRIPTED_PROVIDER + """
async def plain(messages, model=None, tools=None, **kw):
    assert tools is None
    return {'text': 'plain answer', 'tool_calls': []}
prov.chat = plain
out = asyncio.run(orch.query('hello', provider=None, model=None, execute_tools=False))
assert out['text'] == 'plain answer' and out['tools'] == [], out
"""
    result = _run(code)
    assert result.returncode == 0, result.stdout + result.stderr
