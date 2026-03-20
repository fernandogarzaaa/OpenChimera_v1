import re

with open("D:/openclaw/smart_router.py", "r", encoding="utf-8") as f:
    code = f.read()

if "gemini_openrouter" not in code:
    models_addition = """
    "gemini_openrouter": {
        "provider": "openrouter",
        "model": "google/gemini-3-pro-preview",
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "api_key": "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",
        "max_tokens": 8192,
        "latency": "fast",
        "cost": 0.5,
        "strengths": ["general", "reasoning", "coding"]
    },
"""
    code = code.replace("MODELS = {", "MODELS = {" + models_addition)

if 'config["provider"] == "openrouter"' not in code:
    health_addition = """
            elif config["provider"] == "openrouter":
                headers = {"Authorization": f"Bearer {config.get('api_key', '')}"}
                resp = requests.get("https://openrouter.ai/api/v1/auth/key", headers=headers, timeout=5)
                return resp.status_code == 200
"""
    code = code.replace('elif config["provider"] == "hf":', health_addition.strip() + '\n            elif config["provider"] == "hf":', 1)

    route_addition = """
            elif config["provider"] == "openrouter":
                headers = {
                    "Authorization": f"Bearer {config['api_key']}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "http://localhost",
                    "X-Title": "CHIMERA Ultimate"
                }
                resp = requests.post(
                    config["url"],
                    headers=headers,
                    json={
                        "model": config["model"],
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": max_tokens,
                        "temperature": temperature
                    },
                    timeout=120
                )
                if resp.status_code == 200:
                    data = resp.json()
                    content = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
                    return {
                        "content": content,
                        "model": model_name,
                        "provider": "openrouter",
                        "tokens": data.get("usage", {}).get("completion_tokens", 0)
                    }
"""
    code = code.replace('elif config["provider"] == "hf":', route_addition.strip() + '\n            elif config["provider"] == "hf":')

with open("D:/openclaw/smart_router.py", "w", encoding="utf-8") as f:
    f.write(code)

print("Patched smart_router.py successfully!")
