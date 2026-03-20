from __future__ import annotations

from typing import Any, Dict, List, Tuple


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // 4)


def compress_context(
    messages: List[Dict[str, Any]],
    query: str = "",
    max_tokens: int = 3000,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    safe_messages = messages or []

    original_text = "\n".join(str(item.get("content", "")) for item in safe_messages)
    original_tokens = _estimate_tokens(original_text)

    if max_tokens <= 0 or original_tokens <= max_tokens:
        compressed_messages = safe_messages
        compressed_tokens = original_tokens
    else:
        ratio = max_tokens / max(original_tokens, 1)
        compressed_messages = []
        for item in safe_messages:
            content = str(item.get("content", ""))
            keep = max(1, int(len(content) * ratio))
            compressed_messages.append({
                "role": item.get("role", "user"),
                "content": content[:keep],
            })
        compressed_text = "\n".join(str(item.get("content", "")) for item in compressed_messages)
        compressed_tokens = _estimate_tokens(compressed_text)

    stats = {
        "query": query,
        "original_messages": len(safe_messages),
        "original_tokens_estimate": original_tokens,
        "compressed_tokens_estimate": compressed_tokens,
        "target_max_tokens": max_tokens,
        "compression_ratio": (compressed_tokens / original_tokens) if original_tokens else 1.0,
    }

    return compressed_messages, stats
