import sys
import re
import math
from collections import Counter

def optimize_text(text, target_ratio=0.02):
    """
    Extremely aggressive text extraction algorithm.
    Targeting 98% reduction (retaining only 2%).
    """
    original_len = len(text)
    if original_len == 0:
        return ""

    target_len = max(int(original_len * target_ratio), 10)

    # 1. Structural Code Extraction (Signatures)
    # Match class definitions, function definitions, interface, const/let declarations
    structural_patterns = re.findall(r'^(?:def|class|interface|type|const|let|var|public|private|protected)\s+[\w\s\(:\,<>.=\)]+[{;:]', text, re.MULTILINE)
    
    # 2. Key Entities (Capitalized words, constants)
    entities = re.findall(r'\b[A-Z][a-zA-Z0-9_]+\b|\b[A-Z_]{3,}\b', text)
    
    # 3. Frequent significant words (Nouns/Keywords > 5 chars)
    words = [w.lower() for w in re.findall(r'\b[A-Za-z]{5,}\b', text)]
    stopwords = {'return', 'import', 'export', 'public', 'private', 'static', 'function', 'class', 'extends', 'implements', 'which', 'their', 'there', 'about'}
    filtered_words = [w for w in words if w not in stopwords]
    common_words = [w for w, c in Counter(filtered_words).most_common(20)]

    # 4. Construct the summary payload
    summary_parts = []
    if structural_patterns:
        summary_parts.append("--- [STRUCTURAL LOGIC] ---")
        summary_parts.append("\n".join(structural_patterns[:20])) # Cap it
    
    if entities:
        summary_parts.append("--- [KEY ENTITIES] ---")
        summary_parts.append(" ".join(list(set(entities))[:30]))

    if common_words:
        summary_parts.append("--- [HIGH FREQUENCY NOUNS] ---")
        summary_parts.append(" ".join(common_words))

    extracted = "\n".join(summary_parts)
    
    # If we somehow exceeded the 2% target, aggressively truncate.
    if len(extracted) > target_len:
        extracted = extracted[:target_len] + "..."

    # If it's too short (pure prose with no structures), just grab the start and end sentences.
    if len(extracted) < target_len // 2:
        sentences = re.split(r'(?<=[.!?]) +', text.replace('\n', ' '))
        if sentences:
            extracted += "\n--- [CRITICAL EDGES] ---\n" + sentences[0]
            if len(sentences) > 1:
                extracted += " ... " + sentences[-1]
            extracted = extracted[:target_len]

    return f"== 98% OPTIMIZATION ACTIVE ==\nOriginal: {original_len} chars\nOptimized: {len(extracted)} chars\n\n{extracted}"

if __name__ == "__main__":
    try:
        if len(sys.argv) > 1:
            with open(sys.argv[1], 'r', encoding='utf-8') as f:
                input_text = f.read()
        else:
            # Read from stdin
            input_text = sys.stdin.read()
            
        optimized = optimize_text(input_text)
        print(optimized)
    except Exception as e:
        print(f"Error during optimization: {e}", file=sys.stderr)
        sys.exit(1)