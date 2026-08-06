"""Agent-led equipment capability portrait formatting.

This module owns the delivery shape, not the military idea.  Query-aware
Codex agents decide the weapon identity, mechanism, operating process,
decisive effect and falsification boundary upstream.  The helpers below only
remove transport labels, preserve those semantics and arrange the governed
``overview + four sections`` format.
"""

from __future__ import annotations

from collections.abc import Sequence
import re


_EQUIPMENT_TERMS = (
    "无人机",
    "无人僚机",
    "无人艇",
    "无人潜航器",
    "巡飞弹",
    "巡航弹",
    "导弹",
    "制导弹药",
    "拦截弹",
    "鱼雷",
    "火炮",
    "雷达",
    "火控系统",
    "电子战系统",
    "定向能",
    "武器站",
    "作战平台",
    "效应器",
    "弹药",
    "火力舱",
    "发射舱",
)

_GENERIC_TITLES = {
    "无人机",
    "无人作战平台",
    "巡飞弹",
    "反辐射巡飞弹",
    "远程导弹",
    "精确制导弹药",
    "拦截弹",
    "电子压制效应器",
    "具体武器装备方向",
}

_LAUNCH_MODE_GENERIC_RE = re.compile(
    r"^(?:(?:空|地|舰|车|潜|岸)射|(?:车|舰|机)载|箱式|筒式|空投|陆基|岸基)"
    r"(?:无人机|无人作战平台|导弹|巡飞弹|拦截弹|武器)$"
)

_FIELD_LABEL_RE = re.compile(
    r"^(?:概述|主装备对象|装备形态|作战运用|未来触发|对手反适应|失效边界|"
    r"通过条件|验证重点|建设路径|依据[^：:]{0,18})\s*[：:]\s*"
)

_PORTRAIT_MARKERS = (
    "概述：",
    "装备与技术实现：",
    "关键作战流程：",
    "形成能力与作战效果：",
    "制胜逻辑机理与对抗边界：",
)


def _clean_clause(value: object, fallback: str = "") -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    text = _FIELD_LABEL_RE.sub("", text).strip(" ，,；;。:：")
    text = (
        text.replace("。；", "；")
        .replace("；。", "；")
        .replace("。。", "。")
        .replace("；；", "；")
        .replace("“", "")
        .replace("”", "")
    )
    return text or fallback


def _clean_items(values: Sequence[object] | object, *, limit: int) -> list[str]:
    if isinstance(values, Sequence) and not isinstance(values, (str, bytes)):
        rows = list(values)
    elif values not in (None, ""):
        rows = re.split(r"[；;。\n]", str(values))
    else:
        rows = []
    cleaned: list[str] = []
    for item in rows:
        text = _clean_clause(item)
        if text and text not in cleaned:
            cleaned.append(text)
        if len(cleaned) >= limit:
            break
    return cleaned


def _first_complete_clause(value: object, fallback: str) -> str:
    for row in _clean_items(value, limit=6):
        if len(row) >= 8 and not row.endswith(
            ("并", "及", "与", "和", "或", "但", "且", "的", "为", "通过")
        ):
            return row
    return _clean_clause(fallback, "待由Query推演补充")


def is_launch_mode_generic_weapon_title(value: object) -> bool:
    """Whether a title contains only a launch mode and generic weapon class."""

    title = re.sub(r"\s+", "", str(value or "")).strip(" ，,；;。:：")
    return bool(_LAUNCH_MODE_GENERIC_RE.fullmatch(title))


def primary_equipment_form_title(value: object) -> str:
    """Extract the authored main equipment identity without metadata tails."""

    form = re.sub(r"\s+", "", str(value or "")).strip(" ，,；;。:：")
    if not form:
        return ""
    form = re.split(
        r"(?:·\s*)?(?:接口形态|任务接口|发射接口|证据边界)\s*[：:]",
        form,
        maxsplit=1,
    )[0]
    return re.split(r"[；;。]", form, maxsplit=1)[0].strip(" ，,；;。:：")


def _is_concrete_title(value: str) -> bool:
    return (
        len(value) >= 4
        and value not in _GENERIC_TITLES
        and not is_launch_mode_generic_weapon_title(value)
        and any(term in value for term in _EQUIPMENT_TERMS)
        and not value.startswith(("面向", "针对", "关于"))
    )


def build_capability_title(
    *, name: object, equipment_form: object, effect: object = ""
) -> str:
    """Preserve an Agent-authored weapon name; never invent one from a family.

    ``effect`` remains in the signature for compatibility but is deliberately
    ignored.  A combat effect is not a safe local naming dictionary.
    """

    del effect
    title = re.sub(r"\s+", "", str(name or "")).strip(" ，,；;。:：")
    title = re.sub(r"^\d+\s*[：:、.．)）-]\s*", "", title)
    title = re.sub(r"^[A-Ha-h]\s*[：:、.．)）-]\s*", "", title)
    title = re.sub(r"^(?:S[1-6][-_：: ]*)", "", title, flags=re.IGNORECASE)
    title = re.sub(r"(?:能力)?升级(?:方向)?$", "", title).rstrip(" ，,；;。:：")
    form = primary_equipment_form_title(equipment_form)
    if _is_concrete_title(title):
        return title
    if _is_concrete_title(form):
        return form
    return title or form or "待由Codex Agent命名的具体武器装备"


def normalize_capability_problem(value: object, *, fallback: str) -> str:
    """Keep one complete equipment-local problem statement."""

    source = _clean_clause(value)
    source = re.split(r"[；;]该方向装备基线[：:]", source, maxsplit=1)[0]
    return _first_complete_clause(source, fallback)


def normalize_operational_process(
    values: Sequence[object] | object,
    *,
    equipment_identity: object,
) -> list[str]:
    """Clean only model-authored process rows without selecting a stock flow."""

    del equipment_identity
    rows = [
        item
        for item in _clean_items(values, limit=8)
        if not any(
            marker in item
            for marker in (
                "S1增量",
                "S2增量",
                "S3增量",
                "S4增量",
                "S5增量",
                "S6增量",
                "本候选主体",
            )
        )
        and not item.startswith(("对手", "敌方", "威胁"))
        and not item.endswith(("并", "及", "与", "和", "或", "但", "且", "的"))
    ]
    return rows[:6]


def complete_operational_process(
    values: Sequence[object] | object,
    *,
    equipment_identity: object,
) -> list[str]:
    """Compatibility alias that no longer fills missing process semantics."""

    return normalize_operational_process(
        values,
        equipment_identity=equipment_identity,
    )


def normalize_verification_plan(
    values: Sequence[object] | object,
    *,
    equipment_identity: object,
    failure_boundary: object = "",
) -> list[str]:
    """Preserve Agent-authored verification rows without family inference."""

    del equipment_identity, failure_boundary
    return _clean_items(values, limit=12)


def _subject(name: object, equipment_form: object) -> str:
    title = build_capability_title(name=name, equipment_form=equipment_form)
    return title or "待由Codex Agent命名的具体武器装备"


def build_agent_led_capability_portrait(
    *,
    name: object = "",
    scenario: object,
    problem: object,
    principle: object,
    technologies: Sequence[object] | object,
    operational_concept: object,
    operational_steps: Sequence[object] | object,
    capability: object,
    effect: object,
    winning_mechanism: object,
    equipment_form: object = "",
    baseline: object = "",
    development_path: object = "",
    failure_boundary: Sequence[object] | object = "",
    verification_plan: object = "",
) -> str:
    """Arrange supplied S6 semantics in the governed five-part format.

    Missing semantics remain explicitly missing so the upstream quality gate
    can request a bounded Agent rewrite.  No equipment family, process,
    countermeasure, metric or weapon name is inferred here.
    """

    subject = _subject(name, equipment_form)
    scenario_text = _clean_clause(scenario, "任务场景尚未由Agent明确")
    problem_text = normalize_capability_problem(
        problem,
        fallback="核心任务断点尚未由Agent明确",
    )
    principle_text = _clean_clause(principle, "新质制胜原理尚未由Agent论证")
    concept_text = _clean_clause(
        operational_concept,
        "装备专属运用构想尚未由Agent形成",
    )
    capability_text = _clean_clause(capability, "可考核装备能力尚未定义")
    effect_text = _clean_clause(effect, "直接作战结果尚未验证")
    winning_text = _clean_clause(winning_mechanism, principle_text)
    equipment_text = _clean_clause(equipment_form, subject)
    baseline_text = _clean_clause(baseline, "公开对照基线尚待核验")
    technology_rows = _clean_items(technologies, limit=8)
    technology_text = "、".join(technology_rows) or "关键实现尚待Agent补充"
    process_rows = normalize_operational_process(
        operational_steps,
        equipment_identity=f"{subject}；{equipment_text}",
    )
    process_text = "；".join(
        f"{index}.{row}" for index, row in enumerate(process_rows, start=1)
    ) or "装备专属作战流程尚未形成，须回到S5/S6 Agent补写"
    boundary_rows = _clean_items(failure_boundary, limit=6)
    boundary_text = "；".join(boundary_rows) or "失效边界尚未形成，须回到前置质量门补写"
    verification_rows = normalize_verification_plan(
        verification_plan,
        equipment_identity=equipment_text,
    )
    development_rows = _clean_items(development_path, limit=4)
    validation_text = "；".join([*verification_rows, *development_rows])

    mechanism_boundary = f"{winning_text}；对抗与失效边界：{boundary_text}"
    if validation_text:
        mechanism_boundary += f"；验证判据：{validation_text}"

    return "\n".join(
        [
            (
                f"概述：{subject}聚焦{scenario_text}，直接回应{problem_text}。"
                f"其核心构想是{principle_text}，以{concept_text}形成{capability_text}，"
                f"预期取得{effect_text}。"
            ),
            (
                f"- 装备与技术实现：主装备对象为{equipment_text}；"
                f"公开对照为{baseline_text}；关键实现包括{technology_text}。"
            ),
            f"- 关键作战流程：{process_text}。",
            (
                f"- 形成能力与作战效果：{capability_text}；"
                f"直接军事结果为{effect_text}。"
            ),
            f"- 制胜逻辑机理与对抗边界：{mechanism_boundary}。",
        ]
    )


def resolve_capability_portrait(
    existing: object,
    **portrait_fields: object,
) -> str:
    """Keep a complete Agent-written portrait; format structured fields otherwise."""

    text = str(existing or "").strip()
    text = re.sub(
        r"\s+(?=- (?:装备与技术实现|关键作战流程|形成能力与作战效果|制胜逻辑机理与对抗边界|发展与验证路径)：)",
        "\n",
        text,
    )
    overview = text.split("\n", 1)[0]
    internal_markers = ("Harness", "Packet", "Claim")
    complete = (
        all(marker in text for marker in _PORTRAIT_MARKERS)
        and "发展与验证路径：" not in text
        and len(overview.removeprefix("概述：").strip()) >= 48
        and text[-1:] in "。！？；”’」』）)"
        and not any(marker in text for marker in internal_markers)
    )
    if complete:
        return text
    return build_agent_led_capability_portrait(**portrait_fields)


def build_capability_portrait(**portrait_fields: object) -> str:
    """Backward-compatible entry point for the Agent-led formatter."""

    return build_agent_led_capability_portrait(**portrait_fields)
