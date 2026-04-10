# CHIMERA_HARNESS: session_compactor
"""
SessionCompactor: Tracks token count and compacts session history when context limits are reached.
Uses LLM client to summarize old messages into a compressed context block.
"""
from typing import List, Tuple

class SessionCompactor:
    def __init__(self, llm_client) -> None:
        self.llm_client = llm_client

    def should_compact(self, messages: List[dict], threshold_tokens: int = 80000) -> bool:
        token_count = sum(m.get('token_count', 0) for m in messages)
        return token_count > threshold_tokens

    def compact(self, messages: List[dict], keep_last_n: int = 10) -> Tuple[List[dict], str]:
        if len(messages) <= keep_last_n:
            return messages, ""
        to_summarize = messages[:-keep_last_n]
        keep = messages[-keep_last_n:]
        summary = self.llm_client.summarize_messages(to_summarize)
        summary_block = {"role": "system", "content": summary, "token_count": len(summary.split())}
        new_messages = [summary_block] + keep
        return new_messages, summary
