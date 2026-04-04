"""
SkillsPlane
===========
Runtime facade for the OpenChimera skills/  directory.

Responsibilities:
- Discover installed skills (delegating parse to CapabilityRegistry)
- Expose a queryable inventory by id, name, category, or keyword
- Load and cache per-skill Python modules on first invocation
- Invoke skill entry-points with structured input and return output
- Emit lifecycle events over the bus (skill.discovered, skill.invoked, skill.error)
"""
from __future__ import annotations

import importlib.util
import json
import sys
import traceback
from pathlib import Path
from typing import Any, Optional

from core.capabilities import CapabilityRegistry
from core.config import ROOT


class SkillsPlane:
    """Runtime interface for the skills/ directory."""

    def __init__(
        self,
        bus: Any | None = None,
        root: Path | None = None,
    ) -> None:
        self._root = root or ROOT
        self._bus = bus
        self._registry = CapabilityRegistry(root=self._root)
        self._loaded_modules: dict[str, Any] = {}  # skill_id → module

    # ------------------------------------------------------------------
    # Public status / discovery API
    # ------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        """Lightweight status without loading every skill module."""
        skills = self._registry.list_kind("skills")
        return {
            "total": len(skills),
            "loaded": len(self._loaded_modules),
            "root": str(self._root / "skills"),
        }

    def list_skills(
        self,
        category: str | None = None,
        keyword: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return all discovered skills, optionally filtered by category and/or keyword."""
        skills = self._registry.list_kind("skills")
        if category:
            skills = [s for s in skills if s.get("category", "").lower() == category.lower()]
        if keyword:
            kw = keyword.lower()
            skills = [
                s for s in skills
                if kw in s.get("name", "").lower()
                or kw in s.get("description", "").lower()
                or kw in s.get("id", "").lower()
            ]
        return skills

    def get_skill(self, skill_id: str) -> dict[str, Any] | None:
        """Return the metadata record for a single skill, or None if not found."""
        for skill in self._registry.list_kind("skills"):
            if skill["id"] == skill_id:
                return skill
        return None

    def categories(self) -> list[str]:
        """Return unique skill categories, sorted."""
        return sorted({s.get("category", "unknown") for s in self._registry.list_kind("skills")})

    # ------------------------------------------------------------------
    # Runtime invocation
    # ------------------------------------------------------------------

    def load_skill_module(self, skill_id: str) -> Any:
        """
        Import and cache the Python module associated with a skill.

        Discovery strategy (first match wins):
          1. <skills_root>/<skill_dir>/<skill_id_normalized>.py
          2. Any *.py file directly inside the skill directory
          3. <skills_root>/<skill_dir>/scripts/<any>.py

        Returns the loaded module or raises ImportError if nothing is found.
        """
        if skill_id in self._loaded_modules:
            return self._loaded_modules[skill_id]

        skill = self.get_skill(skill_id)
        if skill is None:
            raise ImportError(f"Skill '{skill_id}' is not registered")

        skill_dir = Path(skill["path"]).parent
        candidates: list[Path] = []

        # Strategy 1: file named after normalized skill id
        normalized = skill_id.replace("-", "_")
        candidates.append(skill_dir / f"{normalized}.py")

        # Strategy 2: any .py directly in skill_dir
        candidates.extend(sorted(p for p in skill_dir.glob("*.py") if p.name != "__init__.py"))

        # Strategy 3: scripts/ sub-directory
        scripts_dir = skill_dir / "scripts"
        if scripts_dir.exists():
            candidates.extend(sorted(scripts_dir.glob("*.py")))

        for py_file in candidates:
            if py_file.exists():
                module = _load_py_file(py_file, module_name=f"_skills.{skill_id}")
                self._loaded_modules[skill_id] = module
                return module

        raise ImportError(
            f"No Python module found for skill '{skill_id}' in {skill_dir}"
        )

    def invoke_skill(
        self,
        skill_id: str,
        function: str = "run",
        args: tuple = (),
        kwargs: dict[str, Any] | None = None,
    ) -> Any:
        """
        Load and call a function inside a skill module.

        Parameters
        ----------
        skill_id : str
            The skill identifier as discovered (e.g. "agent-audit-trail").
        function : str
            Name of the callable to invoke inside the module.
        args : tuple
            Positional args forwarded.
        kwargs : dict, optional
            Keyword args forwarded.

        Returns
        -------
        The result of calling the function.
        """
        kwargs = kwargs or {}
        self._publish("skill.invoke_requested", {"skill_id": skill_id, "function": function})
        try:
            module = self.load_skill_module(skill_id)
        except ImportError as exc:
            self._publish("skill.error", {"skill_id": skill_id, "error": str(exc)})
            raise

        fn = getattr(module, function, None)
        if fn is None or not callable(fn):
            err = f"Skill '{skill_id}' has no callable '{function}'"
            self._publish("skill.error", {"skill_id": skill_id, "error": err})
            raise AttributeError(err)

        try:
            result = fn(*args, **kwargs)
            self._publish("skill.invoked", {"skill_id": skill_id, "function": function})
            return result
        except Exception as exc:
            tb = traceback.format_exc()
            self._publish("skill.error", {"skill_id": skill_id, "error": str(exc), "traceback": tb})
            raise

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _publish(self, event: str, payload: dict[str, Any]) -> None:
        if self._bus is None:
            return
        try:
            self._bus.publish(event, payload)
        except Exception:
            pass  # bus failures must never crash the skills plane


# ---------------------------------------------------------------------------
# Module loader utility (no dependency on core.integration to stay minimal)
# ---------------------------------------------------------------------------

def _load_py_file(path: Path, module_name: str) -> Any:
    """Load a .py file into a named module using importlib."""
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot create module spec for {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)  # type: ignore[union-attr]
    except Exception:
        del sys.modules[module_name]
        raise
    return module
