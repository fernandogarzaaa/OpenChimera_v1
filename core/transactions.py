from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def atomic_write_text(path: Path, content: str, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = None
    temp_path: Path | None = None
    try:
        handle = tempfile.NamedTemporaryFile("w", encoding=encoding, delete=False, dir=str(path.parent), newline="")
        temp_path = Path(handle.name)
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        handle = None
        os.replace(temp_path, path)
    finally:
        if handle is not None and not handle.closed:
            handle.close()
        if temp_path is not None and temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass


def atomic_write_json(path: Path, payload: Any, indent: int = 2, encoding: str = "utf-8") -> None:
    atomic_write_text(path, json.dumps(payload, indent=indent), encoding=encoding)


def atomic_write_jsonl(path: Path, records: list[dict[str, Any]], encoding: str = "utf-8") -> None:
    lines = [json.dumps(record, ensure_ascii=True) for record in records]
    content = "\n".join(lines)
    if content:
        content += "\n"
    atomic_write_text(path, content, encoding=encoding)