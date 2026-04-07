"""OpenChimera PlanMode — Structured planning and execution state machine.

Provides plan creation, step tracking, and plan execution state management
for multi-step agent tasks and autonomous operations.

Architecture
────────────
PlanMode        Main class for creating and executing plans
PlanStep        Individual step in a plan
PlanStatus      Plan execution status enum
"""
from __future__ import annotations

import enum
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)


class PlanStatus(enum.Enum):
    """Status of a plan."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"


class StepStatus(enum.Enum):
    """Status of an individual plan step."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class PlanStep:
    """Individual step in a plan."""
    step_id: str
    description: str
    action: str
    parameters: dict[str, Any] = field(default_factory=dict)
    status: StepStatus = StepStatus.PENDING
    dependencies: list[str] = field(default_factory=list)
    result: Any = None
    error: str | None = None
    started_at: float | None = None
    completed_at: float | None = None


@dataclass
class Plan:
    """A structured plan with multiple steps."""
    plan_id: str
    name: str
    description: str
    steps: list[PlanStep] = field(default_factory=list)
    status: PlanStatus = PlanStatus.PENDING
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    completed_at: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class PlanMode:
    """Structured planning and execution state machine.
    
    Provides:
    - Plan creation with multiple steps
    - Dependency tracking between steps
    - Step execution with status tracking
    - Plan pause/resume capability
    - Plan history and querying
    """
    
    def __init__(self, bus: Any | None = None) -> None:
        self._bus = bus
        self._plans: dict[str, Plan] = {}
        self._lock = threading.RLock()
        log.info("PlanMode initialized")
    
    def create_plan(
        self,
        name: str,
        description: str,
        steps: list[dict[str, Any]],
        metadata: dict[str, Any] | None = None,
    ) -> Plan:
        """Create a new plan.
        
        Args:
            name: Human-readable plan name
            description: Plan description
            steps: List of step definitions, each with:
                - description: str
                - action: str (command/function to execute)
                - parameters: dict (optional)
                - dependencies: list[str] (optional, step IDs this depends on)
            metadata: Optional metadata dict
            
        Returns:
            Created Plan object
        """
        with self._lock:
            plan_id = f"plan_{uuid.uuid4().hex[:8]}"
            
            plan_steps = []
            for idx, step_def in enumerate(steps):
                step_id = f"{plan_id}_step_{idx}"
                step = PlanStep(
                    step_id=step_id,
                    description=step_def.get("description", f"Step {idx + 1}"),
                    action=step_def.get("action", "unknown"),
                    parameters=step_def.get("parameters", {}),
                    dependencies=step_def.get("dependencies", []),
                )
                plan_steps.append(step)
            
            plan = Plan(
                plan_id=plan_id,
                name=name,
                description=description,
                steps=plan_steps,
                metadata=metadata or {},
            )
            
            self._plans[plan_id] = plan
            
            if self._bus:
                self._bus.publish_nowait("plan/created", {
                    "plan_id": plan_id,
                    "name": name,
                    "step_count": len(plan_steps),
                })
            
            log.info("Created plan %s with %d steps", plan_id, len(plan_steps))
            return plan
    
    def get_plan(self, plan_id: str) -> Plan | None:
        """Get a plan by ID."""
        with self._lock:
            return self._plans.get(plan_id)
    
    def list_plans(self, status: PlanStatus | None = None) -> list[Plan]:
        """List all plans, optionally filtered by status."""
        with self._lock:
            if status is None:
                return list(self._plans.values())
            return [p for p in self._plans.values() if p.status == status]
    
    def start_plan(self, plan_id: str) -> bool:
        """Start executing a plan."""
        with self._lock:
            plan = self._plans.get(plan_id)
            if plan is None:
                return False
            
            if plan.status != PlanStatus.PENDING:
                return False
            
            plan.status = PlanStatus.IN_PROGRESS
            plan.started_at = time.time()
            
            if self._bus:
                self._bus.publish_nowait("plan/started", {
                    "plan_id": plan_id,
                    "name": plan.name,
                })
            
            log.info("Started plan %s", plan_id)
            return True
    
    def update_step(
        self,
        plan_id: str,
        step_id: str,
        status: StepStatus,
        result: Any = None,
        error: str | None = None,
    ) -> bool:
        """Update the status of a plan step."""
        with self._lock:
            plan = self._plans.get(plan_id)
            if plan is None:
                return False
            
            step = next((s for s in plan.steps if s.step_id == step_id), None)
            if step is None:
                return False
            
            if status == StepStatus.IN_PROGRESS and step.started_at is None:
                step.started_at = time.time()
            
            step.status = status
            step.result = result
            step.error = error
            
            if status in (StepStatus.COMPLETED, StepStatus.FAILED, StepStatus.SKIPPED):
                step.completed_at = time.time()
            
            # Check if plan is complete
            if all(s.status in (StepStatus.COMPLETED, StepStatus.SKIPPED) for s in plan.steps):
                plan.status = PlanStatus.COMPLETED
                plan.completed_at = time.time()
                if self._bus:
                    self._bus.publish_nowait("plan/completed", {
                        "plan_id": plan_id,
                        "name": plan.name,
                        "duration": plan.completed_at - (plan.started_at or plan.created_at),
                    })
            elif any(s.status == StepStatus.FAILED for s in plan.steps):
                plan.status = PlanStatus.FAILED
                plan.completed_at = time.time()
                if self._bus:
                    self._bus.publish_nowait("plan/failed", {
                        "plan_id": plan_id,
                        "name": plan.name,
                        "failed_step": step_id,
                    })
            
            return True
    
    def get_next_step(self, plan_id: str) -> PlanStep | None:
        """Get the next executable step (dependencies satisfied, not started)."""
        with self._lock:
            plan = self._plans.get(plan_id)
            if plan is None or plan.status != PlanStatus.IN_PROGRESS:
                return None
            
            completed_steps = {s.step_id for s in plan.steps if s.status == StepStatus.COMPLETED}
            
            for step in plan.steps:
                if step.status != StepStatus.PENDING:
                    continue
                
                # Check if all dependencies are satisfied
                if all(dep in completed_steps for dep in step.dependencies):
                    return step
            
            return None
    
    def pause_plan(self, plan_id: str) -> bool:
        """Pause a plan."""
        with self._lock:
            plan = self._plans.get(plan_id)
            if plan is None or plan.status != PlanStatus.IN_PROGRESS:
                return False
            
            plan.status = PlanStatus.PAUSED
            log.info("Paused plan %s", plan_id)
            return True
    
    def resume_plan(self, plan_id: str) -> bool:
        """Resume a paused plan."""
        with self._lock:
            plan = self._plans.get(plan_id)
            if plan is None or plan.status != PlanStatus.PAUSED:
                return False
            
            plan.status = PlanStatus.IN_PROGRESS
            log.info("Resumed plan %s", plan_id)
            return True
    
    def status(self) -> dict[str, Any]:
        """Get PlanMode status."""
        with self._lock:
            return {
                "total_plans": len(self._plans),
                "pending": sum(1 for p in self._plans.values() if p.status == PlanStatus.PENDING),
                "in_progress": sum(1 for p in self._plans.values() if p.status == PlanStatus.IN_PROGRESS),
                "completed": sum(1 for p in self._plans.values() if p.status == PlanStatus.COMPLETED),
                "failed": sum(1 for p in self._plans.values() if p.status == PlanStatus.FAILED),
                "paused": sum(1 for p in self._plans.values() if p.status == PlanStatus.PAUSED),
            }
