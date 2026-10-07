"""Agent-led equipment capability portrait formatting.

This module owns the delivery shape, not the military idea.  Query-aware
Codex agents decide the weapon identity, mechanism, operating process,
decisive effect and falsification boundary upstream.  The helpers below only
remove transport labels, preserve those semantics and arrange the governed
``overview + four sections`` format.
"""

from __future__ import annotations

import ast
import json
from collections.abc import Mapping, Sequence
from difflib import SequenceMatcher
import re


_FIELD_LABEL_RE = re.compile(r"(?!)")

# Legacy S6 fallback prose used a portfolio-wide sentence that is unrelated to
# the weapon identity.  Keep this detector at the projection boundary so old
# cards cannot reintroduce it through winning_mechanism/effect fields.
_MECHANICAL_PORTRAIT_FILL_RE = re.compile(
    r"把原本依赖固定节奏的处置过程前移到装备本体或编组内，?"
    r"(?:对目标、火力节点或防御节奏形成可验证的直接约束；?"
    r"在敌方保持原有突防方式时形成直接杀伤或削峰，迫使其改变航路、编组或投入节奏。?)?"
)

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

# S6 launches one decision-spine turn and five independently authored portrait
# columns for every selected weapon. Keep its process pool separate from the
# ordinary research-wave limit: a seven-card portfolio has 42 immediately
# runnable turns, while 32 concurrent ephemeral CLI processes is the highest
# default that still leaves reasonable headroom for the host and gateway.
S6_MODEL_CALLS_PER_CARD = 1 + len(CAPABILITY_PORTRAIT_MODULES)
S6_DEFAULT_CODEX_CONCURRENCY = 32
S6_MAX_CODEX_CONCURRENCY = 32

# S6 aims for roughly 360–400 substantive Chinese characters per module, but
# this is an editorial target rather than a hard limit.  A concise, closed
# argument is preferable to generic filler, and a complete complex argument
# may run a little longer.
CAPABILITY_PORTRAIT_TARGET_MODULE_CHARS = 380
CAPABILITY_PORTRAIT_REPAIR_TRIGGER_CHARS = 360
CAPABILITY_PORTRAIT_QUALITY_CONTRACT_VERSION = (
    "s6-portrait-v5-"
    f"target{CAPABILITY_PORTRAIT_TARGET_MODULE_CHARS}x5-soft"
)
CAPABILITY_PORTRAIT_MIN_BODY_CHARS = 1900
CAPABILITY_PORTRAIT_MAX_BODY_CHARS = 2250
# This smaller floor belongs to the generic, backward-compatible semantic
# diagnostic below. Live concurrent S6 authoring uses the 360-character
# per-module repair trigger above.
CAPABILITY_PORTRAIT_MIN_MODULE_CHARS = 180

# The technology module is a design handoff, not a generic trend paragraph.
# Keep this check small: it only catches prose that never binds the principle
# to an actual weapon body or engineering object.
_TECH_EQUIPMENT_ANCHOR_RE = re.compile(
    r"装备本体|弹载|弹体|母弹|巡飞弹|导弹|拦截器|战斗部|引信|导引头|载荷|舱内|弹舱|"
    r"平台|飞控|控制面|任务计算机|传感器|导航|制导|发射|释放|电源|能源|热控|"
    r"伞骨|网幕|网衣|浮体|系留|绞车|锚定|张紧|"
    r"结构|材料|天线|火控|接口|无人机|无人艇|无人车|潜航器"
)
_TECH_IMPLEMENTATION_ACTION_RE = re.compile(
    r"落到|装入|写入|集成|布置|联锁|融合|控制|约束|落实|实现|配置|承担|"
    r"通过|利用|依据|把|将|依靠|装在|安装|搭载|内置|置于|位于|"
    r"由.+形成"
)

_CAPABILITY_DIMENSION_RULES = (
    (re.compile(r"毁伤|摧毁|杀伤|破坏"), "毁伤维度"),
    (re.compile(r"精打|打击|攻击|火力"), "打击维度"),
    (re.compile(r"拦截|阻断目标"), "拦截维度"),
    (re.compile(r"压制|抑制"), "压制维度"),
    (re.compile(r"拒止|禁入|区域控制"), "拒止维度"),
    (re.compile(r"突防|穿透|渗透"), "突防维度"),
    (re.compile(r"侦察|感知|探测|识别|确认|复核|验真|比对"), "侦察感知维度"),
    (re.compile(r"预警|提前发现"), "预警维度"),
    (re.compile(r"电子对抗|电磁对抗|干扰"), "电子对抗维度"),
    (re.compile(r"威慑"), "威慑维度"),
    (re.compile(r"生存|抗毁|恢复|韧性|任务连续|持续作战"), "生存抗毁维度"),
    (re.compile(r"战场控制|作战主动权|时空控制"), "战场控制维度"),
)
_CAPABILITY_DIMENSION_EQUIPMENT_RE = re.compile(
    r"弹药|导弹|巡飞弹|母弹|战斗体|平台|弹群|舱|无人机|无人艇|无人车|潜航器"
)


def _cjk_count(value: object) -> int:
    return len(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]", str(value or "")))


def cap_portrait_module_length(value: object, *, maximum: int = 400) -> str:
    """Normalize a display column without deleting authored content.

    ``maximum`` remains for source compatibility with older callers, but S6
    columns are no longer character-capped.  Cutting at an arbitrary CJK
    character was the direct cause of incomplete final sentences in the UI.
    """

    del maximum
    return coerce_portrait_module_prose(value, allow_structured_salvage=True)


def normalize_capability_classification(value: object) -> dict[str, object]:
    """Keep one primary and at most two distinct capability dimensions.

    Historical S6 payloads sometimes put equipment names, technology features
    or a second spelling of the primary dimension into ``secondary_dimensions``.
    Normalize those records at the projection boundary so every card uses the
    same compact ``主 + 辅`` reading model.
    """

    if not isinstance(value, Mapping):
        return {}

    def dimension_label(raw: object, *, primary: bool = False) -> str:
        text = _clean_clause(raw)
        if not text:
            return ""
        for pattern, label in _CAPABILITY_DIMENSION_RULES:
            if pattern.search(text):
                return label
        if _CAPABILITY_DIMENSION_EQUIPMENT_RE.search(text):
            return ""
        if primary or text.endswith(("维度", "能力")):
            return text
        return ""

    primary = dimension_label(
        value.get("primary_dimension") or value.get("primary"),
        primary=True,
    )
    raw_secondary = value.get("secondary_dimensions") or value.get("secondary") or []
    if isinstance(raw_secondary, Sequence) and not isinstance(
        raw_secondary, (str, bytes)
    ):
        candidates = raw_secondary
    else:
        candidates = re.split(r"[、,，;；]", str(raw_secondary))
    seen = {primary} if primary else set()
    secondary: list[str] = []
    for candidate in candidates:
        label = dimension_label(candidate)
        if not label or label in seen:
            continue
        seen.add(label)
        secondary.append(label)
        if len(secondary) >= 2:
            break
    result: dict[str, object] = {
        "primary_dimension": primary,
        "secondary_dimensions": secondary,
    }
    basis = re.sub(
        r"\s+", " ", strip_schema_placeholders(value.get("classification_basis", ""))
    ).strip()
    if basis:
        result["classification_basis"] = basis
    return result if primary or secondary else {}

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

# Model drift sometimes returns a nested JSON object for a portrait column.
# Those English keys are never part of the governed delivery vocabulary.
_PORTRAIT_SCHEMA_LEAK_KEY_RE = re.compile(
    r"\b(?:"
    r"key_technologies|system_architecture|implementation_path|"
    r"key_bottlenecks|keyword_context|intelligence_requirement|"
    r"latency_requirement|coordination_requirement|"
    r"enabling_technologies|module_content|operational_steps|"
    r"capability_portrait_modules"
    r")\b"
)
_STRUCTURED_DUMP_RE = re.compile(
    r"^\s*[{\[].*[}\]]\s*$",
    flags=re.DOTALL,
)
_SNAKE_CASE_KEY_FRAGMENT_RE = re.compile(
    r"['\"]?[a-z][a-z0-9]*(?:_[a-z0-9]+)+['\"]?\s*:"
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


def portrait_module_looks_structured(value: object) -> bool:
    """True when a column looks like a nested object or a leaked dict dump."""

    if isinstance(value, Mapping):
        return True
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return True
    text = str(value or "").strip()
    if not text:
        return False
    if _PORTRAIT_SCHEMA_LEAK_KEY_RE.search(text):
        return True
    if _STRUCTURED_DUMP_RE.match(text) and _SNAKE_CASE_KEY_FRAGMENT_RE.search(text):
        return True
    return False


def coerce_portrait_module_prose(
    value: object,
    *,
    module_key: str = "",
    allow_structured_salvage: bool = False,
) -> str:
    """Normalize one portrait column to a single Chinese prose string.

    Authoring boundaries must reject nested objects so each column is rewritten
    as one complete draft. Display boundaries may salvage leaf values from an
    already-persisted Python/JSON dict dump, but never emit raw schema keys.
    """

    if value is None:
        return ""
    if isinstance(value, Mapping):
        preferred = value.get("module_content")
        if isinstance(preferred, str) and preferred.strip():
            return coerce_portrait_module_prose(
                preferred,
                module_key=module_key,
                allow_structured_salvage=allow_structured_salvage,
            )
        if module_key:
            keyed = value.get(module_key)
            if isinstance(keyed, str) and keyed.strip():
                return coerce_portrait_module_prose(
                    keyed,
                    module_key=module_key,
                    allow_structured_salvage=allow_structured_salvage,
                )
        if not allow_structured_salvage:
            return ""
        return _prose_from_structured_leaves(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        if not allow_structured_salvage:
            return ""
        return _prose_from_structured_leaves(value)

    text = strip_schema_placeholders(value).strip()
    if not text:
        return ""
    if not portrait_module_looks_structured(text):
        return re.sub(r"\s+", " ", text).strip()

    parsed = _parse_structured_module_dump(text)
    if parsed is None:
        if allow_structured_salvage:
            return _strip_schema_keys_from_prose(text)
        return ""
    return coerce_portrait_module_prose(
        parsed,
        module_key=module_key,
        allow_structured_salvage=allow_structured_salvage,
    )


def _parse_structured_module_dump(text: str) -> object | None:
    """Best-effort parse of JSON or Python ``str(dict/list)`` dumps."""

    candidate = text.strip()
    if not candidate:
        return None
    for loader in (json.loads, ast.literal_eval):
        try:
            parsed = loader(candidate)
        except (TypeError, ValueError, SyntaxError, RecursionError, MemoryError):
            parsed = None
        if isinstance(parsed, (Mapping, list, tuple, str)):
            return parsed
    # Common model/provider path: single-quoted JSON-like objects.
    if candidate[0] in "{[" and "'" in candidate:
        softened = (
            candidate.replace("None", "null")
            .replace("True", "true")
            .replace("False", "false")
        )
        softened = re.sub(r"'([^'\\]*)'", r'"\1"', softened)
        try:
            parsed = json.loads(softened)
        except (TypeError, ValueError, RecursionError, MemoryError):
            return None
        if isinstance(parsed, (Mapping, list, tuple, str)):
            return parsed
    return None


def _prose_from_structured_leaves(value: object) -> str:
    """Collect leaf strings from a nested object without emitting field names."""

    leaves: list[str] = []

    def walk(node: object) -> None:
        if node is None:
            return
        if isinstance(node, Mapping):
            for item in node.values():
                walk(item)
            return
        if isinstance(node, Sequence) and not isinstance(node, (str, bytes)):
            for item in node:
                walk(item)
            return
        text = re.sub(r"\s+", " ", str(node or "")).strip(" ，,；;。:：")
        if not text or portrait_module_looks_structured(text):
            return
        if _PORTRAIT_SCHEMA_LEAK_KEY_RE.search(text):
            text = _strip_schema_keys_from_prose(text)
        if text and text not in leaves:
            leaves.append(text)

    walk(value)
    if not leaves:
        return ""
    prose = "；".join(leaves).strip(" ；;")
    if prose and prose[-1] not in "。！？":
        prose += "。"
    return prose


def _strip_schema_keys_from_prose(text: str) -> str:
    """Drop leaked English schema keys while keeping Chinese substance."""

    cleaned = _PORTRAIT_SCHEMA_LEAK_KEY_RE.sub(" ", text)
    cleaned = _SNAKE_CASE_KEY_FRAGMENT_RE.sub(" ", cleaned)
    cleaned = re.sub(r"[{}\[\]'\"=]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"\s*[：:]\s*", "：", cleaned)
    cleaned = re.sub(r"(?:；|;|,|，){2,}", "；", cleaned)
    return cleaned.strip(" ，,；;。:：{}[]'\"")


def normalize_capability_portrait_text(value: object) -> str:
    """Re-normalize a full portrait string at the API/display boundary."""

    text = strip_schema_placeholders(value).strip()
    if not text:
        return ""
    modules = parse_capability_portrait_modules(text)
    dirty = portrait_module_looks_structured(text) or any(
        portrait_module_looks_structured(body) for body in modules.values()
    )
    if not dirty:
        return text
    if len(modules) < len(CAPABILITY_PORTRAIT_MODULES):
        return coerce_portrait_module_prose(
            text,
            allow_structured_salvage=True,
        )
    normalized = normalize_capability_portrait_modules(
        modules,
        allow_structured_salvage=True,
    )
    for key, _ in CAPABILITY_PORTRAIT_MODULES:
        if normalized[key]:
            continue
        normalized[key] = _strip_schema_keys_from_prose(str(modules.get(key, "") or ""))
    if any(not body for body in normalized.values()):
        return text
    classification_match = re.match(
        r"能力分类\s*[：:]\s*(?P<body>.+?)(?:\n|$)",
        text,
    )
    # Modules are already salvaged to prose; assemble only rejects raw dumps.
    assembled = assemble_capability_portrait_modules(normalized)
    if not assembled:
        return text
    if classification_match and not assembled.startswith("能力分类："):
        return (
            "能力分类："
            + classification_match.group("body").strip().rstrip("。")
            + "。\n"
            + assembled
        )
    return assembled


def normalize_capability_portrait_modules(
    modules: Mapping[str, object] | object,
    *,
    allow_structured_salvage: bool = True,
) -> dict[str, str]:
    """Normalize every governed portrait column at a storage/display boundary."""

    if not isinstance(modules, Mapping):
        return {}
    return {
        key: coerce_portrait_module_prose(
            modules.get(key, ""),
            module_key=key,
            allow_structured_salvage=allow_structured_salvage,
        )
        for key, _ in CAPABILITY_PORTRAIT_MODULES
    }


def assemble_capability_portrait_modules(modules: Mapping[str, object] | object) -> str:
    """Render five independently authored modules into the governed card shape."""

    if not isinstance(modules, Mapping):
        return ""
    rows: list[str] = []
    classification = normalize_capability_classification(
        modules.get("capability_classification", {})
    )
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
        # Authoring must hand in one-shot prose. Structured dumps are rejected
        # here so callers re-author the column instead of stitching field dumps.
        body = _clean_clause(
            coerce_portrait_module_prose(
                raw_body,
                module_key=key,
                allow_structured_salvage=False,
            )
        )
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


def capability_portrait_module_lengths(
    value: Mapping[str, object] | object,
) -> dict[str, int]:
    """Count substantive CJK characters in each governed portrait module."""

    modules = (
        value
        if isinstance(value, Mapping)
        else parse_capability_portrait_modules(value)
    )
    return {
        key: len(
            re.findall(
                r"[\u3400-\u4dbf\u4e00-\u9fff]",
                coerce_portrait_module_prose(
                    modules.get(key, ""),
                    module_key=key,
                    allow_structured_salvage=False,
                ),
            )
        )
        for key, _ in CAPABILITY_PORTRAIT_MODULES
    }


def short_capability_portrait_modules(
    value: Mapping[str, object] | object,
    *,
    minimum: int = CAPABILITY_PORTRAIT_REPAIR_TRIGGER_CHARS,
) -> list[str]:
    """Return modules below the soft editorial target for diagnostics only."""

    lengths = capability_portrait_module_lengths(value)
    return [
        key
        for key, _ in CAPABILITY_PORTRAIT_MODULES
        if lengths.get(key, 0) < minimum
    ]


def capability_portrait_quality_issues(
    value: Mapping[str, object] | object,
) -> list[str]:
    """Enforce concise, non-repetitive, independently useful S6 modules."""

    raw_modules = (
        {key: value.get(key, "") for key, _ in CAPABILITY_PORTRAIT_MODULES}
        if isinstance(value, Mapping)
        else parse_capability_portrait_modules(value)
    )
    modules = {
        key: _clean_clause(
            coerce_portrait_module_prose(
                raw_modules.get(key, ""),
                module_key=key,
                allow_structured_salvage=False,
            )
        )
        for key, _ in CAPABILITY_PORTRAIT_MODULES
    }
    bodies = [modules.get(key, "") for key, _ in CAPABILITY_PORTRAIT_MODULES]
    if any(not body for body in bodies):
        structured_labels = [
            label
            for key, label in CAPABILITY_PORTRAIT_MODULES
            if portrait_module_looks_structured(raw_modules.get(key, ""))
            and not modules.get(key, "")
        ]
        if structured_labels:
            return [
                "装备能力画像栏目须一次性写成中文正文，禁止嵌套对象或字段清单："
                + "、".join(structured_labels)
            ]
        return ["装备能力画像缺少完整五栏，无法执行精简度交付门"]

    issues: list[str] = []
    for key, label in CAPABILITY_PORTRAIT_MODULES:
        if portrait_module_looks_structured(raw_modules.get(key, "")):
            issues.append(
                f"{label}出现结构化对象或原始字段名，须重写为一次性中文正文"
            )
    # Keep this compatibility diagnostic conservative.  Concurrent S6 has a
    # separate per-column 380-character enhancement trigger; this lower check
    # still lets older persisted cards surface truly empty semantic blurbs
    # without turning report rendering into a hard length gate.
    for key, label in CAPABILITY_PORTRAIT_MODULES:
        compact = re.sub(r"\s+", "", modules.get(key, ""))
        if len(compact) < CAPABILITY_PORTRAIT_MIN_MODULE_CHARS:
            issues.append(
                f"{label}明显过短，低于约180字告警线；请补足缺失论证，但不要用泛化句凑字"
            )
        if portrait_module_has_incomplete_ending(modules.get(key, "")):
            issues.append(
                f"{label}句末疑似截断或逻辑未闭合；请保留完整句和完整因果，不得按字符硬切"
            )

    overview = modules.get("overview", "")
    if _MECHANICAL_PORTRAIT_FILL_RE.search(overview):
        issues.append(
            "概述含跨装备通用机械句式；必须依据本卡具体武器的作用对象、关键动作和直接战果整段重写"
        )
    if not re.search(
        r"传统|原有|过去|敌|对手|常规|旧有|原先",
        overview,
    ):
        issues.append("概述未说明传统能力或敌方优势为何失效")
    if not re.search(
        r"改写|改变|倒转|重构|转为|转变|转化|恢复|压缩|不再|迫使|交换|代价|成本|暴露|时间|消耗",
        overview,
    ):
        issues.append("概述未聚焦颠覆作战关系或敌方新增代价")
    if not re.search(
        r"打击|毁伤|杀伤|摧毁|压制|拦截|拒止|歼灭|破坏|夺取|打开|开辟|阻断|战果",
        overview,
    ):
        issues.append("概述未落到直接战果或新增作战空间")
    # Total length is an editorial target (about 2000–2250 Chinese characters),
    # never a quality or release gate.  Do not reject, retry, truncate, or
    # mechanically expand a card solely because it falls outside that range.

    technology = modules.get("technology_implementation", "")
    if not _TECH_EQUIPMENT_ANCHOR_RE.search(technology):
        issues.append("装备与技术实现未绑定具体武器本体或工程模块")
    elif not _TECH_IMPLEMENTATION_ACTION_RE.search(technology):
        issues.append("装备与技术实现未说明关键原理如何落到装备本体")

    clauses_by_module = [
        [
            clause.strip()
            for clause in re.split(r"[。！？!?；;]+", body)
            if len(re.sub(r"\s+", "", clause)) >= 18
        ]
        for body in bodies
    ]
    repeated_pairs = 0
    for left_index, left_rows in enumerate(clauses_by_module):
        for right_rows in clauses_by_module[left_index + 1 :]:
            if any(
                SequenceMatcher(None, left, right).ratio() >= 0.82
                for left in left_rows
                for right in right_rows
            ):
                repeated_pairs += 1
    if repeated_pairs:
        issues.append(
            f"装备能力画像存在跨栏重复（{repeated_pairs}组栏目复用相同或近似长句）"
        )

    def trigrams(text: str) -> set[str]:
        normalized = re.sub(r"[\s，。；：、,.!?！？:（）()\-]", "", text)
        return {normalized[index : index + 3] for index in range(max(0, len(normalized) - 2))}

    grams = [trigrams(body) for body in bodies]
    nonexclusive: list[str] = []
    for index, own in enumerate(grams):
        others = set().union(*(row for other, row in enumerate(grams) if other != index))
        exclusive_ratio = len(own - others) / max(1, len(own))
        if exclusive_ratio < 0.10:
            nonexclusive.append(CAPABILITY_PORTRAIT_MODULES[index][1])
    if nonexclusive:
        issues.append(
            "装备能力画像栏目缺少独占信息：" + "、".join(nonexclusive)
        )
    return issues


def capability_portrait_repair_issues(
    value: Mapping[str, object] | object,
) -> list[str]:
    """Return the complete repair list with repeated root causes collapsed.

    Every quality issue remains eligible for repair, including shortness,
    cross-column repetition and missing exclusive information. The helper
    only removes duplicate diagnostics that would otherwise make the same
    repair reason appear multiple times in a model prompt or retry ledger.
    The ungrouped :func:`capability_portrait_quality_issues` result remains
    the publication/audit contract.
    """

    issues = capability_portrait_quality_issues(value)
    seen: set[str] = set()
    result: list[str] = []
    for issue in issues:
        text = str(issue).strip()
        if not text:
            continue
        if "跨栏重复" in text:
            root = "cross_column_repetition"
        elif "缺少独占信息" in text:
            root = "missing_exclusive_information"
        elif "明显过短" in text:
            root = "short_module:" + text.split("明显过短", 1)[0]
        elif "句末疑似截断" in text:
            root = "incomplete_ending:" + text.split("句末疑似截断", 1)[0]
        else:
            root = text
        if root in seen:
            continue
        seen.add(root)
        result.append(text)
    return result


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
    if isinstance(value, Mapping) or (
        isinstance(value, Sequence) and not isinstance(value, (str, bytes))
    ):
        value = coerce_portrait_module_prose(
            value,
            allow_structured_salvage=True,
        )
    text = re.sub(r"\s+", " ", strip_schema_placeholders(value)).strip()
    text = _FIELD_LABEL_RE.sub("", text).strip(" ，,；;。:：")
    text = (
        text.replace("。；", "；")
        .replace("；。", "；")
        .replace("。。", "。")
        .replace("；；", "；")
    )
    return text or fallback


_INCOMPLETE_PORTRAIT_END_RE = re.compile(
    r"(?:并且|而且|以及|同时|否则|然而|如果|一旦|由于|因为|其中|包括|分别为|"
    r"取决于|依赖于|转化为|转为|变为|成为|针对|迫使|导致|造成|把|将|由|向|"
    r"在|从|以|按|通过|依靠|依据|围绕|和|与|及|但)$"
)


def portrait_module_has_incomplete_ending(value: object) -> bool:
    """Detect high-confidence dangling endings without judging style.

    The check is deliberately narrow.  It catches a column cut in the middle
    of a connector or prepositional phrase, while allowing ordinary concise
    endings such as ``目标`` or ``能力``.  It is a repair signal, not a
    character-count rule.
    """

    text = coerce_portrait_module_prose(
        value,
        allow_structured_salvage=False,
    )
    text = re.sub(r"\s+", "", str(text or "")).rstrip("。！？!?；;，,：:")
    if not text:
        return False
    if _INCOMPLETE_PORTRAIT_END_RE.search(text):
        return True
    final = text[-1]
    if final == "为" and not text.endswith(("行为", "作为", "称为", "成为", "认为")):
        return True
    if final == "同" and not text.endswith(("协同", "共同", "相同", "不同")):
        return True
    if final == "目" and not text.endswith(("项目", "题目", "科目", "节目")):
        return True
    if final == "民" and not text.endswith(("人民", "农民", "公民", "市民")):
        return True
    if final == "一" and not text.endswith(("第一", "统一", "同一", "唯一")):
        return True
    return False


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
