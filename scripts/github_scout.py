import urllib.request
import json
import os

def search_github(query, limit=3):
    url = f"https://api.github.com/search/repositories?q={query}&sort=stars&order=desc&per_page={limit}"
    req = urllib.request.Request(url, headers={'User-Agent': 'OpenClaw-Scout-Agent'})
    try:
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())
            return [{"name": item["full_name"], "stars": item["stargazers_count"], "url": item["html_url"], "desc": item["description"]} for item in data.get("items", [])]
    except Exception as e:
        return [{"error": str(e)}]

def run_scout():
    print("Initiating GitHub Scout Swarm...")
    
    targets = {
        "Algo Trading Bots": "topic:trading-bot language:python",
        "Crypto Arbitrage": "crypto arbitrage bot language:python",
        "Content Automation": "programmatic seo automation"
    }
    
    results = {}
    for category, query in targets.items():
        print(f"Scouting category: {category}...")
        results[category] = search_github(query)
        
    os.makedirs(r"D:\openclaw\abo", exist_ok=True)
    out_path = r"D:\openclaw\abo\scout_results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
        
    print(f"Scouting complete. Results saved to {out_path}")

if __name__ == "__main__":
    run_scout()
