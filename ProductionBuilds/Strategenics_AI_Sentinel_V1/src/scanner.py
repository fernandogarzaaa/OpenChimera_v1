import json
import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.jira_reporter import AtlassianJiraIntegration
from src.aws_reporter import AWSSecurityHubIntegration

class SentinelAuditor:
    def __init__(self, manifest_path):
        with open(manifest_path, 'r') as f:
            self.manifest = json.load(f)
        
        # Initialize Enterprise Integrations
        self.jira = AtlassianJiraIntegration("strategenics", "user@example.com", "API_TOKEN", "GRC")
        self.aws_hub = AWSSecurityHubIntegration(region="ap-southeast-2")
            
    def scan(self, directory):
        print(f"[*] Quantum Engine: Initializing AI-GRC Audit in {directory}...")
        results = []
        for root, _, files in os.walk(directory):
            for file in files:
                if file.endswith(('.py', '.js', '.ts', '.md', '.json')):
                    findings = self._scan_file(os.path.join(root, file))
                    for finding in findings:
                        results.append(finding)
                        self._dispatch_finding(finding)
        
        print(f"[*] Audit Complete. {len(results)} vulnerabilities routed to AWS and Atlassian.")
        return results
    
    def _scan_file(self, file_path):
        findings = []
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                # Heuristic AI/PII scanning logic
                if "api_key" in content.lower() or "secret" in content.lower():
                    findings.append({"file": file_path, "type": "PII_LEAK_DETECTION", "severity": "CRITICAL"})
        except Exception:
            pass
        return findings

    def _dispatch_finding(self, finding):
        # Dual-routing logic (Atlassian + AWS)
        self.jira.create_incident(finding)
        self.aws_hub.report_finding(finding)

if __name__ == "__main__":
    auditor = SentinelAuditor("Audit_Manifest.json")
    results = auditor.scan("./src")
