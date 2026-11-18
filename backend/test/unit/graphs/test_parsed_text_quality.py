from platform_core.knowledge.training.parsed_text_quality import analyze_parsed_text


def test_readable_chinese_text_is_ready_for_extraction() -> None:
    result = analyze_parsed_text("雷达目标检测与电子对抗协同技术研究。" * 30)

    assert result["ready_for_extraction"] is True
    assert result["recommended_route"] == "keep_current_parser"
    assert result["issues"] == []


def test_cid_glyph_encoding_requires_ocr_without_returning_source() -> None:
    source = " ".join(f"/G{index:02X}" for index in range(128))

    result = analyze_parsed_text(source)

    assert result["ready_for_extraction"] is False
    assert result["recommended_route"] == "ocr"
    assert result["issues"] == ["cid_glyph_encoding"]
    assert source not in str(result)


def test_replacement_and_nul_corruption_are_reported_separately() -> None:
    result = analyze_parsed_text("技术文本" * 30 + "\ufffd" * 10 + "\x00")

    assert result["ready_for_extraction"] is False
    assert "replacement_character_corruption" in result["issues"]
    assert "nul_character" in result["issues"]
