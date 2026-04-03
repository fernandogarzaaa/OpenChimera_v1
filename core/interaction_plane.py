from __future__ import annotations

from typing import Any


class InteractionPlane:
    def __init__(
        self,
        *,
        channels: Any,
        browser: Any,
        multimodal: Any,
        query_engine: Any,
        bus: Any,
        daily_briefing_getter: Any,
    ) -> None:
        self.channels = channels
        self.browser = browser
        self.multimodal = multimodal
        self.query_engine = query_engine
        self.bus = bus
        self.daily_briefing_getter = daily_briefing_getter

    def channel_status(self) -> dict[str, Any]:
        return self.channels.status()

    def channel_delivery_history(self, topic: str | None = None, status: str | None = None, limit: int = 20) -> dict[str, Any]:
        return self.channels.delivery_history(topic=topic, status=status, limit=limit)

    def validate_channel_subscription(self, subscription_id: str = "", subscription: dict[str, Any] | None = None) -> dict[str, Any]:
        result = self.channels.validate_subscription(subscription_id=subscription_id, subscription=subscription)
        self.bus.publish_nowait("system/channels", {"action": "validate", "result": result})
        return result

    def upsert_channel_subscription(self, subscription: dict[str, Any]) -> dict[str, Any]:
        result = self.channels.upsert_subscription(subscription)
        self.bus.publish_nowait("system/channels", {"action": "upsert", "subscription": result})
        return result

    def delete_channel_subscription(self, subscription_id: str) -> dict[str, Any]:
        result = self.channels.delete_subscription(subscription_id)
        self.bus.publish_nowait("system/channels", {"action": "delete", "subscription_id": subscription_id, "result": result})
        return result

    def dispatch_daily_briefing(self) -> dict[str, Any]:
        briefing = self.daily_briefing_getter()
        delivery = self.channels.dispatch("system/briefing/daily", briefing)
        self.bus.publish_nowait("system/briefing/daily", {"briefing": briefing, "delivery": delivery})
        return {"briefing": briefing, "delivery": delivery}

    def dispatch_channel(self, topic: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        normalized_topic = str(topic).strip()
        if not normalized_topic:
            raise ValueError("Channel dispatch requires a topic")
        message = payload if isinstance(payload, dict) else {}
        delivery = self.channels.dispatch(normalized_topic, message)
        result = {"topic": normalized_topic, "payload": message, "delivery": delivery}
        self.bus.publish_nowait("system/channels", {"action": "dispatch", "result": result})
        return result

    def browser_status(self) -> dict[str, Any]:
        return self.browser.status()

    def browser_fetch(self, url: str, max_chars: int = 4000) -> dict[str, Any]:
        result = self.browser.fetch(url=url, max_chars=max_chars)
        self.bus.publish_nowait("system/browser", {"action": "fetch", "result": result})
        return result

    def browser_submit_form(self, url: str, form_data: dict[str, Any], method: str = "POST", max_chars: int = 4000) -> dict[str, Any]:
        result = self.browser.submit_form(url=url, form_data=form_data, method=method, max_chars=max_chars)
        self.bus.publish_nowait("system/browser", {"action": "submit_form", "result": result})
        return result

    def media_status(self) -> dict[str, Any]:
        return self.multimodal.status()

    def media_transcribe(self, audio_text: str = "", audio_base64: str = "", language: str = "en") -> dict[str, Any]:
        result = self.multimodal.transcribe(audio_text=audio_text, audio_base64=audio_base64, language=language)
        self.bus.publish_nowait("system/media", {"action": "transcribe", "result": result})
        return result

    def media_synthesize(
        self,
        text: str,
        voice: str = "openchimera-default",
        audio_format: str = "wav",
        sample_rate_hz: int = 16000,
    ) -> dict[str, Any]:
        result = self.multimodal.synthesize(
            text=text,
            voice=voice,
            audio_format=audio_format,
            sample_rate_hz=sample_rate_hz,
        )
        self.bus.publish_nowait("system/media", {"action": "synthesize", "result": result})
        return result

    def media_understand_image(self, prompt: str = "", image_path: str = "", image_base64: str = "") -> dict[str, Any]:
        result = self.multimodal.understand_image(prompt=prompt, image_path=image_path, image_base64=image_base64)
        self.bus.publish_nowait("system/media", {"action": "understand_image", "result": result})
        return result

    def media_generate_image(self, prompt: str, width: int = 1024, height: int = 1024, style: str = "schematic") -> dict[str, Any]:
        result = self.multimodal.generate_image(prompt=prompt, width=width, height=height, style=style)
        self.bus.publish_nowait("system/media", {"action": "generate_image", "result": result})
        return result

    def query_status(self) -> dict[str, Any]:
        return self.query_engine.status()

    def list_query_sessions(self, limit: int = 20) -> list[dict[str, Any]]:
        return self.query_engine.list_sessions(limit=limit)

    def get_query_session(self, session_id: str) -> dict[str, Any]:
        return self.query_engine.get_session(session_id)

    def inspect_memory(self) -> dict[str, Any]:
        return self.query_engine.inspect_memory()

    def run_query(
        self,
        query: str = "",
        messages: list[dict[str, Any]] | None = None,
        session_id: str | None = None,
        permission_scope: str = "user",
        max_tokens: int = 512,
        allow_tool_planning: bool = True,
        allow_agent_spawn: bool = False,
        spawn_job: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result = self.query_engine.run_query(
            query=query,
            messages=messages,
            session_id=session_id,
            permission_scope=permission_scope,
            max_tokens=max_tokens,
            allow_tool_planning=allow_tool_planning,
            allow_agent_spawn=allow_agent_spawn,
            spawn_job=spawn_job,
        )
        self.bus.publish_nowait("system/query-engine", {"action": "run", "result": result})
        return result