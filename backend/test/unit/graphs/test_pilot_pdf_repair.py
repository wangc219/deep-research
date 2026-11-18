from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter

from platform_core.knowledge.training.pilot_pdf_repair import repair_missing_pages_root


def test_missing_pages_root_repair_generates_separate_valid_candidate(tmp_path: Path) -> None:
    source = tmp_path / "broken.pdf"
    output = tmp_path / "candidate.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=320, height=240)
    writer.write(source)
    original = source.read_bytes()
    pages_root_id = int(re.search(rb"/Pages\s+(\d+)\s+0\s+R", original).group(1))
    objects = list(re.finditer(rb"(?:^|[\r\n])(\d+)\s+0\s+obj\s*(.*?)\s*endobj", original, re.DOTALL))
    page_id = next(
        int(match.group(1))
        for match in objects
        if re.search(rb"/Type\s*/Page(?!s)", match.group(2))
        and re.search(rb"/Parent\s+" + str(pages_root_id).encode() + rb"\s+0\s+R", match.group(2))
    )
    root_match = re.search(
        rb"(?:^|[\r\n])" + str(pages_root_id).encode() + rb"\s+0\s+obj\s*.*?\s*endobj",
        original,
        re.DOTALL,
    )
    broken = (
        original[: root_match.start()]
        + b"\n"
        + b" " * (root_match.end() - root_match.start() - 1)
        + original[root_match.end() :]
    )
    source.write_bytes(broken)

    report = repair_missing_pages_root(
        source,
        output,
        expected_source_sha256=hashlib.sha256(broken).hexdigest(),
        pages_root_object_id=pages_root_id,
        page_object_ids=[page_id],
    )

    assert source.read_bytes() == broken
    assert output.read_bytes().startswith(broken)
    assert len(PdfReader(output).pages) == 1
    assert report["validation"]["all_pages_loadable"] is True
    assert report["adoption_status"] == "human_review_required"


def test_repair_refuses_wrong_hash_and_existing_output(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    output = tmp_path / "candidate.pdf"
    source.write_bytes(b"%PDF-invalid")

    with pytest.raises(ValueError, match="SHA-256"):
        repair_missing_pages_root(
            source,
            output,
            expected_source_sha256="0" * 64,
            pages_root_object_id=3,
            page_object_ids=[5],
        )

    output.write_bytes(b"existing")
    with pytest.raises(ValueError, match="拒绝覆盖"):
        repair_missing_pages_root(
            source,
            output,
            expected_source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
            pages_root_object_id=3,
            page_object_ids=[5],
        )
