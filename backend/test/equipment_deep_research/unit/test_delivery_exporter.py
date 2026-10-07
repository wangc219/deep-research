from pathlib import Path

import pytest
import json

from equipment_deep_research.delivery.exporter import DeliveryExporter, REQUIRED_OUTPUTS


def test_delivery_manifest_hashes_and_verifies_all_outputs(tmp_path: Path) -> None:
    for name in REQUIRED_OUTPUTS:
        (tmp_path / name).write_text(f"content:{name}", encoding="utf-8")
    manifest = DeliveryExporter().build_manifest(tmp_path)
    assert manifest["file_count"] == len(REQUIRED_OUTPUTS)
    assert DeliveryExporter().verify(tmp_path)
    (tmp_path / "report.md").write_text("tampered", encoding="utf-8")
    assert not DeliveryExporter().verify(tmp_path)


def test_delivery_rejects_incomplete_run(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="incomplete"):
        DeliveryExporter().build_manifest(tmp_path)


def test_b_branch_requires_its_three_traceable_capability_artifacts(tmp_path: Path) -> None:
    for name in REQUIRED_OUTPUTS:
        (tmp_path / name).write_text("{}" if name == "branch_deliverables.json" else "content", encoding="utf-8")
    (tmp_path / "branch_deliverables.json").write_text(
        json.dumps({"branch": "B"}), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="demand_cards.json"):
        DeliveryExporter().build_manifest(tmp_path)

    for name in ("demand_cards.json", "capability_panorama.json", "reasoning_traceability.json"):
        (tmp_path / name).write_text("{}", encoding="utf-8")
    assert DeliveryExporter().build_manifest(tmp_path)["required_outputs"][-3:] == [
        "demand_cards.json",
        "capability_panorama.json",
        "reasoning_traceability.json",
    ]


@pytest.mark.parametrize("branch", list("DEFGH"))
def test_similar_branches_require_demand_cards_output(tmp_path: Path, branch: str) -> None:
    for name in REQUIRED_OUTPUTS:
        (tmp_path / name).write_text("content", encoding="utf-8")
    (tmp_path / "branch_deliverables.json").write_text(
        json.dumps({"branch": branch}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="demand_cards.json"):
        DeliveryExporter().build_manifest(tmp_path)
    (tmp_path / "demand_cards.json").write_text("{}", encoding="utf-8")
    assert DeliveryExporter().build_manifest(tmp_path)["required_outputs"][-1] == "demand_cards.json"
