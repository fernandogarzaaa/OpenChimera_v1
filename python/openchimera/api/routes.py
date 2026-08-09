"""FastAPI routes for OpenChimera v2."""

from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from openchimera.config import load_settings
from openchimera.providers.manager import ProviderManager
from openchimera.tools.registry import ToolRegistry
from openchimera.cognitive.bridge import CognitiveBridge
from openchimera.agent import AgentOrchestrator


class StatusResponse(BaseModel):
    version: str
    uptime_seconds: int
    state: str
    providers_online: int
    providers_total: int
    active_agents: int
    queued_tasks: int
    memory_used_mb: int
    cpu_percent: float


class ProviderListResponse(BaseModel):
    providers: list[dict]


class CognitiveStatusResponse(BaseModel):
    axiom: dict
    eve: dict
    adam: dict


class QueryRequest(BaseModel):
    text: str
    provider: str | None = None
    model: str | None = None
    execute_tools: bool = False


class QueryResponse(BaseModel):
    session_id: str
    response_text: str
    provider_used: str
    model_used: str
    tools_executed: list[str]
    duration_ms: int


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = load_settings()
    app.state.settings = settings
    app.state.providers = ProviderManager(settings)
    app.state.tools = ToolRegistry()
    app.state.cognitive = CognitiveBridge(settings)
    app.state.orchestrator = AgentOrchestrator(app.state.providers, app.state.tools)
    app.state.started_at = datetime.now(timezone.utc)
    yield


app = FastAPI(title="OpenChimera v2", version="2.0.0", lifespan=lifespan)

settings = load_settings()
if settings.api.cors.enabled:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.api.cors.origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "version": "2.0.0"}


@app.get("/api/v2/status", response_model=StatusResponse)
def api_status() -> StatusResponse:
    import psutil
    proc = psutil.Process()
    uptime = int((datetime.now(timezone.utc) - app.state.started_at).total_seconds())
    providers = app.state.providers.get_all_status()
    online = sum(1 for p in providers if p.get("healthy"))
    agents = app.state.orchestrator.list_agents()
    return StatusResponse(
        version="2.0.0",
        uptime_seconds=uptime,
        state="online",
        providers_online=online,
        providers_total=len(providers),
        active_agents=len([a for a in agents if a.get("status") == "running"]),
        queued_tasks=len([a for a in agents if a.get("status") == "queued"]),
        memory_used_mb=proc.memory_info().rss // (1024 * 1024),
        cpu_percent=proc.cpu_percent(),
    )


@app.get("/api/v2/providers")
def api_providers() -> list[dict]:
    return app.state.providers.get_all_status()


@app.get("/api/v2/cognitive/status")
def api_cognitive() -> CognitiveStatusResponse:
    return CognitiveStatusResponse(
        axiom=app.state.cognitive.axiom_status(),
        eve=app.state.cognitive.eve_status(),
        adam=app.state.cognitive.adam_status(),
    )


@app.post("/api/v2/query", response_model=QueryResponse)
async def api_query(req: QueryRequest) -> QueryResponse:
    import time
    start = time.perf_counter()
    result = await app.state.orchestrator.query(
        text=req.text,
        provider=req.provider,
        model=req.model,
        execute_tools=req.execute_tools,
    )
    duration = int((time.perf_counter() - start) * 1000)
    return QueryResponse(
        session_id=result.get("session_id", "unknown"),
        response_text=result.get("text", ""),
        provider_used=result.get("provider", "unknown"),
        model_used=result.get("model", "unknown"),
        tools_executed=result.get("tools", []),
        duration_ms=duration,
    )


@app.get("/api/v2/tools")
def api_tools() -> list[dict]:
    return app.state.tools.list_tools()


@app.post("/api/v2/tools/execute")
async def api_tool_execute(request: dict) -> dict:
    tool_id = request.get("tool_id")
    arguments = request.get("arguments", {})
    if not tool_id:
        raise HTTPException(status_code=400, detail="tool_id required")
    result = await app.state.tools.execute(tool_id, arguments)
    return {"tool_id": tool_id, "result": result}


@app.get("/api/v2/agents")
def api_agents() -> list[dict]:
    return app.state.orchestrator.list_agents()


@app.post("/api/v2/agents/spawn")
async def api_spawn_agent(request: dict) -> dict:
    name = request.get("name", "unnamed")
    prompt = request.get("prompt", "")
    agent = await app.state.orchestrator.spawn_agent(name, prompt)
    return agent
