#!/usr/bin/env python3
"""Replace the cover's cached date text with an auto-updating PowerPoint date field."""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import uuid
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


NS_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
NS_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
NS = {"a": NS_A, "p": NS_P}

ET.register_namespace("a", NS_A)
ET.register_namespace("p", NS_P)
ET.register_namespace(
    "r", "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
)


def qn(namespace: str, tag: str) -> str:
    return f"{{{namespace}}}{tag}"


def patch_slide(xml_bytes: bytes) -> bytes:
    root = ET.fromstring(xml_bytes)
    target_paragraph = None
    source_rpr = None

    for shape in root.findall(".//p:sp", NS):
        text = "".join(shape.itertext())
        if "汇报日期" not in text:
            continue
        paragraph = shape.find("./p:txBody/a:p", NS)
        if paragraph is None:
            continue
        run = paragraph.find("a:r", NS)
        if run is None:
            continue
        target_paragraph = paragraph
        source_rpr = run.find("a:rPr", NS)
        break

    if target_paragraph is None or source_rpr is None:
        raise RuntimeError("Cover report-date text box was not found in slide 1")

    for child in list(target_paragraph):
        if child.tag in {
            qn(NS_A, "r"),
            qn(NS_A, "fld"),
            qn(NS_A, "br"),
            qn(NS_A, "endParaRPr"),
        }:
            target_paragraph.remove(child)

    prefix_run = ET.Element(qn(NS_A, "r"))
    prefix_run.append(copy.deepcopy(source_rpr))
    prefix_text = ET.SubElement(prefix_run, qn(NS_A, "t"))
    prefix_text.text = "汇报日期："
    target_paragraph.append(prefix_run)

    field = ET.Element(
        qn(NS_A, "fld"),
        {
            "id": "{" + str(uuid.uuid4()).upper() + "}",
            "type": "datetimeFigureOut",
        },
    )
    field_rpr = copy.deepcopy(source_rpr)
    field_rpr.set("lang", "zh-CN")
    field.append(field_rpr)
    field_text = ET.SubElement(field, qn(NS_A, "t"))
    field_text.text = dt.datetime.now().strftime("%Y-%m-%d")
    target_paragraph.append(field)

    end_rpr = ET.Element(qn(NS_A, "endParaRPr"), {"lang": "zh-CN"})
    target_paragraph.append(end_rpr)

    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_pptx", type=Path)
    parser.add_argument("output_pptx", type=Path)
    args = parser.parse_args()

    if args.input_pptx.resolve() == args.output_pptx.resolve():
        raise SystemExit("Output must be a new PPTX path")

    args.output_pptx.parent.mkdir(parents=True, exist_ok=True)
    patched = False

    with zipfile.ZipFile(args.input_pptx, "r") as source, zipfile.ZipFile(
        args.output_pptx, "w", compression=zipfile.ZIP_DEFLATED
    ) as target:
        for info in source.infolist():
            payload = source.read(info.filename)
            if info.filename == "ppt/slides/slide1.xml":
                payload = patch_slide(payload)
                patched = True
            target.writestr(info, payload)

    if not patched:
        raise RuntimeError("slide1.xml was not found")

    print(f"[OK] Auto-updating cover date added: {args.output_pptx}")


if __name__ == "__main__":
    main()
