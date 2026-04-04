from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


class ContainerAssetTests(unittest.TestCase):
    def test_dockerfile_exposes_runtime_healthcheck(self) -> None:
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("FROM python:3.11-slim", dockerfile)
        self.assertIn("HEALTHCHECK", dockerfile)
        self.assertIn('CMD ["python", "run.py", "serve"]', dockerfile)

    def test_compose_persists_runtime_state(self) -> None:
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn("openchimera-data:/app/data", compose)
        self.assertIn("openchimera-logs:/app/logs", compose)
        self.assertIn("openchimera-models:/app/models", compose)
        self.assertIn("./config/runtime_profile.local.json:/app/config/runtime_profile.local.json:ro", compose)
        self.assertIn("OPENCHIMERA_API_TOKEN: ${OPENCHIMERA_API_TOKEN}", compose)
        self.assertIn("OPENCHIMERA_ADMIN_TOKEN: ${OPENCHIMERA_ADMIN_TOKEN}", compose)

    def test_dockerignore_excludes_runtime_state(self) -> None:
        dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
        self.assertIn(".venv", dockerignore)
        self.assertIn("data/**", dockerignore)
        self.assertIn("logs/**", dockerignore)
        self.assertIn("models/**", dockerignore)

    def test_python_ci_uses_release_validation_and_package_smoke(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "python-ci.yml").read_text(encoding="utf-8")
        self.assertIn("python -m pre_commit run --all-files", workflow)
        self.assertIn("python run.py validate", workflow)
        self.assertIn("python run.py validate --pattern test_*.py", workflow)
        self.assertIn("Full discovery sweep", workflow)
        self.assertIn("openchimera doctor --production --json", workflow)
        self.assertIn("openchimera backup create --json", workflow)

    def test_quality_gate_scripts_wrap_pre_commit_and_validate(self) -> None:
        powershell_script = (ROOT / "scripts" / "run-quality-gate.ps1").read_text(encoding="utf-8")
        shell_script = (ROOT / "scripts" / "run-quality-gate.sh").read_text(encoding="utf-8")
        self.assertIn("python -m pre_commit run --all-files", powershell_script)
        self.assertIn("python run.py validate --pattern $TestPattern", powershell_script)
        self.assertIn("python -m pre_commit run --all-files", shell_script)
        self.assertIn('python run.py validate --pattern "$TEST_PATTERN"', shell_script)

    def test_pre_commit_config_covers_basic_repo_hygiene(self) -> None:
        config = (ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
        self.assertIn("check-yaml", config)
        self.assertIn("trailing-whitespace", config)
        self.assertIn("check-merge-conflict", config)

    def test_release_workflow_runs_production_smoke_checks(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "deploy.yml").read_text(encoding="utf-8")
        self.assertIn("openchimera doctor --production --json", workflow)
        self.assertIn("openchimera backup create --json", workflow)