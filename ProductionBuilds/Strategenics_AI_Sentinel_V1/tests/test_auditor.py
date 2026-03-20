import unittest
import os
import sys
sys.path.append(r'D:\openclaw\ProductionBuilds\Strategenics_AI_Sentinel_V1')
from src.scanner import SentinelAuditor

class TestScanner(unittest.TestCase):
    def test_pii_leak(self):
        # Create a mock file with a secret
        with open("mock_secret.py", "w") as f:
            f.write("api_key = 'super_secret_key'")
        
        auditor = SentinelAuditor(r"D:\openclaw\ProductionBuilds\Strategenics_AI_Sentinel_V1\Audit_Manifest.json")
        findings = auditor._scan_file("mock_secret.py")
        self.assertTrue(any(f['type'] == 'PII_LEAK_DETECTION' for f in findings))
        os.remove("mock_secret.py")

if __name__ == "__main__":
    unittest.main()
