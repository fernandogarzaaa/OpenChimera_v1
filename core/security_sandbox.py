"""
Phase 4: Security & Sandboxing — Docker sandbox, tool policies, prompt injection defense.

Provides:
- SandboxManager: Docker-based execution sandbox with resource limits
- ToolPolicyEngine: per-tool permission and rate-limit policies
- InjectionDefense: prompt injection detection and sanitization
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Prompt Injection Defense
# ---------------------------------------------------------------------------

class InjectionRisk(str, Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# Patterns that indicate injection attempts
INJECTION_PATTERNS = [
    # Role override attempts
    (r"ignore\s+(all\s+)?(previous|prior|above|earlier)\s+(instructions?|prompts?|context)", InjectionRisk.CRITICAL),
    (r"disregard\s+(all\s+)?(previous|prior|above)\s+(instructions?|prompts?)", InjectionRisk.CRITICAL),
    (r"forget\s+(all\s+)?(previous|your)\s+(instructions?|prompts?|training)", InjectionRisk.CRITICAL),
    # System prompt leaking
    (r"(reveal|show|print|output|display)\s+(your\s+)?(system\s+prompt|instructions?|context)", InjectionRisk.HIGH),
    (r"what\s+(are|is)\s+your\s+(system\s+prompt|instructions?|directives?)", InjectionRisk.HIGH),
    # Jailbreaks
    (r"(act|pretend|roleplay|play|imagine)\s+(as|like|you\s+are)\s+(a\s+)?(?:different|evil|unaligned|uncensored|jailbroken|unrestricted)\s+ai", InjectionRisk.HIGH),
    (r"you\s+are\s+now\s+(dan|jailbreak|god\s*mode|devmode)", InjectionRisk.CRITICAL),
    (r"\bdan\b.*jailbreak|\bjailbreak\b.*\bdan\b", InjectionRisk.HIGH),
    # Indirect injection markers
    (r"\[system\]|\[assistant\]|\[user\]|\[inst\]", InjectionRisk.MEDIUM),
    (r"<\|system\|>|<\|assistant\|>|<\|user\|>|<\|im_start\|>", InjectionRisk.HIGH),
    # Code execution attempts
    (r"exec\s*\(|eval\s*\(|__import__\s*\(", InjectionRisk.HIGH),
    (r"os\.system|subprocess\.call|subprocess\.run", InjectionRisk.HIGH),
    # Excessive special characters (obfuscation)
    (r"[^\w\s.,!?;:\-'\"()\[\]{}]{10,}", InjectionRisk.LOW),
]


@dataclass
class InjectionScanResult:
    text: str
    risk_level: InjectionRisk
    matches: List[dict]
    sanitized_text: str
    blocked: bool
    scan_time_ms: float

    def to_dict(self) -> dict:
        return {
            "risk_level": self.risk_level.value,
            "matches": self.matches,
            "blocked": self.blocked,
            "match_count": len(self.matches),
            "scan_time_ms": self.scan_time_ms,
            "sanitized": self.sanitized_text != self.text,
        }


class InjectionDefense:
    """
    Prompt injection detection and sanitization layer.
    Scans incoming text for injection patterns, assigns risk levels,
    and optionally blocks or sanitizes suspicious content.
    """

    def __init__(
        self,
        block_threshold: InjectionRisk = InjectionRisk.HIGH,
        custom_patterns: Optional[List[Tuple[str, InjectionRisk]]] = None,
        audit_log_size: int = 1000,
    ):
        self.block_threshold = block_threshold
        self._patterns = [(re.compile(p, re.IGNORECASE | re.DOTALL), r) for p, r in INJECTION_PATTERNS]
        if custom_patterns:
            for p, r in custom_patterns:
                self._patterns.append((re.compile(p, re.IGNORECASE | re.DOTALL), r))
        self._audit_log: List[dict] = []
        self._audit_log_size = audit_log_size
        self._scan_count = 0
        self._block_count = 0

    def _risk_numeric(self, risk: InjectionRisk) -> int:
        return {
            InjectionRisk.NONE: 0,
            InjectionRisk.LOW: 1,
            InjectionRisk.MEDIUM: 2,
            InjectionRisk.HIGH: 3,
            InjectionRisk.CRITICAL: 4,
        }[risk]

    def scan(self, text: str) -> InjectionScanResult:
        """Scan text for injection patterns."""
        start = time.time()
        matches = []
        max_risk = InjectionRisk.NONE
        sanitized = text
        for pattern, risk in self._patterns:
            found = pattern.findall(text)
            if found:
                matches.append({
                    "pattern": pattern.pattern[:60],
                    "risk": risk.value,
                    "count": len(found),
                })
                if self._risk_numeric(risk) > self._risk_numeric(max_risk):
                    max_risk = risk
                # Sanitize by replacing matched content
                sanitized = pattern.sub("[REDACTED]", sanitized)
        blocked = self._risk_numeric(max_risk) >= self._risk_numeric(self.block_threshold)
        if blocked:
            self._block_count += 1
        self._scan_count += 1
        scan_time_ms = (time.time() - start) * 1000
        result = InjectionScanResult(
            text=text,
            risk_level=max_risk,
            matches=matches,
            sanitized_text=sanitized,
            blocked=blocked,
            scan_time_ms=scan_time_ms,
        )
        if matches:
            entry = {
                "timestamp": time.time(),
                "risk_level": max_risk.value,
                "blocked": blocked,
                "text_hash": hashlib.sha256(text.encode()).hexdigest()[:16],
                "match_count": len(matches),
            }
            self._audit_log.append(entry)
            if len(self._audit_log) > self._audit_log_size:
                self._audit_log = self._audit_log[-self._audit_log_size:]
        return result

    def is_safe(self, text: str) -> bool:
        """Quick safety check — returns True if text is safe to process."""
        return not self.scan(text).blocked

    def sanitize(self, text: str) -> str:
        """Return sanitized version of text."""
        return self.scan(text).sanitized_text

    def get_audit_log(self, limit: int = 50) -> List[dict]:
        return list(reversed(self._audit_log))[:limit]

    def status(self) -> dict:
        return {
            "block_threshold": self.block_threshold.value,
            "pattern_count": len(self._patterns),
            "scan_count": self._scan_count,
            "block_count": self._block_count,
            "audit_log_size": len(self._audit_log),
        }


# ---------------------------------------------------------------------------
# Tool Policy Engine
# ---------------------------------------------------------------------------

class PermissionLevel(str, Enum):
    NONE = "none"
    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    ADMIN = "admin"


@dataclass
class ToolPolicy:
    """Policy definition for a specific tool."""
    tool_id: str
    enabled: bool = True
    required_permission: PermissionLevel = PermissionLevel.EXECUTE
    max_calls_per_minute: int = 60
    max_calls_per_hour: int = 500
    allowed_roles: List[str] = field(default_factory=lambda: ["user", "admin"])
    denied_roles: List[str] = field(default_factory=list)
    require_confirmation: bool = False
    timeout_seconds: float = 30.0
    sandbox_required: bool = False
    audit_enabled: bool = True
    description: str = ""
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "tool_id": self.tool_id,
            "enabled": self.enabled,
            "required_permission": self.required_permission.value,
            "max_calls_per_minute": self.max_calls_per_minute,
            "max_calls_per_hour": self.max_calls_per_hour,
            "allowed_roles": self.allowed_roles,
            "denied_roles": self.denied_roles,
            "require_confirmation": self.require_confirmation,
            "timeout_seconds": self.timeout_seconds,
            "sandbox_required": self.sandbox_required,
            "audit_enabled": self.audit_enabled,
            "tags": self.tags,
        }


@dataclass
class PolicyViolation:
    tool_id: str
    reason: str
    user_id: str
    role: str
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "tool_id": self.tool_id,
            "reason": self.reason,
            "user_id": self.user_id,
            "role": self.role,
            "timestamp": self.timestamp,
        }


class ToolPolicyEngine:
    """
    Enforces per-tool security policies: permissions, rate limits, role checks.
    """

    def __init__(self):
        self._policies: Dict[str, ToolPolicy] = {}
        self._call_counts: Dict[str, Dict[str, Any]] = {}  # tool_id -> {user: counts}
        self._violations: List[PolicyViolation] = []
        self._default_policy = ToolPolicy(tool_id="*", description="Default policy")

    def register_policy(self, policy: ToolPolicy) -> None:
        self._policies[policy.tool_id] = policy

    def get_policy(self, tool_id: str) -> ToolPolicy:
        return self._policies.get(tool_id, self._default_policy)

    def check(self, tool_id: str, user_id: str, role: str) -> Tuple[bool, Optional[str]]:
        """
        Check if a tool call is allowed.
        Returns (allowed, reason) tuple.
        """
        policy = self.get_policy(tool_id)
        if not policy.enabled:
            self._record_violation(tool_id, "tool_disabled", user_id, role)
            return False, "tool_disabled"
        if policy.denied_roles and role in policy.denied_roles:
            self._record_violation(tool_id, "role_denied", user_id, role)
            return False, "role_denied"
        if policy.allowed_roles and role not in policy.allowed_roles:
            self._record_violation(tool_id, "role_not_allowed", user_id, role)
            return False, "role_not_allowed"
        # Rate limiting
        now = time.time()
        key = f"{tool_id}:{user_id}"
        counts = self._call_counts.setdefault(key, {"minute_start": now, "minute_count": 0, "hour_start": now, "hour_count": 0})
        # Reset minute window
        if now - counts["minute_start"] > 60:
            counts["minute_start"] = now
            counts["minute_count"] = 0
        # Reset hour window
        if now - counts["hour_start"] > 3600:
            counts["hour_start"] = now
            counts["hour_count"] = 0
        if counts["minute_count"] >= policy.max_calls_per_minute:
            self._record_violation(tool_id, "rate_limit_minute", user_id, role)
            return False, "rate_limit_minute"
        if counts["hour_count"] >= policy.max_calls_per_hour:
            self._record_violation(tool_id, "rate_limit_hour", user_id, role)
            return False, "rate_limit_hour"
        counts["minute_count"] += 1
        counts["hour_count"] += 1
        return True, None

    def _record_violation(self, tool_id: str, reason: str, user_id: str, role: str) -> None:
        self._violations.append(PolicyViolation(
            tool_id=tool_id, reason=reason, user_id=user_id, role=role
        ))
        if len(self._violations) > 1000:
            self._violations = self._violations[-1000:]

    def get_violations(self, tool_id: Optional[str] = None, limit: int = 50) -> List[dict]:
        violations = self._violations
        if tool_id:
            violations = [v for v in violations if v.tool_id == tool_id]
        return [v.to_dict() for v in reversed(violations)][:limit]

    def status(self) -> dict:
        return {
            "registered_policies": len(self._policies),
            "tracked_call_keys": len(self._call_counts),
            "total_violations": len(self._violations),
            "policies": {k: v.to_dict() for k, v in self._policies.items()},
        }


# ---------------------------------------------------------------------------
# Docker Sandbox Manager
# ---------------------------------------------------------------------------

class SandboxStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"


@dataclass
class SandboxConfig:
    image: str = "python:3.12-slim"
    memory_limit: str = "256m"
    cpu_limit: float = 0.5
    timeout_seconds: float = 30.0
    network_disabled: bool = True
    read_only_filesystem: bool = True
    allowed_volumes: List[str] = field(default_factory=list)
    environment: Dict[str, str] = field(default_factory=dict)
    working_dir: str = "/workspace"


@dataclass
class SandboxResult:
    execution_id: str
    status: SandboxStatus
    stdout: str = ""
    stderr: str = ""
    exit_code: Optional[int] = None
    duration_ms: float = 0.0
    error: Optional[str] = None
    resource_usage: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "execution_id": self.execution_id,
            "status": self.status.value,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "exit_code": self.exit_code,
            "duration_ms": self.duration_ms,
            "error": self.error,
            "resource_usage": self.resource_usage,
            "success": self.status == SandboxStatus.COMPLETED and (self.exit_code or 0) == 0,
        }


class SandboxManager:
    """
    Docker-based execution sandbox manager.
    Provides isolated execution with resource limits and security policies.
    Falls back to subprocess-based sandbox when Docker is unavailable.
    """

    def __init__(
        self,
        config: Optional[SandboxConfig] = None,
        policy_engine: Optional[ToolPolicyEngine] = None,
        injection_defense: Optional[InjectionDefense] = None,
    ):
        self.config = config or SandboxConfig()
        self.policy_engine = policy_engine or ToolPolicyEngine()
        self.injection_defense = injection_defense or InjectionDefense()
        self._docker_available = self._check_docker()
        self._execution_history: List[SandboxResult] = []
        self._execution_count = 0

    def _check_docker(self) -> bool:
        """Check if Docker is available."""
        try:
            import subprocess
            result = subprocess.run(
                ["docker", "version", "--format", "{{.Server.Version}}"],
                capture_output=True, text=True, timeout=5
            )
            return result.returncode == 0
        except Exception:
            return False

    def execute_code(
        self,
        code: str,
        language: str = "python",
        user_id: str = "anonymous",
        role: str = "user",
    ) -> SandboxResult:
        """Execute code in a sandboxed environment."""
        execution_id = f"exec-{int(time.time() * 1000)}-{hashlib.md5(code.encode()).hexdigest()[:8]}"
        # Security scan
        scan = self.injection_defense.scan(code)
        if scan.blocked:
            result = SandboxResult(
                execution_id=execution_id,
                status=SandboxStatus.FAILED,
                error=f"Security scan blocked execution: {scan.risk_level.value}",
            )
            self._execution_history.append(result)
            return result
        # Policy check
        allowed, reason = self.policy_engine.check("code_execution", user_id, role)
        if not allowed:
            result = SandboxResult(
                execution_id=execution_id,
                status=SandboxStatus.FAILED,
                error=f"Policy violation: {reason}",
            )
            self._execution_history.append(result)
            return result
        if self._docker_available:
            result = self._docker_execute(execution_id, code, language)
        else:
            result = self._subprocess_execute(execution_id, code, language)
        self._execution_history.append(result)
        self._execution_count += 1
        return result

    def _docker_execute(self, execution_id: str, code: str, language: str) -> SandboxResult:
        """Execute in Docker container."""
        try:
            import subprocess
            import tempfile
            start = time.time()
            with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
                f.write(code)
                code_file = f.name
            cmd = [
                "docker", "run",
                "--rm",
                "--memory", self.config.memory_limit,
                "--cpus", str(self.config.cpu_limit),
                "--network", "none" if self.config.network_disabled else "bridge",
                "--read-only" if self.config.read_only_filesystem else "",
                "-v", f"{code_file}:/workspace/code.py:ro",
                self.config.image,
                "python", "/workspace/code.py",
            ]
            cmd = [c for c in cmd if c]  # Remove empty strings
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.config.timeout_seconds,
            )
            import os
            os.unlink(code_file)
            return SandboxResult(
                execution_id=execution_id,
                status=SandboxStatus.COMPLETED if proc.returncode == 0 else SandboxStatus.FAILED,
                stdout=proc.stdout[:10000],
                stderr=proc.stderr[:5000],
                exit_code=proc.returncode,
                duration_ms=(time.time() - start) * 1000,
            )
        except subprocess.TimeoutExpired:
            return SandboxResult(
                execution_id=execution_id,
                status=SandboxStatus.TIMEOUT,
                error="Execution timed out",
                duration_ms=self.config.timeout_seconds * 1000,
            )
        except Exception as exc:
            return SandboxResult(
                execution_id=execution_id,
                status=SandboxStatus.FAILED,
                error=str(exc),
            )

    def _subprocess_execute(self, execution_id: str, code: str, language: str) -> SandboxResult:
        """Fallback subprocess-based sandbox (restricted environment)."""
        try:
            import subprocess
            import sys
            import tempfile
            import os
            start = time.time()
            with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
                f.write(code)
                code_file = f.name
            env = {
                "PATH": "/usr/bin:/bin",
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONSAFEPATH": "1",
            }
            proc = subprocess.run(
                [sys.executable, code_file],
                capture_output=True,
                text=True,
                timeout=min(self.config.timeout_seconds, 10.0),
                env=env,
            )
            os.unlink(code_file)
            return SandboxResult(
                execution_id=execution_id,
                status=SandboxStatus.COMPLETED if proc.returncode == 0 else SandboxStatus.FAILED,
                stdout=proc.stdout[:10000],
                stderr=proc.stderr[:5000],
                exit_code=proc.returncode,
                duration_ms=(time.time() - start) * 1000,
                resource_usage={"sandbox_mode": "subprocess_fallback"},
            )
        except subprocess.TimeoutExpired:
            return SandboxResult(
                execution_id=execution_id,
                status=SandboxStatus.TIMEOUT,
                error="Execution timed out",
            )
        except Exception as exc:
            return SandboxResult(
                execution_id=execution_id,
                status=SandboxStatus.FAILED,
                error=str(exc),
            )

    def get_execution_history(self, limit: int = 20) -> List[dict]:
        return [r.to_dict() for r in reversed(self._execution_history)][:limit]

    def status(self) -> dict:
        return {
            "docker_available": self._docker_available,
            "sandbox_mode": "docker" if self._docker_available else "subprocess_fallback",
            "config": {
                "image": self.config.image,
                "memory_limit": self.config.memory_limit,
                "cpu_limit": self.config.cpu_limit,
                "timeout_seconds": self.config.timeout_seconds,
                "network_disabled": self.config.network_disabled,
            },
            "execution_count": self._execution_count,
            "policy_engine": self.policy_engine.status(),
            "injection_defense": self.injection_defense.status(),
        }
