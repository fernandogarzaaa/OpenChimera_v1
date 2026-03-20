import urllib.request
import json
import os

STATE_FILE = r"D:\openclaw\scout_state.json"
FALLBACKS_FILE = r"D:\openclaw\chimera_free_fallbacks.json"

def categorize_model(model_id, name):
    model_str = (model_id + " " + name).lower()
    strengths = ["fallback"]
    
    # Grading by use cases
    if "code" in model_str or "coder" in model_str or "instruct" in model_str:
        strengths.append("coding")
    if "math" in model_str or "reasoning" in model_str or "think" in model_str:
        strengths.append("reasoning")
    if "vision" in model_str or "vl" in model_str:
        strengths.append("vision")
    if "chat" in model_str or "instruct" in model_str:
        strengths.append("general")
    if "roleplay" in model_str or "rp" in model_str or "story" in model_str:
        strengths.append("creative")
        
    # Ensure it at least has general if it's completely generic
    if len(strengths) == 1:
        strengths.append("general")
        
    return list(set(strengths))

def fetch_free_models():
    url = "https://openrouter.ai/api/v1/models"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'CHIMERA-ScoutBot/2.0'})
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())
    except Exception as e:
        print(f"Error fetching models: {e}")
        return []

    free_models = []
    for model in data.get("data", []):
        pricing = model.get("pricing", {})
        prompt_price = pricing.get("prompt", "-1")
        completion_price = pricing.get("completion", "-1")
        
        # Check if pricing is strictly free
        if str(prompt_price) == "0" and str(completion_price) == "0":
            strengths = categorize_model(model.get("id", ""), model.get("name", ""))
            free_models.append({
                "model_id": model.get("id"),
                "name": model.get("name"),
                "context_length": model.get("context_length", 0),
                "tier": "fallback_only",
                "priority": 99,
                "cost": 0,
                "strengths": strengths
            })
    
    # Sort by context length descending to get the most capable free models
    free_models.sort(key=lambda x: x["context_length"], reverse=True)
    return free_models

def update_state_and_save(new_models):
    # Load previous state
    state = {"consecutive_unchanged": 0, "last_model_ids": []}
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                state = json.load(f)
        except:
            pass

    # Enlarge the scope: Scout top 30 free models instead of just top 10
    top_models = new_models[:30]
    new_model_ids = sorted([m["model_id"] for m in top_models])
    
    # Check for stagnation (3 runs with identical models)
    if new_model_ids == state.get("last_model_ids", []):
        state["consecutive_unchanged"] += 1
    else:
        state["consecutive_unchanged"] = 0
        state["last_model_ids"] = new_model_ids

    # Stop scouting if identical 3 times in a row
    if state["consecutive_unchanged"] >= 3:
        print(f"No new models detected for {state['consecutive_unchanged']} consecutive runs. Halting active scout sweep to save bandwidth.")
        # Save state to maintain the counter, but don't overwrite the fallback list unnecessarily
        with open(STATE_FILE, "w") as f:
            json.dump(state, f)
        return
        
    # Save the expanded list to the fallbacks file
    os.makedirs(os.path.dirname(FALLBACKS_FILE), exist_ok=True)
    with open(FALLBACKS_FILE, 'w', encoding='utf-8') as f:
        json.dump(top_models, f, indent=2)
        
    print(f"Saved {len(top_models)} free fallback models to {FALLBACKS_FILE}. Run unchanged: {state['consecutive_unchanged']}/3")
    
    # Save updated state
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)

if __name__ == "__main__":
    print("Scouting for free LLMs on OpenRouter (v2.0 with Auto-Grading & Stagnation Stop)...")
    models = fetch_free_models()
    if models:
        update_state_and_save(models)