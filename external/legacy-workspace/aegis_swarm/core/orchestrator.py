"""
AegisSwarm SwarmOrchestrator — OpenChimera external integration.

Top-level imports are deferred into __init__ so this module can be loaded
(and the class reference obtained via getattr) on any machine, even those
without the full AegisSwarm SDK installed.  If the SDK is absent the
orchestrator raises an ImportError only when instantiated, not at import time.
"""
import os
import sys

# Set root project path so AegisSwarm-internal imports resolve when the SDK
# is present alongside this file.
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)


class SwarmOrchestrator:
    def __init__(self, target_project):
        # Defer heavy SDK imports so the class is *definable* on any machine.
        # ImportError is raised here (at instantiation time) rather than at
        # module-load time, which lets aegis_service.py obtain the class
        # reference and report availability cleanly.
        try:
            from swarms.analysis import AnalysisSwarm  # noqa: PLC0415
            from swarms.audit import AuditSwarm  # noqa: PLC0415
            from swarms.devops import DevOpsSwarm  # noqa: PLC0415
            from swarms.god import GodSwarm  # noqa: PLC0415
            from core.whatsapp import WhatsAppNotifier  # noqa: PLC0415
            from core.token_manager import TokenManager  # noqa: PLC0415
        except ImportError as exc:
            raise ImportError(
                f"AegisSwarm SDK not found ({exc}). "
                "Ensure the AegisSwarm project is installed or its root is on PYTHONPATH."
            ) from exc

        self.target = target_project
        self.analysis = AnalysisSwarm()
        self.audit = AuditSwarm()
        self.devops = DevOpsSwarm()
        self.god = GodSwarm()
        self.notifier = WhatsAppNotifier()
        self.tm = TokenManager()

    def run(self):
        print(f"--- Production Evolution Cycle: {self.target} ---")

        # 1. Activation
        report = self.analysis.run(self.target)
        report = self.tm.fracture(str(report))

        # 2. Audit Swarm
        audit = self.audit.run(self.target, report)

        # 3. DevOps Swarm (Sandbox)
        sandbox = self.devops.prepare_sandbox(self.target, audit)

        # 4. God Swarm
        print("--- CIRCUIT BREAKER: Human Approval Required ---")
        status = self.god.verify(sandbox)

        # 5. Report
        self.notifier.notify(f"Production Ready: {status}")
        return status
