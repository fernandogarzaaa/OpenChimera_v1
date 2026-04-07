# OpenChimera API Reference

## Base URL

```
http://localhost:8000
```

When TLS is enabled:
```
https://localhost:8000
```

## Authentication

All endpoints (except `/health` and `/docs`) require authentication when auth is enabled.

```
Authorization: Bearer <your-token>
```

## Core Endpoints

### Health & Status

#### `GET /health`

Returns system health status.

**Response:**
```json
{
  "status": "healthy",
  "name": "openchimera",
  "base_url": "http://localhost:8000",
  "components": {
    "provider": true,
    "bus": true,
    "database": true
  },
  "healthy_models": 5,
  "known_models": 5,
  "documents": 42,
  "auth_required": false
}
```

#### `GET /api/v1/health`

Returns detailed health information using HealthMonitor.

**Response:**
```json
{
  "status": "healthy",
  "subsystems": [
    {
      "name": "provider",
      "status": "healthy",
      "timestamp": 1704067200.0,
      "details": {}
    }
  ],
  "timestamp": 1704067200.0
}
```

#### `GET /v1/system/readiness`

Returns readiness check for startup orchestration.

**Response:**
```json
{
  "status": "ready",
  "ready": true,
  "checks": {
    "provider_online": true,
    "generation_path": true,
    "auth": true,
    "channels": true
  }
}
```

#### `GET /v1/control-plane/status`

Returns full control plane status.

### Chat & Completions

#### `POST /v1/chat/completions`

OpenAI-compatible chat completion endpoint.

**Request:**
```json
{
  "messages": [
    {"role": "user", "content": "Hello, world!"}
  ],
  "model": "openchimera-local",
  "temperature": 0.7,
  "max_tokens": 512,
  "stream": false
}
```

**Response:**
```json
{
  "id": "chatcmpl-abc123",
  "object": "chat.completion",
  "created": 1704067200,
  "model": "openchimera-local",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "Hello! How can I help you today?"
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 10,
    "completion_tokens": 8,
    "total_tokens": 18
  }
}
```

#### `POST /v1/embeddings`

Generate embeddings for text.

**Request:**
```json
{
  "input": "The quick brown fox",
  "model": "openchimera-local"
}
```

**Response:**
```json
{
  "object": "list",
  "data": [
    {
      "object": "embedding",
      "embedding": [0.1, 0.2, ...],
      "index": 0
    }
  ],
  "model": "openchimera-local",
  "usage": {
    "prompt_tokens": 5,
    "total_tokens": 5
  }
}
```

### Models

#### `GET /v1/models`

List available models.

**Response:**
```json
{
  "object": "list",
  "data": [
    {
      "id": "openchimera-local",
      "object": "model",
      "created": 1704067200,
      "owned_by": "openchimera"
    }
  ]
}
```

### Memory & Inquiry

#### `GET /v1/inquiry/pending`

List all pending inquiry questions.

**Response:**
```json
{
  "questions": [
    {
      "question_id": "abc-123",
      "question": "Is user's preference 'dark' or 'light'?",
      "context": {
        "subject": "user",
        "predicate": "preference"
      },
      "created_at": 1704067200.0,
      "resolved": false
    }
  ]
}
```

#### `POST /v1/inquiry/{question_id}/resolve`

Resolve a pending inquiry question.

**Request:**
```json
{
  "answer": "The user prefers dark mode"
}
```

**Response:**
```json
{
  "resolved": true,
  "question_id": "abc-123"
}
```

#### `GET /v1/memory/show`

Inspect memory contents.

**Response:**
```json
{
  "semantic": {
    "triple_count": 150,
    "recent_triples": [...]
  },
  "episodic": {
    "episode_count": 42,
    "recent_episodes": [...]
  },
  "working": {
    "item_count": 5,
    "items": [...]
  }
}
```

### Subsystems

#### `GET /v1/subsystems/status`

List all integrated subsystems.

**Response:**
```json
{
  "counts": {
    "total": 18,
    "available": 12,
    "invokable": 6
  },
  "subsystems": [
    {
      "id": "aether",
      "name": "Aether",
      "description": "Managed runtime kernel bridge.",
      "available": true,
      "invokable": false
    }
  ]
}
```

#### `POST /v1/subsystems/invoke`

Invoke a subsystem action.

**Request:**
```json
{
  "subsystem_id": "aegis_swarm",
  "action": "run_workflow",
  "payload": {
    "workflow": "remediation",
    "target": "database"
  }
}
```

### MCP (Model Context Protocol)

#### `GET /v1/integrations/status`

List all MCP server registrations.

#### `POST /v1/integrations/mcp/set`

Register an MCP server.

**Request:**
```json
{
  "id": "my-server",
  "transport": "http",
  "url": "http://localhost:8080",
  "name": "My MCP Server",
  "description": "Custom MCP integration"
}
```

#### `POST /v1/integrations/mcp/delete`

Unregister an MCP server.

**Request:**
```json
{
  "id": "my-server"
}
```

### Chimera

#### `POST /v1/chimera/run`

Execute ChimeraLang code.

**Request:**
```json
{
  "source": "rule user_likes(X) :- X = chocolate.",
  "filename": "preferences.chimera"
}
```

#### `POST /v1/chimera/check`

Type-check ChimeraLang code.

#### `POST /v1/chimera/prove`

Prove a ChimeraLang goal.

#### `POST /v1/chimera/scan`

Scan an LLM response for hallucinations.

**Request:**
```json
{
  "response_text": "The Eiffel Tower is in London.",
  "confidence": 0.8
}
```

**Response:**
```json
{
  "hallucination_detected": true,
  "confidence": 0.95,
  "violations": [
    {
      "claim": "Eiffel Tower is in London",
      "actual": "Eiffel Tower is in Paris"
    }
  ]
}
```

### Autonomy

#### `GET /v1/autonomy/status`

Get autonomy subsystem status.

#### `GET /v1/autonomy/operator-digest`

Generate operator digest of pending items.

#### `POST /v1/autonomy/operator-digest/dispatch`

Send operator digest to configured channel.

#### `POST /v1/autonomy/preview-repair`

Preview repair actions without execution.

**Request:**
```json
{
  "issue": "database_connection_failed"
}
```

### Browser

#### `POST /v1/browser/fetch`

Fetch and parse a web page.

**Request:**
```json
{
  "url": "https://example.com",
  "extract_text": true
}
```

#### `POST /v1/browser/submit-form`

Submit a form on a web page.

### Media

#### `POST /v1/media/transcribe`

Transcribe audio to text.

#### `POST /v1/media/synthesize`

Synthesize text to speech.

#### `POST /v1/media/understand-image`

Analyze an image with vision model.

#### `POST /v1/media/generate-image`

Generate an image from a prompt.

### Jobs

#### `GET /v1/jobs/status`

List background jobs.

**Query Parameters:**
- `status` - Filter by status (pending, running, completed, failed)
- `job_type` - Filter by job type
- `limit` - Max results (default 50)

#### `POST /v1/jobs/create`

Create a new background job.

#### `POST /v1/jobs/cancel`

Cancel a running job.

#### `POST /v1/jobs/replay`

Replay a completed job.

### Channels

#### `GET /v1/channels/history`

Get channel message history.

**Query Parameters:**
- `topic` - Filter by topic pattern
- `status` - Filter by status
- `limit` - Max results (default 20)

#### `POST /v1/channels/dispatch`

Dispatch a message to a channel.

**Request:**
```json
{
  "channel_id": "slack",
  "topic": "alerts/critical",
  "content": "Database backup failed"
}
```

### Documentation

#### `GET /docs`

Interactive API documentation (HTML).

#### `GET /openapi.json`

OpenAPI 3.1 specification.

## Error Responses

All errors follow this format:

```json
{
  "error": "Description of the error",
  "details": [
    {
      "field": "temperature",
      "message": "Value must be between 0.0 and 2.0"
    }
  ]
}
```

**Common Status Codes:**
- `200 OK` - Success
- `400 Bad Request` - Invalid input
- `401 Unauthorized` - Missing or invalid auth token
- `403 Forbidden` - Insufficient permissions
- `404 Not Found` - Resource not found
- `422 Unprocessable Entity` - Validation failed
- `429 Too Many Requests` - Rate limit exceeded
- `503 Service Unavailable` - System not ready

## Rate Limiting

Rate limits are per-endpoint and per-identity:

- Default: 100 requests per minute
- Burst allowance: 10 requests
- Headers returned:
  - `X-RateLimit-Limit`
  - `X-RateLimit-Remaining`
  - `X-RateLimit-Reset`

## WebSocket Support

OpenChimera supports streaming responses via Server-Sent Events (SSE) for:
- Chat completions (`stream: true`)
- Real-time event subscriptions

## MCP Protocol

The `/mcp` endpoint implements the Model Context Protocol JSON-RPC 2.0 interface:

```json
{
  "jsonrpc": "2.0",
  "id": "1",
  "method": "tools/list",
  "params": {}
}
```

Supported methods:
- `initialize` - Initialize MCP connection
- `tools/list` - List available tools
- `tools/call` - Invoke a tool
- `resources/list` - List available resources
- `resources/read` - Read a resource
- `prompts/list` - List available prompts
- `prompts/get` - Get a prompt template
