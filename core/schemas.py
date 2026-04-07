from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator, field_validator

from core.config import ROOT


def _is_within_root(candidate: Path, root: Path) -> bool:
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def ensure_safe_local_path(value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    candidate = Path(normalized).expanduser().resolve(strict=False)
    allowed_roots = [ROOT.resolve(), Path(tempfile.gettempdir()).resolve()]
    if not any(_is_within_root(candidate, root) for root in allowed_roots):
        raise ValueError("Path must stay within the OpenChimera workspace or the system temp directory")
    return str(candidate)


class OpenChimeraSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class OpenChimeraFlexibleSchema(BaseModel):
    model_config = ConfigDict(extra="allow", str_strip_whitespace=True)


class ErrorResponse(OpenChimeraSchema):
    error: str
    details: list[dict[str, Any]] = Field(default_factory=list)


class HealthResponse(OpenChimeraFlexibleSchema):
    status: str
    name: str | None = None
    base_url: str | None = None
    components: dict[str, Any] = Field(default_factory=dict)
    healthy_models: int | None = None
    known_models: int | None = None
    documents: int | None = None
    router: dict[str, Any] | None = None
    auth_required: bool = False


class ReadinessResponse(OpenChimeraFlexibleSchema):
    status: str
    ready: bool
    checks: dict[str, Any] = Field(default_factory=dict)
    healthy_models: int | None = None
    minimind_available: bool | None = None
    auth_required: bool = False


class QueryResponse(OpenChimeraFlexibleSchema):
    session_id: str
    query_type: str | None = None
    response: dict[str, Any]


class JobResponse(OpenChimeraFlexibleSchema):
    job_id: str | None = None
    status: str


class EmptyRequest(OpenChimeraSchema):
    pass


class ChannelHistoryQuery(OpenChimeraSchema):
    topic: str | None = None
    status: str | None = None
    limit: int = Field(default=20, ge=1, le=200)


class JobsStatusQuery(OpenChimeraSchema):
    status: str | None = None
    job_type: str | None = None
    limit: int | None = Field(default=None, ge=1, le=500)


class JobGetQuery(OpenChimeraSchema):
    job_id: str = Field(min_length=1)


class QuerySessionsQuery(OpenChimeraSchema):
    limit: int = Field(default=20, ge=1, le=200)


class ArtifactHistoryQuery(OpenChimeraSchema):
    artifact: str | None = None
    limit: int = Field(default=20, ge=1, le=200)


class ArtifactGetQuery(OpenChimeraSchema):
    artifact: str = Field(min_length=1)


class ChatCompletionRequest(OpenChimeraSchema):
    messages: list[dict[str, Any]] = Field(default_factory=list)
    model: str = "openchimera-local"
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1, le=32768)
    max_completion_tokens: int | None = Field(default=None, ge=1, le=32768)
    stream: bool = False


class EmbeddingsRequest(OpenChimeraSchema):
    input: str | list[Any]
    model: str = "openchimera-local"


class RuntimeModelsRequest(OpenChimeraSchema):
    models: list[str] | None = None


class MCPRegistrySetRequest(OpenChimeraSchema):
    id: str = Field(min_length=1)
    transport: Literal["http", "stdio"]
    name: str | None = None
    description: str | None = None
    url: HttpUrl | None = None
    command: str | None = None
    args: list[str] | None = None
    disabled: bool = False

    @model_validator(mode="after")
    def _validate_transport_requirements(self) -> "MCPRegistrySetRequest":
        if self.transport == "http" and self.url is None:
            raise ValueError("HTTP MCP connectors require a url")
        if self.transport == "stdio" and not self.command:
            raise ValueError("stdio MCP connectors require a command")
        return self


class MCPRegistryDeleteRequest(OpenChimeraSchema):
    id: str = Field(min_length=1)


class MCPProbeRequest(OpenChimeraSchema):
    id: str | None = None
    timeout_seconds: float = Field(default=3.0, gt=0.0, le=60.0)


class ProviderConfigureRequest(OpenChimeraSchema):
    enabled_provider_ids: list[str] | None = None
    preferred_cloud_provider: str | None = None
    prefer_free_models: bool | None = None


class ModelRolesConfigureRequest(OpenChimeraSchema):
    overrides: dict[str, Any] = Field(default_factory=dict)


class QueryRunRequest(OpenChimeraSchema):
    query: str = ""
    messages: list[dict[str, Any]] | None = None
    session_id: str | None = None
    permission_scope: Literal["user", "admin"] = "user"
    max_tokens: int = Field(default=512, ge=1, le=32768)
    allow_tool_planning: bool = True
    execute_tools: bool = False
    tool_requests: list[dict[str, Any]] | None = None
    allow_agent_spawn: bool = False
    spawn_job: dict[str, Any] | None = None


class ToolExecuteRequest(OpenChimeraSchema):
    tool_id: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)
    permission_scope: Literal["user", "admin"] = "user"


class AutonomyToolRunRequest(OpenChimeraFlexibleSchema):
    job_name: str = Field(min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)


class QuerySessionGetRequest(OpenChimeraSchema):
    session_id: str = Field(min_length=1)


class SessionResumeRequest(OpenChimeraSchema):
    session_id: str = Field(min_length=1)
    query: str = Field(default="", description="New query to run in the resumed session context")
    permission_scope: Literal["user", "admin"] = "user"
    max_tokens: int = Field(default=512, ge=1, le=32768)


class MemoryClearRequest(OpenChimeraFlexibleSchema):
    scope: str | None = Field(
        default=None,
        description="Memory scope to clear: 'sessions', 'tool_history', or null for all",
    )


class OnboardingApplyRequest(OpenChimeraFlexibleSchema):
    preferred_local_model: str | None = None
    preferred_cloud_provider: str | None = None
    enabled_provider_ids: list[str] | None = None
    prefer_free_models: bool | None = None
    local_model_asset_path: str | None = None
    local_model_asset_id: str | None = None
    register_local_model_path: str | None = None
    register_local_model_id: str | None = None
    runtime_roots: dict[str, str] | None = None
    api_auth: dict[str, Any] | None = None
    provider_credentials: dict[str, dict[str, str]] | None = None
    channel_subscription: dict[str, Any] | None = None
    preferred_channel_id: str | None = None


class AegisRunRequest(OpenChimeraSchema):
    target_project: str | None = None
    preview: bool = True


class AscensionDeliberateRequest(OpenChimeraSchema):
    prompt: str = Field(min_length=1)
    perspectives: list[str] | None = None
    max_tokens: int = Field(default=256, ge=1, le=8192)


class AutonomyRunRequest(OpenChimeraFlexibleSchema):
    job: str = Field(min_length=1)


class PreviewRepairRequest(OpenChimeraSchema):
    target_project: str | None = None
    enqueue: bool = False
    max_attempts: int = Field(default=3, ge=1, le=20)


class OperatorDigestDispatchRequest(OpenChimeraSchema):
    enqueue: bool = False
    max_attempts: int = Field(default=3, ge=1, le=20)
    history_limit: int | None = Field(default=None, ge=1, le=500)
    dispatch_topic: str | None = None


class MiniMindDatasetBuildRequest(OpenChimeraSchema):
    force: bool = True


class MiniMindTrainingStartRequest(OpenChimeraSchema):
    mode: str = "reason_sft"
    force_dataset: bool = False


class MiniMindTrainingStopRequest(OpenChimeraSchema):
    job_id: str = Field(min_length=1)


class ProviderCredentialSetRequest(OpenChimeraSchema):
    provider_id: str = Field(min_length=1)
    key: str = Field(min_length=1)
    value: str = Field(min_length=1)


class ProviderCredentialDeleteRequest(OpenChimeraSchema):
    provider_id: str = Field(min_length=1)
    key: str = Field(min_length=1)


class ChannelSubscriptionPayload(OpenChimeraFlexibleSchema):
    id: str | None = None
    channel: str | None = None
    endpoint: str | None = None
    file_path: str | None = None
    bot_token: str | None = None
    chat_id: str | None = None
    topics: list[str] | None = None
    enabled: bool | None = None

    @field_validator("file_path")
    @classmethod
    def _validate_file_path(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return value
        return ensure_safe_local_path(value)


class ChannelSubscriptionDeleteRequest(OpenChimeraSchema):
    subscription_id: str = Field(min_length=1)


class ChannelSubscriptionValidateRequest(OpenChimeraSchema):
    subscription_id: str = ""
    subscription: ChannelSubscriptionPayload | None = None


class ChannelDispatchRequest(OpenChimeraSchema):
    topic: str = Field(min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)


class BrowserFetchRequest(OpenChimeraSchema):
    url: HttpUrl
    max_chars: int = Field(default=4000, ge=256, le=20000)


class BrowserSubmitFormRequest(OpenChimeraSchema):
    url: HttpUrl
    form_data: dict[str, Any] = Field(default_factory=dict)
    method: Literal["GET", "POST"] = "POST"
    max_chars: int = Field(default=4000, ge=256, le=20000)


class MediaTranscribeRequest(OpenChimeraSchema):
    audio_text: str = ""
    audio_base64: str = ""
    language: str = "en"

    @model_validator(mode="after")
    def _validate_source(self) -> "MediaTranscribeRequest":
        if not self.audio_text and not self.audio_base64:
            raise ValueError("Transcription requires audio_text or audio_base64")
        return self


class MediaSynthesizeRequest(OpenChimeraSchema):
    text: str = Field(min_length=1)
    voice: str = "openchimera-default"
    audio_format: Literal["wav"] = "wav"
    sample_rate_hz: int = Field(default=16000, ge=8000, le=96000)


class MediaUnderstandImageRequest(OpenChimeraSchema):
    prompt: str = ""
    image_path: str = ""
    image_base64: str = ""

    @field_validator("image_path")
    @classmethod
    def _validate_image_path(cls, value: str) -> str:
        return ensure_safe_local_path(value)

    @model_validator(mode="after")
    def _validate_source(self) -> "MediaUnderstandImageRequest":
        if not self.image_path and not self.image_base64:
            raise ValueError("Image understanding requires image_path or image_base64")
        return self


class MediaGenerateImageRequest(OpenChimeraSchema):
    prompt: str = Field(min_length=1)
    width: int = Field(default=1024, ge=256, le=2048)
    height: int = Field(default=1024, ge=256, le=2048)
    style: str = "schematic"


class JobCreateRequest(OpenChimeraSchema):
    job_type: str = Field(default="autonomy", min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)
    max_attempts: int = Field(default=3, ge=1, le=20)


class JobIdRequest(OpenChimeraSchema):
    job_id: str = Field(min_length=1)


class PluginMutationRequest(OpenChimeraSchema):
    plugin_id: str = Field(min_length=1)


class SubsystemInvokeRequest(OpenChimeraSchema):
    subsystem_id: str = Field(min_length=1)
    action: str = Field(default="status", min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# ChimeraLang integration schemas
# ---------------------------------------------------------------------------

class ChimeraRunRequest(OpenChimeraSchema):
    """Execute a ChimeraLang program and return structured results."""
    source: str = Field(min_length=1, description="ChimeraLang source code to execute")
    filename: str = Field(default="<chimera>", description="Filename used in error messages")


class ChimeraCheckRequest(OpenChimeraSchema):
    """Type-check a ChimeraLang program without executing it."""
    source: str = Field(min_length=1, description="ChimeraLang source code to type-check")
    filename: str = Field(default="<chimera>", description="Filename used in error messages")


class ChimeraProveRequest(OpenChimeraSchema):
    """Execute a ChimeraLang program and produce a full integrity proof."""
    source: str = Field(min_length=1, description="ChimeraLang source code to prove")
    filename: str = Field(default="<chimera>", description="Filename used in error messages")


class ChimeraScanRequest(OpenChimeraSchema):
    """Scan a plain-text LLM response through ChimeraLang's hallucination detector."""
    response_text: str = Field(min_length=1, description="LLM response text to scan")
    confidence: float = Field(default=0.8, ge=0.0, le=1.0, description="Confidence score for the response")
    trace: list[str] | None = Field(default=None, description="Optional provenance trace entries")


GET_QUERY_SCHEMAS: dict[str, type[BaseModel]] = {
    "/v1/channels/history": ChannelHistoryQuery,
    "/v1/jobs/status": JobsStatusQuery,
    "/v1/jobs/get": JobGetQuery,
    "/v1/query/sessions": QuerySessionsQuery,
    "/v1/autonomy/artifacts/history": ArtifactHistoryQuery,
    "/v1/autonomy/artifacts/get": ArtifactGetQuery,
}


POST_BODY_SCHEMAS: dict[str, type[BaseModel]] = {
    "/v1/chat/completions": ChatCompletionRequest,
    "/v1/embeddings": EmbeddingsRequest,
    "/v1/runtime/start": RuntimeModelsRequest,
    "/v1/runtime/stop": RuntimeModelsRequest,
    "/v1/model-registry/refresh": EmptyRequest,
    "/v1/mcp/registry/set": MCPRegistrySetRequest,
    "/v1/mcp/registry/delete": MCPRegistryDeleteRequest,
    "/v1/mcp/probe": MCPProbeRequest,
    "/v1/providers/configure": ProviderConfigureRequest,
    "/v1/model-roles/configure": ModelRolesConfigureRequest,
    "/v1/query/run": QueryRunRequest,
    "/v1/tools/execute": ToolExecuteRequest,
    "/v1/query/session/get": QuerySessionGetRequest,
    "/v1/sessions/resume": SessionResumeRequest,
    "/v1/memory/clear": MemoryClearRequest,
    "/v1/onboarding/apply": OnboardingApplyRequest,
    "/v1/onboarding/reset": EmptyRequest,
    "/v1/aegis/run": AegisRunRequest,
    "/v1/ascension/deliberate": AscensionDeliberateRequest,
    "/v1/autonomy/start": EmptyRequest,
    "/v1/autonomy/stop": EmptyRequest,
    "/v1/autonomy/run": AutonomyRunRequest,
    "/v1/autonomy/preview-repair": PreviewRepairRequest,
    "/v1/autonomy/operator-digest/dispatch": OperatorDigestDispatchRequest,
    "/v1/minimind/dataset/build": MiniMindDatasetBuildRequest,
    "/v1/minimind/server/start": EmptyRequest,
    "/v1/minimind/server/stop": EmptyRequest,
    "/v1/minimind/training/start": MiniMindTrainingStartRequest,
    "/v1/minimind/training/stop": MiniMindTrainingStopRequest,
    "/v1/credentials/providers/set": ProviderCredentialSetRequest,
    "/v1/credentials/providers/delete": ProviderCredentialDeleteRequest,
    "/v1/channels/subscriptions/set": ChannelSubscriptionPayload,
    "/v1/channels/subscriptions/delete": ChannelSubscriptionDeleteRequest,
    "/v1/channels/validate": ChannelSubscriptionValidateRequest,
    "/v1/channels/dispatch/daily-briefing": EmptyRequest,
    "/v1/channels/dispatch": ChannelDispatchRequest,
    "/v1/browser/fetch": BrowserFetchRequest,
    "/v1/browser/submit-form": BrowserSubmitFormRequest,
    "/v1/media/transcribe": MediaTranscribeRequest,
    "/v1/media/synthesize": MediaSynthesizeRequest,
    "/v1/media/understand-image": MediaUnderstandImageRequest,
    "/v1/media/generate-image": MediaGenerateImageRequest,
    "/v1/jobs/create": JobCreateRequest,
    "/v1/jobs/cancel": JobIdRequest,
    "/v1/jobs/replay": JobIdRequest,
    "/v1/plugins/install": PluginMutationRequest,
    "/v1/plugins/uninstall": PluginMutationRequest,
    "/v1/subsystems/invoke": SubsystemInvokeRequest,
    "/v1/chimera/run": ChimeraRunRequest,
    "/v1/chimera/check": ChimeraCheckRequest,
    "/v1/chimera/prove": ChimeraProveRequest,
    "/v1/chimera/scan": ChimeraScanRequest,
    "/mcp": OpenChimeraFlexibleSchema,
}