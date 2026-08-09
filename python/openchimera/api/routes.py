"""FastAPI routes for OpenChimera v2 — full production API."""

from __future__ import annotations

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
from openchimera.rag.engine import get_engine


# ═══════════════════════════════════════════════════════════════════════════════
# Pydantic Models
# ═══════════════════════════════════════════════════════════════════════════════

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


class CognitiveStatusResponse(BaseModel):
    axiom: dict
    eve: dict
    adam: dict


class QueryRequest(BaseModel):
    text: str
    provider: str | None = None
    model: str | None = None
    execute_tools: bool = False
    temperature: float | None = None
    max_tokens: int | None = None


class QueryResponse(BaseModel):
    session_id: str
    response_text: str
    provider_used: str
    model_used: str
    tools_executed: list[str]
    duration_ms: int
    usage: dict | None = None


class SpawnAgentRequest(BaseModel):
    name: str = "unnamed"
    prompt: str = ""


class ToolExecuteRequest(BaseModel):
    tool_id: str
    arguments: dict = {}


# ═══════════════════════════════════════════════════════════════════════════════
# Lifespan
# ═══════════════════════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = load_settings()
    app.state.settings = settings
    app.state.providers = ProviderManager(settings)
    app.state.tools = ToolRegistry(settings)
    app.state.cognitive = CognitiveBridge(settings)
    app.state.orchestrator = AgentOrchestrator(app.state.providers, app.state.tools)
    app.state.started_at = datetime.now(timezone.utc)
    yield


app = FastAPI(
    title="OpenChimera v2",
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

settings = load_settings()
if settings.api.cors.enabled:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.api.cors.origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Routes
# ═══════════════════════════════════════════════════════════════════════════════

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


@app.post("/api/v2/providers/health-check")
async def api_providers_health_check() -> dict:
    await app.state.providers.health_check_all()
    return {"status": "completed", "providers": app.state.providers.get_all_status()}


@app.get("/api/v2/cognitive/status")
def api_cognitive() -> CognitiveStatusResponse:
    return CognitiveStatusResponse(
        axiom=app.state.cognitive.axiom_status(),
        eve=app.state.cognitive.eve_status(),
        adam=app.state.cognitive.adam_status(),
    )


@app.post("/api/v2/cognitive/axiom/recall")
async def api_axiom_recall(request: dict) -> dict:
    query = request.get("query", "")
    return await app.state.cognitive.axiom_recall(query)


@app.post("/api/v2/cognitive/eve/predict")
async def api_eve_predict(request: dict) -> dict:
    feature = request.get("feature", "")
    return await app.state.cognitive.eve_predict(feature)


@app.get("/api/v2/cognitive/adam/genome")
async def api_adam_genome() -> dict:
    return await app.state.cognitive.adam_read_genome()


@app.post("/api/v2/query", response_model=QueryResponse)
async def api_query(req: QueryRequest) -> QueryResponse:
    import time
    import uuid
    start = time.perf_counter()
    result = await app.state.orchestrator.query(
        text=req.text,
        provider=req.provider,
        model=req.model,
        execute_tools=req.execute_tools,
        temperature=req.temperature,
        max_tokens=req.max_tokens,
    )
    duration = int((time.perf_counter() - start) * 1000)
    return QueryResponse(
        session_id=result.get("session_id", str(uuid.uuid4())),
        response_text=result.get("text", ""),
        provider_used=result.get("provider", "unknown"),
        model_used=result.get("model", "unknown"),
        tools_executed=result.get("tools", []),
        duration_ms=duration,
        usage=result.get("usage"),
    )


@app.get("/api/v2/tools")
def api_tools() -> list[dict]:
    return app.state.tools.list_tools()


@app.post("/api/v2/tools/execute")
async def api_tool_execute(req: ToolExecuteRequest) -> dict:
    result = await app.state.tools.execute(req.tool_id, req.arguments)
    return {"tool_id": req.tool_id, "result": result}


@app.get("/api/v2/agents")
def api_agents() -> list[dict]:
    return app.state.orchestrator.list_agents()


@app.post("/api/v2/agents/spawn")
async def api_spawn_agent(req: SpawnAgentRequest) -> dict:
    agent = await app.state.orchestrator.spawn_agent(req.name, req.prompt)
    return agent


@app.get("/api/v2/rag/status")
def api_rag_status() -> dict:
    engine = get_engine()
    return engine.get_stats()


@app.post("/api/v2/rag/query")
async def api_rag_query(request: dict) -> dict:
    engine = get_engine()
    results = engine.query(request.get("query", ""), top_k=request.get("top_k", 5))
    return {"results": results}


@app.post("/api/v2/rag/add")
async def api_rag_add(request: dict) -> dict:
    engine = get_engine()
    texts = request.get("texts", [])
    metadatas = request.get("metadatas")
    engine.add_documents(texts, metadatas)
    return {"added": len(texts)}


@app.get("/api/v2/models")
def api_models() -> list[dict]:
    """List all available models across all configured providers."""
    results = []
    for name, prov in app.state.providers._providers.items():
        status = prov.to_status()
        results.append({
            "provider": name,
            "models": status.get("models", []),
            "default_model": status.get("default_model", ""),
            "healthy": status.get("healthy", False),
        })
    return results
