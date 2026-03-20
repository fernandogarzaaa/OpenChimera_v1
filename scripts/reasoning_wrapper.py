import json
import re

class ReasoningWrapper:
    def __init__(self, llm_client):
        self.llm_client = llm_client

    def generate(self, prompt):
        # 1. Force LLM to generate thought-trace
        system_instruction = (
            "You are a System-2 reasoning engine. "
            "You must output exactly: <think>Reasoning process</think><final>Final answer</final>."
        )
        
        raw_output = self.llm_client.call(
            prompt=prompt,
            system_instruction=system_instruction
        )
        
        # 2. Parse
        think_match = re.search(r"<think>(.*?)</think>", raw_output, re.DOTALL)
        final_match = re.search(r"<final>(.*?)</final>", raw_output, re.DOTALL)
        
        thought = think_match.group(1) if think_match else ""
        final = final_match.group(1) if final_match else ""
        
        # 3. Critic/Auditor Step
        is_valid, critique = self._audit(thought, final)
        
        if not is_valid:
            # Re-prompt or handle failure
            return f"Validation failed: {critique}. Please refine your reasoning."
            
        return final

    def _audit(self, thought, final):
        # Placeholder for audit logic
        # In a real impl, this would call a secondary LLM/validator
        if not thought or len(thought) < 50:
            return False, "Reasoning trace too short or missing."
        if not final:
            return False, "Final answer missing."
        return True, "Valid"

# Usage Example
if __name__ == "__main__":
    # Mock client
    class MockClient:
        def call(self, prompt, system_instruction):
            return "<think>Let's consider the objective...</think><final>The objective is achieved.</final>"
    
    wrapper = ReasoningWrapper(MockClient())
    print(wrapper.generate("What is the objective?"))
