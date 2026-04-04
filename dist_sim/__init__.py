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
from .harness import run_sim_scenario
from .node import SimNode

__all__ = ["SimCluster", "SimNode", "run_sim_scenario"]
