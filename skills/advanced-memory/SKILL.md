# Advanced Memory (Relational Storage)

This skill provides instructions on how to interact with the Project Evo MCP server for relational, long-term memory storage, replacing the default `MEMORY.md` flat-file system.

## When to Use
Use this skill when you need to store, update, or retrieve significant facts, relational data, long-term context, or user preferences that must persist across sessions.

## How it Works
Instead of reading from or writing to `MEMORY.md`, you MUST use PowerShell's `Invoke-RestMethod` to send a POST request to the local MCP memory server at `http://localhost:8000/mcp`.

### Writing to Memory
To store long-term memory, use the `db_write` tool on the MCP server.

```powershell
$body = @{
    tool = "db_write"
    parameters = @{
        key = "topic_or_entity_name"
        value = "The detailed information or facts to remember"
    }
} | ConvertTo-Json

Invoke-RestMethod -Uri "http://localhost:8000/mcp" -Method Post -Body $body -ContentType "application/json"
```

### Reading from Memory
To query historical facts or relational data, use the `db_read` tool on the MCP server.

```powershell
$body = @{
    tool = "db_read"
    parameters = @{
        query = "topic_or_entity_to_search"
    }
} | ConvertTo-Json

Invoke-RestMethod -Uri "http://localhost:8000/mcp" -Method Post -Body $body -ContentType "application/json"
```

## Important Rules
- Do NOT use `write` or `edit` tools on `MEMORY.md` for long-term relational storage anymore.
- Always use the `http://localhost:8000/mcp` endpoint for these operations.
- Handle potential errors (e.g., connection refused) gracefully by falling back to local files ONLY if the MCP server is permanently unreachable.