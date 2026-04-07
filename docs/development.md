# OpenChimera Development Guide

## Getting Started

### Prerequisites

- Python 3.10 or higher
- pip and virtualenv
- Git
- (Optional) Docker and docker-compose

### Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/yourusername/OpenChimera_v1.git
   cd OpenChimera_v1
   ```

2. **Create a virtual environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   pip install -r requirements-dev.txt  # For development
   ```

4. **Run the test suite:**
   ```bash
   python -m pytest tests/ --tb=short -q
   ```

### Running Locally

**Option 1: Direct execution**
```bash
python run.py
```

**Option 2: With configuration**
```bash
python run.py --host 0.0.0.0 --port 8000 --verbose
```

**Option 3: Docker**
```bash
docker-compose up
```

## Project Structure

```
OpenChimera_v1/
├── core/                   # Core runtime components
│   ├── kernel.py          # Kernel orchestrator
│   ├── provider.py        # OpenAI-compatible provider
│   ├── api_server.py      # HTTP API server
│   ├── bus.py             # Event bus
│   ├── memory/            # Memory subsystems
│   ├── capabilities.py    # Capability registry
│   └── ...
├── swarms/                # Multi-agent systems
│   ├── god_swarm.py       # God Swarm meta-orchestrator
│   ├── agent.py           # Individual agent
│   └── orchestrator.py    # Swarm coordination
├── config/                # Configuration files
│   ├── runtime_profile.json
│   ├── subsystems.json
│   └── god_swarm_agents.json
├── tests/                 # Test suite
├── docs/                  # Documentation
├── data/                  # Runtime data storage
├── run.py                 # Entry point
└── requirements.txt       # Dependencies
```

## Development Workflow

### 1. Make Changes

Follow the existing code style:
- Use type hints throughout
- Add docstrings for public APIs
- Follow PEP 8 conventions
- Use Pydantic for data validation

### 2. Add Tests

Create tests in `tests/test_<module>.py`:

```python
import pytest
from core.my_module import MyClass

def test_my_feature():
    obj = MyClass()
    result = obj.do_something()
    assert result["status"] == "success"
```

### 3. Run Tests

```bash
# Run all tests
python -m pytest tests/ --tb=short

# Run specific test file
python -m pytest tests/test_my_module.py -v

# Run with coverage
python -m pytest tests/ --cov=core --cov-report=html
```

### 4. Check Code Quality

```bash
# Run bandit security scan
bandit -r core/ -ll

# Check type hints (if using mypy)
mypy core/

# Format code (if using black)
black core/ tests/
```

### 5. Commit Changes

```bash
git add .
git commit -m "feat: add new capability X"
git push
```

## Adding New Features

### Adding a New Capability

1. Create `core/my_capability.py`:
   ```python
   from __future__ import annotations
   import logging
   from typing import Any

   log = logging.getLogger(__name__)

   class MyCapability:
       def __init__(self, bus: Any | None = None) -> None:
           self._bus = bus
       
       def execute(self, params: dict[str, Any]) -> dict[str, Any]:
           # Implementation
           return {"status": "success"}
   ```

2. Register in `core/capabilities.py`:
   ```python
   from core.my_capability import MyCapability
   
   capability = MyCapability(bus=self.bus)
   self.register_capability("my_capability", capability)
   ```

3. Add tests in `tests/test_my_capability.py`

4. Add API endpoint in `core/api_server.py` (if needed)

### Adding a Tool

```python
from core.tool_runtime import ToolMetadata

def my_tool_handler(args: dict) -> str:
    return f"Processed: {args.get('input', '')}"

tool = ToolMetadata(
    name="my_tool",
    description="Does something useful",
    schema={
        "type": "object",
        "properties": {
            "input": {"type": "string"}
        },
        "required": ["input"]
    },
    handler=my_tool_handler,
    tags=["utility"]
)

# Register via UnifiedToolRegistry
tool_registry.register(tool)
```

### Adding a Subsystem

1. Add entry to `config/subsystems.json`:
   ```json
   {
     "id": "my_subsystem",
     "name": "My Subsystem",
     "description": "Does X, Y, and Z",
     "category": "integration"
   }
   ```

2. Implement provider in `core/subsystems.py`:
   ```python
   def my_subsystem_provider() -> dict[str, Any]:
       return {
           "available": True,
           "running": False,
           "root": "/path/to/subsystem"
       }
   ```

3. Add to `ManagedSubsystemRegistry`:
   ```python
   providers = {
       "my_subsystem": my_subsystem_provider,
   }
   ```

### Adding an MCP Server

```python
from core.mcp_adapter import MCPAdapter

adapter = MCPAdapter(bus=bus)
adapter.register_server(
    "my-mcp-server",
    transport="http",
    url="http://localhost:9000",
    name="My MCP Server",
    description="Custom integration"
)
adapter.connect("my-mcp-server")

# List tools
tools = adapter.list_server_tools("my-mcp-server")

# Call a tool
result = adapter.call_tool(
    "my-mcp-server",
    "tool_name",
    {"arg": "value"}
)
```

## Testing Strategy

### Unit Tests
Test individual components in isolation.

```python
def test_component_behavior():
    component = MyComponent()
    result = component.method(input_data)
    assert result.is_valid()
```

### Integration Tests
Test component interactions.

```python
def test_end_to_end_flow():
    kernel = Kernel()
    kernel.boot()
    provider = kernel.get_provider()
    response = provider.chat_completion(
        messages=[{"role": "user", "content": "test"}]
    )
    assert response["choices"]
```

### Contract Tests
Ensure API compatibility.

```python
from core.schemas import HealthResponse

def test_health_response_schema():
    data = {"status": "healthy", "name": "test"}
    validated = HealthResponse.model_validate(data)
    assert validated.status == "healthy"
```

## Configuration

### Runtime Profile

Edit `config/runtime_profile.json`:

```json
{
  "provider": {
    "default_model": "openchimera-local",
    "temperature": 0.7,
    "max_tokens": 2048
  },
  "memory": {
    "semantic_capacity": 10000,
    "episodic_retention_days": 30
  }
}
```

### Environment Variables

```bash
export OPENCHIMERA_HOST=0.0.0.0
export OPENCHIMERA_PORT=8000
export OPENCHIMERA_AUTH_TOKEN=your-secret-token
export OPENCHIMERA_LOG_LEVEL=DEBUG
```

## Debugging

### Enable Verbose Logging

```bash
python run.py --verbose
```

### Use the Python Debugger

```python
import pdb; pdb.set_trace()
```

### Check Health

```bash
curl http://localhost:8000/health
```

### Inspect Memory

```bash
curl http://localhost:8000/v1/memory/show
```

## Performance Optimization

### Profile Code

```python
import cProfile
import pstats

profiler = cProfile.Profile()
profiler.enable()

# Your code here

profiler.disable()
stats = pstats.Stats(profiler)
stats.sort_stats('cumulative')
stats.print_stats(20)
```

### Memory Profiling

```python
from core.observability import ObservabilityStore

store = ObservabilityStore()
store.record_event("category", {"metric": "value"})
stats = store.aggregate_stats()
```

## Contributing

### Code Review Checklist

- [ ] Tests pass locally
- [ ] New tests added for new features
- [ ] Documentation updated
- [ ] Type hints added
- [ ] No security warnings from bandit
- [ ] Code follows existing patterns
- [ ] Commit message is descriptive

### Pull Request Template

```markdown
## Description
Brief description of changes

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Breaking change
- [ ] Documentation update

## Testing
- [ ] Unit tests added
- [ ] Integration tests added
- [ ] Manual testing performed

## Checklist
- [ ] Code follows style guidelines
- [ ] Self-review completed
- [ ] Documentation updated
- [ ] Tests pass
```

## Release Process

1. **Update version** in `__init__.py`
2. **Update CHANGELOG.md**
3. **Run full test suite**
4. **Tag release**: `git tag v1.0.0`
5. **Push tag**: `git push origin v1.0.0`
6. **Build Docker image**: `docker build -t openchimera:v1.0.0 .`
7. **Deploy**

## Troubleshooting

### Common Issues

**Issue: Import errors**
```bash
# Ensure you're in the project root and venv is activated
python -c "import core; print('OK')"
```

**Issue: Port already in use**
```bash
# Find process using port 8000
lsof -i :8000
# Kill it
kill -9 <PID>
```

**Issue: Database locked**
```bash
# Remove database file
rm data/openchimera.db
# Restart
python run.py
```

**Issue: Memory growth**
```bash
# Check memory usage
curl http://localhost:8000/v1/memory/show
# Clear working memory
# (API endpoint TBD)
```

## Resources

- [Architecture Documentation](architecture.md)
- [API Reference](api-reference.md)
- [GitHub Issues](https://github.com/yourusername/OpenChimera_v1/issues)
- [Discord Community](https://discord.gg/openchimera)

## License

See [LICENSE](../LICENSE) file.
