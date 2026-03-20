import urllib.request, json

req = urllib.request.Request("https://openrouter.ai/api/v1/models")
with urllib.request.urlopen(req) as resp:
    data = json.loads(resp.read())

free_models = []
for m in data["data"]:
    pricing = m.get("pricing", {})
    if pricing.get("prompt") == "0" and pricing.get("completion") == "0":
        free_models.append(m)

for m in free_models[:40]:
    ctx = m.get("top_provider", {}).get("context_length", "?")
    mid = m["id"]
    name = m["name"][:60]
    print(f"  {mid} | ctx={ctx} | {name}")

print(f"\nTotal free models: {len(free_models)}")
