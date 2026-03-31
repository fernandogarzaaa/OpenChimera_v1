from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.harness_port import HarnessPortAdapter
from core.config import ROOT, get_minimind_root, get_minimind_training_output_dir, load_runtime_profile


class MiniMindService:
    def __init__(self):
        self.root = get_minimind_root()
        self.profile = load_runtime_profile()
        self.training_output_dir = get_minimind_training_output_dir()
        self.available = (self.root / "model" / "model_minimind.py").exists()

    def status(self) -> dict[str, Any]:
        checkpoints = self._collect_weight_files(self.root / "checkpoints")
        outputs = self._collect_weight_files(self.root / "out")
        datasets = self._collect_jsonl_files(self.root / "dataset")
        reasoning_engine = self.profile.get("local_runtime", {}).get("reasoning_engine")
        return {
            "available": self.available,
            "root": str(self.root),
            "reasoning_engine": reasoning_engine,
            "model_definition": str(self.root / "model" / "model_minimind.py"),
            "api_script": str(self.root / "scripts" / "serve_openai_api.py"),
            "trainer_script": str(self.root / "trainer" / "train_reason.py"),
            "training_output_dir": str(self.training_output_dir),
            "checkpoints": checkpoints,
            "out_weights": outputs,
            "datasets": datasets,
        }

    def build_training_dataset(
        self,
        harness_port: HarnessPortAdapter,
        identity_snapshot: dict[str, Any],
        force: bool = True,
    ) -> dict[str, Any]:
        self.training_output_dir.mkdir(parents=True, exist_ok=True)
        sft_path = self.training_output_dir / "harness_openchimera_sft.jsonl"
        pretrain_path = self.training_output_dir / "harness_openchimera_pretrain.jsonl"
        manifest_path = self.training_output_dir / "harness_openchimera_dataset_manifest.json"

        sft_records = self._build_sft_records(harness_port, identity_snapshot)
        pretrain_records = self._build_pretrain_records(harness_port, identity_snapshot)

        if force or not sft_path.exists():
            self._write_jsonl(sft_path, sft_records)
        if force or not pretrain_path.exists():
            self._write_jsonl(pretrain_path, pretrain_records)

        manifest = {
            "generated_from": {
                "openchimera_root": str(ROOT),
                "harness_repo_root": str(harness_port.root),
                "minimind_root": str(self.root),
            },
            "files": {
                "sft": str(sft_path),
                "pretrain": str(pretrain_path),
            },
            "counts": {
                "sft_records": len(sft_records),
                "pretrain_records": len(pretrain_records),
            },
            "recommended_commands": {
                "reason_sft": (
                    f"python {self.root / 'trainer' / 'train_reason.py'} "
                    f"--data_path {sft_path} --epochs 1 --batch_size 4 --device cuda:0"
                ),
                "pretrain": (
                    f"python {self.root / 'trainer' / 'train_pretrain.py'} "
                    f"--data_path {pretrain_path} --epochs 1 --batch_size 8 --device cuda:0"
                ),
            },
        }
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return manifest

    def _build_sft_records(
        self,
        harness_port: HarnessPortAdapter,
        identity_snapshot: dict[str, Any],
    ) -> list[dict[str, Any]]:
        harness_status = harness_port.status()
        runtime_summary = self._build_runtime_summary(identity_snapshot)
        training_strategy = self._build_training_strategy(harness_status, identity_snapshot)
        checkpoint_summary = self._build_checkpoint_summary()
        records = harness_port.build_sft_examples()
        system_prompt = (
            "You are MiniMind, the compact reasoning engine embedded in OpenChimera. "
            "Use architectural context carefully, keep claims grounded in local files, and be explicit about what is only a training artifact."
        )
        records.extend(
            [
                {
                    "conversations": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": "Summarize OpenChimera's current runtime and subsystem layout."},
                        {"role": "assistant", "content": runtime_summary},
                    ]
                },
                {
                    "conversations": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": "How should upstream harness-derived data be used to train MiniMind inside OpenChimera?"},
                        {"role": "assistant", "content": training_strategy},
                    ]
                },
                {
                    "conversations": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": "What MiniMind checkpoints and datasets are currently available?"},
                        {"role": "assistant", "content": checkpoint_summary},
                    ]
                },
            ]
        )
        return records

    def _build_pretrain_records(
        self,
        harness_port: HarnessPortAdapter,
        identity_snapshot: dict[str, Any],
    ) -> list[dict[str, str]]:
        harness_status = harness_port.status()
        records = [
            {"text": harness_status.get("summary", "")},
            {"text": self._build_runtime_summary(identity_snapshot)},
            {"text": self._build_training_strategy(harness_status, identity_snapshot)},
            {"text": self._build_checkpoint_summary()},
        ]
        readme_path = ROOT / "README.md"
        if readme_path.exists():
            records.append({"text": readme_path.read_text(encoding="utf-8", errors="ignore")[:4000]})
        records.append(
            {
                "text": (
                    "Upstream harness source is mounted locally for architectural study only. "
                    "OpenChimera uses sanitized manifest, command, tool, and workflow summaries rather than raw branded README text."
                )
            }
        )
        proposal_path = self.root / "CHIMERA_MINI_PROPOSAL.md"
        if proposal_path.exists():
            records.append({"text": proposal_path.read_text(encoding="utf-8", errors="ignore")[:4000]})
        return [record for record in records if record.get("text")]

    def _build_runtime_summary(self, identity_snapshot: dict[str, Any]) -> str:
        hardware = identity_snapshot.get("hardware", {})
        local_runtime = identity_snapshot.get("local_runtime", {})
        model_inventory = identity_snapshot.get("model_inventory", {})
        integration_roots = identity_snapshot.get("integration_roots", {})
        return (
            "OpenChimera is a local orchestration runtime rooted at "
            f"{identity_snapshot.get('root', 'unknown')}. "
            "It hosts an OpenAI-compatible provider, retrieval layer, token compression, and local llama.cpp process control. "
            f"Preferred local models: {', '.join(local_runtime.get('preferred_local_models', [])) or 'unknown'}. "
            f"Available model inventory: {', '.join(model_inventory.get('available_models', [])) or 'unknown'}. "
            f"Reasoning engine target: {identity_snapshot.get('reasoning_engine', 'unknown')}. "
            f"Harness repo root: {integration_roots.get('harness_repo', 'unknown')}. "
            f"MiniMind root: {integration_roots.get('minimind', 'unknown')}. "
            f"Hardware: cpu_count={hardware.get('cpu_count', 'unknown')}, ram_gb={hardware.get('ram_gb', 'unknown')}, "
            f"gpu={hardware.get('gpu', {}).get('name', 'unknown')}, vram_gb={hardware.get('gpu', {}).get('vram_gb', 'unknown')}."
        )

    def _build_training_strategy(self, harness_status: dict[str, Any], identity_snapshot: dict[str, Any]) -> str:
        command_names = ", ".join(item["name"] for item in harness_status.get("commands", [])) or "none"
        tool_names = ", ".join(item["name"] for item in harness_status.get("tools", [])) or "none"
        return (
            "Use the upstream Python harness port as a curriculum source rather than pretending it is a drop-in model backend. "
            "Train MiniMind on structured architecture summaries, command metadata, tool metadata, and OpenChimera runtime descriptions so it learns the harness shape and operational language. "
            f"Current harness-derived commands: {command_names}. Current harness-derived tools: {tool_names}. "
            "This exported dataset is intended for local SFT or light reasoning distillation, not for claiming upstream model parity."
        )

    def _build_checkpoint_summary(self) -> str:
        status = self.status()
        checkpoints = status.get("checkpoints", [])
        out_weights = status.get("out_weights", [])
        datasets = status.get("datasets", [])
        return (
            f"MiniMind checkpoints: {', '.join(checkpoints) if checkpoints else 'none found'}. "
            f"Output weights: {', '.join(out_weights) if out_weights else 'none found'}. "
            f"Datasets: {', '.join(datasets) if datasets else 'none found'}."
        )

    def _collect_weight_files(self, directory: Path) -> list[str]:
        if not directory.exists():
            return []
        return sorted(str(path) for path in directory.glob("*.pth"))

    def _collect_jsonl_files(self, directory: Path) -> list[str]:
        if not directory.exists():
            return []
        return sorted(str(path) for path in directory.glob("*.jsonl"))

    def _write_jsonl(self, output_path: Path, records: list[dict[str, Any]]) -> None:
        with output_path.open("w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(self._sanitize_record(record), ensure_ascii=True) + "\n")

    def _sanitize_record(self, record: dict[str, Any]) -> dict[str, Any]:
        raw = json.dumps(record, ensure_ascii=False)
        raw = raw.replace("Claude Code", "Upstream Harness")
        raw = raw.replace("claude-code", "upstream-harness-repo")
        raw = raw.replace("Claude", "Harness")
        raw = raw.replace("Anthropic", "upstream vendor")
        return json.loads(raw)