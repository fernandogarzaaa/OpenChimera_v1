import sys
import os
import json

# Add the skill directory to path
skill_dir = os.path.join(os.path.dirname(__file__), 'skills', 'token-optimizer')
if skill_dir not in sys.path:
    sys.path.append(skill_dir)

try:
    from optimizer import optimize_text
except ImportError:
    # Fallback if missing
    def optimize_text(text, target_ratio=0.02):
        return text[:int(len(text) * target_ratio)] + "... [OPTIMIZER MISSING]"

def optimize_context(context_dict, token_threshold=6000):
    """
    Checks if a context dictionary exceeds a rough token threshold.
    If it does, it stringifies it, runs the 98% optimizer, and returns
    a new compressed context dictionary.
    
    1 token ~ 4 characters, so threshold 6000 tokens ~ 24000 chars.
    """
    try:
        raw_str = json.dumps(context_dict)
    except Exception:
        raw_str = str(context_dict)
        
    char_count = len(raw_str)
    char_threshold = token_threshold * 4
    
    if char_count > char_threshold:
        print(f"?? Context exceeded {token_threshold} tokens ({char_count} chars). Activating 98% Token Optimizer...")
        optimized_str = optimize_text(raw_str)
        print(f"?? Optimization complete. New size: {len(optimized_str)} chars.")
        return {
            "__optimized_context__": True,
            "structural_skeleton": optimized_str,
            "original_size": char_count,
            "new_size": len(optimized_str)
        }
    return context_dict
