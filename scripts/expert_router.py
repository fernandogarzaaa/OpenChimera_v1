#!/usr/bin/env python3
"""
expert_router.py

Sparse Mixture of Experts (SMoE) Dynamic Router for CHIMERA.
Routes prompts to the optimal model based on intent analysis.
"""

import re
import logging

# Configuration for models
MODELS = {
    "LOGIC": ["Llama3", "Qwen2.5-Coder"],
    "CREATIVE": ["Mistral-Small", "Gemma-2"],
}

# Intent mapping
INTENT_MAP = {
    "LOGIC": [
        "code", "analyze", "debug", "math", "plan", "security", 
        "architecture", "refactor", "algorithm", "data", "database"
    ],
    "CREATIVE": [
        "write", "story", "poem", "blog", "imagine", "marketing", 
        "brainstorm", "copy", "summarize", "creative"
    ]
}

def detect_intent(prompt: str) -> str:
    """Analyze prompt to determine intent."""
    prompt_lower = prompt.lower()
    
    scores = {"LOGIC": 0, "CREATIVE": 0}
    
    for intent, keywords in INTENT_MAP.items():
        for keyword in keywords:
            if re.search(rf"\b{keyword}\b", prompt_lower):
                scores[intent] += 1
                
    # Return highest scoring intent, default to LOGIC
    return max(scores, key=scores.get)

def route(prompt: str) -> str:
    """Route prompt to the most capable model."""
    intent = detect_intent(prompt)
    model_pool = MODELS[intent]
    
    # In a production environment, this would interface with the CHIMERA endpoint
    # to check model availability/load. For now, we return the primary expert.
    selected_model = model_pool[0]
    
    print(f"[Router] Intent: {intent} | Model: {selected_model}")
    return selected_model

if __name__ == "__main__":
    # Simple test cases
    test_prompts = [
        "Debug this python script for memory leaks",
        "Write a creative story about a robot finding its soul",
        "Explain the time complexity of this algorithm"
    ]
    
    for p in test_prompts:
        print(f"Prompt: {p}")
        route(p)
        print("-" * 20)
