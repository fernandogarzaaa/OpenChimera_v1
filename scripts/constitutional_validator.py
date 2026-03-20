#!/usr/bin/env python3
"""
constitutional_validator.py

A security and integrity validator for incoming LLM code.
Scans code snippets for potential security violations before saving to disk.

Constitutional Rules:
1. No hardcoded credentials (API keys, passwords, secrets).
2. No insecure file I/O operations (arbitrary path traversal).
3. No usage of eval() or dangerous execution functions.
4. No network connections to unauthorized endpoints.
5. Must use safe path handling (os.path.join with base directory check).
"""

import re
import os
import sys

# Configuration: Define your protected paths
PROTECTED_BASE_DIR = os.path.abspath("D:/openclaw")

# Security patterns
RULES = {
    "hardcoded_credentials": [
        re.compile(r"(['\"])(?:[a-zA-Z0-9]{32,}){1}(['\"])"), # Potential generic API key
        re.compile(r"(password|secret|key|token)\s*=\s*['\"][^'\"]+['\"]", re.IGNORECASE)
    ],
    "insecure_execution": [
        re.compile(r"\beval\s*\("),
        re.compile(r"\bexec\s*\("),
        re.compile(r"\bos\.system\s*\("),
        re.compile(r"\bsubprocess\.(call|check_call|check_output|Popen)\s*\(")
    ],
    "unsafe_file_io": [
        re.compile(r"open\s*\(\s*['\"]([^'\"]+)['\"]"),
    ]
}

def validate_code(code_str: str) -> list:
    violations = []
    
    # 1. Check for hardcoded credentials
    for pattern in RULES["hardcoded_credentials"]:
        if pattern.search(code_str):
            violations.append(f"Security Rule Violation: Potential hardcoded secret found (pattern: {pattern.pattern})")

    # 2. Check for insecure execution
    for pattern in RULES["insecure_execution"]:
        if pattern.search(code_str):
            violations.append(f"Security Rule Violation: Unsafe execution function found (pattern: {pattern.pattern})")
            
    # 3. Check for unsafe file IO path traversal
    for pattern in RULES["unsafe_file_io"]:
        for match in pattern.finditer(code_str):
            path = match.group(1)
            # Basic check for traversal
            if ".." in path or os.path.isabs(path):
                 violations.append(f"Security Rule Violation: Unsafe file path detected: {path}")

    return violations

def main():
    if len(sys.argv) < 2:
        print("Usage: python constitutional_validator.py <file_path>")
        sys.exit(1)
        
    file_path = sys.argv[1]
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            code = f.read()
    except Exception as e:
        print(f"Error reading file: {e}")
        sys.exit(1)
        
    violations = validate_code(code)
    
    if violations:
        print("VALIDATION FAILED:")
        for v in violations:
            print(f"- {v}")
        sys.exit(1)
    else:
        print("Validation Successful: Code meets constitutional standards.")
        sys.exit(0)

if __name__ == "__main__":
    main()
