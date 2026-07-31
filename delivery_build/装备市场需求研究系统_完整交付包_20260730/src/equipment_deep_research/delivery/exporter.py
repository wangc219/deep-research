from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any


REQUIRED_OUTPUTS = (
    "report.md",
    "capability_images.json",
    "branch_deliverables.json",
    "round_summary.json",
    "domain.jsonl",
    "trace.jsonl",
)

_BRANCH_REQUIRED_OUTPUTS = {
    "B": (
        "demand_cards.json",
        "capability_panorama.json",
        "reasoning_traceability.json",
    ),
    # D–H 按"类似输出"要求统一交付需求卡片
    **{code: ("demand_cards.json",) for code in "DEFGH"},
}


class DeliveryExporter:
    def build_manifest(self, run_dir: str | Path) -> dict[str, Any]:
        root = Path(run_dir).resolve()
        if not root.is_dir():
            raise FileNotFoundError(root)
        required_outputs = _required_outputs_for_run(root)
        missing = [name for name in required_outputs if not (root / name).is_file()]
        if missing:
            raise ValueError(f"run output is incomplete: {missing}")
        files = []
        for path in sorted(item for item in root.rglob("*") if item.is_file() and item.name != "delivery-manifest.json"):
            relative = path.relative_to(root).as_posix()
            files.append({"path": relative, "size": path.stat().st_size, "sha256": sha256(path.read_bytes()).hexdigest()})
        manifest = {"schema_version": "1.0", "required_outputs": list(required_outputs), "files": files, "file_count": len(files)}
        (root / "delivery-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        return manifest

    def verify(self, run_dir: str | Path) -> bool:
        root = Path(run_dir).resolve()
        payload = json.loads((root / "delivery-manifest.json").read_text(encoding="utf-8"))
        return all((root / item["path"]).is_file() and sha256((root / item["path"]).read_bytes()).hexdigest() == item["sha256"] for item in payload["files"])


def _required_outputs_for_run(root: Path) -> tuple[str, ...]:
    branch = ""
    try:
        payload = json.loads((root / "branch_deliverables.json").read_text(encoding="utf-8"))
        branch = str(payload.get("branch", ""))
    except (FileNotFoundError, json.JSONDecodeError, AttributeError):
        pass
    return (*REQUIRED_OUTPUTS, *_BRANCH_REQUIRED_OUTPUTS.get(branch, ()))
