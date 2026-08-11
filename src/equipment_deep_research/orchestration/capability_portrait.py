"""Agent-led equipment capability portrait formatting.

This module owns the delivery shape, not the military idea.  Query-aware
Codex agents decide the weapon identity, mechanism, operating process,
decisive effect and falsification boundary upstream.  The helpers below only
remove transport labels, preserve those semantics and arrange the governed
``overview + four sections`` format.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import re


_FIELD_LABEL_RE = re.compile(r"(?!)")

_PORTRAIT_MARKERS = (
    "能力分类：",
    "概述：",
    "装备与技术实现：",
    "关键作战流程：",
    "形成能力与作战效果：",
    "制胜逻辑机理：",
)

CAPABILITY_PORTRAIT_MODULES = (
    ("overview", "概述"),
    ("technology_implementation", "装备与技术实现"),
    ("operational_process", "关键作战流程"),
    ("capability_effects", "形成能力与作战效果"),
    ("winning_logic", "制胜逻辑机理"),
)

_CAPABILITY_PORTRAIT_LEGACY_LABELS = {
    "winning_logic": ("制胜逻辑机理与对抗边界", "制胜逻辑与边界"),
}

_CAPABILITY_PORTRAIT_LEGACY_KEYS = {
    "winning_logic": ("winning_logic_boundary",),
}

_SCHEMA_PLACEHOLDER_RE = re.compile(
    r"(^|[；;，,\n])\s*(?:string|array|object|null|number|boolean)\s*"
    r"(?=$|[；;，,。\n])",
    flags=re.IGNORECASE,
)


def strip_schema_placeholders(value: object) -> str:
    """Remove standalone JSON-schema sample values from authored prose."""

    text = str(value or "")
    previous = None
    while previous != text:
        previous = text
        text = _SCHEMA_PLACEHOLDER_RE.sub(r"\1", text)
    return (
        text.replace("；；", "；")
        .replace(";;", ";")
        .replace("；。", "。")
        .replace(";。", "。")
    )


def assemble_capability_portrait_modules(modules: Mapping[str, object] | object) -> str:
    """Render five independently authored modules into the governed card shape."""

    if not isinstance(modules, Mapping):
        return ""
    rows: list[str] = []
    classification = modules.get("capability_classification", {})
    if isinstance(classification, Mapping):
        primary = _clean_clause(classification.get("primary_dimension", ""))
        raw_secondary = classification.get("secondary_dimensions", [])
        secondary = _clean_items(raw_secondary, limit=2)
        labels = [
            *(f"主：{primary}" for _ in [0] if primary),
            *(f"辅：{'、'.join(secondary)}" for _ in [0] if secondary),
        ]
        if labels:
            rows.append("能力分类：" + "；".join(labels) + "。")
    elif _clean_clause(classification):
        rows.append("能力分类：" + _clean_clause(classification).rstrip("。") + "。")
    for index, (key, label) in enumerate(CAPABILITY_PORTRAIT_MODULES):
        raw_body = modules.get(key, "")
        if not raw_body:
            raw_body = next(
                (
                    modules.get(legacy_key, "")
                    for legacy_key in _CAPABILITY_PORTRAIT_LEGACY_KEYS.get(key, ())
                    if modules.get(legacy_key, "")
                ),
                "",
            )
        body = _clean_clause(raw_body)
        if not body:
            return ""
        accepted_labels = (label, *_CAPABILITY_PORTRAIT_LEGACY_LABELS.get(key, ()))
        label_pattern = "|".join(re.escape(item) for item in accepted_labels)
        body = re.sub(rf"^(?:-\s*)?(?:{label_pattern})\s*[：:]\s*", "", body)
        body = body.rstrip("。！？；") + "。"
        prefix = "" if index == 0 else "- "
        rows.append(f"{prefix}{label}：{body}")
    return "\n".join(rows)


def parse_capability_portrait_modules(value: object) -> dict[str, str]:
    """Extract the governed modules from new or legacy portrait prose."""

    text = strip_schema_placeholders(value).strip()
    modules: dict[str, str] = {}
    for index, (key, label) in enumerate(CAPABILITY_PORTRAIT_MODULES):
        labels = (label, *_CAPABILITY_PORTRAIT_LEGACY_LABELS.get(key, ()))
        label_pattern = "|".join(re.escape(item) for item in labels)
        next_key_label = (
            CAPABILITY_PORTRAIT_MODULES[index + 1]
            if index + 1 < len(CAPABILITY_PORTRAIT_MODULES)
            else None
        )
        pattern = rf"(?:^|\n)\s*(?:-\s*)?(?:{label_pattern})\s*[：:]\s*(?P<body>.*?)"
        if next_key_label:
            next_key, next_label = next_key_label
            next_labels = (
                next_label,
                *_CAPABILITY_PORTRAIT_LEGACY_LABELS.get(next_key, ()),
            )
            next_pattern = "|".join(re.escape(item) for item in next_labels)
            pattern += rf"(?=\n\s*(?:-\s*)?(?:{next_pattern})\s*[：:])"
        else:
            pattern += r"\s*\Z"
        match = re.search(pattern, text, flags=re.DOTALL)
        if match:
            modules[key] = _clean_clause(match.group("body"))
    return modules


def _legacy_overview_semantics(value: object) -> dict[str, str]:
    """Recover useful S6 semantics from the former long-form overview.

    Old completed runs stored the strongest battlefield reasoning in an
    unstructured lede.  When the API reformats those runs, retain that authored
    reasoning instead of replacing it with a baseline citation or placeholder.
    """

    overview = str(value or "").split("\n", 1)[0].strip()
    match = re.search(
        r"概述：?.*?聚焦(?P<scenario>.+?)(?:，|,)(?:直接回应|针对).*?"
        r"其核心构想是(?P<principle>.+?)(?:，|,)以(?P<concept>.+?)形成"
        r"(?P<capability>.+?)(?:，|,)(?:预期取得|实现)(?P<effect>.+?)[。.]?$",
        overview,
    )
    if not match:
        return {}
    key_map = {
        "scenario": "scenario",
        "principle": "principle",
        "concept": "operational_concept",
        "capability": "capability",
        "effect": "effect",
    }
    return {
        key_map[key]: _clean_clause(raw)
        for key, raw in match.groupdict().items()
        if _clean_clause(raw)
    }


def _clean_clause(value: object, fallback: str = "") -> str:
    text = re.sub(r"\s+", " ", strip_schema_placeholders(value)).strip()
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


def _compact_clause(value: object, fallback: str, *, limit: int) -> str:
    """Keep one complete decision-relevant clause without cutting its meaning.

    The full structured card remains available for traceability.  The portrait
    is the decision-facing reading surface, so character limits are soft layout
    guidance only.  Never replace authored military information with an
    ellipsis; concision must be achieved upstream by the Agent.
    """

    del limit

    direct = _clean_clause(value)
    text = (
        direct
        if direct and not direct.endswith(("并", "及", "与", "和", "或", "但", "且", "的", "为", "通过"))
        else _first_complete_clause(value, fallback)
    )
    text = re.split(r"[；;]", text, maxsplit=1)[0].strip()
    return text


def _detail_clause(value: object, fallback: str, *, limit: int) -> str:
    """Retain complete multi-clause military detail for the lower modules."""

    del limit
    return _clean_clause(value, fallback)


def _operational_step_digest(value: object) -> str:
    """Return a complete stage label for the overview, never a cut sentence.

    The detailed module keeps the entire authored step.  The overview only
    needs the leading action of each stage so the reader can grasp the combat
    chain without seeing character-truncation marks.
    """

    text = _clean_clause(value)
    return re.split(r"[；;，,。]", text, maxsplit=1)[0].strip()


def is_launch_mode_generic_weapon_title(value: object) -> bool:
    """Deprecated: equipment-title semantics belong to the Codex author."""

    del value
    return False


def primary_equipment_form_title(value: object) -> str:
    """Keep the first authored equipment-form clause without class inference."""

    form = re.sub(r"\s+", "", str(value or "")).strip(" ，,；;。:：")
    if not form:
        return ""
    return re.split(r"[；;。]", form, maxsplit=1)[0].strip(" ，,；;。:：")


def _is_concrete_title(value: str) -> bool:
    return bool(str(value or "").strip())


def build_capability_title(
    *, name: object, equipment_form: object, effect: object = ""
) -> str:
    """Preserve an Agent-authored weapon name; never invent one from a family.

    ``effect`` remains in the signature for compatibility but is deliberately
    ignored.  A combat effect is not a safe local naming dictionary.
    """

    del effect
    title = re.sub(r"\s+", "", str(name or "")).strip(" ，,；;。:：")
    form = primary_equipment_form_title(equipment_form)
    return title or form


def normalize_capability_problem(value: object, *, fallback: str) -> str:
    """Keep one complete equipment-local problem statement."""

    source = _clean_clause(value)
    source = re.split(r"[；;]该方向装备基线[：:]", source, maxsplit=1)[0]
    if "尚不能" in source:
        gap = "现有能力尚不能" + source.split("尚不能", 1)[1]
        return _first_complete_clause(gap, fallback)
    # A baseline citation is useful in the implementation module but is not a
    # combat problem on its own.  Do not let a legacy evidence preface occupy
    # the "针对" position in the overview.
    if (
        "公开基线" in source
        and not any(
            marker in source
            for marker in ("不能", "难以", "不足", "缺", "受限", "中断", "失效", "不具备")
        )
    ):
        return _first_complete_clause(fallback, "核心任务断点尚未由Agent明确")
    return _first_complete_clause(source, fallback)


def _winning_clause(value: object, fallback: str) -> str:
    """Prefer the actual mechanism over a leading public-baseline citation."""

    rows = _clean_items(value, limit=5)
    evidence_prose = re.compile(
        r"(?:公开基线|\b[A-Z][A-Z0-9-]{2,}\b.*(?:研究|项目|报告|论文|支持|证实)|"
        r"(?:研究|项目|报告|论文).*(?:支持|证实|表明))"
    )
    meaningful = next(
        (
            row
            for row in rows
            if "公开基线" not in row
            and "基线" not in row
            and not evidence_prose.search(row)
        ),
        rows[0] if rows else fallback,
    )
    return _compact_clause(meaningful, fallback, limit=80)


def _capability_and_effect_details(
    capability: object,
    effect: object,
) -> tuple[str, str]:
    """Separate ability from battlefield effect without duplicating one field.

    Some historical S6 cards placed both the capability and its downstream
    consequences in ``capability_outcome`` while leaving ``military_value``
    empty.  Preserve those authored clauses, but partition them for the reader
    instead of printing the same list twice.
    """

    capability_rows = _clean_items(capability, limit=5)
    effect_rows = _clean_items(effect, limit=5)
    # Historical cards commonly copied the same aggregate outcome into all
    # outcome fields. Treat an exact copy as absent here so later clauses can
    # serve their intended role as battlefield consequences.
    if _clean_clause(effect) == _clean_clause(capability):
        effect_rows = []
    if not effect_rows and len(capability_rows) > 1:
        effect_rows = capability_rows[1:]
        capability_rows = capability_rows[:1]
    if not capability_rows:
        capability_rows = [""]
    if not effect_rows:
        effect_rows = [""]

    def render(rows: list[str]) -> str:
        detail = _detail_clause("；".join(rows), rows[0], limit=260)
        detail = re.sub(
            r"^(?:形成|实现|直接作战效果为|作战效果为)\s*",
            "",
            detail,
        )
        # "形成对X形成Y能力" is a common aggregate-field artefact. Preserve
        # the meaning while making the delivered sentence natural.
        match = re.match(r"^对(.+?)形成([^；;。]+)(.*)$", detail)
        if match:
            detail = f"对{match.group(1)}的{match.group(2)}{match.group(3)}"
        return detail

    return render(capability_rows), render(effect_rows)


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
    return title or "待命名具体武器装备"


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
    """Arrange Agent-authored semantics into the governed portrait shape.

    This renderer does not select a weapon family, invent a process, or fill a
    catalogue template.  It only turns semantic fields already supplied by the
    model into a readable card so a missing prose blob cannot mechanically fail
    an otherwise substantive candidate.
    """

    subject = _subject(name, equipment_form)
    scenario_text = _clean_clause(scenario, "当前Query作战场景")
    problem_text = _clean_clause(problem, "关键任务链断点待验证")
    principle_text = _clean_clause(
        principle or operational_concept or winning_mechanism,
        "按候选声明的核心机理改变对抗关系",
    )
    concept_text = _clean_clause(
        operational_concept or principle,
        principle_text,
    )
    capability_text = _clean_clause(
        capability,
        f"形成{subject}对应的任务能力",
    )
    effect_text = _clean_clause(
        effect,
        capability_text,
    )
    mechanism_text = _clean_clause(
        winning_mechanism or principle or operational_concept,
        principle_text,
    )
    technology_rows = _clean_items(technologies, limit=6)
    equipment_rows = [
        row
        for row in (
            _clean_clause(equipment_form),
            "、".join(technology_rows),
            _clean_clause(baseline),
        )
        if row
    ]
    process_rows = normalize_operational_process(
        operational_steps,
        equipment_identity=subject,
    )
    development_text = _clean_clause(development_path)

    return "\n".join(
        [
            (
                f"概述：{subject}面向{scenario_text}，针对{problem_text}，"
                f"以{principle_text}形成{capability_text}，直接指向{effect_text}。"
            ),
            (
                "装备与技术实现："
                + ("；".join(equipment_rows) if equipment_rows else subject)
                + (f"；{development_text}" if development_text else "")
                + "。"
            ),
            (
                "关键作战流程："
                + (
                    "；".join(process_rows)
                    if process_rows
                    else f"按{concept_text}执行候选声明的装备专属任务流程"
                )
                + "。"
            ),
            f"形成能力与作战效果：{capability_text}；{effect_text}。",
            f"制胜逻辑机理：{mechanism_text}。",
        ]
    )


def resolve_capability_portrait(
    existing: object,
    *,
    force_compact: bool = False,
    **portrait_fields: object,
) -> str:
    """Return only model-authored portrait text; never synthesize missing prose."""

    text = strip_schema_placeholders(existing).strip()
    text = re.sub(
        r"\s+(?=- (?:装备与技术实现|关键作战流程|形成能力与作战效果|制胜逻辑机理(?:与对抗边界)?|发展与验证路径)：)",
        "\n",
        text,
    )
    del force_compact, portrait_fields
    return text


def build_capability_portrait(**portrait_fields: object) -> str:
    """Backward-compatible entry point for the Agent-led formatter."""

    return build_agent_led_capability_portrait(**portrait_fields)
