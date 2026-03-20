from repos import REPOS

# Score each repo based on relevance to CHIMERA + AppForge
def score_repo(repo):
    score = 0
    desc = (repo['desc'] + ' ' + repo['name']).lower()
    category = repo['category']
    
    # High value categories for our stack
    if category in ['inference', 'agents', 'framework', 'local']:
        score += 3
    if category in ['quantum', 'compression', 'cache', 'routing']:
        score += 2
    if category in ['vector', 'memory', 'swarm']:
        score += 1
    
    # Key terms
    if 'llm' in desc or 'local' in desc:
        score += 2
    if 'quantum' in desc:
        score += 3
    if 'agent' in desc or 'multi-agent' in desc or 'swarm' in desc:
        score += 3
    if 'inference' in desc or 'serving' in desc:
        score += 2
    if 'cache' in desc or 'semantic' in desc:
        score += 2
    if 'token' in desc or 'compress' in desc:
        score += 2
    if repo['lang'] == 'Python':
        score += 1
    
    # Stars bonus (popular = well-maintained)
    if repo['stars'] > 10000:
        score += 1
    if repo['stars'] > 50000:
        score += 1
        
    return score

# Sort by score
scored = [(r, score_repo(r)) for r in REPOS]
scored.sort(key=lambda x: x[1], reverse=True)

print('=' * 60)
print('TOP 50 REPOS FOR CHIMERA + APPFORGE')
print('=' * 60)
print()

for i, (repo, score) in enumerate(scored[:50], 1):
    print(f"{i:2}. [{score:2}] {repo['name']}")
    print(f"     {repo['desc']}")
    print(f"     {repo['stars']:,} stars | {repo['lang']} | {repo['category']}")
    print()
