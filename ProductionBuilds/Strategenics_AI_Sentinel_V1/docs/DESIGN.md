# Strategenics AI-GRC Sentinel: DESIGN.md

## Overview
An automated audit engine designed for Strategenics' GRC/Compliance clients. It scans AI implementation logic, model configurations, and data handling workflows against industry standards (ISO 27001, HIPAA).

## Core Capabilities
1. **AI Readiness Score**: Automated scoring of system compliance.
2. **PII/Leak Detection**: Scans prompt templates and code for unsecured data handling.
3. **Dual Enterprise Integration**: Native Atlassian Jira reporting and AWS Security Hub (ASFF) ingestion.

## Quantum-Optimized Architecture
- `src/scanner.py`: Core orchestrator.
- `src/jira_reporter.py`: Atlassian REST API v3 Integration.
- `src/aws_reporter.py`: AWS Security Hub (Boto3) ASFF Integrator (Target Region: ap-southeast-2).
- `Audit_Manifest.json`: Configurable compliance ruleset mapping.

## Roadmap
- Phase 1: Local codebase scanning with enterprise ticketing.
- Phase 2: Live AWS Bedrock Model Auditing (Macie / Guardrails integration).
- Phase 3: Real-time telemetry via AWS CloudWatch.
