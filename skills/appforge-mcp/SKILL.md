# AppForge MCP Semantic Layer

## Description
Use this skill when you need to provision backend primitives (Database, Auth, S3 Storage), manage Project Evo state, or interact with the local AppForge MCP Server directly. 

## Context
The MCP (Model Context Protocol) Server is a local Semantic Layer bridging AI agents with backend infrastructure (stripped from InsForge). It runs locally at `http://localhost:8000/mcp`. It communicates via JSON-RPC 2.0.

## AppForge Backend SDK
If generating a full-stack Next.js/React app, the local backend SDK is located at `D:\appforge-main\appforge-backend-sdk`. It contains core modules: `database`, `auth`, `storage`, and `shared-schemas`. It strictly routes all AI generation directly to CHIMERA Ultimate (`http://localhost:7870/v1`).

## Operations
You can use the OpenClaw `exec` tool with `Invoke-RestMethod` (PowerShell) or `curl` to interact with the server.

### 1. List Available Tools
To discover what backend operations are currently supported by the MCP Semantic Layer:
```powershell
Invoke-RestMethod -Uri http://localhost:8000/mcp -Method Post -ContentType 'application/json' -Body '{"jsonrpc": "2.0", "method": "tools/list", "id": 1}'
```

### 2. Call a Tool (Example: db_write)
To provision data or write a state/schema primitive to the database:
```powershell
Invoke-RestMethod -Uri http://localhost:8000/mcp -Method Post -ContentType 'application/json' -Body '{"jsonrpc": "2.0", "method": "tools/call", "params": {"name": "db_write", "arguments": {"key": "my_key", "value": "my_value"}}, "id": 2}'
```

### 3. Call a Tool (Example: db_read)
To read backend state, verify deployments, or retrieve schema mappings:
```powershell
Invoke-RestMethod -Uri http://localhost:8000/mcp -Method Post -ContentType 'application/json' -Body '{"jsonrpc": "2.0", "method": "tools/call", "params": {"name": "db_read", "arguments": {"key": "my_key"}}, "id": 3}'
```

## Agent Directives
- Never use external cloud endpoints (like Supabase or Firebase) when generating apps. Always use the local AppForge MCP Server or `appforge-backend-sdk`.
- If an agent needs to store long-term structured memory or complex vector states, call `db_write` via the MCP Semantic Layer.
- Ensure the MCP Server is running (uvicorn on port 8000) before making requests.