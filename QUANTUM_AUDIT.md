# QUANTUM DIRECTIVE: Deep Security Audit

## Objective
Execute a comprehensive, adversarial security audit on the entire codebase located at `D:\appforge-main\appforge` and `D:\project-evo`.

## Adversarial Protocol (Debate Protocol)
Use the `DebateProtocol` logic (Coder vs. Auditor) to ensure false positives are minimized.
1. **Auditor Agent**: Scan for OWASP Top 10 vulnerabilities (SQLi, XSS, Auth bypass, Hardcoded secrets).
2. **Coder Agent**: If a vulnerability is found, the Coder *must* propose a remediation patch.
3. **Audit Loop**: The Auditor verifies the patch. If the Auditor approves, the finding is valid. If rejected, the Coder revises.

## Scope
- `D:\appforge-main\appforge` (Frontend/Backend)
- `D:\project-evo` (Swarm Logic)
- `D:\appforge-main\appforge-backend-sdk` (Core Primitives)

## Report
Output a structured report in `D:\openclaw\SECURITY_AUDIT_REPORT.md` categorized by:
- Critical Findings
- Remediation Proposals (already debated/verified)
- Residual Risk
