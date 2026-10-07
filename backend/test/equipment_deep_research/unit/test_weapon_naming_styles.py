from equipment_deep_research.agents.workflows.winning import (
    S3_S4_WEAPON_NAMING_TYPES,
    _creative_s3_candidate_instruction,
    _random_s3_s4_naming_types,
    _s3_s4_naming_assignment,
)


def test_s3_s4_naming_types_cover_a_through_o() -> None:
    assert [item["code"] for item in S3_S4_WEAPON_NAMING_TYPES] == list(
        "ABCDEFGHIJKLMNO"
    )
    assert all(item["label"] and item["focus"] for item in S3_S4_WEAPON_NAMING_TYPES)
    assert all(
        item.get("naming_core")
        and item.get("keywords")
        and item.get("example")
        and item.get("name_format")
        and item.get("naming_question")
        for item in S3_S4_WEAPON_NAMING_TYPES
    )
    assert next(item["label"] for item in S3_S4_WEAPON_NAMING_TYPES if item["code"] == "K") == (
        "体系节点型"
    )


def test_s3_s4_random_naming_assignment_is_stable_and_diverse() -> None:
    first = _random_s3_s4_naming_types("run-a|agent-a|1")
    assert first == _random_s3_s4_naming_types("run-a|agent-a|1")
    assert len(first) == 2
    assert first[0]["code"] != first[1]["code"]

    observed = {
        item["code"]
        for index in range(40)
        for item in _random_s3_s4_naming_types(f"run-{index}|agent-{index}|1")
    }
    assert observed == set("ABCDEFGHIJKLMNO")


def test_s3_s4_creative_prompt_requires_assigned_style_and_short_name() -> None:
    instruction = _creative_s3_candidate_instruction()
    assert "random_naming_style_assignment" in instruction
    assert "两个候选不得使用同一类型" in instruction
    assert "8—12个汉字" in instruction


def test_s3_s4_assignment_maps_unique_types_to_candidate_order() -> None:
    assignment = _s3_s4_naming_assignment("static-s4", count=6)
    assert assignment["selection_mode"] == "random_without_replacement"
    assert [item["candidate_position"] for item in assignment["candidate_order"]] == list(
        range(1, 7)
    )
    assert len({item["code"] for item in assignment["candidate_order"]}) == 6
    assert "8—12个汉字" in assignment["name_length"]
