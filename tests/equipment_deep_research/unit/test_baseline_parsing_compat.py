from equipment_deep_research.agents.workflows.baseline_execution import (
    _parse_baseline_payload,
    _parse_confidence,
)


def test_parse_confidence_accepts_qualitative_chinese_values():
    assert _parse_confidence("中低") == 0.45
    assert _parse_confidence("高") == 0.85


def test_parse_confidence_accepts_percentages_and_falls_back():
    assert _parse_confidence("80%") == 0.8
    assert _parse_confidence("0.7") == 0.7
    assert _parse_confidence("unknown", fallback=0.42) == 0.42


def test_parse_baseline_payload_normalizes_deepseek_aliases():
    payload = _parse_baseline_payload(
        '{"baseline_findings":["发现一","发现二"],'
        '"confidence_score":0.8,"summary":"已完成"}'
    )
    assert payload["findings"] == ["发现一", "发现二"]
    assert payload["confidence"] == 0.8
    assert payload["handoff_summary"] == "已完成"


def test_parse_baseline_payload_normalizes_nested_result():
    payload = _parse_baseline_payload(
        '{"result":{"observations":["关键观察"],"未决问题":["需复核"]}}'
    )
    assert payload["findings"] == ["关键观察"]
    assert payload["open_questions"] == ["需复核"]
