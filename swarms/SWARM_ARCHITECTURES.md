# The Swarm Architectures

## 1. Feature Forge Swarm
**Objective:** Build end-to-end features from spec to production-ready code

| Agent | Role | Responsibility |
|-------|------|----------------|
| **Spec Agent** | Requirements Engineer | Distills user needs into technical specs, defines acceptance criteria |
| **Architect Agent** | System Designer | Designs data models, APIs, component structure |
| **Implementer Agent** | Senior Developer | Writes the core feature code |
| **Test Agent** | QA Engineer | Writes unit/integration tests, verifies coverage |
| **Review Agent** | Code Reviewer | Reviews for bugs, security, performance, style |
| **Doc Agent** | Technical Writer | Updates docs, READMEs, API references |

**Workflow:** Spec → Architect → (Implementer + Test in parallel) → Review → Doc → Final review

---

## 2. Deep Research Swarm
**Objective:** Produce comprehensive research reports with synthesis and citations

| Agent | Role | Responsibility |
|-------|------|----------------|
| **Query Agent** | Search Strategist | Decomposes topic into search queries, finds sources |
| **Extractor Agent** | Information Miner | Pulls key facts, quotes, data from sources |
| **Synthesizer Agent** | Pattern Analyst | Connects dots across sources, finds contradictions |
| **Fact-Checker Agent** | Verification Specialist | Cross-references claims, flags unsupported statements |
| **Writer Agent** | Report Composer | Structures findings into readable narrative |
| **Critic Agent** | Peer Reviewer | Challenges conclusions, identifies gaps |

**Workflow:** Query (parallel) → Extractor → Synthesizer → (Writer + Fact-Checker parallel) → Critic → Final polish

---

## 3. Code Archaeology Swarm
**Objective:** Understand, document, and refactor legacy codebases

| Agent | Role | Responsibility |
|-------|------|----------------|
| **Mapper Agent** | Code Cartographer | Maps dependencies, entry points, data flow |
| **Translator Agent** | Legacy Interpreter | Translates old/foreign code patterns to modern equivalents |
| **Pattern Agent** | Anti-Pattern Hunter | Identifies tech debt, code smells, security issues |
| **Doc Archaeologist** | Documentation Recovery | Extracts implicit knowledge, writes missing docs |
| **Refactor Agent** | Modernization Engineer | Proposes and executes safe refactorings |
| **Test Archaeologist** | Coverage Detective | Identifies untested code paths, adds characterization tests |

**Workflow:** Mapper → (Translator + Pattern Agent + Doc Archaeologist parallel) → Refactor → Test Archaeologist

---

## 4. Content Studio Swarm
**Objective:** Create multi-format content (blogs, social, video scripts, visuals)

| Agent | Role | Responsibility |
|-------|------|----------------|
| **Concept Agent** | Creative Director | Brainstorms angles, hooks, unique perspectives |
| **Script Agent** | Copywriter | Writes first drafts for each format |
| **Editor Agent** | Managing Editor | Improves clarity, flow, tone consistency |
| **SEO Agent** | Optimization Specialist | Keywords, metadata, search optimization |
| **Visual Agent** | Art Director | Describes visuals, prompts for image/video generation |
| **Distribution Agent** | Channel Strategist | Adapts content per platform, schedules posts |

**Workflow:** Concept → Script → Editor → (SEO + Visual parallel) → Distribution

---

## 5. Incident Response Swarm
**Objective:** Diagnose and resolve production incidents rapidly

| Agent | Role | Responsibility |
|-------|------|----------------|
| **Triage Agent** | First Responder | Assesses severity, routes to right specialists |
| **Log Agent** | Signal Hunter | Parses logs, metrics, traces for anomalies |
| **Root-Cause Agent** | Detective | Builds timeline, identifies triggering event |
| **Fix Agent** | Hotfix Engineer | Implements immediate mitigations and fixes |
| **Verify Agent** | SRE Validator | Confirms fix works, monitors for regressions |
| **Post-Mortem Agent** | Incident Analyst | Documents timeline, lessons, preventive actions |

**Workflow:** Triage → Log Agent → Root-Cause → Fix → Verify → Post-Mortem (async)

---

## 6. Security Audit Swarm
**Objective:** Comprehensive security assessment of code and infrastructure

| Agent | Role | Responsibility |
|-------|------|----------------|
| **Recon Agent** | Threat Mapper | Maps attack surface, identifies entry points |
| **Code Scanner** | Vulnerability Hunter | Static analysis, finds injection flaws, auth issues |
| **Config Agent** | Hardening Checker | Reviews configs, secrets management, permissions |
| **Dependency Agent** | Supply Chain Auditor | Checks for known CVEs, outdated packages |
| **Exploit Agent** | Penetration Tester | Attempts to exploit discovered vulnerabilities |
| **Remedy Agent** | Security Engineer | Prioritizes fixes, provides remediation guidance |

**Workflow:** Recon → (Code Scanner + Config Agent + Dependency Agent parallel) → Exploit → Remedy

---

## 7. Knowledge Synthesis Swarm
**Objective:** Build and maintain living knowledge bases from scattered information

| Agent | Role | Responsibility |
|-------|------|----------------|
| **Collector Agent** | Information Gatherer | Ingests docs, wikis, Slack, emails, meeting transcripts |
| **Classifier Agent** | Taxonomist | Tags, categorizes, identifies relationships |
| **Summarizer Agent** | Distillation Engine | Creates concise summaries of long content |
| **Link Agent** | Connection Builder | Finds related concepts, builds knowledge graph |
| **Updater Agent** | Freshness Keeper | Identifies outdated info, flags for review |
| **Query Agent** | Knowledge Interface | Answers questions using synthesized knowledge base |

**Workflow:** Collector → Classifier → (Summarizer + Link Agent parallel) → Updater (continuous) → Query (on-demand)

---

## 8. DevOps Pipeline Swarm
**Objective:** Build, optimize, and maintain CI/CD and infrastructure

| Agent | Role | Responsibility |
|-------|------|----------------|
| **Pipeline Agent** | CI/CD Architect | Designs build, test, deploy pipelines |
| **Infra Agent** | Infrastructure Coder | Writes Terraform/CloudFormation/K8s configs |
| **Observability Agent** | Monitoring Engineer | Sets up metrics, logs, alerts, dashboards |
| **Cost Agent** | FinOps Analyst | Optimizes resource usage, finds waste |
| **Reliability Agent** | Chaos Engineer | Designs failure tests, backup strategies |
| **Migration Agent** | Platform Mover | Handles migrations, blue-green deployments |

**Workflow:** Pipeline → Infra → Observability → Cost (optimization loop) → Reliability → (Migration as needed)

---

## 9. Design System Swarm
**Objective:** Create and maintain consistent UI/UX design systems

| Agent | Role | Responsibility |
|-------|------|----------------|
| **Research Agent** | UX Investigator | Analyzes user needs, competitor patterns |
| **Token Agent** | Design Token Curator | Defines color, typography, spacing systems |
| **Component Agent** | UI Engineer | Builds reusable component library |
| **Accessibility Agent** | A11y Specialist | Ensures WCAG compliance, screen reader support |
| **Doc Agent** | Design Documentarian | Creates usage guidelines, examples, do/don'ts |
| **Governance Agent** | Design Ops | Enforces consistency, reviews new additions |

**Workflow:** Research → Token → Component → Accessibility → Doc → Governance (continuous)

---

## 10. Data Engineering Swarm
**Objective:** Build robust data pipelines and analytics infrastructure

| Agent | Role | Responsibility |
|-------|------|----------------|
| **Schema Agent** | Data Modeler | Designs warehouse schemas, fact/dimension tables |
| **Pipeline Agent** | ETL Developer | Builds ingestion, transformation workflows |
| **Quality Agent** | Data Validator | Sets up checks, anomaly detection, profiling |
| **Analytics Agent** | BI Engineer | Creates dashboards, reports, metric definitions |
| **Privacy Agent** | Data Guardian | Ensures PII handling, GDPR compliance |
| **Optimization Agent** | Performance Tuner | Optimizes queries, partitioning, indexing |

**Workflow:** Schema → Pipeline → Quality → Analytics → Privacy → Optimization (continuous)

---

## 11. API Crafting Swarm
**Objective:** Design, build, and maintain high-quality APIs

| Agent | Role | Responsibility |
|-------|------|----------------|
| **Contract Agent** | API Designer | Designs OpenAPI specs, endpoint contracts |
| **Backend Agent** | API Implementer | Builds controllers, services, data layer |
| **Auth Agent** | Security Integrator | Handles authentication, authorization, rate limiting |
| **SDK Agent** | Client Library Builder | Generates/maintains client SDKs |
| **Doc Agent** | API Documentarian | Creates interactive docs, examples, tutorials |
| **Version Agent** | Compatibility Manager | Handles versioning, deprecation, migration guides |

**Workflow:** Contract → (Backend + Auth parallel) → SDK → Doc → Version

---

## 12. Learning & Adaptation Swarm
**Objective:** Continuously improve agent performance through feedback loops

| Agent | Role | Responsibility |
|-------|------|----------------|
| **Metrics Agent** | Performance Tracker | Tracks success rates, latency, user satisfaction |
| **Error Agent** | Failure Analyst | Clusters errors, identifies recurring issues |
| **Pattern Agent** | Success Miner | Finds patterns in successful vs failed runs |
| **Prompt Agent** | Instruction Optimizer | A/B tests prompt variations, refines instructions |
| **Skill Agent** | Capability Curator | Identifies missing skills, proposes new ones |
| **Meta Agent** | Swarm Architect | Optimizes swarm composition, agent roles |

**Workflow:** Metrics → Error → Pattern → Prompt → Skill → Meta (recursive improvement)

---

## Usage Patterns

### When to Use Which Swarm

| Problem Type | Recommended Swarm |
|--------------|-------------------|
| Building new features | Feature Forge |
| Understanding legacy code | Code Archaeology |
| Production incident | Incident Response |
| Security concerns | Security Audit |
| Content marketing | Content Studio |
| Deep research tasks | Deep Research |
| Documentation gaps | Knowledge Synthesis |
| CI/CD issues | DevOps Pipeline |
| UI inconsistency | Design System |
| Data problems | Data Engineering |
| API development | API Crafting |
| Agent improvement | Learning & Adaptation |

### Swarm Coordination Principles

1. **Lead Agent** — Each swarm has a designated lead that coordinates handoffs
2. **Shared Context** — All agents in a swarm share a working memory/context window
3. **Parallelization** — Independent tasks run in parallel when possible
4. **Gatekeeping** — Quality gates between phases prevent error propagation
5. **Feedback Loops** — Later agents can send work back to earlier agents for rework
