# Changelog

All notable changes to OpenChimera will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **DRY Improvements**: Extracted shared `ToolExecutor` helper from tool_registry.py and tool_runtime.py
- **DRY Improvements**: Extracted shared MCP entry normalization into `mcp_normalization.py`
- **Configuration Externalization**: Moved 18-subsystem list from hardcoded to `config/subsystems.json` with dynamic loading
- **Configuration Externalization**: Extracted GodSwarm agent specs to `config/god_swarm_agents.json`
- **REST Endpoints**: Added `GET /api/v1/inquiry/pending` for listing pending inquiry questions
- **REST Endpoints**: Added `POST /api/v1/inquiry/{id}/resolve` for resolving inquiry questions
- **REST Endpoints**: Added `GET /api/v1/health` using HealthMonitor for detailed health status
- **GodSwarm Enhancement**: Added uniqueness check on agent_id in GodSwarm.spawn_agent()
- **Embodied Interaction Enhancement**: Added timeout handling and retry logic for actuator commands
- **Social Cognition Enhancement**: Improved SocialCognition.evaluate() to use word embedding similarity (character n-gram cosine similarity) instead of simple keyword matching
- **Type Safety**: Improved type hints throughout ActiveInquiry, removing Optional/List/Dict imports in favor of modern union syntax
- **Documentation**: Created `docs/architecture.md` with comprehensive system architecture documentation
- **Documentation**: Created `docs/api-reference.md` with full API endpoint reference
- **Documentation**: Created `docs/development.md` with development workflow and contribution guidelines
- **Documentation**: Created `CHANGELOG.md` following Keep a Changelog format

### Changed
- **Tool Execution**: Unified tool execution patterns using shared ToolExecutor for permission gating, timing, and event emission
- **MCP Normalization**: Consolidated MCP server entry normalization logic into single reusable helper
- **Subsystem Loading**: Changed subsystem registry from hardcoded list to dynamic JSON-based configuration
- **GodSwarm Initialization**: Updated GodSwarm to load agent specs from config with fallback to defaults
- **ActiveInquiry Type Hints**: Modernized type annotations to use PEP 604 union syntax (e.g., `str | None` instead of `Optional[str]`)

### Fixed
- **Runtime Tool Execution**: Previously stubbed RuntimeToolRegistry.execute() now fully functional using ToolExecutor
- **Actuator Timeout Handling**: ActuatorInterface.issue_command() now properly handles timeouts and retries

### Security
- Pydantic schemas already use `extra="forbid"` for strict validation (verified as existing feature)
- All key models enforce input validation with cross-field validators where appropriate

## [1.0.0] - 2024-01-01 (Baseline)

### Added
- Core kernel orchestration system
- OpenAI-compatible provider API
- Multi-agent orchestration with Quantum Engine
- Memory systems (semantic, episodic, working)
- 10 AGI capabilities (ActiveInquiry, SocialCognition, EmbodiedInteraction, etc.)
- GodSwarm meta-orchestrator with 10 agents
- MCP (Model Context Protocol) adapter
- Integration with 18 recovered subsystems
- ChimeraLang bridge for logical reasoning
- Health monitoring and observability
- Rate limiting and authentication
- Structured JSON logging
- Comprehensive test suite (2449+ tests)

### Infrastructure
- Docker support with docker-compose
- Configuration management via runtime profiles
- Event bus for inter-component communication
- Capability plane for unified tool/skill/subsystem registry
- REST API with OpenAPI documentation

[Unreleased]: https://github.com/yourusername/OpenChimera_v1/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/yourusername/OpenChimera_v1/releases/tag/v1.0.0
