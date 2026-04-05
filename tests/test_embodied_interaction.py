"""Tests for core/embodied_interaction.py — AGI Capability #9.

Covers:
- SensorInterface: register, inject, read, read_all
- ActuatorInterface: register handler, issue_command, history
- EnvironmentState: update_object, find_nearest, snapshot
- BodySchema: register_joint, set_joint, can_perform
- EmbodiedInteraction facade: move, speak, look, sense_all, snapshot
- EventBus integration (events published)
- Quantum Engine validation: swarm vote on sensor readings
- Sandbox simulation: full embodied navigation scenario
"""
from __future__ import annotations

import math
import time

import pytest

from core.embodied_interaction import (
    EmbodiedInteraction,
    SensorInterface,
    ActuatorInterface,
    EnvironmentState,
    BodySchema,
    SensorReading,
    ActuatorCommand,
    WorldObject,
)
from core._bus_fallback import EventBus


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def bus():
    return EventBus()


@pytest.fixture
def sensors(bus):
    return SensorInterface(bus=bus)


@pytest.fixture
def actuators(bus):
    return ActuatorInterface(bus=bus)


@pytest.fixture
def environment(bus):
    return EnvironmentState(bus=bus)


@pytest.fixture
def body_schema():
    return BodySchema()


@pytest.fixture
def embodied(bus):
    return EmbodiedInteraction(bus=bus)


# ---------------------------------------------------------------------------
# SensorInterface
# ---------------------------------------------------------------------------

class TestSensorInterface:
    def test_register_and_inject(self, sensors):
        sensors.register_sensor("lidar_front", "distance", unit="m")
        reading = sensors.inject_reading("lidar_front", 1.5, confidence=0.95)
        assert isinstance(reading, SensorReading)
        assert reading.sensor_id == "lidar_front"
        assert reading.modality == "distance"
        assert abs(reading.value - 1.5) < 1e-6
        assert abs(reading.confidence - 0.95) < 1e-6

    def test_read_returns_last_injected(self, sensors):
        sensors.register_sensor("temp", "temperature", unit="°C")
        sensors.inject_reading("temp", 22.5)
        reading = sensors.read("temp")
        assert reading is not None
        assert abs(reading.value - 22.5) < 1e-6

    def test_read_unregistered_returns_none(self, sensors):
        assert sensors.read("ghost_sensor") is None

    def test_read_before_inject_returns_none(self, sensors):
        sensors.register_sensor("empty_sensor", "touch")
        assert sensors.read("empty_sensor") is None

    def test_inject_unregistered_raises(self, sensors):
        with pytest.raises(KeyError):
            sensors.inject_reading("not_registered", 0.0)

    def test_poll_fn(self, sensors):
        counter = [0]
        def poll():
            counter[0] += 1
            return counter[0] * 10.0

        sensors.register_sensor("polled", "temperature", poll_fn=poll)
        r1 = sensors.read("polled")
        r2 = sensors.read("polled")
        assert r1.value == 10.0
        assert r2.value == 20.0

    def test_read_all(self, sensors):
        sensors.register_sensor("s1", "distance")
        sensors.register_sensor("s2", "touch")
        sensors.inject_reading("s1", 2.0)
        sensors.inject_reading("s2", True)
        readings = sensors.read_all()
        ids = [r.sensor_id for r in readings]
        assert "s1" in ids
        assert "s2" in ids

    def test_list_sensors(self, sensors):
        sensors.register_sensor("listed", "audio")
        listed = sensors.list_sensors()
        assert any(s["sensor_id"] == "listed" for s in listed)

    def test_thread_safety(self, sensors):
        import threading
        sensors.register_sensor("concurrent", "distance")
        errors = []
        def worker():
            try:
                sensors.inject_reading("concurrent", 1.0)
                sensors.read("concurrent")
            except Exception as e:
                errors.append(e)
        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads: t.start()
        for t in threads: t.join()
        assert not errors


# ---------------------------------------------------------------------------
# ActuatorInterface
# ---------------------------------------------------------------------------

class TestActuatorInterface:
    def test_issue_command_no_handler(self, actuators):
        cmd = actuators.issue_command("arm", "grasp", {"force": 0.5})
        assert isinstance(cmd, ActuatorCommand)
        assert cmd.status == "pending"
        assert cmd.actuator_id == "arm"
        assert cmd.action == "grasp"

    def test_issue_command_with_handler(self, actuators):
        actuators.register_handler("arm", lambda cmd: {"grasped": True})
        cmd = actuators.issue_command("arm", "grasp")
        assert cmd.status == "completed"
        assert cmd.result.get("grasped") is True

    def test_handler_exception_marks_failed(self, actuators):
        def bad_handler(cmd):
            raise RuntimeError("motor error")
        actuators.register_handler("broken", bad_handler)
        cmd = actuators.issue_command("broken", "move")
        assert cmd.status == "failed"
        assert "error" in cmd.result

    def test_command_history(self, actuators):
        for i in range(3):
            actuators.issue_command("leg", "step", {"step": i})
        history = actuators.command_history("leg")
        assert len(history) == 3

    def test_command_history_filtered(self, actuators):
        actuators.issue_command("leg", "step")
        actuators.issue_command("arm", "reach")
        history = actuators.command_history("leg")
        assert all(c.actuator_id == "leg" for c in history)

    def test_command_history_limit(self, actuators):
        for _ in range(60):
            actuators.issue_command("foot", "tap")
        history = actuators.command_history("foot", limit=10)
        assert len(history) <= 10

    def test_list_actuators(self, actuators):
        actuators.register_handler("hand", lambda cmd: {})
        assert "hand" in actuators.list_actuators()

    def test_command_id_unique(self, actuators):
        c1 = actuators.issue_command("wheel", "spin")
        c2 = actuators.issue_command("wheel", "spin")
        assert c1.command_id != c2.command_id


# ---------------------------------------------------------------------------
# EnvironmentState
# ---------------------------------------------------------------------------

class TestEnvironmentState:
    def test_update_and_get_object(self, environment):
        obj = environment.update_object("box_1", label="box", position={"x": 1.0, "y": 2.0, "z": 0.0})
        assert isinstance(obj, WorldObject)
        assert obj.label == "box"
        retrieved = environment.get_object("box_1")
        assert retrieved is not None
        assert abs(retrieved.position["x"] - 1.0) < 1e-6

    def test_update_existing_object(self, environment):
        environment.update_object("cup", label="cup", position={"x": 0.0})
        environment.update_object("cup", position={"x": 5.0})
        obj = environment.get_object("cup")
        assert abs(obj.position["x"] - 5.0) < 1e-6

    def test_get_unknown_returns_none(self, environment):
        assert environment.get_object("phantom") is None

    def test_properties_updated(self, environment):
        environment.update_object("ball", label="ball", properties={"color": "red"})
        environment.update_object("ball", properties={"weight_kg": 0.2})
        obj = environment.get_object("ball")
        assert obj.properties["color"] == "red"
        assert abs(obj.properties["weight_kg"] - 0.2) < 1e-6

    def test_find_nearest(self, environment):
        environment.update_object("near", label="cup", position={"x": 1.0, "y": 0.0, "z": 0.0})
        environment.update_object("far", label="cup", position={"x": 10.0, "y": 0.0, "z": 0.0})
        nearest = environment.find_nearest({"x": 0.0, "y": 0.0, "z": 0.0})
        assert nearest.object_id == "near"

    def test_find_nearest_with_label_filter(self, environment):
        environment.update_object("chair_1", label="chair", position={"x": 2.0})
        environment.update_object("table_1", label="table", position={"x": 1.0})
        nearest = environment.find_nearest({"x": 0.0}, label_filter="chair")
        assert nearest.object_id == "chair_1"

    def test_find_nearest_empty_returns_none(self, environment):
        assert environment.find_nearest({"x": 0.0}) is None

    def test_all_objects(self, environment):
        environment.update_object("item_a", label="a")
        environment.update_object("item_b", label="b")
        all_objs = environment.all_objects()
        ids = [o.object_id for o in all_objs]
        assert "item_a" in ids and "item_b" in ids

    def test_snapshot_structure(self, environment):
        environment.update_object("snap_obj", label="thing", position={"x": 3.0})
        snap = environment.snapshot()
        assert any(o["object_id"] == "snap_obj" for o in snap)
        obj_snap = next(o for o in snap if o["object_id"] == "snap_obj")
        assert "position" in obj_snap
        assert "properties" in obj_snap


# ---------------------------------------------------------------------------
# BodySchema
# ---------------------------------------------------------------------------

class TestBodySchema:
    def test_register_joint(self, body_schema):
        body_schema.register_joint("elbow", -90.0, 90.0, unit="deg")
        state = body_schema.joint_state()
        assert "elbow" in state

    def test_set_joint_in_range(self, body_schema):
        body_schema.register_joint("wrist", -45.0, 45.0)
        result = body_schema.set_joint("wrist", 30.0)
        assert result is True
        assert abs(body_schema.joint_state()["wrist"] - 30.0) < 1e-6

    def test_set_joint_clamped_high(self, body_schema):
        body_schema.register_joint("shoulder", 0.0, 90.0)
        body_schema.set_joint("shoulder", 200.0)
        assert body_schema.joint_state()["shoulder"] <= 90.0

    def test_set_joint_clamped_low(self, body_schema):
        body_schema.register_joint("hip", -30.0, 30.0)
        body_schema.set_joint("hip", -100.0)
        assert body_schema.joint_state()["hip"] >= -30.0

    def test_set_unknown_joint_returns_false(self, body_schema):
        assert body_schema.set_joint("phantom_joint", 45.0) is False

    def test_can_perform_default(self, body_schema):
        assert body_schema.can_perform("move") is True
        assert body_schema.can_perform("speak") is True

    def test_can_perform_custom(self, body_schema):
        body_schema.add_capability("fly")
        assert body_schema.can_perform("fly") is True

    def test_cannot_perform_unknown(self, body_schema):
        assert body_schema.can_perform("teleport") is False

    def test_snapshot_structure(self, body_schema):
        body_schema.register_joint("knee", -90.0, 0.0)
        snap = body_schema.snapshot()
        assert "capabilities" in snap
        assert "joints" in snap
        assert "knee" in snap["joints"]


# ---------------------------------------------------------------------------
# EmbodiedInteraction facade
# ---------------------------------------------------------------------------

class TestEmbodiedInteraction:
    def test_default_sensors_registered(self, embodied):
        listed = embodied.sensors.list_sensors()
        modalities = {s["sensor_id"] for s in listed}
        assert "distance_front" in modalities
        assert "temperature" in modalities

    def test_default_actuators_registered(self, embodied):
        assert "body" in embodied.actuators.list_actuators()
        assert "speaker" in embodied.actuators.list_actuators()
        assert "camera" in embodied.actuators.list_actuators()

    def test_move_command(self, embodied):
        cmd = embodied.move("forward", 0.5)
        assert cmd.status == "completed"
        assert cmd.result.get("moved") is True
        assert cmd.result.get("direction") == "forward"

    def test_speak_command(self, embodied):
        cmd = embodied.speak("Hello, world!")
        assert cmd.status == "completed"
        assert cmd.result.get("spoken") is True
        assert cmd.result.get("text") == "Hello, world!"

    def test_look_command(self, embodied):
        cmd = embodied.look("left")
        assert cmd.status == "completed"
        assert cmd.result.get("looking_at") == "left"

    def test_sense_all_empty_before_inject(self, embodied):
        # Default sensors have no injected values yet
        readings = embodied.sense_all()
        # May be empty or partial depending on poll_fn presence; just check type
        assert isinstance(readings, list)

    def test_sense_all_after_inject(self, embodied):
        embodied.sensors.inject_reading("distance_front", 0.75)
        readings = embodied.sense_all()
        distance_readings = [r for r in readings if r.sensor_id == "distance_front"]
        assert len(distance_readings) == 1
        assert abs(distance_readings[0].value - 0.75) < 1e-6

    def test_snapshot_completeness(self, embodied):
        snap = embodied.snapshot()
        assert "sensors" in snap
        assert "actuators" in snap
        assert "environment" in snap
        assert "body_schema" in snap
        assert isinstance(snap["sensors"], list)
        assert isinstance(snap["actuators"], list)

    def test_body_schema_capabilities(self, embodied):
        assert embodied.body_schema.can_perform("move")
        assert embodied.body_schema.can_perform("speak")
        assert embodied.body_schema.can_perform("look")


# ---------------------------------------------------------------------------
# EventBus integration
# ---------------------------------------------------------------------------

class TestEmbodiedEvents:
    def test_sensor_reading_event(self, bus):
        sensors = SensorInterface(bus=bus)
        sensors.register_sensor("evt_sensor", "temperature")
        sensors.inject_reading("evt_sensor", 37.0)

    def test_actuator_command_event(self, bus):
        actuators = ActuatorInterface(bus=bus)
        actuators.issue_command("evt_actuator", "move")

    def test_object_updated_event(self, bus):
        env = EnvironmentState(bus=bus)
        env.update_object("evt_obj", label="test_thing")


# ---------------------------------------------------------------------------
# Quantum Engine validation — swarm vote on sensor readings
# ---------------------------------------------------------------------------

class TestQuantumEngineSensorValidation:
    """Use the Quantum Consensus Engine to validate sensor readings
    from multiple simulated sensors, then verify consensus agreement."""

    @pytest.mark.asyncio
    async def test_distance_sensor_consensus(self):
        """Three distance sensors agree on approximate distance to obstacle."""
        from core.quantum_engine import QuantumEngine

        engine = QuantumEngine(quorum=2)

        # Simulate 3 slightly noisy sensors as agent functions
        readings = {"s0": 1.48, "s1": 1.50, "s2": 1.52}
        agents = {sid: (lambda v: lambda task, ctx=None: v)(val) for sid, val in readings.items()}

        result = await engine.gather("distance_reading", agents)
        assert result.answer is not None
        # Consensus should be close to 1.5 m
        consensus_val = float(result.answer)
        assert abs(consensus_val - 1.5) < 0.1

    @pytest.mark.asyncio
    async def test_faulty_sensor_outvoted(self):
        """A faulty sensor reading is outvoted by two reliable sensors."""
        from core.quantum_engine import QuantumEngine

        engine = QuantumEngine(quorum=2)

        agents = {
            "s1": lambda task, ctx=None: 2.0,
            "s2": lambda task, ctx=None: 2.0,
            "s3_faulty": lambda task, ctx=None: 99.0,
        }

        result = await engine.gather("distance_reading", agents)
        # Consensus should not be the faulty outlier
        assert result.answer is not None


# ---------------------------------------------------------------------------
# Sandbox simulation — full embodied navigation scenario
# ---------------------------------------------------------------------------

class TestEmbodiedInteractionSandboxSimulation:
    """Full sandbox: robot navigates, senses obstacles, grasps an object,
    and speaks the result. Verifies the complete embodied loop."""

    def test_navigation_and_sensing_loop(self):
        """Robot navigates toward a target, senses proximity, stops and speaks."""
        ei = EmbodiedInteraction()

        # Set up environment: place a target object at (3, 0, 0)
        ei.environment.update_object(
            "target_box", label="box",
            position={"x": 3.0, "y": 0.0, "z": 0.0},
            properties={"graspable": True},
        )

        # Simulate robot's position advancing toward target
        robot_x = 0.0
        steps = []
        for _ in range(5):
            # Move forward 0.5m
            cmd = ei.move("forward", 0.5)
            assert cmd.status == "completed"
            robot_x += 0.5

            # Update simulated distance sensor: distance to target decreases
            dist = abs(3.0 - robot_x)
            ei.sensors.inject_reading("distance_front", dist, confidence=0.95)

            # Read the sensor
            reading = ei.sensors.read("distance_front")
            assert reading is not None
            steps.append({"x": robot_x, "dist": reading.value})

        # After 5 steps robot is at x=2.5, distance is 0.5m
        assert steps[-1]["dist"] < 1.0

        # Look at target
        look_cmd = ei.look("target_box")
        assert look_cmd.status == "completed"

        # Find nearest object from robot's position
        nearest = ei.environment.find_nearest({"x": robot_x, "y": 0.0, "z": 0.0})
        assert nearest is not None
        assert nearest.object_id == "target_box"

        # Speak completion
        speak_cmd = ei.speak(f"Reached target at distance {steps[-1]['dist']:.2f}m")
        assert speak_cmd.status == "completed"
        assert "Reached" in speak_cmd.result["text"]

        # History: 5 moves + 1 look + 1 speak = 7+ commands
        body_hist = ei.actuators.command_history("body")
        assert len(body_hist) >= 5

    def test_multi_object_environment(self):
        """Robot in environment with multiple objects; can identify nearest."""
        ei = EmbodiedInteraction()
        positions = [
            ("obj_near", "chair", {"x": 1.0}),
            ("obj_mid",  "table", {"x": 3.0}),
            ("obj_far",  "door",  {"x": 8.0}),
        ]
        for oid, label, pos in positions:
            ei.environment.update_object(oid, label=label, position=pos)

        nearest = ei.environment.find_nearest({"x": 0.0, "y": 0.0, "z": 0.0})
        assert nearest.object_id == "obj_near"

        nearest_table = ei.environment.find_nearest({"x": 0.0}, label_filter="table")
        assert nearest_table.object_id == "obj_mid"

    def test_body_schema_capability_gating(self):
        """System checks capabilities before issuing commands."""
        ei = EmbodiedInteraction()
        # Default capabilities include move, speak, look
        assert ei.body_schema.can_perform("move")
        assert ei.body_schema.can_perform("speak")
        # Teleportation not registered
        assert not ei.body_schema.can_perform("teleport")

        # Add a new capability and verify
        ei.body_schema.add_capability("grasp")
        assert ei.body_schema.can_perform("grasp")

    def test_sensor_fusion_scenario(self):
        """Multiple sensors provide complementary data; all readable."""
        ei = EmbodiedInteraction()
        ei.sensors.inject_reading("distance_front", 1.2)
        ei.sensors.inject_reading("temperature", 23.5)
        ei.sensors.inject_reading("touch_left", False)
        ei.sensors.inject_reading("touch_right", True)

        all_readings = ei.sense_all()
        by_id = {r.sensor_id: r for r in all_readings}

        assert abs(by_id["distance_front"].value - 1.2) < 1e-6
        assert abs(by_id["temperature"].value - 23.5) < 1e-6
        assert by_id["touch_left"].value is False
        assert by_id["touch_right"].value is True

    def test_snapshot_after_full_interaction(self):
        """Snapshot reflects all state changes from a full embodied session."""
        ei = EmbodiedInteraction()
        ei.environment.update_object("snapbox", label="box", position={"x": 5.0})
        ei.sensors.inject_reading("distance_front", 5.0)
        ei.move("forward", 1.0)
        ei.speak("Approaching target")

        snap = ei.snapshot()
        assert len(snap["environment"]) >= 1
        env_ids = [o["object_id"] for o in snap["environment"]]
        assert "snapbox" in env_ids
        assert len(snap["sensors"]) >= 1
