import sys
import json
import requests
import concurrent.futures
from pathlib import Path

# Add the openclaw root so we can import the quantum engine
sys.path.append(str(Path(__file__).parent.parent.parent))

try:
    from quantum_consensus_v2 import quantum_consensus, entanglement_detector
except ImportError:
    print(json.dumps({"error": "Failed to import quantum_consensus_v2. Ensure OpenChimera or the configured OpenClaw root is available on PYTHONPATH."}))
    sys.exit(1)

def query_local_llm(prompt: str, sys_prompt: str = "You are a Hyper-Intelligent System.", temp: float = 0.7) -> str:
    """Helper to query the local CHIMERA Ultimate backend directly."""
    url = "http://localhost:7870/v1/chat/completions"
    payload = {
        "model": "chimera-local", # Use the local proxy/fallback model
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": prompt}
        ],
        "temperature": temp,
        "max_tokens": 1024
    }
    try:
        resp = requests.post(url, json=payload, timeout=120)
        if resp.status_code == 200:
            return resp.json()['choices'][0]['message']['content']
        else:
            return f"Error: {resp.text}"
    except Exception as e:
        return f"Error connecting to local LLM: {str(e)}"

def generate_divergent_thoughts(query: str) -> list[str]:
    """Generates 3 distinct logical approaches to the problem."""
    print("  [>] Generating 3 Divergent Quantum State Hypotheses...")
    prompt = f"Analyze this query: '{query}'. Provide exactly 3 fundamentally different, valid approaches or hypotheses to solve this. Separate each approach with '---APPROACH---'."
    response = query_local_llm(prompt, temp=0.9)
    
    approaches = [a.strip() for a in response.split("---APPROACH---") if len(a.strip()) > 10]
    
    # Ensure we have at least 2, pad if necessary
    if len(approaches) == 0:
        return ["Approach 1: Direct logical deduction.", "Approach 2: Lateral thinking and edge case analysis.", "Approach 3: Systems-level architectural review."]
    elif len(approaches) == 1:
        approaches.append("Approach 2: Inverse problem-solving (starting from the goal backward).")
        approaches.append("Approach 3: First-principles reduction.")
        
    return approaches[:3] # Keep exactly 3

def expand_thought(query: str, thought: str, index: int) -> str:
    """Expands a single hypothesis into a full reasoning chain and solution."""
    print(f"  [>] Expanding Superposition State |ψ_{index}⟩...")
    sys_prompt = "You are an analytical hyper-intelligence. Fully develop the provided approach into a comprehensive solution, showing all reasoning steps."
    prompt = f"Query: {query}\n\nApproach to take:\n{thought}\n\nDevelop a complete, rigorous solution based ONLY on this approach."
    return query_local_llm(prompt, sys_prompt, temp=0.5)

def score_expansion(expansion: str) -> float:
    """A rapid scoring function based on structural complexity and confidence markers."""
    score = 0.5
    if "therefore" in expansion.lower() or "conclusion" in expansion.lower(): score += 0.1
    if "however" in expansion.lower() or "conversely" in expansion.lower(): score += 0.1 # Nuance
    if len(expansion) > 500: score += 0.1 # Depth
    if "error" in expansion.lower() or "i am sorry" in expansion.lower(): score -= 0.4
    return min(1.0, max(0.1, score))

def main():
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    try:
        input_data = sys.stdin.read()
        if not input_data.strip():
            print(json.dumps({"error": "No input provided on stdin"}))
            return
            
        params = json.loads(input_data)
        query = params.get("query", "")
        
        if not query:
            print(json.dumps({"error": "Query parameter is missing"}))
            return
            
        print("\n" + "="*50)
        print(" --- HYPER INTELLIGENCE Q-ToT (Tree of Thoughts) --- ")
        print("="*50 + "\n")
        
        print(f"Query Input: {query}\n")
        
        # Phase 1: Superposition (Divergent Generation)
        print("[PHASE 1] Initializing Quantum Superposition (Thought Generation)...")
        hypotheses = generate_divergent_thoughts(query)
        for i, hyp in enumerate(hypotheses):
            preview = hyp.split('\n')[0][:80] + "..." if len(hyp) > 80 else hyp
            print(f"  |ψ_{i}⟩: {preview}")
            
        # Phase 2: Entanglement Analysis
        print("\n[PHASE 2] Calculating Multi-Dimensional Semantic Entanglement...")
        entanglements = entanglement_detector.detect(hypotheses)
        for ent in entanglements:
            print(f"  Fidelity: {ent['fidelity']:.4f} -> {ent['type']}")
            
        # Phase 3: Parallel Expansion
        print("\n[PHASE 3] Executing Parallel Deep Expansion...")
        expansions = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(expand_thought, query, hyp, i) for i, hyp in enumerate(hypotheses)]
            for future in concurrent.futures.as_completed(futures):
                expansions.append(future.result())
                
        # Phase 4: Quantum Collapse (Consensus Voting via Qiskit/SciPy)
        print("\n[PHASE 4] Wave Function Collapse (Quantum Consensus Voting)...")
        
        # Run the consensus vote!
        consensus_result = quantum_consensus.vote(expansions, scoring_fn=score_expansion, n_iterations=100)
        
        winner = consensus_result['winner']
        confidence = consensus_result['confidence']
        engine_used = consensus_result.get('engine', 'unknown')
        
        print(f"  Collapse complete. Engine: {engine_used.upper()}")
        print(f"  Mathematical Confidence Level: {confidence:.2%}")
        
        print("\n" + "="*50)
        print(" --- ULTIMATE TRUTH (Final Output) --- ")
        print("="*50 + "\n")
        
        print(winner)
        print("\n" + "="*50)

    except json.JSONDecodeError:
        print("[Fatal Error] Failed to parse input parameters. Valid JSON required.")
    except Exception as e:
        print(f"[Fatal Error] {str(e)}")

if __name__ == "__main__":
    main()
