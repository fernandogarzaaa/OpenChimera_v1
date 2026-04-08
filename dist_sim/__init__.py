"""OpenChimera Distributed Simulation Environment.

Provides a lightweight, fully in-process distributed simulation layer for
stress-testing the QuantumEngine consensus control plane.

Public API
----------
SimNode     — A single simulated node wrapping a QuantumEngine instance.
SimCluster  — Round-robin load balancer over multiple SimNodes.
run_sim_scenario — General harness that runs a task list against a cluster.
"""
from .cluster import SimCluster
from .cognitive_scenarios import run_all_cognitive
from .harness import run_concurrent_scenario, run_sim_scenario
from .multi_agent_scenarios import run_all_extended
from .node import SimNode

__all__ = [
    "SimCluster",
    "SimNode",
    "run_sim_scenario",
    "run_concurrent_scenario",
    "run_all_extended",
    "run_all_cognitive",
]
