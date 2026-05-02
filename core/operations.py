"""
Phase 7: Operations — Daemon mode, release channels, remote access.

Provides:
- DaemonManager: process lifecycle (start/stop/restart/status)
- ReleaseChannelManager: version management and update channels
- RemoteAccessManager: secure remote control endpoints
- OperationsController: unified operations facade
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import secrets
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Daemon Manager
# ---------------------------------------------------------------------------

class DaemonState(str, Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    CRASHED = "crashed"
    UNKNOWN = "unknown"


@dataclass
class DaemonProcess:
    """Represents a managed daemon process."""
    name: str
    command: List[str]
    working_dir: str = "."
    env: Dict[str, str] = field(default_factory=dict)
    pid_file: Optional[str] = None
    log_file: Optional[str] = None
    auto_restart: bool = True
    max_restart_attempts: int = 5
    restart_delay_seconds: float = 2.0
    # Runtime state
    pid: Optional[int] = None
    state: DaemonState = DaemonState.STOPPED
    started_at: Optional[float] = None
    restart_count: int = 0
    last_error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "command": self.command,
            "working_dir": self.working_dir,
            "pid": self.pid,
            "state": self.state.value,
            "started_at": self.started_at,
            "restart_count": self.restart_count,
            "last_error": self.last_error,
            "auto_restart": self.auto_restart,
        }


class DaemonManager:
    """
    Manages background daemon processes for OpenChimera.
    Supports start/stop/restart/status operations.
    """

    def __init__(self, run_dir: Optional[Path] = None, log_dir: Optional[Path] = None):
        self._run_dir = run_dir or Path("data/run")
        self._log_dir = log_dir or Path("data/logs")
        self._processes: Dict[str, DaemonProcess] = {}
        self._subprocesses: Dict[str, subprocess.Popen] = {}
        self._callbacks: Dict[str, List[Callable]] = {}

    def register(self, process: DaemonProcess) -> None:
        """Register a daemon process definition."""
        self._processes[process.name] = process
        logger.info("Daemon registered: %s", process.name)

    def start(self, name: str) -> dict:
        """Start a registered daemon process."""
        proc = self._processes.get(name)
        if not proc:
            return {"status": "error", "reason": "daemon_not_registered", "name": name}
        if proc.state == DaemonState.RUNNING:
            return {"status": "already_running", "name": name, "pid": proc.pid}
        try:
            proc.state = DaemonState.STARTING
            env = {**os.environ, **proc.env}
            log_path = None
            if proc.log_file:
                log_path = Path(proc.log_file)
                log_path.parent.mkdir(parents=True, exist_ok=True)
            stdout = open(str(log_path), "a") if log_path else subprocess.DEVNULL
            sub = subprocess.Popen(
                proc.command,
                cwd=proc.working_dir,
                env=env,
                stdout=stdout,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            proc.pid = sub.pid
            proc.state = DaemonState.RUNNING
            proc.started_at = time.time()
            self._subprocesses[name] = sub
            # Write PID file
            if proc.pid_file:
                pid_path = Path(proc.pid_file)
                pid_path.parent.mkdir(parents=True, exist_ok=True)
                pid_path.write_text(str(proc.pid))
            self._emit_event(name, "started", {"pid": proc.pid})
            return {"status": "started", "name": name, "pid": proc.pid}
        except Exception as exc:
            proc.state = DaemonState.CRASHED
            proc.last_error = str(exc)
            return {"status": "error", "reason": str(exc), "name": name}

    def stop(self, name: str, timeout: float = 10.0) -> dict:
        """Stop a running daemon process."""
        proc = self._processes.get(name)
        if not proc:
            return {"status": "error", "reason": "daemon_not_registered", "name": name}
        if proc.state != DaemonState.RUNNING:
            return {"status": "not_running", "name": name}
        sub = self._subprocesses.get(name)
        proc.state = DaemonState.STOPPING
        try:
            if sub and sub.poll() is None:
                sub.terminate()
                try:
                    sub.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    sub.kill()
                    sub.wait()
            proc.pid = None
            proc.state = DaemonState.STOPPED
            if proc.pid_file and Path(proc.pid_file).exists():
                Path(proc.pid_file).unlink()
            self._emit_event(name, "stopped", {})
            return {"status": "stopped", "name": name}
        except Exception as exc:
            proc.last_error = str(exc)
            return {"status": "error", "reason": str(exc), "name": name}

    def restart(self, name: str) -> dict:
        """Restart a daemon process."""
        stop_result = self.stop(name)
        time.sleep(0.5)
        start_result = self.start(name)
        return {"status": "restarted", "stop": stop_result, "start": start_result, "name": name}

    def check_health(self, name: str) -> dict:
        """Check if a daemon is still alive."""
        proc = self._processes.get(name)
        if not proc:
            return {"status": "not_registered", "name": name}
        sub = self._subprocesses.get(name)
        if proc.state == DaemonState.RUNNING:
            if sub and sub.poll() is not None:
                # Process has died
                exit_code = sub.returncode
                proc.state = DaemonState.CRASHED
                proc.last_error = f"Process exited with code {exit_code}"
                if proc.auto_restart and proc.restart_count < proc.max_restart_attempts:
                    proc.restart_count += 1
                    self._emit_event(name, "restart_scheduled", {"attempt": proc.restart_count})
                    return {"status": "crashed", "name": name, "exit_code": exit_code, "restart_scheduled": True}
                return {"status": "crashed", "name": name, "exit_code": exit_code}
            return {"status": "healthy", "name": name, "pid": proc.pid, "uptime_seconds": time.time() - (proc.started_at or time.time())}
        return {"status": proc.state.value, "name": name}

    def on_event(self, name: str, handler: Callable) -> None:
        self._callbacks.setdefault(name, []).append(handler)

    def _emit_event(self, name: str, event_type: str, data: dict) -> None:
        for handler in self._callbacks.get(name, []):
            try:
                handler(event_type, data)
            except Exception as exc:
                logger.warning("Daemon event handler error: %s", exc)

    def list_processes(self) -> List[dict]:
        return [p.to_dict() for p in self._processes.values()]

    def status(self) -> dict:
        return {
            "total": len(self._processes),
            "running": sum(1 for p in self._processes.values() if p.state == DaemonState.RUNNING),
            "stopped": sum(1 for p in self._processes.values() if p.state == DaemonState.STOPPED),
            "crashed": sum(1 for p in self._processes.values() if p.state == DaemonState.CRASHED),
            "processes": self.list_processes(),
        }


# ---------------------------------------------------------------------------
# Release Channel Manager
# ---------------------------------------------------------------------------

class ReleaseChannel(str, Enum):
    STABLE = "stable"
    BETA = "beta"
    NIGHTLY = "nightly"
    CANARY = "canary"
    LTS = "lts"


@dataclass
class Release:
    """Represents a software release."""
    version: str
    channel: ReleaseChannel
    release_notes: str = ""
    published_at: float = field(default_factory=time.time)
    download_url: str = ""
    checksum_sha256: str = ""
    min_os_version: str = ""
    breaking_changes: bool = False
    required: bool = False  # Forced update
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "channel": self.channel.value,
            "release_notes": self.release_notes,
            "published_at": self.published_at,
            "download_url": self.download_url,
            "checksum_sha256": self.checksum_sha256,
            "breaking_changes": self.breaking_changes,
            "required": self.required,
            "tags": self.tags,
        }


def _version_tuple(version: str) -> Tuple[int, ...]:
    """Parse version string to tuple for comparison (handles pre-release like 2.0.0-beta.1)."""
    try:
        # Strip v prefix, take only the numeric part before any hyphen (pre-release)
        clean = version.lstrip("v").split("-")[0]  # "2.0.0-beta.1" -> "2.0.0"
        parts = clean.split(".")[:4]
        return tuple(int(x) for x in parts)
    except (ValueError, AttributeError):
        return (0,)


class ReleaseChannelManager:
    """
    Manages software releases and update channels.
    """

    def __init__(self, current_version: str = "1.0.0"):
        self.current_version = current_version
        self.preferred_channel = ReleaseChannel.STABLE
        self._releases: Dict[str, Release] = {}  # version -> release
        self._subscribers: Dict[str, ReleaseChannel] = {}  # user_id -> channel

    def publish_release(self, release: Release) -> dict:
        """Publish a new release."""
        self._releases[release.version] = release
        logger.info("Release published: v%s (%s)", release.version, release.channel.value)
        return {"status": "published", "version": release.version, "channel": release.channel.value}

    def set_channel(self, user_id: str, channel: ReleaseChannel) -> None:
        """Set update channel preference for a user."""
        self._subscribers[user_id] = channel

    def get_channel(self, user_id: str) -> ReleaseChannel:
        return self._subscribers.get(user_id, self.preferred_channel)

    def check_for_updates(self, user_id: str = "system", current_version: Optional[str] = None) -> dict:
        """Check for available updates in the user's preferred channel."""
        channel = self.get_channel(user_id)
        cv = current_version or self.current_version
        # Channel precedence: canary > nightly > beta > stable > lts
        channel_priority = {
            ReleaseChannel.CANARY: 5,
            ReleaseChannel.NIGHTLY: 4,
            ReleaseChannel.BETA: 3,
            ReleaseChannel.STABLE: 2,
            ReleaseChannel.LTS: 1,
        }
        user_priority = channel_priority.get(channel, 2)
        eligible = [
            r for r in self._releases.values()
            if channel_priority.get(r.channel, 0) <= user_priority
            and _version_tuple(r.version) > _version_tuple(cv)
        ]
        if not eligible:
            return {"has_update": False, "current_version": cv, "channel": channel.value}
        latest = max(eligible, key=lambda r: _version_tuple(r.version))
        return {
            "has_update": True,
            "current_version": cv,
            "latest_version": latest.version,
            "channel": channel.value,
            "release": latest.to_dict(),
            "required": latest.required,
        }

    def list_releases(self, channel: Optional[ReleaseChannel] = None, limit: int = 10) -> List[dict]:
        releases = list(self._releases.values())
        if channel:
            releases = [r for r in releases if r.channel == channel]
        releases.sort(key=lambda r: _version_tuple(r.version), reverse=True)
        return [r.to_dict() for r in releases[:limit]]

    def status(self) -> dict:
        return {
            "current_version": self.current_version,
            "preferred_channel": self.preferred_channel.value,
            "total_releases": len(self._releases),
            "subscribers": len(self._subscribers),
            "channels": {
                c.value: sum(1 for r in self._releases.values() if r.channel == c)
                for c in ReleaseChannel
            },
        }


# ---------------------------------------------------------------------------
# Remote Access Manager
# ---------------------------------------------------------------------------

class AccessLevel(str, Enum):
    READ_ONLY = "read_only"
    OPERATOR = "operator"
    ADMIN = "admin"
    SUPERADMIN = "superadmin"


@dataclass
class RemoteSession:
    """A remote access session."""
    session_id: str
    user_id: str
    access_level: AccessLevel
    api_key_hash: str = ""
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    expires_at: Optional[float] = None
    source_ip: str = ""
    active: bool = True
    commands_executed: int = 0

    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "access_level": self.access_level.value,
            "created_at": self.created_at,
            "last_activity": self.last_activity,
            "expires_at": self.expires_at,
            "expired": self.is_expired(),
            "active": self.active,
            "commands_executed": self.commands_executed,
        }


@dataclass
class RemoteCommand:
    """A command executed via remote access."""
    command_id: str
    session_id: str
    command: str
    arguments: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    result: Optional[dict] = None
    error: Optional[str] = None
    duration_ms: float = 0.0

    def to_dict(self) -> dict:
        return {
            "command_id": self.command_id,
            "session_id": self.session_id,
            "command": self.command,
            "arguments": self.arguments,
            "timestamp": self.timestamp,
            "result": self.result,
            "error": self.error,
            "duration_ms": self.duration_ms,
        }


class RemoteAccessManager:
    """
    Manages secure remote access to OpenChimera.
    Handles API key auth, session management, and command routing.
    """

    ALLOWED_COMMANDS = {
        AccessLevel.READ_ONLY: {"status", "list", "health", "version", "logs"},
        AccessLevel.OPERATOR: {"status", "list", "health", "version", "logs", "restart", "reload_config", "flush_cache"},
        AccessLevel.ADMIN: {"status", "list", "health", "version", "logs", "restart", "reload_config", "flush_cache", "shutdown", "update", "exec"},
        AccessLevel.SUPERADMIN: None,  # All commands
    }

    def __init__(self, session_ttl_seconds: float = 3600 * 8):
        self._sessions: Dict[str, RemoteSession] = {}
        self._api_keys: Dict[str, Tuple[str, AccessLevel]] = {}  # key_hash -> (user_id, access_level)
        self._session_ttl = session_ttl_seconds
        self._command_handlers: Dict[str, Callable] = {}
        self._command_history: List[RemoteCommand] = []
        self._audit_log: List[dict] = []

    def create_api_key(self, user_id: str, access_level: AccessLevel = AccessLevel.OPERATOR) -> str:
        """Generate a new API key for a user."""
        api_key = f"oc-{secrets.token_hex(24)}"
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        self._api_keys[key_hash] = (user_id, access_level)
        logger.info("API key created for user %s (%s)", user_id, access_level.value)
        return api_key

    def authenticate(self, api_key: str, source_ip: str = "") -> Optional[RemoteSession]:
        """Authenticate with an API key and create a session."""
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        key_info = self._api_keys.get(key_hash)
        if not key_info:
            self._audit(None, "auth_failed", {"source_ip": source_ip})
            return None
        user_id, access_level = key_info
        session_id = f"rsess-{secrets.token_hex(16)}"
        session = RemoteSession(
            session_id=session_id,
            user_id=user_id,
            access_level=access_level,
            api_key_hash=key_hash[:8] + "...",
            expires_at=time.time() + self._session_ttl,
            source_ip=source_ip,
        )
        self._sessions[session_id] = session
        self._audit(session_id, "auth_success", {"user_id": user_id, "access_level": access_level.value})
        return session

    def validate_session(self, session_id: str) -> Optional[RemoteSession]:
        """Validate an existing session."""
        session = self._sessions.get(session_id)
        if not session or not session.active or session.is_expired():
            return None
        session.last_activity = time.time()
        return session

    def execute_command(self, session_id: str, command: str, arguments: Optional[dict] = None) -> dict:
        """Execute a remote command within a session."""
        session = self.validate_session(session_id)
        if not session:
            return {"status": "error", "reason": "invalid_or_expired_session"}
        # Check command authorization
        allowed = self.ALLOWED_COMMANDS.get(session.access_level)
        if allowed is not None and command not in allowed:
            self._audit(session_id, "command_denied", {"command": command, "reason": "insufficient_permissions"})
            return {"status": "error", "reason": "insufficient_permissions", "command": command}
        command_id = f"cmd-{secrets.token_hex(8)}"
        cmd = RemoteCommand(command_id=command_id, session_id=session_id, command=command, arguments=arguments or {})
        start = time.time()
        handler = self._command_handlers.get(command)
        if handler:
            try:
                result = handler(arguments or {})
                cmd.result = result
            except Exception as exc:
                cmd.error = str(exc)
        else:
            cmd.result = {"message": f"Command '{command}' queued (no handler registered)"}
        cmd.duration_ms = (time.time() - start) * 1000
        session.commands_executed += 1
        self._command_history.append(cmd)
        self._audit(session_id, "command_executed", {"command": command, "command_id": command_id})
        return {
            "status": "ok" if not cmd.error else "error",
            "command_id": command_id,
            "result": cmd.result,
            "error": cmd.error,
            "duration_ms": cmd.duration_ms,
        }

    def register_command_handler(self, command: str, handler: Callable) -> None:
        """Register a handler for a remote command."""
        self._command_handlers[command] = handler

    def revoke_session(self, session_id: str) -> bool:
        """Revoke a remote session."""
        session = self._sessions.get(session_id)
        if not session:
            return False
        session.active = False
        self._audit(session_id, "session_revoked", {})
        return True

    def _audit(self, session_id: Optional[str], event: str, data: dict) -> None:
        self._audit_log.append({
            "timestamp": time.time(),
            "session_id": session_id,
            "event": event,
            **data,
        })
        if len(self._audit_log) > 10000:
            self._audit_log = self._audit_log[-10000:]

    def get_audit_log(self, limit: int = 50) -> List[dict]:
        return list(reversed(self._audit_log))[:limit]

    def list_active_sessions(self) -> List[dict]:
        return [s.to_dict() for s in self._sessions.values() if s.active and not s.is_expired()]

    def status(self) -> dict:
        active = self.list_active_sessions()
        return {
            "active_sessions": len(active),
            "total_sessions": len(self._sessions),
            "registered_commands": sorted(self._command_handlers.keys()),
            "api_keys_count": len(self._api_keys),
            "audit_log_size": len(self._audit_log),
            "command_history_size": len(self._command_history),
        }


# ---------------------------------------------------------------------------
# Operations Controller (Unified Facade)
# ---------------------------------------------------------------------------

class OperationsController:
    """
    Unified operations facade combining daemon, releases, and remote access.
    """

    def __init__(
        self,
        current_version: str = "1.0.0",
        run_dir: Optional[Path] = None,
    ):
        self.daemon_manager = DaemonManager(run_dir=run_dir)
        self.release_manager = ReleaseChannelManager(current_version=current_version)
        self.remote_access = RemoteAccessManager()
        self._started_at = time.time()
        self._register_builtin_daemons()
        self._register_builtin_remote_commands()

    def _register_builtin_daemons(self) -> None:
        """Register standard OpenChimera daemon processes."""
        self.daemon_manager.register(DaemonProcess(
            name="api-server",
            command=[sys.executable, "run.py", "--api-only"],
            log_file="data/logs/api-server.log",
            pid_file="data/run/api-server.pid",
        ))
        self.daemon_manager.register(DaemonProcess(
            name="fim-daemon",
            command=[sys.executable, "-m", "core.fim_daemon"],
            log_file="data/logs/fim-daemon.log",
            pid_file="data/run/fim-daemon.pid",
        ))
        self.daemon_manager.register(DaemonProcess(
            name="task-worker",
            command=[sys.executable, "-m", "core.job_queue", "--worker"],
            log_file="data/logs/task-worker.log",
            pid_file="data/run/task-worker.pid",
            auto_restart=True,
        ))

    def _register_builtin_remote_commands(self) -> None:
        """Register standard remote command handlers."""
        self.remote_access.register_command_handler("status", lambda _: self.status())
        self.remote_access.register_command_handler("health", lambda _: {"status": "healthy", "uptime": time.time() - self._started_at})
        self.remote_access.register_command_handler("version", lambda _: {"version": self.release_manager.current_version})
        self.remote_access.register_command_handler("list", lambda args: {
            "daemons": self.daemon_manager.list_processes(),
            "sessions": self.remote_access.list_active_sessions(),
        })

    def status(self) -> dict:
        return {
            "uptime_seconds": time.time() - self._started_at,
            "version": self.release_manager.current_version,
            "platform": platform.system(),
            "python_version": sys.version.split()[0],
            "daemons": self.daemon_manager.status(),
            "releases": self.release_manager.status(),
            "remote_access": self.remote_access.status(),
        }
