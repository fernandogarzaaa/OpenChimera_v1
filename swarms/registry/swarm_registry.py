"""SwarmRegistry — maps objective patterns to swarm compositions via regex."""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

# Pattern tuples: (compiled_regex, swarm_name, description)
_DEFAULT_PATTERNS: List[Tuple[re.Pattern, str, str]] = [
    (
        re.compile(r"code|program|develop|implement|build|feature", re.IGNORECASE),
        "coding_swarm",
        "Software development and feature implementation",
    ),
    (
        re.compile(r"security|audit|vuln|pentest|threat|exploit|CVE", re.IGNORECASE),
        "security_swarm",
        "Security analysis and vulnerability assessment",
    ),
    (
        re.compile(r"arch|design|scale|infra|blueprint|system design", re.IGNORECASE),
        "architect_swarm",
        "Architectural design and system planning",
    ),
    (
        re.compile(r"debug|fix|error|bug|crash|traceback|exception", re.IGNORECASE),
        "debug_swarm",
        "Debugging and error resolution",
    ),
]

_DEFAULT_SWARM = "god_swarm"


class SwarmRegistry:
    """
    Maps free-text objectives to pre-defined swarm compositions via regex.

    Built-in patterns ship with the class.  Callers can add custom patterns
    at runtime via :meth:`register_pattern`.
    """

    def __init__(self) -> None:
        self._patterns: List[Tuple[re.Pattern, str, str]] = list(_DEFAULT_PATTERNS)

    def register_pattern(self, pattern: str, swarm_name: str, description: str = "") -> None:
        """Add a new regex → swarm_name mapping."""
        compiled = re.compile(pattern, re.IGNORECASE)
        self._patterns.append((compiled, swarm_name, description))

    def resolve(self, objective: str) -> str:
        """
        Return the swarm_name whose pattern first matches *objective*.
        Falls back to ``"god_swarm"`` when no pattern matches.
        """
        for pattern, swarm_name, _ in self._patterns:
            if pattern.search(objective):
                return swarm_name
        return _DEFAULT_SWARM

    def resolve_all(self, objective: str) -> List[str]:
        """Return all matching swarm names (may be empty → caller uses default)."""
        matches = [name for pattern, name, _ in self._patterns if pattern.search(objective)]
        return matches or [_DEFAULT_SWARM]

    def list_patterns(self) -> List[dict]:
        return [
            {"pattern": p.pattern, "swarm": name, "description": desc}
            for p, name, desc in self._patterns
        ]
