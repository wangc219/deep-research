import json
from pathlib import Path

import pytest

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
