from __future__ import annotations

import hmac
from dataclasses import dataclass
from http import HTTPStatus
from typing import Mapping

from core.config import get_api_admin_token, get_api_auth_header, get_api_auth_token, is_api_auth_enabled


PUBLIC_PATHS = {"/health", "/v1/system/readiness", "/openapi.json", "/docs"}
PRIVILEGED_POST_PATHS = {
    "/v1/runtime/start",
    "/v1/runtime/stop",
    "/v1/model-registry/refresh",
    "/v1/aegis/run",
    "/v1/autonomy/start",
    "/v1/autonomy/stop",
    "/v1/autonomy/run",
    "/v1/autonomy/preview-repair",
    "/v1/minimind/dataset/build",
    "/v1/minimind/server/start",
    "/v1/minimind/server/stop",
    "/v1/minimind/training/start",
    "/v1/minimind/training/stop",
    "/v1/credentials/providers/set",
    "/v1/credentials/providers/delete",
    "/v1/channels/subscriptions/set",
    "/v1/channels/subscriptions/delete",
    "/v1/channels/validate",
    "/v1/channels/dispatch/daily-briefing",
    "/v1/browser/fetch",
    "/v1/browser/submit-form",
    "/v1/media/transcribe",
    "/v1/media/synthesize",
    "/v1/media/understand-image",
    "/v1/media/generate-image",
    "/v1/jobs/create",
    "/v1/jobs/cancel",
    "/v1/jobs/replay",
    "/v1/onboarding/apply",
    "/v1/onboarding/reset",
    "/v1/providers/configure",
    "/v1/query/run",
    "/v1/model-roles/configure",
    "/v1/subsystems/invoke",
    "/v1/plugins/install",
    "/v1/plugins/uninstall",
}


@dataclass(frozen=True)
class AuthDecision:
    allowed: bool
    status: HTTPStatus
    error: str | None
    auth_required: bool
    required_permission: str | None
    granted_permission: str | None


class RequestAuthorizer:
    def __init__(self):
        self.auth_enabled = is_api_auth_enabled()
        self.auth_header = get_api_auth_header()
        self.user_token = get_api_auth_token().strip()
        self.admin_token = get_api_admin_token().strip()

    def is_public_path(self, path: str) -> bool:
        return path in PUBLIC_PATHS

    def required_permission(self, method: str, path: str) -> str | None:
        if self.is_public_path(path):
            return None
        if not self.auth_enabled:
            return None
        if method.upper() == "POST" and path in PRIVILEGED_POST_PATHS:
            return "admin"
        return "user"

    def authorize(self, method: str, path: str, headers: Mapping[str, str]) -> AuthDecision:
        required_permission = self.required_permission(method, path)
        if required_permission is None:
            return AuthDecision(True, HTTPStatus.OK, None, self.auth_enabled, None, None)

        supplied = headers.get(self.auth_header, "")
        if supplied.startswith("Bearer "):
            supplied = supplied[7:]
        supplied = supplied.strip()
        if not supplied:
            return AuthDecision(False, HTTPStatus.UNAUTHORIZED, "Unauthorized", True, required_permission, None)

        granted_permission = self._permission_for_token(supplied)
        if granted_permission is None:
            return AuthDecision(False, HTTPStatus.UNAUTHORIZED, "Unauthorized", True, required_permission, None)
        if required_permission == "admin" and granted_permission != "admin":
            return AuthDecision(False, HTTPStatus.FORBIDDEN, "Forbidden", True, required_permission, granted_permission)
        return AuthDecision(True, HTTPStatus.OK, None, True, required_permission, granted_permission)

    def _permission_for_token(self, supplied: str) -> str | None:
        if self.admin_token and hmac.compare_digest(supplied, self.admin_token):
            return "admin"
        if self.user_token and hmac.compare_digest(supplied, self.user_token):
            return "user"
        if self.auth_enabled and not self.user_token and self.admin_token and hmac.compare_digest(supplied, self.admin_token):
            return "admin"
        return None