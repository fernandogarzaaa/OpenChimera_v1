"""OpenChimera Embodied Interaction — AGI Capability #9.

Provides a sensor abstraction layer, an actuator command bus, an environment
state model, and a body-schema registry so OpenChimera can reason about and
simulate interaction with a physical (or simulated) world.

Architecture
────────────
SensorReading       Immutable snapshot of a single sensor observation.
SensorInterface     Manages sensor registrations and delivers readings.
ActuatorCommand     An action the system wants the body to perform.
ActuatorInterface   Dispatch actuator commands; track execution results.
EnvironmentState    Maintains a spatial map / object registry of the world.
BodySchema          The system's self-model of its own physical capabilities.
EmbodiedInteraction Top-level facade; all other classes are composed here.

All classes are thread-safe and publish events via EventBus when available.
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from core._bus_fallback import EventBus

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SensorReading:
    """Immutable snapshot of a single sensor observation."""

    sensor_id: str
    modality: str            # "distance", "temperature", "touch", "visual", "audio", etc.
    value: Any               # numeric, list, or dict depending on modality
    unit: str = ""
    confidence: float = 1.0
    timestamp: float = field(default_factory=time.time)


@dataclass
class ActuatorCommand:
    """A command for a physical or simulated actuator."""

    command_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    actuator_id: str = ""
    action: str = ""         # "move", "grasp", "release", "speak", "look", "halt"
    params: dict[str, Any] = field(default_factory=dict)
    issued_at: float = field(default_factory=time.time)
    status: str = "pending"  # "pending", "executing", "completed", "failed"
    result: dict[str, Any] = field(default_factory=dict)


@dataclass
class WorldObject:
    """An object tracked in the environment state."""

    object_id: str
    label: str
    position: dict[str, float] = field(default_factory=lambda: {"x": 0.0, "y": 0.0, "z": 0.0})
    properties: dict[str, Any] = field(default_factory=dict)
    last_seen: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Sensor Interface
# ---------------------------------------------------------------------------


class SensorInterface:
    """Manages sensor registrations and delivers readings.

    Sensors are registered with a *modality* and an optional *poll_fn* that
    returns a raw value when called.  A simulated sensor always returns its
    last injected value.

    Parameters
    ──────────
    bus  Optional EventBus for publishing ``embodied/sensor_reading`` events.
    """

    def __init__(self, bus: "Any | None" = None) -> None:
        self._bus = bus
        self._sensors: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()

    def register_sensor(
        self,
        sensor_id: str,
        modality: str,
        unit: str = "",
        poll_fn: "Callable[[], Any] | None" = None,
    ) -> None:
        """Register a sensor with an optional polling function."""
        with self._lock:
            self._sensors[sensor_id] = {
                "modality": modality,
                "unit": unit,
                "poll_fn": poll_fn,
                "last_value": None,
                "last_read": 0.0,
            }
        log.debug("[Sensor] Registered sensor '%s' modality=%s", sensor_id, modality)

    def inject_reading(self, sensor_id: str, value: Any, confidence: float = 1.0) -> SensorReading:
        """Directly inject a sensor value (used in simulation or testing)."""
        with self._lock:
            meta = self._sensors.get(sensor_id)
            if meta is None:
                raise KeyError(f"Sensor '{sensor_id}' is not registered.")
            meta["last_value"] = value
            meta["last_read"] = time.time()
            reading = SensorReading(
                sensor_id=sensor_id,
                modality=meta["modality"],
                value=value,
                unit=meta.get("unit", ""),
                confidence=confidence,
            )

        if self._bus is not None:
            self._bus.publish_nowait(
                "embodied/sensor_reading",
                {"sensor_id": sensor_id, "modality": meta["modality"], "value": value},
            )
        return reading

    def read(self, sensor_id: str) -> "SensorReading | None":
        """Return the latest reading for *sensor_id*, polling if a poll_fn exists."""
        with self._lock:
            meta = self._sensors.get(sensor_id)
            if meta is None:
                return None
            poll_fn = meta.get("poll_fn")
            if poll_fn is not None:
                try:
                    value = poll_fn()
                    meta["last_value"] = value
                    meta["last_read"] = time.time()
                except Exception as exc:
                    log.warning("[Sensor] Poll failed for '%s': %s", sensor_id, exc)
            if meta["last_value"] is None:
                return None
            return SensorReading(
                sensor_id=sensor_id,
                modality=meta["modality"],
                value=meta["last_value"],
                unit=meta.get("unit", ""),
            )

    def read_all(self) -> list[SensorReading]:
        """Read all registered sensors."""
        with self._lock:
            sensor_ids = list(self._sensors)
        return [r for sid in sensor_ids if (r := self.read(sid)) is not None]

    def list_sensors(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {"sensor_id": sid, "modality": m["modality"], "unit": m.get("unit", ""), "last_read": m["last_read"]}
                for sid, m in self._sensors.items()
            ]


# ---------------------------------------------------------------------------
# Actuator Interface
# ---------------------------------------------------------------------------


class ActuatorInterface:
    """Dispatch actuator commands and track their execution results.

    In simulation mode, commands are executed immediately by a registered
    *handler* function.  If no handler is registered the command is queued
    with status ``"pending"``.

    Parameters
    ──────────
    bus  Optional EventBus for publishing ``embodied/actuator_command`` events.
    allowed_actions
        Optional set of permitted action names.  When provided, any action
        not in the set is rejected with status ``"rejected"``.
    command_timeout_s
        Maximum seconds a synchronous handler may run before being treated
        as a timeout (applied when handler raises).
    """

    _DEFAULT_ALLOWED_ACTIONS: frozenset[str] = frozenset({
        "move", "grasp", "release", "speak", "look", "halt",
        "rotate", "push", "pull", "scan", "idle",
    })

    def __init__(
        self,
        bus: "Any | None" = None,
        allowed_actions: "set[str] | None" = None,
        command_timeout_s: float = 30.0,
    ) -> None:
        self._bus = bus
        self._handlers: dict[str, Callable[[ActuatorCommand], dict[str, Any]]] = {}
        self._history: list[ActuatorCommand] = []
        self._lock = threading.RLock()
        self._allowed_actions: frozenset[str] = (
            frozenset(allowed_actions) if allowed_actions else self._DEFAULT_ALLOWED_ACTIONS
        )
        self._command_timeout_s = command_timeout_s

    def register_handler(
        self,
        actuator_id: str,
        handler: "Callable[[ActuatorCommand], dict[str, Any]]",
    ) -> None:
        """Register an actuator handler function for *actuator_id*."""
        with self._lock:
            self._handlers[actuator_id] = handler
        log.debug("[Actuator] Registered handler for actuator '%s'", actuator_id)

    def issue_command(
        self,
        actuator_id: str,
        action: str,
        params: "dict[str, Any] | None" = None,
        *,
        timeout_s: float | None = None,
        retry_count: int = 0,
    ) -> ActuatorCommand:
        """Issue a command to *actuator_id*.

        The *action* is validated against the allowed-actions whitelist.
        If a handler is registered it is called synchronously with timeout protection.
        Failed commands can be automatically retried up to *retry_count* times.
        Otherwise the command is stored with status ``"pending"``.
        Returns the completed (or pending) command.
        
        Parameters
        ──────────
        timeout_s:
            Command timeout in seconds. Defaults to self._command_timeout_s.
        retry_count:
            Number of automatic retries on failure (default 0 = no retries).
        """
        cmd = ActuatorCommand(actuator_id=actuator_id, action=action, params=params or {})
        timeout = timeout_s if timeout_s is not None else self._command_timeout_s

        # Validate action against whitelist
        if action not in self._allowed_actions:
            cmd.status = "rejected"
            cmd.result = {"error": f"Action {action!r} is not in the allowed actions list"}
            log.warning("[Actuator] Rejected disallowed action '%s' for actuator '%s'", action, actuator_id)
            with self._lock:
                self._history.append(cmd)
            return cmd

        if self._bus is not None:
            self._bus.publish_nowait(
                "embodied/actuator_command",
                {"command_id": cmd.command_id, "actuator_id": actuator_id, "action": action},
            )

        with self._lock:
            handler = self._handlers.get(actuator_id)
            
            if handler is not None:
                attempts = 0
                max_attempts = 1 + max(0, retry_count)
                
                while attempts < max_attempts:
                    attempts += 1
                    try:
                        cmd.status = "executing"
                        started = time.perf_counter()
                        result = handler(cmd)
                        elapsed = time.perf_counter() - started
                        
                        # Check for timeout
                        if elapsed > timeout:
                            raise TimeoutError(f"Command execution exceeded {timeout}s timeout")
                        
                        cmd.result = result or {}
                        cmd.status = "completed"
                        break  # Success, exit retry loop
                        
                    except TimeoutError as exc:
                        cmd.status = "timeout"
                        cmd.result = {"error": str(exc), "attempt": attempts}
                        log.warning("[Actuator] Timeout for '%s' (attempt %d/%d): %s",
                                   actuator_id, attempts, max_attempts, exc)
                        if attempts >= max_attempts:
                            break
                            
                    except Exception as exc:
                        cmd.status = "failed"
                        cmd.result = {"error": str(exc), "attempt": attempts}
                        log.warning("[Actuator] Handler failed for '%s' (attempt %d/%d): %s",
                                   actuator_id, attempts, max_attempts, exc)
                        if attempts >= max_attempts:
                            break
                            
            self._history.append(cmd)

        log.debug("[Actuator] Command '%s' → actuator='%s' action='%s' status=%s",
                  cmd.command_id, actuator_id, action, cmd.status)
        return cmd

    def command_history(self, actuator_id: "str | None" = None, limit: int = 50) -> list[ActuatorCommand]:
        """Return recent commands, optionally filtered by *actuator_id*."""
        with self._lock:
            history = self._history if actuator_id is None else [
                c for c in self._history if c.actuator_id == actuator_id
            ]
            return list(reversed(history[-limit:]))

    def list_actuators(self) -> list[str]:
        with self._lock:
            return list(self._handlers)


# ---------------------------------------------------------------------------
# Environment State
# ---------------------------------------------------------------------------


class EnvironmentState:
    """Maintains a spatial map / object registry of the physical environment.

    Objects are tracked by *object_id* with position and arbitrary properties.
    The system can query the nearest object by Euclidean distance.

    Parameters
    ──────────
    bus  Optional EventBus for publishing ``embodied/object_updated`` events.
    """

    def __init__(self, bus: "Any | None" = None) -> None:
        self._bus = bus
        self._objects: dict[str, WorldObject] = {}
        self._lock = threading.RLock()

    def update_object(
        self,
        object_id: str,
        label: str = "",
        position: "dict[str, float] | None" = None,
        properties: "dict[str, Any] | None" = None,
    ) -> WorldObject:
        """Upsert an object in the environment."""
        with self._lock:
            obj = self._objects.get(object_id)
            if obj is None:
                obj = WorldObject(object_id=object_id, label=label or object_id)
                self._objects[object_id] = obj
            if label:
                obj.label = label
            if position is not None:
                obj.position.update(position)
            if properties is not None:
                obj.properties.update(properties)
            obj.last_seen = time.time()

        if self._bus is not None:
            self._bus.publish_nowait(
                "embodied/object_updated",
                {"object_id": object_id, "label": obj.label, "position": obj.position},
            )
        return obj

    def get_object(self, object_id: str) -> "WorldObject | None":
        with self._lock:
            return self._objects.get(object_id)

    def find_nearest(
        self,
        position: dict[str, float],
        label_filter: "str | None" = None,
    ) -> "WorldObject | None":
        """Return the nearest object to *position* (Euclidean distance in XYZ)."""
        import math
        with self._lock:
            candidates = [
                obj for obj in self._objects.values()
                if label_filter is None or obj.label == label_filter
            ]
        if not candidates:
            return None
        def dist(obj: WorldObject) -> float:
            return math.sqrt(sum(
                (obj.position.get(ax, 0.0) - position.get(ax, 0.0)) ** 2
                for ax in ("x", "y", "z")
            ))
        return min(candidates, key=dist)

    def all_objects(self) -> list[WorldObject]:
        with self._lock:
            return list(self._objects.values())

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {
                    "object_id": obj.object_id,
                    "label": obj.label,
                    "position": dict(obj.position),
                    "properties": dict(obj.properties),
                    "last_seen": obj.last_seen,
                }
                for obj in self._objects.values()
            ]


# ---------------------------------------------------------------------------
# Body Schema
# ---------------------------------------------------------------------------


class BodySchema:
    """The system's self-model of its own physical capabilities.

    Tracks available joints/degrees-of-freedom, reach envelope, and
    current joint state.  Can report which actions are feasible given
    current configuration.
    """

    def __init__(self) -> None:
        self._joints: dict[str, dict[str, Any]] = {}
        self._capabilities: list[str] = ["move", "halt", "speak", "look"]
        self._pose: dict[str, float] = {}
        self._lock = threading.RLock()

    def register_joint(self, name: str, min_val: float, max_val: float, unit: str = "deg") -> None:
        with self._lock:
            self._joints[name] = {"min": min_val, "max": max_val, "unit": unit, "current": 0.0}

    def set_joint(self, name: str, value: float) -> bool:
        with self._lock:
            jnt = self._joints.get(name)
            if jnt is None:
                return False
            jnt["current"] = float(max(jnt["min"], min(jnt["max"], value)))
            return True

    def add_capability(self, capability: str) -> None:
        with self._lock:
            if capability not in self._capabilities:
                self._capabilities.append(capability)

    def can_perform(self, action: str) -> bool:
        """Return True if *action* is in the registered capabilities."""
        with self._lock:
            return action in self._capabilities

    def joint_state(self) -> dict[str, float]:
        with self._lock:
            return {name: data["current"] for name, data in self._joints.items()}

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "capabilities": list(self._capabilities),
                "joints": {
                    name: {k: v for k, v in data.items() if k != "current"}
                    | {"current": data["current"]}
                    for name, data in self._joints.items()
                },
            }


# ---------------------------------------------------------------------------
# EmbodiedInteraction — top-level facade
# ---------------------------------------------------------------------------


class EmbodiedInteraction:
    """Top-level facade for OpenChimera's embodied interaction subsystem.

    Composes:
    - :class:`SensorInterface` — register sensors, inject/read values
    - :class:`ActuatorInterface` — issue and track actuator commands
    - :class:`EnvironmentState` — maintain spatial object registry
    - :class:`BodySchema` — self-model of physical capabilities

    Publishes events via EventBus and provides a unified ``snapshot()`` for
    persistence or introspection.

    Parameters
    ──────────
    bus  Optional :class:`~core._bus_fallback.EventBus` instance.
    """

    def __init__(self, bus: "Any | None" = None) -> None:
        self._bus = bus
        self.sensors = SensorInterface(bus=bus)
        self.actuators = ActuatorInterface(bus=bus)
        self.environment = EnvironmentState(bus=bus)
        self.body_schema = BodySchema()
        self._setup_default_sensors()
        self._setup_default_actuators()
        log.info("[EmbodiedInteraction] Subsystem initialised.")

    # ------------------------------------------------------------------
    # Default simulation setup
    # ------------------------------------------------------------------

    def _setup_default_sensors(self) -> None:
        self.sensors.register_sensor("distance_front", "distance", unit="m")
        self.sensors.register_sensor("temperature", "temperature", unit="°C")
        self.sensors.register_sensor("touch_left", "touch", unit="bool")
        self.sensors.register_sensor("touch_right", "touch", unit="bool")
        self.sensors.register_sensor("visual_field", "visual", unit="pixels")

    def _setup_default_actuators(self) -> None:
        def _sim_move(cmd: ActuatorCommand) -> dict[str, Any]:
            direction = cmd.params.get("direction", "forward")
            distance = cmd.params.get("distance_m", 0.1)
            log.debug("[SimActuator] move: direction=%s distance=%.2fm", direction, distance)
            return {"moved": True, "direction": direction, "distance_m": distance}

        def _sim_speak(cmd: ActuatorCommand) -> dict[str, Any]:
            text = cmd.params.get("text", "")
            log.debug("[SimActuator] speak: '%s'", text)
            return {"spoken": True, "text": text}

        def _sim_look(cmd: ActuatorCommand) -> dict[str, Any]:
            target = cmd.params.get("target", "forward")
            log.debug("[SimActuator] look: target=%s", target)
            return {"looking_at": target}

        self.actuators.register_handler("body", _sim_move)
        self.actuators.register_handler("speaker", _sim_speak)
        self.actuators.register_handler("camera", _sim_look)

        self.body_schema.add_capability("move")
        self.body_schema.add_capability("speak")
        self.body_schema.add_capability("look")
        self.body_schema.add_capability("grasp")

    # ------------------------------------------------------------------
    # High-level convenience methods
    # ------------------------------------------------------------------

    def move(self, direction: str = "forward", distance_m: float = 0.1) -> ActuatorCommand:
        """Issue a move command to the body actuator."""
        return self.actuators.issue_command("body", "move", {"direction": direction, "distance_m": distance_m})

    def speak(self, text: str) -> ActuatorCommand:
        """Issue a speak command to the speaker actuator."""
        return self.actuators.issue_command("speaker", "speak", {"text": text})

    def look(self, target: str = "forward") -> ActuatorCommand:
        """Issue a look command to the camera actuator."""
        return self.actuators.issue_command("camera", "look", {"target": target})

    def sense_all(self) -> list[SensorReading]:
        """Return the latest reading from all registered sensors."""
        return self.sensors.read_all()

    # ------------------------------------------------------------------
    # Snapshot / export
    # ------------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        """Return a full serialisable snapshot of the embodied interaction subsystem."""
        return {
            "sensors": self.sensors.list_sensors(),
            "actuators": self.actuators.list_actuators(),
            "environment": self.environment.snapshot(),
            "body_schema": self.body_schema.snapshot(),
        }
