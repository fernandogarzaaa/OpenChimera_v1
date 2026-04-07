from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from core.autonomy_plane import AutonomyPlane
from core.autonomy import AutonomyScheduler
from core.aegis_service import AegisService
from core.activation_plane import ActivationPlane
from core.ascension_service import AscensionService
from core.bus import EventBus
from core.browser_service import BrowserService
from core.bootstrap_plane import BootstrapPlane
from core.capabilities import CapabilityRegistry
from core.capability_plane import CapabilityPlane
from core.channels import ChannelManager
from core.credential_store import CredentialStore
from core.database import DatabaseManager
from core.config import (
    get_aegis_mobile_root,
    get_aether_root,
    get_appforge_root,
    get_api_admin_token,
    get_api_auth_header,
    get_api_auth_token,
    get_legacy_workspace_root,
    get_observability_db_path,
    get_observability_recent_limit,
    get_provider_base_url,
    get_rag_storage_path,
    load_runtime_profile,
)
from core.control_plane import OperatorControlPlane
from core.inference_plane import InferencePlane
from core.integration_plane import IntegrationPlane
from core.interaction_plane import InteractionPlane
from core.harness_port import HarnessPortAdapter
from core.integration_audit import IntegrationAudit
from core.job_queue import PersistentJobQueue
from core.local_llm import LocalLLMManager
from core.model_registry import ModelRegistry
from core.model_roles import ModelRoleManager
from core.minimind_service import MiniMindService
from core.multimodal_service import MultimodalService
from core.observability import ObservabilityStore
from core.onboarding import OnboardingManager
from core.personality import Personality
from core.plugins import PluginManager
from core.query_engine import QueryEngine
from core.rag import Document, SimpleRAG
from core.router import OpenChimeraRouter
from core.runtime_plane import RuntimePlane
from core.service_plane import ServicePlane
from core.subsystems import ManagedSubsystemRegistry
from core.tool_runtime import RuntimeToolRegistry, RuntimeToolSpec
from core.schemas import (
    ArtifactGetQuery,
    ArtifactHistoryQuery,
    AutonomyToolRunRequest,
    BrowserFetchRequest,
    BrowserSubmitFormRequest,
    ChannelDispatchRequest,
    JobCreateRequest,
    MediaGenerateImageRequest,
    MediaSynthesizeRequest,
    MediaTranscribeRequest,
    MediaUnderstandImageRequest,
    OperatorDigestDispatchRequest,
    PreviewRepairRequest,
    SubsystemInvokeRequest,
)


LOGGER = logging.getLogger(__name__)


class OpenChimeraProvider:
    def __init__(self, bus: EventBus, personality: Personality):
        self.bus = bus
        self.personality = personality
        self.profile = load_runtime_profile()
        self.llm_manager = LocalLLMManager()
        self.rag = SimpleRAG(get_rag_storage_path())
        self.database = DatabaseManager()
        self.database.initialize()
        self.harness_port = HarnessPortAdapter()
        self.minimind = MiniMindService()
        self.autonomy = AutonomyScheduler(self.bus, self.harness_port, self.minimind, self.personality.identity)
        self.credential_store = CredentialStore(database=self.database)
        self.browser = BrowserService()
        self.multimodal = MultimodalService(credential_store=self.credential_store)
        self.channels = ChannelManager(database=self.database)
        self.capabilities = CapabilityRegistry()
        self.model_registry = ModelRegistry(credential_store=self.credential_store)
        self.model_roles = ModelRoleManager(self.model_registry)
        self.router = OpenChimeraRouter(self.llm_manager, self.model_roles)
        self.plugins = PluginManager(self.capabilities)
        self.capability_plane = CapabilityPlane(capabilities=self.capabilities, plugins=self.plugins, bus=self.bus)
        self.tool_runtime = RuntimeToolRegistry(
            capability_registry=self.capabilities,
            bus=self.bus,
            specs=[
                RuntimeToolSpec(
                    tool_id="browser.fetch",
                    name="Browser Fetch",
                    description="Fetch a web page through the browser service.",
                    schema=BrowserFetchRequest,
                    executor=lambda arguments: self.browser_fetch(
                        url=str(arguments.get("url", "")),
                        max_chars=int(arguments.get("max_chars", 4000)),
                    ),
                    requires_admin=True,
                    category="browser",
                ),
                RuntimeToolSpec(
                    tool_id="browser.submit_form",
                    name="Browser Submit Form",
                    description="Submit a form through the browser service.",
                    schema=BrowserSubmitFormRequest,
                    executor=lambda arguments: self.browser_submit_form(
                        url=str(arguments.get("url", "")),
                        form_data=dict(arguments.get("form_data", {})),
                        method=str(arguments.get("method", "POST")),
                        max_chars=int(arguments.get("max_chars", 4000)),
                    ),
                    requires_admin=True,
                    category="browser",
                ),
                RuntimeToolSpec(
                    tool_id="media.transcribe",
                    name="Media Transcribe",
                    description="Transcribe local text or audio payloads.",
                    schema=MediaTranscribeRequest,
                    executor=lambda arguments: self.media_transcribe(
                        audio_text=str(arguments.get("audio_text", "")),
                        audio_base64=str(arguments.get("audio_base64", "")),
                        language=str(arguments.get("language", "en")),
                    ),
                    requires_admin=True,
                    category="media",
                ),
                RuntimeToolSpec(
                    tool_id="media.synthesize",
                    name="Media Synthesize",
                    description="Synthesize local speech audio artifacts.",
                    schema=MediaSynthesizeRequest,
                    executor=lambda arguments: self.media_synthesize(
                        text=str(arguments.get("text", "")),
                        voice=str(arguments.get("voice", "openchimera-default")),
                        audio_format=str(arguments.get("audio_format", "wav")),
                        sample_rate_hz=int(arguments.get("sample_rate_hz", 16000)),
                    ),
                    requires_admin=True,
                    category="media",
                ),
                RuntimeToolSpec(
                    tool_id="media.understand_image",
                    name="Media Understand Image",
                    description="Analyze an image using the configured multimodal backend.",
                    schema=MediaUnderstandImageRequest,
                    executor=lambda arguments: self.media_understand_image(
                        prompt=str(arguments.get("prompt", "")),
                        image_path=str(arguments.get("image_path", "")),
                        image_base64=str(arguments.get("image_base64", "")),
                    ),
                    requires_admin=True,
                    category="media",
                ),
                RuntimeToolSpec(
                    tool_id="media.generate_image",
                    name="Media Generate Image",
                    description="Generate an image through the configured multimodal backend.",
                    schema=MediaGenerateImageRequest,
                    executor=lambda arguments: self.media_generate_image(
                        prompt=str(arguments.get("prompt", "")),
                        width=int(arguments.get("width", 1024)),
                        height=int(arguments.get("height", 1024)),
                        style=str(arguments.get("style", "schematic")),
                    ),
                    requires_admin=True,
                    category="media",
                ),
                RuntimeToolSpec(
                    tool_id="jobs.create",
                    name="Create Operator Job",
                    description="Enqueue a durable operator job.",
                    schema=JobCreateRequest,
                    executor=lambda arguments: self.create_operator_job(
                        job_type=str(arguments.get("job_type", "autonomy")),
                        payload=dict(arguments.get("payload", {})),
                        max_attempts=int(arguments.get("max_attempts", 3)),
                    ),
                    requires_admin=True,
                    category="runtime",
                ),
                RuntimeToolSpec(
                    tool_id="autonomy.run_job",
                    name="Run Autonomy Job",
                    description="Run one autonomy scheduler job immediately through the validated runtime tool registry.",
                    schema=AutonomyToolRunRequest,
                    executor=lambda arguments: self.run_autonomy_job(
                        str(arguments.get("job_name", "")),
                        payload=dict(arguments.get("payload", {})),
                    ),
                    requires_admin=True,
                    category="autonomy",
                ),
                RuntimeToolSpec(
                    tool_id="autonomy.preview_self_repair",
                    name="Preview Self Repair",
                    description="Generate or enqueue the preview-only self-repair plan through autonomy.",
                    schema=PreviewRepairRequest,
                    executor=lambda arguments: self.preview_self_repair(
                        target_project=str(arguments.get("target_project", "")).strip() or None,
                        enqueue=bool(arguments.get("enqueue", False)),
                        max_attempts=int(arguments.get("max_attempts", 3)),
                    ),
                    requires_admin=True,
                    category="autonomy",
                ),
                RuntimeToolSpec(
                    tool_id="autonomy.dispatch_operator_digest",
                    name="Dispatch Operator Digest",
                    description="Generate or enqueue the autonomy operator digest dispatch.",
                    schema=OperatorDigestDispatchRequest,
                    executor=lambda arguments: self.dispatch_operator_digest(
                        enqueue=bool(arguments.get("enqueue", False)),
                        max_attempts=int(arguments.get("max_attempts", 3)),
                        history_limit=int(arguments.get("history_limit", 0)) or None,
                        dispatch_topic=str(arguments.get("dispatch_topic", "")).strip() or None,
                    ),
                    requires_admin=True,
                    category="autonomy",
                ),
                RuntimeToolSpec(
                    tool_id="autonomy.artifact_history",
                    name="Autonomy Artifact History",
                    description="Inspect recent autonomy artifact history through the validated runtime tool registry.",
                    schema=ArtifactHistoryQuery,
                    executor=lambda arguments: self.autonomy_artifact_history(
                        artifact_name=str(arguments.get("artifact", "")).strip() or None,
                        limit=int(arguments.get("limit", 20)),
                    ),
                    category="autonomy",
                ),
                RuntimeToolSpec(
                    tool_id="autonomy.artifact_get",
                    name="Get Autonomy Artifact",
                    description="Read one autonomy artifact through the validated runtime tool registry.",
                    schema=ArtifactGetQuery,
                    executor=lambda arguments: self.autonomy_artifact(str(arguments.get("artifact", "")).strip()),
                    category="autonomy",
                ),
                RuntimeToolSpec(
                    tool_id="channels.dispatch_topic",
                    name="Dispatch Channel Topic",
                    description="Dispatch a topic payload to configured channels.",
                    schema=ChannelDispatchRequest,
                    executor=lambda arguments: self.dispatch_channel(
                        topic=str(arguments.get("topic", "")),
                        payload=dict(arguments.get("payload", {})),
                    ),
                    requires_admin=True,
                    category="channels",
                ),
                RuntimeToolSpec(
                    tool_id="channels.dispatch_daily_briefing",
                    name="Dispatch Daily Briefing",
                    description="Dispatch the current daily briefing to configured channels.",
                    schema=None,
                    executor=lambda arguments: self.dispatch_daily_briefing(),
                    requires_admin=True,
                    category="channels",
                ),
                RuntimeToolSpec(
                    tool_id="aegis.run_workflow",
                    name="Run Aegis Workflow",
                    description="Run an Aegis workflow preview or execution.",
                    schema=None,
                    executor=lambda arguments: self.run_aegis_workflow(
                        target_project=str(arguments.get("target_project", "")).strip() or None,
                        preview=bool(arguments.get("preview", True)),
                    ),
                    requires_admin=True,
                    category="subsystem",
                ),
                RuntimeToolSpec(
                    tool_id="ascension.deliberate",
                    name="Ascension Deliberation",
                    description="Run a structured deliberation through Ascension.",
                    schema=None,
                    executor=lambda arguments: self.deliberate(
                        prompt=str(arguments.get("prompt", "")),
                        perspectives=[str(item) for item in arguments.get("perspectives", [])] if isinstance(arguments.get("perspectives", []), list) else None,
                        max_tokens=int(arguments.get("max_tokens", 256)),
                    ),
                    category="reasoning",
                ),
                RuntimeToolSpec(
                    tool_id="subsystems.invoke",
                    name="Invoke Subsystem",
                    description="Invoke a managed subsystem by id and action.",
                    schema=SubsystemInvokeRequest,
                    executor=lambda arguments: self.invoke_subsystem(
                        subsystem_id=str(arguments.get("subsystem_id", "")),
                        action=str(arguments.get("action", "status")),
                        payload=dict(arguments.get("payload", {})),
                    ),
                    requires_admin=True,
                    category="subsystem",
                ),
            ],
        )
        self.job_queue = PersistentJobQueue(self.bus, executor=lambda job: self.autonomy_plane.execute_operator_job(job), database=self.database)
        self.observability = ObservabilityStore(
            recent_limit=get_observability_recent_limit(),
            persist_path=get_observability_db_path(),
        )
        self.onboarding = OnboardingManager(self.model_registry, self.credential_store, self.channels)
        self.integration_audit = IntegrationAudit()
        self.aegis = AegisService()
        self.ascension = AscensionService(self.llm_manager, self.minimind)
        self.started = False
        self.base_url = get_provider_base_url()
        self.bootstrap_plane = BootstrapPlane(
            profile_loader=load_runtime_profile,
            profile_setter=lambda profile: setattr(self, "profile", profile),
            started_getter=lambda: self.started,
            started_setter=lambda started: setattr(self, "started", started),
            llm_manager=self.llm_manager,
            job_queue=self.job_queue,
            minimind=self.minimind,
            autonomy=self.autonomy,
            aegis=self.aegis,
            ascension=self.ascension,
            bus=self.bus,
            status_getter=self.status,
            rag=self.rag,
            harness_port=self.harness_port,
            onboarding=self.onboarding,
            model_registry=self.model_registry,
        )
        self.activation_plane = ActivationPlane(
            profile_getter=lambda: self.profile,
            refresh_profile=self._reload_profile,
            credential_store=self.credential_store,
            model_registry=self.model_registry,
            model_roles=self.model_roles,
            bus=self.bus,
        )
        self.inference_plane = InferencePlane(
            personality=self.personality,
            rag=self.rag,
            llm_manager=self.llm_manager,
            minimind=self.minimind,
            router=self.router,
            model_registry=self.model_registry,
            credential_store=self.credential_store,
            observability=self.observability,
            bus=self.bus,
            profile_getter=lambda: self.profile,
        )
        self.integration_plane = IntegrationPlane(
            integration_audit=self.integration_audit,
            mcp_status_getter=self.mcp_status,
            aegis_status_getter=self.aegis.status,
            ascension_status_getter=self.ascension.status,
        )
        self.autonomy_plane = AutonomyPlane(
            profile_getter=lambda: self.profile,
            autonomy=self.autonomy,
            job_queue=self.job_queue,
            channels=self.channels,
            bus=self.bus,
            provider_activation_getter=self.provider_activation_status,
            job_queue_status_getter=self.job_queue_status,
            daily_briefing_getter=self.daily_briefing,
            create_operator_job_callback=lambda job_type, payload, max_attempts=3: self.create_operator_job(job_type, payload, max_attempts=max_attempts),
            run_autonomy_job_callback=self.run_autonomy_job,
        )
        self.subsystems = ManagedSubsystemRegistry(
            self.integration_audit,
            providers={
                "aegis_swarm": self.aegis.status,
                "ascension_engine": self.ascension.status,
                "aether_operator_stack": self.aether_operator_stack_status,
                "clawd_hybrid_rtx": self.clawd_hybrid_rtx_status,
                "qwen_agent": self.qwen_agent_status,
                "context_hub": self.context_hub_status,
                "deepagents_stack": self.deepagents_stack_status,
                "aegis_mobile_gateway": self.aegis_mobile_gateway_status,
                "minimind": self.minimind.status,
            },
            invokers={
                "aegis_swarm": self._invoke_managed_subsystem,
                "ascension_engine": self._invoke_managed_subsystem,
                "aether_operator_stack": self._invoke_managed_subsystem,
                "clawd_hybrid_rtx": self._invoke_managed_subsystem,
                "qwen_agent": self._invoke_managed_subsystem,
                "context_hub": self._invoke_managed_subsystem,
                "deepagents_stack": self._invoke_managed_subsystem,
                "aegis_mobile_gateway": self._invoke_managed_subsystem,
                "minimind": self._invoke_managed_subsystem,
            },
        )
        self.query_engine = QueryEngine(
            capability_registry=self.capabilities,
            model_roles=self.model_roles,
            tool_registry=self.tool_runtime,
            completion_callback=self.chat_completion,
            job_submitter=self.create_operator_job,
            database=self.database,
        )
        self.interaction_plane = InteractionPlane(
            channels=self.channels,
            browser=self.browser,
            multimodal=self.multimodal,
            query_engine=self.query_engine,
            bus=self.bus,
            daily_briefing_getter=lambda: self.daily_briefing(),
        )
        self.service_plane = ServicePlane(
            aegis=self.aegis,
            ascension=self.ascension,
            minimind=self.minimind,
            autonomy=self.autonomy,
            llm_manager=self.llm_manager,
            harness_port=self.harness_port,
            identity_snapshot=self.personality.identity,
            subsystems=self.subsystems,
            bus=self.bus,
            clawd_hybrid_rtx_status_getter=self.clawd_hybrid_rtx_status,
            qwen_agent_status_getter=self.qwen_agent_status,
            context_hub_status_getter=self.context_hub_status,
            deepagents_stack_status_getter=self.deepagents_stack_status,
            aether_operator_stack_status_getter=self.aether_operator_stack_status,
            aegis_mobile_gateway_status_getter=self.aegis_mobile_gateway_status,
        )
        self.control_plane = OperatorControlPlane(
            base_url_getter=lambda: self.base_url,
            profile_getter=lambda: self.profile,
            llm_manager=self.llm_manager,
            rag=self.rag,
            router=self.router,
            harness_port=self.harness_port,
            minimind=self.minimind,
            autonomy=self.autonomy,
            model_registry=self.model_registry,
            model_roles=self.model_roles,
            onboarding=self.onboarding,
            provider_activation_builder=self.activation_plane.provider_activation_status,
            fallback_learning_builder=self.activation_plane.fallback_learning_summary,
            integration_status_builder=self._build_integration_status,
            subsystem_status_builder=self.subsystems.status,
            channel_status_builder=self.channels.status,
            channel_history_builder=self.channels.delivery_history,
            bus=self.bus,
            aegis=self.aegis,
            ascension=self.ascension,
        )
        self.runtime_plane = RuntimePlane(
            base_url_getter=lambda: self.base_url,
            profile_getter=lambda: self.profile,
            llm_manager=self.llm_manager,
            rag=self.rag,
            router=self.router,
            harness_port=self.harness_port,
            minimind=self.minimind,
            autonomy=self.autonomy,
            observability=self.observability,
            health_getter=lambda: self.control_plane.health(),
            autonomy_diagnostics_getter=self.autonomy_diagnostics,
            aegis_status_getter=self.aegis_status,
            ascension_status_getter=self.ascension_status,
            model_registry_status_getter=self.model_registry_status,
            browser_status_getter=self.browser_status,
            media_status_getter=self.media_status,
            query_status_getter=self.query_status,
            model_role_status_getter=self.model_role_status,
            plugin_status_getter=self.plugin_status,
            tool_status_getter=self.tool_status,
            subsystem_status_getter=self.subsystem_status,
            onboarding_status_getter=self.onboarding_status,
            integration_status_getter=self.integration_status,
        )
        self.autonomy.bind_runtime_context(
            health=self.health,
            provider_activation=self.provider_activation_status,
            onboarding=self.onboarding_status,
            integrations=self.integration_status,
            subsystems=self.subsystem_status,
            job_queue=self.job_queue_status,
            daily_briefing=self.daily_briefing,
            channel_history=self.channel_delivery_history,
            channel_dispatch=self.dispatch_channel,
            aegis_preview=self._autonomy_aegis_preview,
        )
        self.bus.subscribe("system/autonomy/job", self._handle_autonomy_job_event)
        self._seed_knowledge()

    def start(self) -> None:
        self.bootstrap_plane.start()

    def stop(self) -> None:
        self.bootstrap_plane.stop()
        self.database.close()

    def _seed_knowledge(self) -> None:
        self.bootstrap_plane.seed_knowledge()

    def _infer_query_type(self, query: str) -> str:
        return self.inference_plane._infer_query_type(query)

    def _reload_profile(self) -> dict[str, Any]:
        return self.bootstrap_plane.reload_profile()

    def _should_force_fast_path(self, query: str, query_type: str, max_tokens: int) -> bool:
        return self.inference_plane._should_force_fast_path(query, query_type, max_tokens)

    def _should_skip_retrieval(self, query: str, query_type: str) -> bool:
        return self.inference_plane._should_skip_retrieval(query, query_type)

    def _build_context_messages(
        self,
        messages: list[dict[str, Any]],
        max_tokens: int,
        query_type: str,
    ) -> tuple[list[dict[str, str]], dict[str, Any], list[Document]]:
        return self.inference_plane._build_context_messages(messages, max_tokens, query_type)

    def _fallback_answer(self, query: str, documents: list[Document], model_error: str | None) -> str:
        return self.inference_plane._fallback_answer(query, documents, model_error)

    def _free_model_fallback_enabled(self) -> bool:
        return self.inference_plane._free_model_fallback_enabled()

    def _openrouter_api_key(self) -> str:
        return self.inference_plane._openrouter_api_key()

    def _post_json_request(
        self,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        return self.inference_plane._post_json_request(url, payload, headers=headers, timeout=timeout)

    def _call_openrouter_free_model(
        self,
        model_id: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        timeout: float,
    ) -> dict[str, Any]:
        return self.inference_plane._call_openrouter_free_model(model_id, messages, temperature, max_tokens, timeout)

    def _call_ollama_free_model(
        self,
        model_id: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        timeout: float,
    ) -> dict[str, Any]:
        return self.inference_plane._call_ollama_free_model(model_id, messages, temperature, max_tokens, timeout)

    def _extract_remote_completion_text(self, payload: dict[str, Any]) -> str:
        return self.inference_plane._extract_remote_completion_text(payload)

    def _supports_free_fallback_candidate(self, candidate: dict[str, Any]) -> bool:
        return self.inference_plane._supports_free_fallback_candidate(candidate)

    def _free_fallback_candidates(self, query_type: str, exclude: list[str] | None = None) -> list[dict[str, Any]]:
        return self.inference_plane._free_fallback_candidates(query_type, exclude=exclude)

    def _run_free_model_fallback(
        self,
        messages: list[dict[str, str]],
        query_type: str,
        temperature: float,
        max_tokens: int,
        timeout: float,
        exclude: list[str] | None = None,
    ) -> dict[str, Any]:
        return self.inference_plane._run_free_model_fallback(
            messages,
            query_type,
            temperature,
            max_tokens,
            timeout,
            exclude=exclude,
        )

    def health(self) -> dict[str, Any]:
        return self.runtime_plane.health()

    def list_models(self) -> dict[str, Any]:
        return self.runtime_plane.list_models()

    def local_runtime_status(self) -> dict[str, Any]:
        return self.runtime_plane.local_runtime_status()

    def harness_port_status(self) -> dict[str, Any]:
        return self.runtime_plane.harness_port_status()

    def minimind_status(self) -> dict[str, Any]:
        return self.runtime_plane.minimind_status()

    def autonomy_status(self) -> dict[str, Any]:
        return self.runtime_plane.autonomy_status()

    def model_registry_status(self) -> dict[str, Any]:
        return self.activation_plane.model_registry_status()

    def _fallback_learning_summary(self, registry: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.activation_plane.fallback_learning_summary(registry)

    def provider_activation_status(self) -> dict[str, Any]:
        return self.activation_plane.provider_activation_status()

    def model_role_status(self) -> dict[str, Any]:
        return self.activation_plane.model_role_status()

    def configure_model_roles(self, overrides: dict[str, Any]) -> dict[str, Any]:
        return self.activation_plane.configure_model_roles(overrides)

    def capability_status(self) -> dict[str, Any]:
        return self.capability_plane.capability_status()

    def list_capabilities(self, kind: str) -> list[dict[str, Any]]:
        return self.capability_plane.list_capabilities(kind)

    def mcp_status(self) -> dict[str, Any]:
        return self.capability_plane.mcp_status()

    def mcp_registry_status(self) -> dict[str, Any]:
        return self.capability_plane.mcp_registry_status()

    def register_mcp_connector(
        self,
        server_id: str,
        *,
        transport: str,
        name: str | None = None,
        description: str | None = None,
        url: str | None = None,
        command: str | None = None,
        args: list[str] | None = None,
        enabled: bool = True,
    ) -> dict[str, Any]:
        return self.capability_plane.register_mcp_connector(
            server_id,
            transport=transport,
            name=name,
            description=description,
            url=url,
            command=command,
            args=args,
            enabled=enabled,
        )

    def unregister_mcp_connector(self, server_id: str) -> dict[str, Any]:
        return self.capability_plane.unregister_mcp_connector(server_id)

    def probe_mcp_connectors(self, server_id: str | None = None, timeout_seconds: float = 3.0) -> dict[str, Any]:
        return self.capability_plane.probe_mcp_connectors(server_id=server_id, timeout_seconds=timeout_seconds)

    def credential_status(self) -> dict[str, Any]:
        return self.activation_plane.credential_status()

    def channel_status(self) -> dict[str, Any]:
        return self.interaction_plane.channel_status()

    def channel_delivery_history(self, topic: str | None = None, status: str | None = None, limit: int = 20) -> dict[str, Any]:
        return self.interaction_plane.channel_delivery_history(topic=topic, status=status, limit=limit)

    def validate_channel_subscription(self, subscription_id: str = "", subscription: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.interaction_plane.validate_channel_subscription(subscription_id=subscription_id, subscription=subscription)

    def plugin_status(self) -> dict[str, Any]:
        return self.capability_plane.plugin_status()

    def install_plugin(self, plugin_id: str) -> dict[str, Any]:
        return self.capability_plane.install_plugin(plugin_id)

    def uninstall_plugin(self, plugin_id: str) -> dict[str, Any]:
        return self.capability_plane.uninstall_plugin(plugin_id)

    def browser_status(self) -> dict[str, Any]:
        return self.interaction_plane.browser_status()

    def query_status(self) -> dict[str, Any]:
        return self.interaction_plane.query_status()

    def tool_status(self) -> dict[str, Any]:
        tools = self.tool_runtime.list_tools()
        return {
            "counts": {
                "total": len(tools),
                "admin_required": sum(1 for item in tools if bool(item.get("requires_admin"))),
            },
            "tools": tools,
        }

    def get_tool(self, tool_id: str) -> dict[str, Any]:
        return self.tool_runtime.get_tool(tool_id)

    def execute_tool(self, tool_id: str, arguments: dict[str, Any] | None = None, permission_scope: str = "user") -> dict[str, Any]:
        return self.tool_runtime.execute(tool_id, arguments, permission_scope=permission_scope)

    def list_query_sessions(self, limit: int = 20) -> list[dict[str, Any]]:
        return self.interaction_plane.list_query_sessions(limit=limit)

    def get_query_session(self, session_id: str) -> dict[str, Any]:
        return self.interaction_plane.get_query_session(session_id)

    def inspect_memory(self) -> dict[str, Any]:
        return self.interaction_plane.inspect_memory()

    def resume_session(
        self,
        session_id: str,
        query: str,
        permission_scope: str = "user",
        max_tokens: int = 512,
    ) -> dict[str, Any]:
        return self.interaction_plane.resume_session(
            session_id=session_id,
            query=query,
            permission_scope=permission_scope,
            max_tokens=max_tokens,
        )

    def clear_memory(self, scope: str | None = None) -> dict[str, Any]:
        return self.interaction_plane.clear_memory(scope=scope)

    def run_query(
        self,
        query: str = "",
        messages: list[dict[str, Any]] | None = None,
        session_id: str | None = None,
        permission_scope: str = "user",
        max_tokens: int = 512,
        allow_tool_planning: bool = True,
        execute_tools: bool = False,
        tool_requests: list[dict[str, Any]] | None = None,
        allow_agent_spawn: bool = False,
        spawn_job: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.interaction_plane.run_query(
            query=query,
            messages=messages,
            session_id=session_id,
            permission_scope=permission_scope,
            max_tokens=max_tokens,
            allow_tool_planning=allow_tool_planning,
            execute_tools=execute_tools,
            tool_requests=tool_requests,
            allow_agent_spawn=allow_agent_spawn,
            spawn_job=spawn_job,
        )

    def browser_fetch(self, url: str, max_chars: int = 4000) -> dict[str, Any]:
        return self.interaction_plane.browser_fetch(url=url, max_chars=max_chars)

    def browser_submit_form(self, url: str, form_data: dict[str, Any], method: str = "POST", max_chars: int = 4000) -> dict[str, Any]:
        return self.interaction_plane.browser_submit_form(url=url, form_data=form_data, method=method, max_chars=max_chars)

    def media_status(self) -> dict[str, Any]:
        return self.interaction_plane.media_status()

    def media_transcribe(self, audio_text: str = "", audio_base64: str = "", language: str = "en") -> dict[str, Any]:
        return self.interaction_plane.media_transcribe(audio_text=audio_text, audio_base64=audio_base64, language=language)

    def media_synthesize(
        self,
        text: str,
        voice: str = "openchimera-default",
        audio_format: str = "wav",
        sample_rate_hz: int = 16000,
    ) -> dict[str, Any]:
        return self.interaction_plane.media_synthesize(
            text=text,
            voice=voice,
            audio_format=audio_format,
            sample_rate_hz=sample_rate_hz,
        )

    def media_understand_image(self, prompt: str = "", image_path: str = "", image_base64: str = "") -> dict[str, Any]:
        return self.interaction_plane.media_understand_image(prompt=prompt, image_path=image_path, image_base64=image_base64)

    def media_generate_image(self, prompt: str, width: int = 1024, height: int = 1024, style: str = "schematic") -> dict[str, Any]:
        return self.interaction_plane.media_generate_image(prompt=prompt, width=width, height=height, style=style)

    def job_queue_status(
        self,
        status_filter: str | None = None,
        job_type: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        return self.job_queue.status(status_filter=status_filter, job_type=job_type, limit=limit)

    def get_operator_job(self, job_id: str) -> dict[str, Any]:
        return self.job_queue.get(job_id)

    def create_operator_job(self, job_type: str, payload: dict[str, Any], max_attempts: int = 3) -> dict[str, Any]:
        return self.autonomy_plane.create_operator_job(job_type, payload, max_attempts)

    def cancel_operator_job(self, job_id: str) -> dict[str, Any]:
        result = self.job_queue.cancel(job_id)
        self.bus.publish_nowait("system/jobs", {"action": "cancel", "result": result})
        return result

    def replay_operator_job(self, job_id: str) -> dict[str, Any]:
        result = self.job_queue.replay(job_id)
        self.bus.publish_nowait("system/jobs", {"action": "replay", "result": result})
        return result

    def upsert_channel_subscription(self, subscription: dict[str, Any]) -> dict[str, Any]:
        return self.interaction_plane.upsert_channel_subscription(subscription)

    def delete_channel_subscription(self, subscription_id: str) -> dict[str, Any]:
        return self.interaction_plane.delete_channel_subscription(subscription_id)

    def dispatch_daily_briefing(self) -> dict[str, Any]:
        return self.interaction_plane.dispatch_daily_briefing()

    def dispatch_channel(self, topic: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.interaction_plane.dispatch_channel(topic, payload)

    def autonomy_diagnostics(self) -> dict[str, Any]:
        return self.autonomy_plane.diagnostics()

    def autonomy_artifact_history(self, artifact_name: str | None = None, limit: int = 20) -> dict[str, Any]:
        return self.autonomy_plane.artifact_history(artifact_name=artifact_name, limit=limit)

    def autonomy_artifact(self, artifact_name: str) -> dict[str, Any]:
        return self.autonomy_plane.artifact(artifact_name)

    def operator_digest(self) -> dict[str, Any]:
        return self.autonomy_plane.operator_digest()

    def dispatch_operator_digest(
        self,
        enqueue: bool = False,
        max_attempts: int = 3,
        history_limit: int | None = None,
        dispatch_topic: str | None = None,
    ) -> dict[str, Any]:
        return self.autonomy_plane.dispatch_operator_digest(
            enqueue=enqueue,
            max_attempts=max_attempts,
            history_limit=history_limit,
            dispatch_topic=dispatch_topic,
        )

    def auth_status(self) -> dict[str, Any]:
        return self.activation_plane.auth_status()

    def observability_status(self) -> dict[str, Any]:
        return self.runtime_plane.observability_status()

    def set_provider_credential(self, provider_id: str, key: str, value: str) -> dict[str, Any]:
        return self.activation_plane.set_provider_credential(provider_id, key, value)

    def delete_provider_credential(self, provider_id: str, key: str) -> dict[str, Any]:
        return self.activation_plane.delete_provider_credential(provider_id, key)

    def refresh_model_registry(self) -> dict[str, Any]:
        return self.activation_plane.refresh_model_registry()

    def configure_provider_activation(
        self,
        enabled_provider_ids: list[str] | None = None,
        preferred_cloud_provider: str | None = None,
        prefer_free_models: bool | None = None,
    ) -> dict[str, Any]:
        return self.activation_plane.configure_provider_activation(
            enabled_provider_ids=enabled_provider_ids,
            preferred_cloud_provider=preferred_cloud_provider,
            prefer_free_models=prefer_free_models,
        )

    def onboarding_status(self) -> dict[str, Any]:
        return self.control_plane.onboarding_status()

    def apply_onboarding(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.bootstrap_plane.apply_onboarding(payload)

    def reset_onboarding(self) -> dict[str, Any]:
        return self.bootstrap_plane.reset_onboarding()

    def validate_onboarding_credential(self, provider_id: str, key: str, value: str) -> dict[str, Any]:
        return self.bootstrap_plane.validate_onboarding_credential(provider_id, key, value)

    def _build_integration_status(self) -> dict[str, Any]:
        return self.integration_plane.build_integration_status()

    def integration_status(self) -> dict[str, Any]:
        return self.control_plane.integration_status()

    def subsystem_status(self) -> dict[str, Any]:
        return self.control_plane.subsystem_status()

    def invoke_subsystem(self, subsystem_id: str, action: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.service_plane.invoke_subsystem(subsystem_id, action, payload)

    def aegis_status(self) -> dict[str, Any]:
        return self.service_plane.aegis_status()

    def run_aegis_workflow(
        self,
        target_project: str | None = None,
        preview: bool = True,
        preview_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.service_plane.run_aegis_workflow(target_project=target_project, preview=preview, preview_context=preview_context)

    def preview_self_repair(self, target_project: str | None = None, enqueue: bool = False, max_attempts: int = 3) -> dict[str, Any]:
        return self.autonomy_plane.preview_self_repair(target_project=target_project, enqueue=enqueue, max_attempts=max_attempts)

    def ascension_status(self) -> dict[str, Any]:
        return self.service_plane.ascension_status()

    def deliberate(self, prompt: str, perspectives: list[str] | None = None, max_tokens: int = 256) -> dict[str, Any]:
        return self.service_plane.deliberate(prompt=prompt, perspectives=perspectives, max_tokens=max_tokens)

    def daily_briefing(self) -> dict[str, Any]:
        return self.control_plane.build_daily_briefing(
            integrations=self.integration_status(),
            onboarding=self.onboarding_status(),
            autonomy=self.autonomy_status(),
            llm_status=self.llm_manager.get_status(),
            registry=self.model_registry.status(),
            recent_events=self.bus.recent_events(),
        )

    def control_plane_readiness(self, system_status: dict[str, Any] | None = None, auth_required: bool = False) -> dict[str, Any]:
        return self.control_plane.readiness_status(system_status=system_status, auth_required=auth_required)

    def control_plane_status(self, system_status: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.control_plane.status_snapshot(system_status=system_status, job_queue_status=self.job_queue_status(limit=20))

    def _handle_autonomy_job_event(self, payload: Any) -> None:
        self.autonomy_plane.handle_job_event(payload)

    def _autonomy_aegis_preview(self, target_project: str | None = None, preview_context: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.run_aegis_workflow(target_project=target_project, preview=True, preview_context=preview_context)

    def _build_autonomy_alert(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        return self.autonomy_plane.build_autonomy_alert(payload)

    def _severity_rank(self, severity: str) -> int:
        return self.autonomy_plane.severity_rank(severity)

    def _execute_operator_job(self, job: dict[str, Any]) -> dict[str, Any]:
        return self.autonomy_plane.execute_operator_job(job)

    def _classify_operator_job(self, job_type: str, payload: dict[str, Any]) -> tuple[str, str, str]:
        return self.autonomy_plane.classify_operator_job(job_type, payload)

    def _invoke_managed_subsystem(self, subsystem_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.service_plane.invoke_managed_subsystem(subsystem_id, payload)

    def build_minimind_dataset(self, force: bool = True) -> dict[str, Any]:
        return self.service_plane.build_minimind_dataset(force=force)

    def start_minimind_server(self) -> dict[str, Any]:
        return self.service_plane.start_minimind_server()

    def stop_minimind_server(self) -> dict[str, Any]:
        return self.service_plane.stop_minimind_server()

    def start_minimind_training(self, mode: str = "reason_sft", force_dataset: bool = False) -> dict[str, Any]:
        return self.service_plane.start_minimind_training(mode=mode, force_dataset=force_dataset)

    def stop_minimind_training(self, job_id: str) -> dict[str, Any]:
        return self.service_plane.stop_minimind_training(job_id)

    def start_autonomy(self) -> dict[str, Any]:
        return self.service_plane.start_autonomy()

    def qwen_agent_status(self) -> dict[str, Any]:
        return self.integration_plane.qwen_agent_status()

    def context_hub_status(self) -> dict[str, Any]:
        return self.integration_plane.context_hub_status()

    def deepagents_stack_status(self) -> dict[str, Any]:
        return self.integration_plane.deepagents_stack_status()

    def aether_operator_stack_status(self) -> dict[str, Any]:
        return self.integration_plane.aether_operator_stack_status()

    def clawd_hybrid_rtx_status(self) -> dict[str, Any]:
        return self.integration_plane.clawd_hybrid_rtx_status()

    def aegis_mobile_gateway_status(self) -> dict[str, Any]:
        return self.integration_plane.aegis_mobile_gateway_status()

    def stop_autonomy(self) -> dict[str, Any]:
        return self.service_plane.stop_autonomy()

    def run_autonomy_job(self, job_name: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.service_plane.run_autonomy_job(job_name, payload=payload)

    def start_local_models(self, models: list[str] | None = None) -> dict[str, Any]:
        return self.service_plane.start_local_models(models)

    def stop_local_models(self, models: list[str] | None = None) -> dict[str, Any]:
        return self.service_plane.stop_local_models(models)

    def embeddings(self, input_text: str, model: str = "openchimera-local") -> dict[str, Any]:
        return self.runtime_plane.embeddings(input_text=input_text, model=model)

    def chat_completion(
        self,
        messages: list[dict[str, Any]],
        model: str = "openchimera-local",
        temperature: float = 0.7,
        max_tokens: int = 1024,
        stream: bool = False,
    ) -> dict[str, Any]:
        return self.inference_plane.chat_completion(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=stream,
        )

    def status(self) -> dict[str, Any]:
        return self.runtime_plane.status()

    # ------------------------------------------------------------------
    # ChimeraLang integration
    # ------------------------------------------------------------------

    def chimera_status(self) -> dict[str, Any]:
        """Return ChimeraLang integration availability and version info."""
        from core.chimera_bridge import get_bridge
        return get_bridge().status()

    def chimera_run(self, source: str, filename: str = "<chimera>") -> dict[str, Any]:
        """Execute a ChimeraLang program and return structured results."""
        from core.chimera_bridge import get_bridge
        return get_bridge().run(source, filename=filename)

    def chimera_check(self, source: str, filename: str = "<chimera>") -> dict[str, Any]:
        """Type-check a ChimeraLang program without executing it."""
        from core.chimera_bridge import get_bridge
        return get_bridge().check(source, filename=filename)

    def chimera_prove(self, source: str, filename: str = "<chimera>") -> dict[str, Any]:
        """Execute a ChimeraLang program and produce a full integrity proof."""
        from core.chimera_bridge import get_bridge
        return get_bridge().prove(source, filename=filename)

    def chimera_scan(
        self,
        response_text: str,
        confidence: float = 0.8,
        trace: list[str] | None = None,
    ) -> dict[str, Any]:
        """Scan an LLM response through ChimeraLang's hallucination detector."""
        from core.chimera_bridge import get_bridge
        return get_bridge().scan_response(response_text, confidence=confidence, trace=trace)