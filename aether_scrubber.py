import os
import re

SENSITIVE_DATA = [
    "+639919465677", 
    "Inan", 
    "Fernando", 
    "garza",
    "RTX 2060",
    "D:\\openclaw",
    "D:\\appforge-main",
    "chimeraswarmbot@gmail.com",
    "CT1Ud6MvZ4NeACuF1x1EsnGpynLW6s7dWCx7C2LXJwsJ"
]

def scan_directory(directory):
    found_issues = []
    
    for root, dirs, files in os.walk(directory):
        # Skip git and cache directories
        if ".git" in root or "node_modules" in root or "__pycache__" in root or ".pytest_cache" in root:
            continue
            
        for file in files:
            if not file.endswith(('.py', '.json', '.md', '.bat', '.txt', '.js', '.jsx', '.ts', '.tsx')):
                continue
                
            filepath = os.path.join(root, file)
            try:
                with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                    
                for sensitive in SENSITIVE_DATA:
                    if sensitive.lower() in content.lower():
                        found_issues.append((filepath, sensitive))
            except Exception as e:
                pass
                
    return found_issues

if __name__ == "__main__":
    print("⚡ PROJECT AETHER: OPEN SOURCE SCRUBBER ACTIVE ⚡")
    print("Scanning AppForge Repository for hardcoded personal configurations...\n")
    
    # Simulate scanning AppForge Main
    issues = scan_directory("D:\\appforge-main")
    
    if issues:
        print(f"⚠️ FOUND {len(issues)} INSTANCES OF PERSONAL DATA IN OPEN SOURCE REPO:")
        # Group by file
        file_issues = {}
        for filepath, sensitive in issues:
            if filepath not in file_issues:
                file_issues[filepath] = set()
            file_issues[filepath].add(sensitive)
            
        for file, sens_set in list(file_issues.items())[:10]: # Limit output
            print(f"- {file}")
            print(f"  Contains: {', '.join(sens_set)}")
    else:
        print("✅ REPOSITORY IS CLEAN. No personal identifiers or hardcoded paths detected in tracked files.")
