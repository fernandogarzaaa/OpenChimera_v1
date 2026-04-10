# CHIMERA_HARNESS: plan_mode
"""
PlanModeContext: Singleton for toggling plan (read-only) mode in OpenChimera.
Blocks side-effecting tool calls and logs plan steps for system prompt injection.
"""
from typing import List
from threading import Lock

class PlanModeContext:
    _instance = None
    _lock = Lock()

    def __init__(self) -> None:
        self.is_planning: bool = False
        self.plan_steps: List[str] = []

    @classmethod
    def instance(cls) -> "PlanModeContext":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def enter_plan_mode(self) -> None:
        self.is_planning = True
        self.plan_steps.clear()

    def exit_plan_mode(self) -> None:
        self.is_planning = False
        self.plan_steps.clear()

    def log_step(self, step: str) -> None:
        if self.is_planning:
            self.plan_steps.append(step)
