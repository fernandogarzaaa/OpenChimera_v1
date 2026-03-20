import os
import re

PATTERNS = {
    "Anthropic/OpenAI Key": r"sk-[a-zA-Z0-9]{20,}",
    "GitHub Token": r"gh[pousr]_[a-zA-Z0-9]{36}",
    "Generic API Key": r"(?i)api_?key\s*[\"']?[:=]\s*[\"']?[a-zA-Z0-9_\-]{20,}",
    "Discord/Telegram Token": r"[a-zA-Z0-9_-]{24}\.[a-zA-Z0-9_-]{6}\.[a-zA-Z0-9_-]{27}"
}

def scan_aether_fs():
    print("Scanning AetherFS for Hardcoded Secrets...")
    found = False
    
    for root, dirs, files in os.walk(r"D:\openclaw\AetherFS"):
        for file in files:
            path = os.path.join(root, file)
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                    for name, pattern in PATTERNS.items():
                        matches = re.findall(pattern, content)
                        if matches:
                            found = True
                            print(f"\n[!] WARNING: Found {name} in: {path}")
                            print(f"    Matches: {len(matches)} instance(s)")
                            
                            # Auto-strip the secrets
                            for match in set(matches):
                                content = content.replace(match, "REDACTED_BY_AETHER_SECURITY")
                            
                            # Save scrubbed file
                            with open(path, "w", encoding="utf-8") as f_out:
                                f_out.write(content)
                            print(f"    [+] Auto-Redacted and saved.")
            except Exception as e:
                pass
                
    if not found:
        print("No hardcoded secrets detected in AetherFS.")

if __name__ == "__main__":
    scan_aether_fs()
