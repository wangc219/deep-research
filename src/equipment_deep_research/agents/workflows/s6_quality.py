"""S6 capability-portrait normalization, validation and repair rules."""
# ruff: noqa: F401, F821, F841

from __future__ import annotations

from equipment_deep_research.agents.workflows import coordinator as _legacy
from equipment_deep_research.agents.workflows.reporting_support import (
    _clip_complete_report_phrase,
)
from equipment_deep_research.orchestration.capability_portrait import (
    CAPABILITY_PORTRAIT_MODULES,
    assemble_capability_portrait_modules,
    parse_capability_portrait_modules,
)

globals().update(
    {name: value for name, value in vars(_legacy).items() if not name.startswith("__")}
)

def _normalized_source_title(title: str, url: str) -> str:
    return _legacy._normalized_source_title(title, url)

def _without_tracking_parameters(url: str) -> str:
    return _legacy._without_tracking_parameters(url)

def _has_combat_effect_signal(direction: Mapping[str, Any]) -> bool:
    text = " ".join(
        str(direction.get(field, ""))
        for field in (
            "combat_effect_uplift",
            "strike_countermeasure_value",
            "operational_mechanism",
            "capability_portrait",
        )
    )
    return any(term in text for term in _COMBAT_EFFECT_TERMS)


def _has_high_order_combat_value(direction: Mapping[str, Any]) -> bool:
    """Require a concrete combat-chain effect, not generic continuity language."""

    text = " ".join(
        str(direction.get(field, ""))
        for field in (
            "name",
            "function",
            "military_value",
            "strike_countermeasure_value",
            "operational_mechanism",
            "combat_effect_uplift",
            "strike_chain_contribution",
        )
    )
    return any(term in text for term in _HIGH_ORDER_COMBAT_EFFECT_TERMS)


def _is_ordinary_support_direction(direction: Mapping[str, Any]) -> bool:
    name = str(direction.get("name", ""))
    if any(term.lower() in name.lower() for term in _PRIMARY_SUPPORT_MISSION_TERMS):
        return True
    name_has_support_identity = any(
        term in name for term in _ORDINARY_SUPPORT_LAYER_TERMS
    )
    name_has_direct_effect = any(
        term in name for term in _STRONG_DIRECT_COMBAT_EFFECT_TERMS
    ) or any(term in name for term in ("命中", "开窗", "制胜窗口"))
    name_has_combat_equipment = any(
        term.lower() in name.lower()
        for term in (
            *_DIRECT_COMBAT_EQUIPMENT_NAME_TERMS,
            *_UNMANNED_COMBAT_EQUIPMENT_TERMS,
            *_MISSILE_PRECISION_MUNITION_TERMS,
        )
    )
    if name_has_support_identity:
        return not (name_has_direct_effect and name_has_combat_equipment)

    # A direct weapon direction may legitimately contain an internal data link,
    # resupply vehicle or maintenance element. Those subordinate components do
    # not change the semantic identity of the card into a support-only direction.
    public_effect_text = " ".join(
        str(direction.get(field, ""))
        for field in (
            "function",
            "military_value",
            "operational_mechanism",
            "combat_effect_uplift",
            "strike_chain_contribution",
        )
    )
    return (
        not name_has_combat_equipment
        and not name_has_direct_effect
        and any(term in public_effect_text for term in _ORDINARY_SUPPORT_LAYER_TERMS)
        and not any(term in public_effect_text for term in _HIGH_ORDER_COMBAT_EFFECT_TERMS)
    )


def _has_combat_munition_compound(value: Any) -> bool:
    """Recognize bounded combat-munition compounds without enumerating names.

    The rule captures semantic families such as electronic-decoy, jamming,
    anti-radiation, guided and loitering munitions while logistics compounds
    remain excluded by ``_strip_weapon_support_context``.
    """

    text = _strip_weapon_support_context(str(value or ""))
    return bool(_COMBAT_MUNITION_COMPOUND_PATTERN.search(text))


def _has_specific_model_designator(value: Any) -> bool:
    """Recognize a concrete public equipment model/family in a short title."""

    text = str(value or "")
    return bool(
        re.search(
            r"(?<![A-Za-z0-9])[A-Z][A-Z0-9-]{2,}"
            r"(?:/[A-Z][A-Z0-9-]{2,})*(?![A-Za-z0-9])",
            text,
        )
        or re.search(
            r"(?<![A-Za-z0-9])[A-Z][A-Za-z0-9-]{3,}"
            r"\s+Block\s+[IVX0-9A-Za-z-]+(?![A-Za-z0-9])",
            text,
        )
        or re.search(
            r"(?<![A-Za-z0-9])[A-Z][A-Za-z0-9-]{2,}"
            r"\s+Increment\s+[0-9]+(?:/[0-9]+)*(?![A-Za-z0-9])",
            text,
        )
    )


def _direction_name_has_equipment_object(direction: Mapping[str, Any]) -> bool:
    """Return whether a direction is bound to one concrete equipment object.

    The title lexicons below are deliberately only *hints*.  New-build cards
    are authored from a structured S5/S6 identity contract, so names such as
    ``分布式效应滑翔打击舱`` must not fail merely because ``打击舱`` is not in
    a continuously growing keyword table.  The hard decision is based on the
    card's declared identity, form, mechanism and direct military effect;
    lexicon/model matches remain a backwards-compatible fast path.
    """

    name = str(direction.get("name", ""))
    semantic_check = direction.get("semantic_consistency_check")
    primary_identity = str(
        direction.get("primary_equipment_identity", "") or ""
    ).strip()
    if (
        name.rstrip("。；，, ").endswith(
            ("能力", "体系", "方案", "接口", "链路", "机制")
        )
        and not (
            isinstance(semantic_check, Mapping)
            and semantic_check.get("consistent") is True
            and primary_identity
        )
    ):
        return False
    if any(
        term.lower() in name.lower()
        for term in (
            *_DIRECT_COMBAT_EQUIPMENT_NAME_TERMS,
            *_CAPABILITY_EQUIPMENT_OBJECT_TERMS,
        )
    ):
        return True
    if _has_combat_munition_compound(name):
        return True
    # Accept concise compound equipment titles whose platform noun is split by
    # a mission modifier.  Examples from real S6 runs include
    # ``可消耗低空无人侦打诱骗机`` and ``远域反辐射压制无人僚机``;
    # requiring the contiguous token ``无人机`` caused the deterministic
    # compactor to replace these already-good titles with long equipment-form
    # fragments.  Keep the pattern bounded so abstract ``无人作战能力`` titles
    # are still rejected.
    if re.search(
        r"无人[\u3400-\u9fffA-Za-z0-9/-]{0,10}(?:机|平台|集群|蜂群)$",
        name,
    ):
        return True

    # Structured identity contract: accept novel equipment nouns without
    # enumerating every possible suffix (舱、匣、节点、载体、效应单元……).
    # Require the visible name and the declared primary/form identity to refer
    # to the same object, plus enough mission semantics to distinguish an
    # actual weapon from an abstract capability label.
    primary = str(direction.get("primary_equipment_identity", "") or "").strip()
    equipment_form = str(direction.get("equipment_form", "") or "").strip()
    identity = primary or equipment_form
    if identity and name:
        compact_name = re.sub(r"[\s、，,：:；;（）()\[\]{}\"'“”‘’]", "", name)
        compact_identity = re.sub(
            r"[\s、，,：:；;（）()\[\]{}\"'“”‘’]", "", identity
        )
        # Identity matching is structural rather than lexical: a governed
        # card may use any physical form, but its visible title and declared
        # identity must be the same object (or one may add a short descriptor
        # around the other).  Character-set overlap is intentionally avoided;
        # it caused unrelated Chinese names to look like a match.
        same_object = bool(
            compact_name
            and compact_identity
            and (
                compact_name == compact_identity
                or compact_name in compact_identity
                or compact_identity in compact_name
            )
        )
        abstract_markers = (
            "能力", "体系", "机制", "方法", "方案", "逻辑", "链路",
            "算法", "接口", "治理", "架构", "服务", "流程",
        )
        direct_semantics = " ".join(
            str(direction.get(field, "") or "")
            for field in (
                "function", "operational_mechanism", "operational_process",
                "military_value", "capability_outcome", "combat_effect_uplift",
                "strike_countermeasure_value",
            )
        )
        has_direct_semantics = bool(
            direct_semantics.strip()
            and (
                _has_combat_effect_signal(direction)
                or any(
                    marker in direct_semantics
                    for marker in _HIGH_ORDER_COMBAT_EFFECT_TERMS
                )
            )
        )
        contract_locked = bool(
            isinstance(semantic_check, Mapping)
            and semantic_check.get("consistent") is True
            and primary
        )
        if same_object and (
            contract_locked
            or (
                primary
                and has_direct_semantics
                and not any(
                    compact_name.endswith(marker)
                    for marker in abstract_markers
                )
            )
        ):
            return True
    if not _has_specific_model_designator(name):
        return False
    supporting_identity = " ".join(
        str(direction.get(field, ""))
        for field in ("baseline_system", "equipment_form")
    )
    return any(
        term.lower() in supporting_identity.lower()
        for term in _DIRECT_COMBAT_EQUIPMENT_NAME_TERMS
    )


def _is_ancillary_support_equipment_direction(
    direction: Mapping[str, Any],
) -> bool:
    """Identify concrete but non-combat support cards such as camouflage sites."""

    if _equipment_direction_categories(direction):
        return False
    name = str(direction.get("name", ""))
    name_is_support = any(
        term in name for term in _ANCILLARY_SUPPORT_EQUIPMENT_TERMS
    )
    name_has_combat_equipment = _direction_name_has_equipment_object(direction)
    name_has_direct_effect = any(
        term in name for term in _HIGH_ORDER_COMBAT_EFFECT_TERMS
    )
    if name_is_support:
        return not (name_has_combat_equipment and name_has_direct_effect)

    # A fire-control vehicle, weapon system or unmanned effector may contain a
    # camouflage, resupply or maintenance submodule.  That subordinate module
    # must not reclassify the entire combat card as a support-only direction.
    identity = " ".join(
        str(direction.get(field, ""))
        for field in ("name", "equipment_form", "function", "military_value")
    )
    return (
        not name_has_combat_equipment
        and not name_has_direct_effect
        and any(term in identity for term in _ANCILLARY_SUPPORT_EQUIPMENT_TERMS)
    )


def _query_explicitly_requests_support_equipment(query: str) -> bool:
    normalized = re.sub(r"\s+", "", str(query or ""))
    return bool(normalized) and any(
        term in normalized for term in _SUPPORT_FOCUSED_QUERY_TERMS
    )


def _weapon_equipment_identity(direction: Mapping[str, Any]) -> str:
    package = direction.get("upgrade_package", [])
    package_text = (
        " ".join(str(item) for item in package)
        if isinstance(package, list)
        else str(package)
    )
    return " ".join(
        (
            str(direction.get("name", "")),
            str(direction.get("equipment_form", "")),
            str(direction.get("baseline_system", "")),
            package_text,
        )
    )


def _strip_weapon_support_context(value: str) -> str:
    """Remove logistics-only mentions before classifying weapon identity.

    A support platform such as an ammunition resupply vehicle must not satisfy
    a missile/munition portfolio gate merely because its name contains
    ``弹药``.  The remaining text is still available to other equipment-class
    checks; this helper only removes support compounds from weapon semantics.
    """

    cleaned = str(value)
    for pattern in _WEAPON_SUPPORT_CONTEXT_PATTERNS:
        cleaned = pattern.sub("支援装备", cleaned)
    return cleaned


def _equipment_direction_categories(direction: Mapping[str, Any]) -> set[str]:
    """Classify the primary equipment role using name-led semantics.

    Portfolio gates intentionally lead with the user-facing direction name and
    verify it against the concrete equipment form.  A term buried only in an
    upgrade package or support baseline is not considered an independent
    weapon-development direction.
    """

    name = _strip_weapon_support_context(str(direction.get("name", "")))
    equipment_form = _strip_weapon_support_context(
        str(direction.get("equipment_form", ""))
    )
    identity = f"{name} {equipment_form}".lower()
    categories: set[str] = set()
    if any(term.lower() in identity for term in _UNMANNED_COMBAT_EQUIPMENT_TERMS):
        categories.add("unmanned_combat_platform")

    name_has_munition = any(
        term.lower() in name.lower() for term in _MISSILE_PRECISION_MUNITION_TERMS
    ) or _has_combat_munition_compound(name)
    name_has_precision_concept = any(
        term in name for term in _MISSILE_PRECISION_MUNITION_NAME_CONCEPTS
    )
    form_has_munition = any(
        term.lower() in equipment_form.lower()
        for term in _MISSILE_PRECISION_MUNITION_TERMS
    ) or _has_combat_munition_compound(equipment_form)
    if name_has_munition or (name_has_precision_concept and form_has_munition):
        categories.add("missile_precision_munition")

    if any(
        term in identity
        for term in (
            "火炮",
            "舰炮",
            "武器站",
            "定向能",
            "激光武器",
            "高能激光",
            "激光器",
            "高功率微波",
            "拦截器",
            "截击器",
            "电子攻击",
            "电子压制器",
            "反无人效应器",
        )
    ):
        categories.add("direct_weapon_effector")
    elif "效应器" in identity and _has_high_order_combat_value(direction):
        categories.add("direct_weapon_effector")

    # Mobile launchers and precision-fire vehicles are direct combat equipment,
    # not support nodes.  Keep this name-led and effect-gated so an ammunition
    # truck or generic C2 vehicle cannot satisfy the portfolio requirement just
    # because its equipment list mentions a launcher.
    direct_fire_platform_terms = (
        "发射车",
        "火力车",
        "炮车",
        "拦截车",
        "压制车",
        "截击器车",
        "发射单元",
        "武器站",
        "自行火炮",
        "舰炮",
        "火炮",
    )
    name_has_direct_fire_platform = any(term in name for term in direct_fire_platform_terms)
    model_led_direct_fire_platform = (
        _has_specific_model_designator(name)
        and any(term in equipment_form for term in direct_fire_platform_terms)
        and any(term in name for term in _HIGH_ORDER_COMBAT_EFFECT_TERMS)
    )
    if (
        name_has_direct_fire_platform or model_led_direct_fire_platform
    ) and _has_high_order_combat_value(direction):
        categories.add("direct_fire_platform")
    # New-build effectors may use a novel physical form (for example a
    # distributed glide strike pod) that is intentionally absent from the
    # legacy noun tables.  Once the structured identity contract is coherent
    # and the card states a high-order combat effect, classify it as a direct
    # effector without guessing a family from its spelling.
    if (
        _direction_name_has_equipment_object(direction)
        and _has_high_order_combat_value(direction)
        and bool(
            str(direction.get("primary_equipment_identity", "") or "").strip()
            or (
                str(direction.get("name", "")).strip()
                and str(direction.get("name", "")).strip()
                == str(direction.get("equipment_form", "")).strip()
            )
        )
        and not any(
            marker in str(direction.get("name", ""))
            for marker in _PRIMARY_SUPPORT_MISSION_TERMS
        )
    ):
        categories.add("structured_direct_effector")
    return categories


def _is_unmanned_combat_equipment_direction(direction: Mapping[str, Any]) -> bool:
    return "unmanned_combat_platform" in _equipment_direction_categories(direction)


def _is_lethal_weapon_equipment_direction(direction: Mapping[str, Any]) -> bool:
    return bool(
        _equipment_direction_categories(direction)
        & {
            "missile_precision_munition",
            "direct_weapon_effector",
            "direct_fire_platform",
            "structured_direct_effector",
        }
    )


def _is_missile_precision_munition_direction(
    direction: Mapping[str, Any],
) -> bool:
    return "missile_precision_munition" in _equipment_direction_categories(direction)


def _dedupe_capability_title(value: Any) -> str:
    title = re.sub(r"\s+", " ", str(value or "").strip())
    # Drop presentation-only enumerators emitted by upstream synthesis while
    # preserving model names such as AARGM-ER, B-21 and 2S35.  Requiring a
    # punctuation separator keeps genuine equipment identifiers intact.
    title = re.sub(
        r"^(?:[A-Za-z]\d{1,2}|[A-Za-z]|\d{1,2}|候选[A-Za-z0-9]{0,3})\s*[\.．、:：]\s*(?=\S)",
        "",
        title,
    )
    # Chinese titles frequently contain layout whitespace that is never
    # semantic, while ASCII equipment abbreviations may legitimately contain
    # one space (for example ``FAAD C2``).  Remove whitespace touching CJK
    # characters, but preserve a normalized single space between ASCII tokens.
    title = re.sub(r"(?<=[\u3400-\u9fff]) +| +(?=[\u3400-\u9fff])", "", title)
    title = re.sub(r" *([。；，、：]) *", r"\1", title)
    title = re.sub(r"[。；，、:：]+$", "", title)
    for term in _CAPABILITY_TITLE_REPEAT_TERMS:
        repeated = term + term
        while repeated in title:
            title = title.replace(repeated, term)
    return title


def _s6_title_requires_structural_repair(
    direction: Mapping[str, Any],
    title: str,
) -> bool:
    """Tell a complete weapon identity from a label or a malformed title.

    Dynamic-swarm candidates are allowed to carry a long, query-specific
    equipment name straight into S6.  This predicate is intentionally about
    *structure*, never length: it preserves a valid specific name while still
    sending labels, public baseline names and platform/payload mix-ups through
    the established deterministic title resolver.
    """

    normalized = _dedupe_capability_title(title)
    if not normalized:
        return True
    if re.match(r"^[A-Za-z][A-Za-z0-9./ -]{2,}", normalized):
        return True
    if re.search(r"具备|能够|可以|通过|实现|以及|包括|已集成", normalized):
        return True
    if normalized.startswith(("含", "由", "采用")):
        return True
    if "或" in normalized and sum(
        term in normalized for term in _CAPABILITY_EQUIPMENT_OBJECT_TERMS
    ) >= 2:
        return True
    if any(marker in normalized for marker in ("证据链", "任务链", "信息链", "杀伤链", "闭环")):
        return True
    if normalized.endswith(
        (
            "窗口", "续接", "支撑", "协同", "再捕获", "补击", "补射", "目标发现",
            "火力", "平台", "弹药", "弹群",
        )
    ):
        return True
    if not _direction_name_has_equipment_object({**direction, "name": normalized}):
        return True

    # Where the equipment form explicitly establishes a launcher, carrier or
    # mother-round as the main combat object, do not retain a payload-only or
    # ramming-platform title merely because it happens to name an equipment.
    form = str(direction.get("equipment_form", ""))
    primary_form_markers = (
        "栖岛弹舱", "岛岸弹舱", "岛礁弹舱", "巡飞弹发射舱",
        "短距起降", "短距起飞", "巡航母弹", "运输母弹", "远程母弹",
    )
    if any(marker in form for marker in primary_form_markers) and not any(
        marker in normalized for marker in primary_form_markers
    ):
        return True
    if (
        any(
            marker in form
            for marker in ("半潜无人艇", "半潜无人平台", "无人半潜平台", "巡航弹舱")
        )
        and any(marker in form for marker in ("巡航弹", "远程弹药", "远程反舰", "火力舱"))
        and not any(marker in normalized for marker in ("弹舱", "火力舱", "巡航弹无人艇"))
    ):
        return True
    return False


def _capability_title_equipment_anchor(value: Any) -> str:
    """Extract a concise equipment object instead of copying a baseline sentence."""

    text = _clean_capability_handoff_text(value, limit=180)
    text = re.sub(
        r"^(?:该卡独有)?(?:现役或类比)?(?:装备)?基线(?:为|是)|^被升级对象为|^升级",
        "",
        text,
    ).strip(" ：:，,；。")
    text = re.split(
        r"具备|能够|可以|通过|依托|用于|实现|形成|获得|提升|增强|已集成|主要依赖",
        text,
        maxsplit=1,
    )[0].strip(" ：:，,；。")

    model_match = re.search(
        r"(?<![A-Za-z0-9])([A-Z][A-Z0-9-]{2,}(?:/[A-Z][A-Z0-9-]{2,})+)(?![A-Za-z0-9])",
        text,
    )
    if model_match and any(
        term.lower() in text.lower()
        for term in (
            *_DIRECT_COMBAT_EQUIPMENT_NAME_TERMS,
            "防空",
            "反无人",
            "武器",
            "作战系统",
            "任务系统",
        )
    ):
        model_parts = model_match.group(1).split("/")
        # Public baselines often enumerate several adjacent systems in one
        # sentence (MADIS/L-MADIS/O-CSUAS/MRIC).  A capability title needs the
        # primary family, not a truncated tail of the whole catalogue.
        anchor = "/".join(model_parts[:2])
        return f"{'现役' if '现役' in text else ''}{anchor}"

    candidates = [
        re.sub(
            r"^(?:公开证据(?:显示|表明)?|其中|该方向|本方向|该能力|升级)",
            "",
            item,
        ).strip(" ：:，,；。")
        for item in re.split(r"[、，,；。]|以及|并包括|包括|和|与|及", text)
    ]
    candidates = [item for item in candidates if item]
    equipment_terms = tuple(
        dict.fromkeys(
            (*_DIRECT_COMBAT_EQUIPMENT_NAME_TERMS, *_CAPABILITY_EQUIPMENT_OBJECT_TERMS)
        )
    )

    def score(item: str, position: int) -> tuple[int, int, int]:
        specific = sum(
            marker in item
            for marker in (
                "弹炮结合",
                "弹炮合一",
                "巡飞弹",
                "无人",
                "导弹",
                "拦截弹",
                "火控",
                "电子战",
                "破障",
                "扫雷",
            )
        )
        has_object = any(term.lower() in item.lower() for term in equipment_terms)
        return (int(has_object) * 10 + specific * 3, min(len(item), 18), -position)

    anchored = [
        (item, position)
        for position, item in enumerate(candidates)
        if any(term.lower() in item.lower() for term in equipment_terms)
    ]
    anchor = (
        max(anchored, key=lambda row: score(row[0], row[1]))[0]
        if anchored
        else (candidates[0] if candidates else text)
    )
    if "现役" in text and not anchor.startswith("现役"):
        anchor = "现役" + anchor
    anchor = re.sub(r"(?:相关|综合|一体化)+$", "", anchor).strip()
    if len(anchor) > 18:
        compact = re.sub(r"有人驾驶|公开基线|类比装备|综合|一体化", "", anchor)
        anchor = compact if len(compact) <= 18 else compact[:18]
    return anchor.rstrip("的与和及、，；")


def _capability_upgrade_effect_anchor(identity: str, effect_text: str) -> str:
    del identity
    return str(effect_text).strip()


def _compact_capability_direction_title(direction: Mapping[str, Any]) -> str:
    """Preserve the Agent-authored weapon identity after light cleanup.

    Equipment naming is an upstream reasoning decision.  This delivery helper
    must not infer a weapon family or manufacture a name from keyword matches,
    a foreign baseline, a payload mention, or a stock combat-effect lexicon.
    """

    name = _dedupe_capability_title(direction.get("name", ""))
    return name


def _uniquify_compacted_capability_titles(
    directions: list[Any],
) -> list[Any]:
    """Keep title collisions visible for the semantic quality gate.

    A local descriptor dictionary can make duplicate concepts look novel.
    Only the query-aware Agent may rename or split a candidate; deterministic
    normalization therefore preserves the submitted identities unchanged.
    """

    return directions


def _capability_portrait_alignment_issues(
    position: int,
    direction: Mapping[str, Any],
) -> list[str]:
    """Check the governed portrait contract without inferring a weapon family."""

    portrait = str(direction.get("capability_portrait", "") or "").strip()
    if not portrait:
        return []
    label = f"第{position}项" if position > 0 else "该项"
    issues: list[str] = []
    required_markers = (
        "概述：",
        "装备与技术实现：",
        "关键作战流程：",
        "形成能力与作战效果：",
        "制胜逻辑机理：",
    )
    missing = [marker for marker in required_markers if marker not in portrait]
    if direction.get("capability_classification") and "能力分类：" not in portrait:
        missing.insert(0, "能力分类：")
    if missing:
        issues.append(f"{label}装备能力画像缺少治理模块：{'、'.join(missing)}")
    if "发展与验证路径：" in portrait:
        issues.append(f"{label}仍含已废弃的第五分点；验证信息应仅保留在独立结构化字段")
    if any(marker in portrait for marker in ("Harness", "Packet", "Claim")):
        issues.append(f"{label}装备能力画像泄露内部执行标签")

    return issues


def _capability_language_issues(
    position: int,
    direction: Mapping[str, Any],
    *,
    semantic_contract_required: bool = False,
) -> list[str]:
    """Validate presentation structure without re-judging model semantics."""

    del semantic_contract_required
    issues: list[str] = []
    name = str(direction.get("name", "")).strip()
    normalized_name = _dedupe_capability_title(name)
    if not normalized_name:
        issues.append(f"S6第{position}项标题为空")
        return issues
    if normalized_name != name:
        issues.append(f"S6第{position}项标题存在重复词、冗余标点或空白")
    for left, right in (("（", "）"), ("(", ")"), ("“", "”")):
        if normalized_name.count(left) != normalized_name.count(right):
            issues.append(f"S6第{position}项标题括号或引号不配对")
            break
    return issues


def _collect_reference_ids(value: Any) -> set[str]:
    references: set[str] = set()
    if isinstance(value, Mapping):
        for item in value.values():
            references.update(_collect_reference_ids(item))
    elif isinstance(value, list):
        for item in value:
            references.update(_collect_reference_ids(item))
    elif isinstance(value, str) and value.startswith(("ev-", "packet-")):
        references.add(value)
    return references


def _normalize_effect_chain_references(
    value: Any,
    effect_chain_count: int,
) -> Any:
    """Normalize common numeric and lettered effect-chain references."""

    if effect_chain_count <= 0:
        return value
    if isinstance(value, Mapping):
        return {
            str(key): _normalize_effect_chain_references(item, effect_chain_count)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            _normalize_effect_chain_references(item, effect_chain_count)
            for item in value
        ]
    if not isinstance(value, str):
        return value

    def replace_numeric(match: re.Match[str]) -> str:
        index = int(match.group(1))
        if index == effect_chain_count:
            return f"effect_chain[{effect_chain_count - 1}]"
        return match.group(0)

    normalized = re.sub(r"effect_chain\[(\d+)\]", replace_numeric, value)

    def replace_letter(match: re.Match[str]) -> str:
        index = ord(match.group(1).upper()) - ord("A")
        if 0 <= index < effect_chain_count:
            return f"effect_chain[{index}]"
        return match.group(0)

    return re.sub(
        r"effect_chain:(?:链条)?([A-Z])",
        replace_letter,
        normalized,
        flags=re.IGNORECASE,
    )


def _normalize_concept_direction_priorities(value: Mapping[str, Any]) -> dict[str, Any]:
    """Make the final S6 ranking unique and contiguous in output order."""

    result = dict(value)
    rows = result.get("concept_directions", [])
    if not isinstance(rows, list):
        return result
    result["concept_directions"] = [
        {**dict(item), "priority": f"P{index}"}
        if isinstance(item, Mapping)
        else item
        for index, item in enumerate(rows, start=1)
    ]
    return result


def _normalize_priority_references(value: Any, maximum: int) -> Any:
    """Clamp advisory P-number references after S6 has finalized its ranking."""

    if maximum <= 0:
        return value
    if isinstance(value, Mapping):
        return {
            str(key): _normalize_priority_references(item, maximum)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_normalize_priority_references(item, maximum) for item in value]
    if not isinstance(value, str):
        return value

    def replace(match: re.Match[str]) -> str:
        priority = int(match.group(1))
        return f"P{min(priority, maximum)}"

    return re.sub(r"(?<![A-Za-z0-9])P(\d+)(?!\d)", replace, value)


def _prioritized_evidence_index(
    rows: Sequence[Any],
    *,
    preferred_ids: set[str],
    allowed_agents: set[str],
    limit: int,
) -> list[dict[str, Any]]:
    candidates = [dict(item) for item in rows if isinstance(item, Mapping)]

    def rank(item: Mapping[str, Any]) -> tuple[int, str]:
        evidence_id = str(item.get("evidence_id", ""))
        created_by = str(item.get("created_by", ""))
        if evidence_id in preferred_ids:
            priority = 0
        elif allowed_agents and created_by in allowed_agents:
            priority = 1
        else:
            priority = 2
        return priority, evidence_id

    return sorted(candidates, key=rank)[: max(1, int(limit))]


def _compact_s6_prior_outputs(value: Mapping[str, Any]) -> dict[str, Any]:
    """Project decision-bearing S3-S5 fields without replaying entire outputs."""

    def text_rows(key: str, *, limit: int = 8, chars: int = 700) -> list[Any]:
        rows = value.get(key, [])
        if not isinstance(rows, list):
            return []
        return [
            _compact_prompt_value(item, max_string_chars=chars, max_list_items=8)
            for item in rows[:limit]
        ]

    def object_rows(
        key: str,
        fields: Sequence[str],
        *,
        limit: int = 8,
        chars: int = 420,
    ) -> list[dict[str, Any]]:
        rows = value.get(key, [])
        if not isinstance(rows, list):
            return []
        return [
            {
                field: _compact_prompt_value(
                    item[field],
                    max_string_chars=chars,
                    max_list_items=8,
                )
                for field in fields
                if field in item
            }
            for item in rows[:limit]
            if isinstance(item, Mapping)
        ]

    result: dict[str, Any] = {}
    for key in (
        "capability_mapping",
        "winning_paths",
        "effect_chain",
        "breakthrough_directions",
    ):
        projected = text_rows(key)
        if projected:
            result[key] = projected
    gaps = object_rows(
        "gap_assessment",
        (
            "capability",
            "grade",
            "gap_statement",
            "evidence_strength",
            "current_upgrade",
            "new_development",
            "verification",
            "evidence_refs",
            "basis",
        ),
    )
    if gaps:
        result["gap_assessment"] = gaps
    directions = object_rows(
        "s4_concept_directions",
        (
            "name",
            "priority",
            "type",
            "function",
            "feasibility",
            "feasibility_basis",
            "direct_evidence_refs",
            "derived_from",
            "verification",
            "uncertainty_boundary",
            "military_value",
            "depth_mechanism",
            "foresight",
            "novelty",
            "strike_countermeasure_value",
            "equipment_form",
            "operational_mechanism",
        ),
        limit=6,
    )
    if directions:
        result["s4_concept_directions"] = directions
    return result


_CAPABILITY_HANDOFF_INTERNAL_PATTERN = re.compile(
    r"(?i)(?<![A-Za-z0-9])(?:S[1-6]|L[1-4])(?![A-Za-z0-9])|"
    r"Codex|Harness|Packet|Claim|Agent|智能体|循环门控|执行轨迹|物理Cohort|"
    r"候选账本|专家盲评|非支配候选|组合评审|质量门|角色合同|补写|交接状态|"
    r"退回S[1-6]|回到S[1-6]"
)


def _evidence_boundary_is_public_semantic(value: Any) -> bool:
    """Accept only user-facing epistemic limits, never workflow commentary.

    ``evidence_boundary`` describes what public material supports and what
    remains an inference or hypothesis.  It is not an orchestration note.  A
    boundary containing stage/agent language must be removed before S6 rather
    than copied into a card and discovered by the final delivery gate.
    """

    text = " ".join(str(value or "").split()).strip()
    if not text or _CAPABILITY_HANDOFF_INTERNAL_PATTERN.search(text):
        return False
    has_evidence_subject = any(
        marker in text
        for marker in (
            "公开证据",
            "公开资料",
            "公开材料",
            "现有证据",
            "现有资料",
            "对象证据",
            "证据",
            "相邻项目",
            "组成技术",
            "类比装备",
        )
    )
    has_epistemic_limit = any(
        marker in text
        for marker in (
            "不证明",
            "不能证明",
            "不足以证明",
            "不能外推",
            "不得外推",
            "仅支持",
            "只支持",
            "尚无",
            "未证明",
            "待验证",
            "属于研究假设",
        )
    )
    return has_evidence_subject and has_epistemic_limit

_CAPABILITY_EQUIPMENT_OBJECT_TERMS = (
    "平台",
    "系统",
    "雷达",
    "预警机",
    "无人机",
    "无人僚机",
    "无人艇",
    "无人潜航器",
    "巡航弹",
    "打击弹",
    "舰",
    "船",
    "车辆",
    "炮车",
    "拦截车",
    "压制车",
    "截击器车",
    "卫星",
    "星座",
    "导弹",
    "巡飞弹",
    "反辐射弹",
    "电子压制弹",
    "诱饵弹",
    "无人弹",
    "弹药",
    "拦截弹",
    "拦截器",
    "截击器",
    "发射单元",
    "武器站",
    "指挥所",
    "终端",
    "任务载荷",
    "传感器",
    "通信节点",
    "数据链",
    "电子战",
    "效应器",
    "保障节点",
    "维修",
    "补给",
    "母舰",
)

_CAPABILITY_STAGE_TERMS = (
    "侦察",
    "预警",
    "识别",
    "跟踪",
    "指挥",
    "决策",
    "机动",
    "突防",
    "交战",
    "火力",
    "拦截",
    "打击",
    "毁伤",
    "评估",
    "重组",
    "保障",
    "恢复",
    "持续作战",
)

_QUERY_RELEVANCE_ANCHOR_TERMS = (
    "西太",
    "台海",
    "近海",
    "远海",
    "海上",
    "陆上",
    "空中",
    "太空",
    "城市战",
    "岛礁",
    "局部战争",
    "高强度对抗",
    "反介入",
    "区域拒止",
    "强干扰",
    "电磁干扰",
    "弱通信",
    "通信受限",
    "链路不稳定",
    "低信息依赖",
    "导航拒止",
    "饱和突防",
    "饱和攻击",
    "无人集群",
    "无人作战",
    "远程精确火力",
    "反舰",
    "防空",
    "反导",
    "反无人",
    "制海",
    "制空",
    "人工智能",
    "自主协同",
    "精确制导",
)

_QUERY_RELEVANCE_PRESSURE_TERMS = (
    "威胁",
    "对手",
    "受压",
    "强干扰",
    "压制",
    "诱饵",
    "突防",
    "饱和",
    "蜂群",
    "集群",
    "低成本",
    "高强度",
    "节点损耗",
    "生存压力",
    "反介入",
    "区域拒止",
)


def _query_relevance_issues(
    position: int,
    direction: Mapping[str, Any],
    *,
    query: str,
) -> list[str]:
    """Validate that a missile card explains a query-led causal mapping.

    This deliberately inspects the dedicated ``query_relevance`` field rather
    than accepting topical words scattered across the rest of the card.  It is
    a bounded semantic contract, not a general similarity score: the statement
    must retain a topic anchor from the user's query and connect a pressured
    mission stage to a direct combat effect.
    """

    relevance = str(direction.get("query_relevance", "")).strip()
    if not relevance:
        return []  # The general required-field check reports this separately.

    issues: list[str] = []
    normalized_query = re.sub(r"\s+", "", str(query or ""))
    normalized_relevance = re.sub(r"\s+", "", relevance)
    anchors = [
        term for term in _QUERY_RELEVANCE_ANCHOR_TERMS if term in normalized_query
    ]
    if anchors and not any(term in normalized_relevance for term in anchors):
        issues.append(
            f"S6第{position}项导弹/精确制导弹药方向未保留当前query的主题锚点"
            f"（至少应明确{ '、'.join(anchors[:4]) }之一），不能用通用导弹需求凑数"
        )
    if not any(term in relevance for term in _CAPABILITY_STAGE_TERMS):
        issues.append(
            f"S6第{position}项导弹/精确制导弹药方向的query_relevance未明确作用的作战阶段"
        )
    if not any(term in relevance for term in _QUERY_RELEVANCE_PRESSURE_TERMS):
        issues.append(
            f"S6第{position}项导弹/精确制导弹药方向的query_relevance未明确威胁压力"
        )
    if not any(term in relevance for term in _HIGH_ORDER_COMBAT_EFFECT_TERMS):
        issues.append(
            f"S6第{position}项导弹/精确制导弹药方向的query_relevance未说明毁伤、"
            "拦截、拒止或其他直接作战效果"
        )
    return issues


def _truncate_complete_text(text: str, *, limit: int) -> str:
    """Keep bounded user-facing text on a complete sentence boundary."""

    if len(text) <= limit:
        return text
    candidate = text[:limit]
    sentence_end = max(candidate.rfind(mark) for mark in "。！？!?\n")
    if sentence_end >= max(80, limit // 2):
        return candidate[: sentence_end + 1].rstrip()
    return text


def _clean_capability_handoff_text(
    value: Any, *, limit: int | None = 360
) -> str:
    """Remove orchestration language before S6 sees an upstream judgment."""

    text = " ".join(str(value or "").replace("\n", " ").split())
    text = _CAPABILITY_HANDOFF_INTERNAL_PATTERN.sub("", text)
    text = re.sub(r"(?:packet|claim|reasoning|trace)-[A-Za-z0-9_.:-]+", "", text, flags=re.I)
    text = re.sub(r"\s{2,}", " ", text).strip(" ；,，")
    return text if limit is None else _truncate_complete_text(text, limit=limit)


def _capability_handoff_statement(value: Any, *, limit: int = 360) -> str:
    if isinstance(value, Mapping):
        preferred = (
            "name",
            "capability",
            "task",
            "scenario",
            "gap_statement",
            "conclusion",
            "function",
            "mechanism",
            "effect",
            "military_value",
            "strike_countermeasure_value",
            "combat_effect_uplift",
            "strike_chain_contribution",
            "operational_mechanism",
            "basis",
        )
        parts = [
            _clean_capability_handoff_text(value.get(field), limit=180)
            for field in preferred
            if value.get(field) not in (None, "", [], {})
        ]
        return _clean_capability_handoff_text("；".join(dict.fromkeys(parts)), limit=limit)
    if isinstance(value, list):
        parts = [
            _capability_handoff_statement(item, limit=180)
            for item in value[:3]
        ]
        return _clean_capability_handoff_text("；".join(filter(None, parts)), limit=limit)
    return _clean_capability_handoff_text(value, limit=limit)


def _capability_synthesis_handoff(
    *,
    topic: str,
    branch: str,
    prior_step_outputs: Mapping[str, Any],
    evidence_index: Sequence[Any],
    s6_parallelism: int | None = None,
) -> dict[str, Any]:
    """Build the only upstream context consumed by the independent S6 call.

    The projection intentionally excludes role names, execution governance,
    reasoning-node payloads and complete upstream objects. S6 receives the
    query plus a few decision-bearing military judgments and public sources.
    """

    def statements(*keys: str, limit: int) -> list[str]:
        rows: list[str] = []
        for key in keys:
            raw = prior_step_outputs.get(key, [])
            values = raw if isinstance(raw, list) else [raw]
            for item in values:
                text = _capability_handoff_statement(item)
                if text and text not in rows:
                    rows.append(text)
                if len(rows) >= limit:
                    return rows
        return rows

    def high_value_effects(*keys: str, limit: int) -> list[str]:
        rows: list[str] = []

        def visit(value: Any) -> None:
            if len(rows) >= limit:
                return
            if isinstance(value, Mapping):
                text = _capability_handoff_statement(value, limit=300)
                if (
                    text
                    and any(term in text for term in _HIGH_ORDER_COMBAT_EFFECT_TERMS)
                    and text not in rows
                ):
                    rows.append(text)
                for item in value.values():
                    visit(item)
            elif isinstance(value, list):
                for item in value:
                    visit(item)
            else:
                text = _clean_capability_handoff_text(value, limit=300)
                if (
                    text
                    and any(term in text for term in _HIGH_ORDER_COMBAT_EFFECT_TERMS)
                    and text not in rows
                ):
                    rows.append(text)

        for key in keys:
            visit(prior_step_outputs.get(key, []))
            if len(rows) >= limit:
                break
        return rows[:limit]

    gaps: list[dict[str, Any]] = []
    for item in prior_step_outputs.get("gap_assessment", [])[:6]:
        if not isinstance(item, Mapping):
            continue
        row = {
            "capability": _clean_capability_handoff_text(item.get("capability"), limit=100),
            "grade": _clean_capability_handoff_text(item.get("grade"), limit=40),
            "gap": _clean_capability_handoff_text(
                item.get("gap_statement") or item.get("basis"), limit=260
            ),
            "verification": _clean_capability_handoff_text(
                item.get("verification"), limit=160
            ),
            "evidence_refs": [
                str(ref) for ref in item.get("evidence_refs", [])[:4]
            ],
        }
        gaps.append({key: value for key, value in row.items() if value not in ("", [])})
        if len(gaps) >= 3:
            break

    preferred_ids = _collect_reference_ids(
        {
            "effect_chain": prior_step_outputs.get("effect_chain", []),
            "gap_assessment": prior_step_outputs.get("gap_assessment", []),
            "s4_concept_directions": prior_step_outputs.get(
                "s4_concept_directions", []
            ),
        }
    )
    raw_evidence_rows = [
        dict(item) for item in evidence_index if isinstance(item, Mapping)
    ]
    direct_weapon_rows = [
        item
        for item in raw_evidence_rows
        if str(item.get("created_by", "")) == "weapon_equipment"
        or str(item.get("evidence_id", "")).startswith("ev-weapon_equipment-")
    ]
    evidence_rows = _prioritized_evidence_index(
        direct_weapon_rows,
        preferred_ids=preferred_ids,
        allowed_agents={"weapon_equipment"},
        limit=12,
    )
    selected_evidence_ids = {
        str(item.get("evidence_id", "")) for item in evidence_rows
    }
    if len(evidence_rows) < 14:
        evidence_rows.extend(
            _prioritized_evidence_index(
                [
                    item
                    for item in raw_evidence_rows
                    if str(item.get("evidence_id", ""))
                    not in selected_evidence_ids
                ],
                preferred_ids=preferred_ids,
                allowed_agents=set(),
                limit=14 - len(evidence_rows),
            )
        )
    evidence: list[dict[str, str]] = []
    for item in evidence_rows:
        row = {
            "evidence_id": str(item.get("evidence_id", "")),
            "title": _clean_capability_handoff_text(
                item.get("source_title"), limit=120
            ),
            "url": str(item.get("source_url", "")).strip(),
            "claim": _clean_capability_handoff_text(item.get("claim"), limit=220),
            "excerpt": _clean_capability_handoff_text(
                item.get("excerpt"), limit=260
            ),
            "quality": _clean_capability_handoff_text(
                item.get("quality_assessment") or item.get("source_tier"),
                limit=100,
            ),
        }
        evidence.append({key: value for key, value in row.items() if value})

    preflight_rows: list[dict[str, Any]] = []
    raw_preflight = prior_step_outputs.get("s6_preflight", {})
    if isinstance(raw_preflight, Mapping):
        for item in raw_preflight.get("equipment_buckets", [])[:6]:
            if not isinstance(item, Mapping):
                continue
            category = str(item.get("category", "")).strip()
            if not category:
                continue
            row = {
                "category": category,
                "ready": item.get("ready") is True,
                "query_relevance": _clean_capability_handoff_text(
                    item.get("query_relevance"), limit=220
                ),
                "baseline_system": _clean_capability_handoff_text(
                    item.get("baseline_system"), limit=180
                ),
                "capability_gap": _clean_capability_handoff_text(
                    item.get("capability_gap"), limit=220
                ),
                "candidate_equipment": _clean_capability_handoff_text(
                    item.get("candidate_equipment"), limit=160
                ),
                "evidence_refs": [
                    str(ref) for ref in item.get("evidence_refs", [])[:4]
                ],
                "blocking_reason": _clean_capability_handoff_text(
                    item.get("blocking_reason"), limit=180
                ),
            }
            preflight_rows.append(
                {key: value for key, value in row.items() if value not in ("", [])}
            )

    dynamic_swarm = prior_step_outputs.get("winning_swarm", {})
    dynamic_swarm = dynamic_swarm if isinstance(dynamic_swarm, Mapping) else {}
    dynamic_policy = dynamic_swarm.get("policy", {})
    dynamic_policy = dynamic_policy if isinstance(dynamic_policy, Mapping) else {}
    hypothesis_ledger = dynamic_swarm.get("hypothesis_ledger", {})
    hypothesis_ledger = (
        hypothesis_ledger if isinstance(hypothesis_ledger, Mapping) else {}
    )
    source_titles_by_id = {
        str(item.get("hypothesis_id", "")): str(item.get("title", "")).strip()
        for item in hypothesis_ledger.get("hypotheses", [])
        if isinstance(item, Mapping)
        and str(item.get("hypothesis_id", "")).strip()
        and str(item.get("title", "")).strip()
    }
    raw_selected_portfolio = dynamic_swarm.get("final_equipment_portfolio", [])
    selected_portfolio: list[dict[str, Any]] = []
    if isinstance(raw_selected_portfolio, list):
        for item in raw_selected_portfolio:
            if (
                not isinstance(item, Mapping)
                or item.get("direct_combat_equipment") is False
                or not str(item.get("name") or item.get("equipment_form") or "").strip()
            ):
                continue
            projected = {
                key: item.get(key)
                for key in (
                    "hypothesis_id", "name", "source_hypothesis_title", "type", "equipment_form",
                    "direct_combat_equipment",
                    "primary_equipment_identity", "target_scenario", "problem_statement",
                    "military_value", "mission_effects", "equipment_forms",
                    "baseline_system", "capability_gap", "direct_evidence_refs",
                    "evidence_ids", "failure_boundaries", "failure_boundary",
                    "validation_plan", "indicator_portrait", "query_relevance",
                    "capability_classification",
                    "concise_winning_summary",
                    "unique_operational_role", "launch_or_release_domain",
                    "target_and_direct_effect", "non_substitutable_difference",
                    "portfolio_identity_contract", "foresight_evidence_status",
                    "evidence_boundary", "expert_score", "expert_assessment_id",
                )
                if item.get(key) not in (None, "", [])
            }
            # S6 must receive the selected military judgment, not upstream
            # orchestration labels accidentally embedded in evidence notes or
            # candidate prose. Identity fields remain byte-for-byte frozen;
            # narrative contract fields are cleaned before they become public
            # card inputs.
            for field in (
                "unique_operational_role",
                "launch_or_release_domain",
                "target_and_direct_effect",
                "non_substitutable_difference",
                "target_scenario",
                "problem_statement",
                "military_value",
                "baseline_system",
                "capability_gap",
                "failure_boundary",
                "indicator_portrait",
                "query_relevance",
                "concise_winning_summary",
                "evidence_boundary",
            ):
                if field in projected:
                    raw_value = projected[field]
                    cleaned_value = _clean_capability_handoff_text(
                        raw_value,
                        limit=None,
                    )
                    if field == "evidence_boundary" and (
                        _CAPABILITY_HANDOFF_INTERNAL_PATTERN.search(
                            str(raw_value or "")
                        )
                        or not _evidence_boundary_is_public_semantic(cleaned_value)
                    ):
                        # This is optional traceability context.  Dropping a
                        # polluted workflow note is safer than freezing it as
                        # public S6 prose; the S6 writer may author a clean
                        # evidence boundary from the supplied evidence.
                        projected.pop(field, None)
                    else:
                        projected[field] = cleaned_value
            for field in (
                "mission_effects",
                "failure_boundaries",
                "validation_plan",
            ):
                if isinstance(projected.get(field), list):
                    projected[field] = [
                        cleaned
                        for value in projected[field]
                        if (
                            cleaned := _clean_capability_handoff_text(
                                value,
                                limit=None,
                            )
                        )
                    ]
            hypothesis_id = str(projected.get("hypothesis_id", ""))
            if not str(projected.get("source_hypothesis_title", "")).strip():
                source_title = source_titles_by_id.get(hypothesis_id, "")
                if source_title:
                    projected["source_hypothesis_title"] = source_title
            selected_portfolio.append(projected)
    return {
        "query": _clean_capability_handoff_text(topic, limit=600),
        "branch": str(branch),
        "decisive_task_chain_breaks": statements(
            "effect_chain", "winning_paths", limit=2
        ),
        "opponent_adaptation_and_failure_pressure": statements(
            "defense_decomposition",
            "operational_review",
            "breakthrough_directions",
            limit=2,
        ),
        "high_value_combat_effects": high_value_effects(
            "winning_paths",
            "effect_chain",
            "operational_review",
            "breakthrough_directions",
            "capability_mapping",
            "s4_concept_directions",
            "gap_assessment",
            limit=4,
        ),
        "high_value_capability_gaps": gaps,
        "equipment_portfolio_preflight": preflight_rows,
        "support_layer_constraint": (
            "上游支撑性方案名称和既有解决方案已剔除；不得把非直接作战效应事项单列为最终方向。"
        ),
        "mission_effect_escalation_questions": [
            "该能力最终使哪类现役武器、侦察、指挥或效应平台获得新的目标发现、火力分配、突防、拦截、毁伤或再打击能力？",
            "相较只维持通信与任务连续性，它新增了什么可改变打击、歼灭、反制、拒止或威慑结果的制胜机制？",
            "若无法证明直接作战增益，是否应合并为横向支撑层而不是独立能力方向？",
        ],
        "public_evidence": evidence,
        # In dynamic mode this is the authoritative, expert-reviewed weapon
        # portfolio. S6 authors one card per row rather than replanning it to a
        # preset number of generic cards.
        "selected_equipment_portfolio": selected_portfolio,
        "selected_portfolio_rule": (
            "仅传入已通过动态组合评审的直接战斗武器；装备名称和主装备身份已在前置候选阶段冻结。"
            "S6逐卡并行撰写能力画像，必须逐字继承名称，不得清理、微调、改写或替换。"
        ),
        "s6_card_capacity": int(dynamic_policy.get("finalist_maximum", 12) or 12),
        # This is an internal Codex CLI call ceiling for one research run. It
        # is intentionally independent from the Worker pool's task capacity.
        "s6_parallelism": max(
            1,
            min(
                6,
                int(
                    s6_parallelism
                    if s6_parallelism is not None
                    else os.environ.get("EQUIPMENT_DR_S6_CODEX_CONCURRENCY", "6")
                ),
            ),
        ),
    }


def _s6_card_is_reusable(direction: Mapping[str, Any]) -> bool:
    """Whether a persisted direction is a completed S6 card, not an S5 brief."""

    portrait = str(direction.get("capability_portrait", "") or "").strip()
    process = direction.get("operational_process", [])
    consistency = direction.get("semantic_consistency_check", {})
    consistent = (
        consistency.get("consistent") is True
        if isinstance(consistency, Mapping)
        else False
    )
    return bool(
        str(direction.get("name", "")).strip()
        and direction.get("s6_authoring_status") != "limited_provider_failure"
        and isinstance(direction.get("capability_classification"), Mapping)
        and str(
            direction.get("capability_classification", {}).get(
                "primary_dimension", ""
            )
        ).strip()
        and "能力分类：" in portrait
        and len(parse_capability_portrait_modules(portrait))
        == len(CAPABILITY_PORTRAIT_MODULES)
        and isinstance(process, list)
        and len([item for item in process if str(item).strip()]) >= 2
        and consistent
    )


def _s6_first_pass_quality_contract(
    *,
    topic: str,
    handoff: Mapping[str, Any],
) -> dict[str, Any]:
    """Front-load S6 acceptance criteria without adding a model call.

    S5 already emits its equipment portfolio preflight in the same response as
    the gap assessment.  This projection turns that material plus deterministic
    query anchors into a compact first-draft contract, so the normal path is a
    single accepted S6 call and the quality gate remains an exception handler.
    """

    normalized_topic = re.sub(r"\s+", "", str(topic or ""))
    query_anchors = [
        term for term in _QUERY_RELEVANCE_ANCHOR_TERMS if term in normalized_topic
    ][:8]
    portfolio_preflight = handoff.get("equipment_portfolio_preflight", [])
    preflight_rows = (
        [item for item in portfolio_preflight if isinstance(item, Mapping)]
        if isinstance(portfolio_preflight, list)
        else []
    )
    preflight_issues: list[str] = []
    relevant_preflights: list[tuple[str, dict[str, Any]]] = [
        (str(item.get("category", "query专属装备")), dict(item))
        for item in preflight_rows
        if item.get("ready") is True
    ][:5]
    if not relevant_preflights:
        preflight_issues.append(
            "前置S3-S5尚未形成任何与query直接对应的具体打击杀伤武器候选、对象证据和军事效果闭环"
        )
    for label, row in relevant_preflights:
        if row.get("ready") is not True:
            preflight_issues.append(
                f"{label}前置装备桶尚未ready，首次S6必须从query和公开证据补齐因果映射"
            )
        missing = [
            field
            for field in (
                "query_relevance",
                "baseline_system",
                "capability_gap",
                "candidate_equipment",
            )
            if not str(row.get(field, "")).strip()
        ]
        if missing:
            preflight_issues.append(f"{label}前置装备桶缺少{','.join(missing)}")
        refs = row.get("evidence_refs", [])
        if not isinstance(refs, list) or not any(str(item).strip() for item in refs):
            preflight_issues.append(f"{label}前置装备桶缺少可用证据引用")

    return {
        "goal": "first_pass_acceptance_without_gate_retry",
        "query_anchors": query_anchors or [_clean_capability_handoff_text(topic, limit=120)],
        "query_led_combat_equipment_themes": (
            _query_led_combat_equipment_theme_contract()
        ),
        "query_combat_equipment_divergence_brief": (
            _query_combat_equipment_divergence_brief(
                topic,
                structured_query_brief=(
                    handoff.get("structured_query_brief", {})
                    if isinstance(handoff, Mapping)
                    else {}
                ),
            )
        ),
        "preflight_acceptance": {
            "passed": not preflight_issues,
            "issues_to_resolve_before_submission": preflight_issues,
            "rule": "这些问题必须在首次S6调用内部解决；不得先提交不合格组合再依赖质量门修复。",
        },
        "portfolio": {
            "direction_count": "由动态蜂群传入的合格直接战斗武器数量决定，不设固定配额",
            "membership_and_identity_locked_before_s6": True,
            "same_family_independence_rule": (
                "同一装备族必须在平台或发射域、目标效果、核心机理、授权时序、"
                "专属验证指标中至少两项可独立验收差异，否则前置合并为一个主卡和任务变体"
            ),
            "resume_rule": (
                "恢复时复用已完成卡片，只修复质量残差命中的位置；"
                "不得重跑已通过卡片、重新规划组合或重复调用上游角色"
            ),
            "required_independent_directions": [
                "query_specific_direct_weapon_families",
                "query_led_OTHER_architectures_compete_without_reserved_slot",
            ],
            "missile_and_unmanned_must_be_separate_cards": (
                "only_when_both_are_query_aligned_and_selected"
            ),
            "direct_weapon_portfolio_rule": (
                "具体打击、歼灭、杀伤或反杀伤武器必须构成组合主体；"
                "不使用固定数量或固定类别配额"
            ),
            "maximum_standalone_support_directions": (
                1 if _query_explicitly_requests_support_equipment(topic) else 0
            ),
            "type_rule": (
                "升级或新研由query差距和对象证据决定，不为覆盖类型机械各生成一项"
            ),
            "named_public_equipment_anchor_rule": (
                "具名时逐卡引用对象证据，不按固定数量配额"
            ),
            "each_card_one_primary_equipment_family": True,
            "per_card_confidence_must_reflect_evidence_and_inference_span": True,
            "support_mission_exclusion": (
                "以回收、数据读取、数据下载、BDA或接口为主任务的无人平台属于支撑层，"
                "即使标题含‘无人机’或‘火力’也必须在首次自检中剔除；这些功能只能作为"
                "具体打击、毁伤、压制、拦截或猎歼武器的内部子系统。"
            ),
        },
        "query_specific_preflight_directions": preflight_rows,
        "disruptive_dimension_use": {
            "internal_query_causal_lenses": "2..3",
            "relationship_diversity_policy": (
                "由前置Codex发散提升，不作为固定数量后置阻断门"
            ),
            "do_not_publish_methodology_checklist": True,
            "seed_is_not_title_or_evidence": True,
            "final_direction_must_name_concrete_equipment": True,
            "rule": (
                "只保留与query任务对象、作战阶段和证据直接相关的镜头；"
                "不得为了覆盖维度生成无关方向。"
            ),
        },
        "per_card_submission_check": [
            "标题由S3提出、S4装备化收敛并由S5冻结；S6必须逐字继承，不得清理、压缩、扩写、同义替换、换装或由公开基线反向改名",
            "每卡只允许一个主装备族；不同平台、直接效应和任务边界不得压成同一方向",
            "先锁定primary_equipment_identity，再让项目功能、装备形态、运用主体、发射/释放域、完整operational_process、目标对象、直接战果、画像和失效边界全部围绕同一主装备；流程步数由该装备真实交战逻辑决定，不得由本地关键词模板代写流程",
            "提交前完成semantic_consistency_check：逐字段复核主语、平台/弹体/载荷边界、发射域、目标与毁伤方式；载荷不得无说明替代母平台或发射装置，公开基线不得擅自改变方案发射域，防御装备不得串入进攻察打流程；consistent必须是JSON布尔值true而不是字符串",
            "公开型号只作为baseline_system证据锚点；可见标题必须使用S3已给出命名论证的Query专属新质武器名称，不得由公开基线反向生成或覆盖",
            "direct_evidence_refs、foresight_evidence_status与evidence_boundary属于推荐追溯信息：有则按卡片用途填写，"
            "无公开证据时不得因此阻断前瞻new_capability；现役升级或声称公开型号既有能力时仍不得把未经证实的属性写成事实，"
            "应明确不确定性并安排后续验证",
            "confidence必须按对象证据直接性、来源质量和工程推导跨度逐卡给出，禁止整组机械同值；前瞻新质方向允许较低置信度，低置信度本身不是失败原因",
            "能力画像是区别于完整报告的决策短卡，并在本次单装备Codex调用内直接成稿；五个结构化模块各回答一个问题：概述给关键断点、核心改变和直接结果，技术实现给决定性机理及装备内实现，流程只给改变任务状态的专属动作，能力效果给直接战果与判别信号，制胜逻辑给被颠覆的常规关系及新优势。没有最低字数、固定句数或关键词清单，不得先写长文再压缩；由Codex语义编辑避免跨栏复述",
            "能力画像开头显示能力分类；主维度按本卡最主要可验收战果自然确定，可为毁伤、突防或Query驱动的其他维度，辅维度只在改变设计判断时保留，不按示例凑类",
            "关键作战流程突出决定成败的节点及其进入条件、行动主体、状态变化和转入下一节点的条件；技术实现说明可复用底座、决定性瓶颈、装备内实现、集成约束与可判退验证，不以通用流程或成熟度标签代替推理",
            "面向一线设计人员使用通俗、准确中文；必要术语首次写全称，避免生僻造词、无解释缩写、字段拼接和跨栏重复",
            "baseline_system为该卡独有的现役或类比装备基线",
            "capability_gap为该卡独有且与query相关的能力差距",
            "query_relevance明确任务对象、阶段、压力和直接效果",
            "indicator_portrait与query_relevance由S5交接门闭合并锁定；S6逐字继承，不重新生成、不补洞",
            "卡片间标题、基线、差距和作战机理不套用同一模板",
            "每卡必须声明且兑现一个不可由其他卡替代的差异变量，至少明确发射域/平台、目标运动包线、末制导传感器、授权来源、补击时序和专属验证指标中的两项；禁止用同一目标、同一再捕获机理和同一战果重复占位，无法独立验收时合并或替换该卡",
            "逐卡自检后执行组合级语义复核，比较全部卡片的主装备、发射域、目标、作用机理和验证指标；实质重复项必须在首次提交前合并或替换，不得依赖后置去重或卡片修复",
        ],
        "s6_latency_budget": {
            "normal_model_passes": 1,
            "maximum_targeted_repair_passes": 1,
            "repair_scope": "failed_portrait_modules_only_identity_locked",
            "card_scope": (
                "每卡只写一个具体战场问题、一条装备专属交战链、直接战果、"
                "2至5个专属验证轴和必要失效边界；不复述完整上游研究过程"
            ),
        },
    }


def _capability_text_similarity(left: str, right: str) -> float:
    """Detect only exact normalized reuse; semantic similarity belongs to Codex."""

    left_normalized = re.sub(r"\s+", "", str(left or ""))
    right_normalized = re.sub(r"\s+", "", str(right or ""))
    if not left_normalized or not right_normalized:
        return 0.0
    return 1.0 if left_normalized == right_normalized else 0.0


def _capability_primary_equipment_family(direction: Mapping[str, Any]) -> str:
    """Return only an explicit model-governed semantic identity."""

    return str(
        direction.get("equipment_semantic_identity")
        or direction.get("hypothesis_id")
        or ""
    ).strip()


def _s6_primary_equipment_object_kind(value: Any) -> str:
    """Deprecated compatibility hook; object kind is supplied by the model."""

    del value
    return ""


def _s6_primary_equipment_identity_mismatch(direction: Mapping[str, Any]) -> bool:
    """Semantic mismatch is decided by ``semantic_consistency_check``."""

    del direction
    return False


def _build_direction_capability_portrait(
    direction: Mapping[str, Any],
    *,
    topic: str = "",
    source: str = "",
) -> str:
    """Recompose one governed portrait from the card's structured facts."""

    return build_agent_led_capability_portrait(
        name=direction.get("name"),
        scenario=direction.get("target_scenario") or topic or "典型作战场景",
        problem=direction.get("capability_gap")
        or direction.get("problem_statement")
        or source,
        principle=direction.get("scientific_principle")
        or direction.get("novelty")
        or direction.get("operational_mechanism"),
        technologies=direction.get("enabling_technologies")
        or direction.get("upgrade_package")
        or direction.get("equipment_form"),
        operational_concept=direction.get("operational_concept")
        or direction.get("operational_mechanism"),
        operational_steps=direction.get("operational_process")
        or direction.get("strike_chain_contribution"),
        capability=direction.get("capability_outcome")
        or direction.get("function")
        or direction.get("equipment_form"),
        effect=direction.get("military_value")
        or direction.get("combat_effect_uplift")
        or direction.get("strike_countermeasure_value"),
        winning_mechanism=direction.get("winning_mechanism")
        or direction.get("novelty")
        or direction.get("operational_mechanism"),
        equipment_form=direction.get("equipment_form")
        or direction.get("equipment_category"),
        baseline=direction.get("baseline_system") or direction.get("equipment_form"),
        development_path=direction.get("development_path"),
        failure_boundary=[
            direction.get("adversary_adaptation", ""),
            direction.get("failure_boundary", ""),
            direction.get("upgrade_boundary", ""),
        ],
        verification_plan=direction.get("verification")
        or direction.get("feasibility_basis"),
    )


def _normalize_s6_deterministic_format(
    result: Mapping[str, Any],
    *,
    topic: str = "",
) -> dict[str, Any]:
    """Normalize transport-level S6 presentation without authoring semantics.

    This may clean transport whitespace, scalar types and concrete titles, but
    it never composes or rewrites ``capability_portrait``.  The portrait is an
    S6 Codex deliverable; missing or invalid prose must be repaired by the
    owning model session or rejected by the quality gate.
    """

    normalized = dict(result)
    raw_directions = result.get("concept_directions", [])
    if not isinstance(raw_directions, list):
        return normalized

    try:
        portfolio_confidence = float(result.get("confidence", 0.68) or 0.68)
    except (TypeError, ValueError):
        portfolio_confidence = 0.68
    portfolio_confidence = max(0.55, min(0.88, portfolio_confidence))

    public_string_fields = (
        "name",
        "function",
        "military_value",
        "depth_mechanism",
        "foresight",
        "novelty",
        "strike_countermeasure_value",
        "equipment_form",
        "primary_equipment_identity",
        "operational_mechanism",
        "development_path",
        "future_trigger",
        "adversary_adaptation",
        "failure_boundary",
        "query_relevance",
        "baseline_system",
        "capability_gap",
        "combat_effect_uplift",
        "strike_chain_contribution",
        "upgrade_boundary",
        "capability_portrait",
    )
    directions: list[Any] = []
    for raw_direction in raw_directions:
        if not isinstance(raw_direction, Mapping):
            directions.append(raw_direction)
            continue
        direction = dict(raw_direction)
        portrait_modules = direction.get("capability_portrait_modules", {})
        if isinstance(portrait_modules, Mapping):
            portrait_modules = dict(portrait_modules)
            classification = direction.get("capability_classification", {})
            if classification:
                portrait_modules["capability_classification"] = classification
        assembled_portrait = assemble_capability_portrait_modules(portrait_modules)
        if assembled_portrait:
            direction["capability_portrait"] = assembled_portrait
        evidence_boundary = str(
            direction.get("evidence_boundary", "") or ""
        ).strip()
        if evidence_boundary:
            if _evidence_boundary_is_public_semantic(evidence_boundary):
                direction["evidence_boundary"] = _clean_capability_handoff_text(
                    evidence_boundary,
                    limit=800,
                )
            else:
                # Optional traceability prose must never turn an otherwise
                # deliverable weapon card into a failed task. Internal notes
                # stay in audit events and are omitted from the public card.
                direction.pop("evidence_boundary", None)
        semantic_check = direction.get("semantic_consistency_check")
        if isinstance(semantic_check, Mapping):
            normalized_semantic_check = dict(semantic_check)
            raw_consistent = normalized_semantic_check.get("consistent")
            if isinstance(raw_consistent, str):
                normalized_boolean = raw_consistent.strip().lower()
                if normalized_boolean == "true":
                    normalized_semantic_check["consistent"] = True
                elif normalized_boolean == "false":
                    normalized_semantic_check["consistent"] = False
            direction["semantic_consistency_check"] = normalized_semantic_check
        for field_name in public_string_fields:
            if field_name in direction:
                if field_name == "capability_portrait":
                    # The portrait's line breaks delimit the governed overview
                    # and five controlled modules. Flattening them here makes
                    # the whole card look like one overlong overview and forces
                    # a generic deterministic rebuild, discarding otherwise
                    # valid equipment-specific combat prose.
                    direction[field_name] = "\n".join(
                        cleaned
                        for line in str(direction.get(field_name, "")).splitlines()
                        if (
                            cleaned := _clean_capability_handoff_text(
                                line,
                                limit=None,
                            )
                        )
                    )
                else:
                    direction[field_name] = _clean_capability_handoff_text(
                        direction.get(field_name),
                        limit=360,
                    )
        if not str(direction.get("capability_gap", "") or "").strip():
            inherited_gap = next(
                (
                    _clean_capability_handoff_text(value, limit=360)
                    for value in (
                        direction.get("problem_statement"),
                        direction.get("non_substitutable_difference"),
                        direction.get("changed_confrontation_variable"),
                        direction.get("unique_operational_role"),
                        direction.get("query_relevance"),
                    )
                    if str(value or "").strip()
                ),
                "",
            )
            if inherited_gap:
                direction["capability_gap"] = inherited_gap
        semantic_check = direction.get("semantic_consistency_check", {})
        model_asserts_consistency = (
            isinstance(semantic_check, Mapping)
            and semantic_check.get("consistent") is True
        )
        equipment_form_text = str(direction.get("equipment_form", "")).strip()
        if equipment_form_text and not model_asserts_consistency:
            role_text = " ".join(
                str(direction.get(field, ""))
                for field in (
                    "name",
                    "function",
                    "military_value",
                    "operational_mechanism",
                    "query_relevance",
                )
            )
            if (
                "反舰或对陆" in equipment_form_text
                and (
                    "反舰" in str(direction.get("name", ""))
                    or any(
                        marker in role_text
                        for marker in ("海上编队", "水面舰艇", "舰队", "补给船", "海上目标")
                    )
                )
            ):
                # The card already selected an anti-ship mission and target set.
                # Keep one independently fundable payload instead of publishing
                # a post-hoc ``anti-ship or land-attack`` alternative family.
                equipment_form_text = equipment_form_text.replace("反舰或对陆", "反舰")
            equipment_form_text = re.sub(
                r"^(?:一枚|一种|一个)\s*",
                "",
                equipment_form_text,
            ).strip()
            if "：" in equipment_form_text:
                primary, suffix = equipment_form_text.split("：", 1)
                if any(
                    marker in suffix
                    for marker in ("兼容发射", "发射边界", "挂载边界", "接口边界")
                ):
                    equipment_form_text = primary.strip()
            equipment_form_text = _equipment_form_identity_text(
                equipment_form_text
            )
            direction["equipment_form"] = equipment_form_text
        # Equipment naming is owned by the query-aware S3/S5 Codex Agents.
        # Normalization preserves their semantic decision and performs only
        # whitespace/repetition cleanup; it never promotes equipment_form,
        # extracts a public baseline, or composes a title from effect words.
        direction["name"] = _dedupe_capability_title(direction.get("name", ""))
        if isinstance(direction.get("upgrade_package"), list):
            direction["upgrade_package"] = [
                cleaned
                for item in direction["upgrade_package"]
                if (
                    cleaned := _clean_capability_handoff_text(item, limit=180)
                )
            ][:6]

        # Confidence is a card-level evidence calibration, not prose that
        # warrants another model call.  Some gateways omit the nested numeric
        # field even when the portfolio-level confidence and all evidence refs
        # are present.  Derive only missing/invalid values from observable card
        # facts: direct evidence count, object-level equipment evidence,
        # implementation span, and explicit validation bounds.
        # Existing valid model-authored confidences remain authoritative.
        try:
            direction_confidence = float(direction.get("confidence"))
        except (TypeError, ValueError):
            direction_confidence = -1.0
        if not 0.0 <= direction_confidence <= 1.0:
            direct_refs = list(
                dict.fromkeys(
                    str(ref).strip()
                    for ref in direction.get("direct_evidence_refs", [])
                    if str(ref).strip()
                )
            )
            evidence_gain = 0.02 * min(4, len(direct_refs))
            object_gain = (
                0.03
                if any(ref.startswith("ev-weapon_equipment-") for ref in direct_refs)
                else 0.0
            )
            implementation_adjustment = (
                0.01 if str(direction.get("type", "")) == "upgrade" else -0.02
            )
            validation_gain = (
                0.01
                if str(direction.get("verification", "")).strip()
                and str(direction.get("failure_boundary", "")).strip()
                else 0.0
            )
            direction["confidence"] = round(
                max(
                    0.55,
                    min(
                        0.86,
                        portfolio_confidence
                        - 0.08
                        + evidence_gain
                        + object_gain
                        + implementation_adjustment
                        + validation_gain,
                    ),
                ),
                3,
            )

        # Preserve the user's topic anchors in the dedicated causal-mapping
        # field without asking the model to rewrite an otherwise complete
        # weapon card.  This is a deterministic projection of the query, not a
        # new capability claim.  Stage, pressure and combat-effect semantics
        # must still be present in the model-authored relevance statement and
        # remain subject to the normal quality gate.
        relevance = str(direction.get("query_relevance", "")).strip()
        normalized_topic = re.sub(r"\s+", "", str(topic or ""))
        topic_anchors = [
            term
            for term in _QUERY_RELEVANCE_ANCHOR_TERMS
            if term in normalized_topic
        ][:4]
        if relevance and _is_missile_precision_munition_direction(direction):
            prefixes: list[str] = []
            if topic_anchors and not any(term in relevance for term in topic_anchors):
                prefixes.append("、".join(topic_anchors))
            topic_pressure_anchors = [
                term
                for term in (
                    "强电磁压制",
                    "电磁压制",
                    "GNSS拒止",
                    "导航拒止",
                    "强干扰",
                    "诱饵",
                    "饱和攻击",
                    "节点损耗",
                )
                if term in normalized_topic
            ][:3]
            if topic_pressure_anchors and not any(
                term in relevance for term in _QUERY_RELEVANCE_PRESSURE_TERMS
            ):
                prefixes.append("、".join(topic_pressure_anchors))
            if prefixes:
                direction["query_relevance"] = _truncate_complete_text(
                    f"面向{'、'.join(prefixes)}条件，{relevance}",
                    limit=360,
                )

        portrait = str(direction.get("capability_portrait", "")).strip()
        if portrait and portrait[-1] not in "。！？；”’」』）)":
            direction["capability_portrait"] = f"{portrait}。"
        directions.append(direction)

    names_before_uniquify = [
        str(direction.get("name", "")).strip()
        if isinstance(direction, Mapping)
        else ""
        for direction in directions
    ]
    unique_directions = _uniquify_compacted_capability_titles(directions)
    for position, unique_direction in enumerate(unique_directions, start=1):
        if not isinstance(unique_direction, Mapping):
            continue
        # Title collision repair runs after the first portrait pass. When the
        # recovered title carries a real sub-family contract (for example
        # single-munition finite-area search versus salvo coordination), rebuild
        # once with that final identity so the portrait is as distinct as the
        # name and remains independently testable.
        title_changed = (
            str(unique_direction.get("name", "")).strip()
            != names_before_uniquify[position - 1]
        )
        # A deterministic title cleanup must not trigger a second semantic
        # authoring path.  The Codex-authored card remains authoritative; any
        # substantive identity conflict is handled by its structured semantic
        # consistency contract before delivery.
        del title_changed
    normalized["concept_directions"] = unique_directions
    return normalized


def _equipment_form_identity_text(value: Any) -> str:
    """Keep the proposed weapon identity, not its trailing evidence caveat."""

    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return ""
    fragments = [item.strip() for item in re.split(r"[；;]", text) if item.strip()]
    kept: list[str] = []
    evidence_markers = (
        "公开证据",
        "证据仅",
        "证据不足",
        "证据边界",
        "不证明",
        "不能证明",
        "保留类别级",
    )
    for fragment in fragments:
        if kept and any(marker in fragment for marker in evidence_markers):
            break
        kept.append(fragment)
    return "；".join(kept).strip(" ，,；;")


def _direction_is_defensive_only(direction: Mapping[str, Any]) -> bool:
    return bool(direction.get("defensive_only")) or str(
        direction.get("combat_posture", "")
    ).strip() == "defensive_only"


def _s6_frontier_evidence_allowance(direction: Mapping[str, Any]) -> bool:
    """Identify new-capability cards using bounded analogous/component evidence."""

    status = str(direction.get("foresight_evidence_status", "")).strip()
    refs = direction.get("direct_evidence_refs", [])
    has_traceable_evidence = isinstance(refs, list) and any(
        str(item).strip() for item in refs
    )
    return bool(
        str(direction.get("type", "")).strip() == "new_capability"
        and status
        in {"analogous_project_evidence", "component_mechanism_evidence"}
        and has_traceable_evidence
        and str(direction.get("evidence_boundary", "")).strip()
    )


def _indicator_portrait_is_specific(value: object) -> bool:
    """Whether an indicator portrait closes axis, baseline and falsification."""

    text = str(value or "").strip()
    return bool(
        len(text) >= 30
        and not any(
            marker in text
            for marker in (
                "尚未由研究",
                "须回到前置质量门",
                "待形成",
                "待补充",
                "待校准",
                "尚未形成",
            )
        )
        and any(
            marker in text
            for marker in (
                "覆盖",
                "射程",
                "响应",
                "毁伤",
                "压制",
                "拦截",
                "生存",
                "成本",
                "规模",
                "授权",
            )
        )
        and any(
            marker in text
            for marker in ("对照", "基线", "门槛", "判退", "停止", "淘汰")
        )
    )


def _query_relevance_is_specific(value: object) -> bool:
    """Whether Query relevance names task, stage, pressure and battle effect."""

    text = str(value or "").strip()
    return bool(
        len(text) >= 30
        and any(marker in text for marker in ("任务", "作战", "战斗"))
        and any(marker in text for marker in ("阶段", "场景", "窗口", "地域", "海域", "空域", "发射域", "释放域"))
        and any(marker in text for marker in ("威胁", "压力", "对手", "敌", "断点", "差距", "变量", "受限"))
        and any(
            marker in text
            for marker in (
                "打击",
                "毁伤",
                "压制",
                "拦截",
                "歼灭",
                "拒止",
                "瘫痪",
                "破障",
                "直接军事效果",
                "战场结果",
            )
        )
    )


def _prepare_pre_s6_card_contract(
    value: Mapping[str, Any],
    *,
    query: str = "",
) -> dict[str, Any]:
    """Close S5-owned card fields before parallel S6 authoring begins.

    S6 owns prose synthesis only.  Indicator axes, comparison baseline,
    falsification condition and query-task relevance are deterministic
    projections of the selected S3-S5 candidate ledger and are locked before
    card writers run.  This prevents every parallel writer from independently
    rediscovering the same missing contract and entering an expensive repair
    loop.
    """

    card = dict(value)

    raw_evidence_boundary = str(card.get("evidence_boundary", "") or "").strip()
    cleaned_evidence_boundary = _clean_capability_handoff_text(
        raw_evidence_boundary,
        limit=None,
    )
    if raw_evidence_boundary and _evidence_boundary_is_public_semantic(
        raw_evidence_boundary
    ) and _evidence_boundary_is_public_semantic(cleaned_evidence_boundary):
        card["evidence_boundary"] = cleaned_evidence_boundary
        evidence_boundary_status = "accepted_public_epistemic_boundary"
    else:
        card.pop("evidence_boundary", None)
        evidence_boundary_status = (
            "omitted_internal_or_non_epistemic_boundary"
            if raw_evidence_boundary
            else "omitted_not_supplied"
        )

    def first_text(*fields: str, fallback: str = "") -> str:
        for field in fields:
            raw = card.get(field)
            if isinstance(raw, list):
                text = "；".join(
                    str(item).strip() for item in raw if str(item).strip()
                )
            else:
                text = str(raw or "").strip()
            if text:
                return _clean_capability_handoff_text(text, limit=None)
        return _clean_capability_handoff_text(fallback, limit=None)

    name = first_text(
        "name",
        "primary_equipment_identity",
        "equipment_form",
        fallback="本装备",
    )
    baseline = first_text(
        "baseline_system",
        fallback="当前同类装备与既有任务链",
    )
    changed_variable = first_text(
        "non_substitutable_difference",
        "capability_gap",
        "problem_statement",
        "changed_confrontation_variable",
        fallback="当前任务链的关键对抗变量",
    )
    # ``capability_gap`` is owned by the frozen S3-S5 candidate ledger.  Some
    # S6 card writers omit the duplicate scalar even though the same meaning is
    # already present in problem_statement/non_substitutable_difference.  Carry
    # that upstream semantic value forward instead of treating a missing JSON
    # key as evidence that the military analysis failed.
    if not str(card.get("capability_gap", "") or "").strip():
        card["capability_gap"] = changed_variable
    if not str(card.get("baseline_system", "") or "").strip():
        card["baseline_system"] = baseline
    direct_effect = first_text(
        "target_and_direct_effect",
        "military_value",
        "capability_outcome",
        "combat_effect_uplift",
        "unique_operational_role",
        fallback="形成可验证的直接军事效果",
    )
    validation_focus = first_text(
        "validation_plan",
        "verification_plan",
        fallback=direct_effect,
    )
    failure_boundary = first_text(
        "failure_boundary",
        "failure_boundaries",
        "upgrade_boundary",
        fallback=f"{direct_effect}无法稳定形成",
    )

    indicator = str(card.get("indicator_portrait", "") or "").strip()
    if not _indicator_portrait_is_specific(indicator):
        card["indicator_portrait"] = (
            f"测量轴：围绕“{changed_variable}”变化，重点评估{direct_effect}的任务响应、"
            f"作用保持和关键授权边界，并以“{validation_focus}”作为观测重点。"
            f"对照基线：以“{baseline}”在相同场景、约束和对抗压力下的任务表现为对照。"
            f"判退条件：若上述测量轴未达到任务门槛，或触及“{failure_boundary}”，"
            "则停止转段并判退；不虚构尚无公开依据的精确数值。"
        )

    query_relevance = str(card.get("query_relevance", "") or "").strip()
    if not _query_relevance_is_specific(query_relevance):
        launch_domain = first_text(
            "launch_or_release_domain",
            "target_scenario",
            fallback="Query指定的作战阶段与运用域",
        )
        task_role = first_text(
            "unique_operational_role",
            "project_function",
            "function",
            fallback="当前核心作战任务",
        )
        query_anchor = str(query or "").strip()
        query_anchor = re.split(r"[。；;\n]", query_anchor, maxsplit=1)[0].strip()
        query_prefix = f"围绕“{query_anchor}”，" if query_anchor else "围绕当前Query，"
        card["query_relevance"] = (
            f"{query_prefix}{name}在{launch_domain}承担{task_role}，"
            f"针对{changed_variable}形成{direct_effect}，直接回应任务对象、作战阶段、"
            "威胁压力和预期战场结果。"
        )

    identity_contract = card.get("portfolio_identity_contract", {})
    identity_contract = (
        dict(identity_contract) if isinstance(identity_contract, Mapping) else {}
    )
    identity_contract["pre_s6_quality_contract"] = {
        "indicator_portrait": card["indicator_portrait"],
        "query_relevance": card["query_relevance"],
        "evidence_boundary_status": evidence_boundary_status,
        "owner": "S5_handoff",
        "s6_mutation_allowed": False,
    }
    card["portfolio_identity_contract"] = identity_contract
    return card


def _capability_direction_quality_issues(
    result: Mapping[str, Any],
    *,
    handoff: Mapping[str, Any] | None = None,
) -> list[str]:
    """Collect non-blocking authoring diagnostics for real S6 output.

    These checks intentionally retain their detailed messages for audit and
    prompt evaluation, but none of them is allowed to decide delivery,
    trigger a repair call, delete a card or fail a run.  Military semantic
    admission belongs to the Codex-led S3-S5 candidate process; S6 is a
    presentation pass over that frozen portfolio.
    """

    issues: list[str] = []
    directions = result.get("concept_directions", [])
    if not isinstance(directions, list):
        return ["S6必须形成至少一项具体、互异且高军事价值的最终武器装备方向"]
    if not directions:
        issues.append("S6必须形成至少一项具体、互异且高军事价值的最终武器装备方向")

    semantic_contract_required = bool(
        handoff and "equipment_portfolio_preflight" in handoff
    )
    if semantic_contract_required:
        # Dynamic S6 consumes identities already selected by independent
        # Codex clustering, expert review and the S5 handoff contract.  At
        # this point local code validates only the contract shape; vocabulary
        # scans, known-model catalogues and text-similarity thresholds must not
        # re-open the semantic decision.
        hypothesis_ids: list[str] = []
        for position, direction in enumerate(directions, start=1):
            if not isinstance(direction, Mapping):
                issues.append(f"S6第{position}项不是结构化能力方向")
                continue
            required = (
                "hypothesis_id",
                "name",
                "primary_equipment_identity",
                "equipment_form",
                "target_and_direct_effect",
                "query_relevance",
                "indicator_portrait",
            )
            missing = [
                field
                for field in required
                if not str(direction.get(field, "")).strip()
            ]
            if missing:
                issues.append(f"S6第{position}项缺少{','.join(missing)}")
            classification = direction.get("capability_classification", {})
            if not isinstance(classification, Mapping) or not str(
                classification.get("primary_dimension", "")
            ).strip():
                issues.append(f"S6第{position}项缺少Query驱动的主要能力分类维度")
            portrait = str(direction.get("capability_portrait", ""))
            if "能力分类：" not in portrait:
                issues.append(f"S6第{position}项能力画像未显示能力分类维度")
            hypothesis_id = str(direction.get("hypothesis_id", "")).strip()
            if hypothesis_id:
                hypothesis_ids.append(hypothesis_id)
            process = direction.get("operational_process", [])
            if not isinstance(process, list) or not any(
                str(item).strip() for item in process
            ):
                issues.append(f"S6第{position}项operational_process缺失")
            semantic_check = direction.get("semantic_consistency_check", {})
            if not isinstance(semantic_check, Mapping) or (
                semantic_check.get("consistent") is not True
            ):
                issues.append(f"S6第{position}项语义一致性合同未通过")
            try:
                confidence = float(direction.get("confidence"))
            except (TypeError, ValueError):
                confidence = -1.0
            if not 0.0 <= confidence <= 1.0:
                issues.append(f"S6第{position}项缺少0至1之间的独立confidence")
            issues.extend(
                _capability_language_issues(
                    position,
                    direction,
                    semantic_contract_required=True,
                )
            )
        if len(hypothesis_ids) != len(set(hypothesis_ids)):
            issues.append("S6存在重复hypothesis_id")
        return list(dict.fromkeys(issues))[:64]

    public_fields = (
        "name",
        "function",
        "equipment_form",
        "operational_mechanism",
        "target_scenario",
        "operational_process",
        "military_value",
        "combat_effect_uplift",
        "strike_chain_contribution",
        "development_path",
        "query_relevance",
        "baseline_system",
        "capability_gap",
        "capability_portrait",
        "indicator_portrait",
        "evidence_boundary",
    )
    portraits: list[tuple[int, str]] = []
    directions_by_position: dict[int, Mapping[str, Any]] = {}
    direction_names: list[tuple[int, str]] = []
    type_rows: list[str] = []
    high_order_positions: list[int] = []
    ordinary_support_positions: list[int] = []
    ancillary_support_positions: list[int] = []
    unmanned_equipment_positions: list[int] = []
    lethal_weapon_positions: list[int] = []
    missile_precision_positions: list[int] = []
    confidence_rows: list[tuple[int, float]] = []
    evidence_ref_sets: list[tuple[int, tuple[str, ...]]] = []
    operational_processes: list[tuple[int, str]] = []
    query = str((handoff or {}).get("query", "")).strip()
    handoff_texts: list[str] = []
    if handoff:
        for key in (
            "decisive_task_chain_breaks",
            "opponent_adaptation_and_failure_pressure",
        ):
            for item in handoff.get(key, []):
                text = str(item)
                if len(text) >= 80:
                    handoff_texts.append(text)
        for item in handoff.get("high_value_capability_gaps", []):
            if isinstance(item, Mapping):
                text = " ".join(str(value) for value in item.values())
                if len(text) >= 80:
                    handoff_texts.append(text)

    for position, direction in enumerate(directions, start=1):
        if not isinstance(direction, Mapping):
            issues.append(f"S6第{position}项不是结构化能力方向")
            continue
        issues.extend(_capability_portrait_alignment_issues(position, direction))
        semantic_check = direction.get("semantic_consistency_check", {})
        codex_identity_locked = bool(
            semantic_contract_required
            and isinstance(semantic_check, Mapping)
            and semantic_check.get("consistent") is True
            and str(direction.get("primary_equipment_identity", "")).strip()
        )
        direction_type = str(direction.get("type", ""))
        frontier_evidence_allowance = _s6_frontier_evidence_allowance(direction)
        type_rows.append(direction_type)
        name = str(direction.get("name", "")).strip()
        direction_names.append((position, name))
        direct_refs = tuple(
            dict.fromkeys(
                str(ref).strip()
                for ref in direction.get("direct_evidence_refs", [])
                if str(ref).strip()
            )
        )
        evidence_ref_sets.append((position, direct_refs))
        # Evidence references and evidence_boundary are recommended context.
        # They must not block a foresight direction whose public evidence is
        # sparse; only explicit false claims or contradictory evidence remain
        # substantive gate failures.
        try:
            direction_confidence = float(direction.get("confidence"))
        except (TypeError, ValueError):
            direction_confidence = -1.0
        if 0.0 <= direction_confidence <= 1.0:
            confidence_rows.append((position, direction_confidence))
        else:
            issues.append(f"S6第{position}项缺少0至1之间的独立confidence")
        portrait = str(direction.get("capability_portrait", "")).strip()
        portraits.append((position, portrait))
        directions_by_position[position] = direction
        required_fields = (
            "equipment_form",
            "operational_mechanism",
            "military_value",
            "adversary_adaptation",
            "failure_boundary",
            "query_relevance",
            "baseline_system",
            "capability_gap",
        )
        if frontier_evidence_allowance:
            required_fields = tuple(
                field
                for field in required_fields
                if field not in {"adversary_adaptation", "failure_boundary"}
            )
        if semantic_contract_required:
            required_fields = (
                "primary_equipment_identity",
                "operational_process",
                "semantic_consistency_check",
                "indicator_portrait",
                "capability_classification",
                *required_fields,
            )
        missing = [
            field
            for field in required_fields
            if direction.get(field) in (None, "", [])
            or not str(direction.get(field, "")).strip()
        ]
        if missing:
            issues.append(f"S6第{position}项缺少{','.join(missing)}")
        if semantic_contract_required:
            operational_process = direction.get("operational_process", [])
            process_rows = (
                [
                    str(item).strip()
                    for item in operational_process
                    if str(item).strip()
                ]
                if isinstance(operational_process, list)
                else []
            )
            if not process_rows:
                issues.append(
                    f"S6第{position}项operational_process必须由Codex按整卡语义形成完整时序，"
                    "不得留空或由本地模板补写"
                )
            if process_rows:
                operational_processes.append((position, "；".join(process_rows)))
            if (
                not isinstance(semantic_check, Mapping)
                or semantic_check.get("consistent") is not True
            ):
                issues.append(
                    f"S6第{position}项未通过Codex整卡语义一致性自检，需在同次成稿内统一主装备、"
                    "流程主体、发射/释放域、目标与直接战果"
                )
            elif not all(
                str(semantic_check.get(field, "")).strip()
                for field in (
                    "process_actor",
                    "launch_or_release_mode",
                    "target_and_direct_effect",
                    "resolution_note",
                )
            ):
                issues.append(
                    f"S6第{position}项Codex整卡语义一致性自检缺少主体、发射域、目标战果或复核说明"
                )
            indicator_portrait = str(
                direction.get("indicator_portrait", "")
            ).strip()
            if indicator_portrait and not _indicator_portrait_is_specific(
                indicator_portrait
            ):
                issues.append(
                    f"S6第{position}项indicator_portrait未形成由本装备机理推导的差异化测量轴、"
                    "对照基线与判退条件"
                )
        issues.extend(
            _capability_language_issues(
                position,
                direction,
                semantic_contract_required=semantic_contract_required,
            )
        )

        query_relevance = str(direction.get("query_relevance", "")).strip()
        query_relevance_invalid = bool(
            query_relevance
            and (
                not _query_relevance_is_specific(query_relevance)
                if semantic_contract_required
                else (
                    len(query_relevance) < 30
                    or query_relevance
                    in {"符合query", "满足query需求", "与query相关"}
                )
            )
        )
        if query_relevance_invalid:
            issues.append(
                f"S6第{position}项query_relevance过于空泛，需写明任务对象、作战阶段、"
                "威胁压力和直接作战效果"
            )

        public_values = {
            field: str(direction.get(field, "")) for field in public_fields
        }
        public_text = " ".join(public_values.values())
        internal_leak_fields = [
            field
            for field, value in public_values.items()
            if _CAPABILITY_HANDOFF_INTERNAL_PATTERN.search(value)
        ]
        blocking_internal_leak_fields = [
            field for field in internal_leak_fields if field != "evidence_boundary"
        ]
        if blocking_internal_leak_fields:
            issues.append(
                f"S6第{position}项{','.join(blocking_internal_leak_fields[:4])}"
                "混入执行流程或内部角色语言"
            )
        if "evidence_boundary" in internal_leak_fields:
            issues.append(
                f"S6第{position}项evidence_boundary为内部审计备注，交付时忽略该可选字段"
            )
        if not _has_combat_effect_signal(direction) or not any(
            term in public_text for term in _CAPABILITY_STAGE_TERMS
        ):
            issues.append(
                f"S6第{position}项未说明具体作战阶段、任务对象及打击/反制效果"
            )
        if _has_high_order_combat_value(direction):
            high_order_positions.append(position)
        else:
            issues.append(
                f"S6第{position}项只停留在通信、保障、恢复或持续性层，未形成目标发现、"
                "火力分配、突防、拦截、毁伤、再打击、拒止或威慑等高阶作战效果"
            )
        if _is_ordinary_support_direction(direction):
            ordinary_support_positions.append(position)
        if _is_ancillary_support_equipment_direction(direction):
            ancillary_support_positions.append(position)
        if _is_unmanned_combat_equipment_direction(direction):
            unmanned_equipment_positions.append(position)
        if _is_lethal_weapon_equipment_direction(direction):
            lethal_weapon_positions.append(position)
        if _is_missile_precision_munition_direction(direction):
            missile_precision_positions.append(position)
            issues.extend(
                _query_relevance_issues(
                    position,
                    direction,
                    query=query,
                )
            )
        equipment_form = str(direction.get("equipment_form", ""))
        if not codex_identity_locked and not _direction_name_has_equipment_object(
            direction
        ):
            issues.append(
                f"S6第{position}项名称未直接点明具体装备对象，不能只在equipment_form中补充"
            )
        if not codex_identity_locked and not _direction_name_has_equipment_object(
            direction
        ):
            issues.append(f"S6第{position}项未绑定具体装备、平台或任务系统对象")
        if _s6_primary_equipment_identity_mismatch(direction):
            issues.append(
                f"S6第{position}项名称与equipment_form不是同一主装备对象，"
                "必须统一为该卡Query专属的单一平台、弹体或载荷身份"
            )
        generic_markers = ("自治", "网关", "算法", "中间件", "审计", "同步")
        if not codex_identity_locked and any(
            marker in name for marker in generic_markers
        ) and not any(
            term in name for term in _CAPABILITY_EQUIPMENT_OBJECT_TERMS
        ):
            issues.append(
                f"S6第{position}项名称是抽象技术标签，应退回前置Codex按完整整装语义自然命名，"
                "不能用字段短语拼接补救"
            )

        if direction_type == "upgrade":
            upgrade_required = (
                "baseline_system",
                "combat_effect_uplift",
                "strike_chain_contribution",
                "upgrade_boundary",
            )
            upgrade_missing = [
                field
                for field in upgrade_required
                if not str(direction.get(field, "")).strip()
            ]
            package = direction.get("upgrade_package", [])
            if not isinstance(package, list) or len(
                [item for item in package if str(item).strip()]
            ) < 2:
                upgrade_missing.append("upgrade_package>=2")
            if upgrade_missing:
                issues.append(
                    f"S6第{position}项现役升级论证缺少{','.join(upgrade_missing)}"
                )
            if not any(term in name for term in _HIGH_ORDER_COMBAT_EFFECT_TERMS):
                issues.append(
                    f"S6第{position}项现役升级名称未体现升级对象获得的直接打击、猎歼、"
                    "拦截、反制、拒止或威慑增益"
                )
            forbidden_name_terms = [
                term for term in _FORBIDDEN_UPGRADE_NAME_TERMS if term in name
            ]
            if forbidden_name_terms:
                issues.append(
                    f"S6第{position}项现役升级标题禁止使用"
                    + "、".join(forbidden_name_terms[:4])
                    + "等支撑性或产品化名称；应退回前置Codex按完整整装语义自然命名，"
                    "升级属性仅保留在结构化字段，复杂作用写入名称下方说明"
                )
            if (
                not codex_identity_locked
                and not _direction_name_has_equipment_object(direction)
            ):
                issues.append(
                    f"S6第{position}项现役升级标题未明确现役武器、传感器、火控、"
                    "电子战或指挥任务系统对象"
                )

        if any(
            _capability_text_similarity(portrait, upstream) >= 0.82
            for upstream in handoff_texts
        ):
            issues.append(f"S6第{position}项近似复制上游文字，必须独立综合重写")

    if directions and len(high_order_positions) <= len(directions) // 2:
        issues.append(
            "S6直接作战效应装备未构成组合主体，通信、保障、恢复、伪装或工程内容占比过高"
        )
    duplicate_names = [
        name
        for name, count in Counter(name for _, name in direction_names if name).items()
        if count > 1
    ]
    if duplicate_names:
        issues.append(
            "S6最终方向名称必须互异，禁止多个不同装备被压缩为同一标题："
            + "、".join(duplicate_names[:3])
        )
    # Evidence for a foresight/new-build direction is optional context. The
    # gate no longer blocks missing references or boundaries; it only retains
    # checks for explicit false claims and genuine cross-card contradictions.
    nonempty_ref_sets = [refs for _, refs in evidence_ref_sets if refs]
    if len(nonempty_ref_sets) >= 4 and len(set(nonempty_ref_sets)) == 1:
        issues.append(
            "S6各能力画像不得机械共用完全相同的direct_evidence_refs，必须按主装备族逐项映射"
        )
    if len(confidence_rows) >= 5:
        confidence_values = [value for _, value in confidence_rows]
        if max(confidence_values) - min(confidence_values) < 0.005:
            issues.append(
                "S6各能力画像confidence不得机械同值，必须反映对象证据直接性、来源质量和工程推导跨度差异"
            )
    support_focused_query = _query_explicitly_requests_support_equipment(query)
    standalone_support_positions = sorted(
        set(ordinary_support_positions + ancillary_support_positions)
    )
    if ordinary_support_positions and not support_focused_query:
        issues.append(
            "S6不得把普通通信、链路、保障、恢复、接口或治理单列为最终能力方向；"
            "只能把它们作为具体武器、传感器、火控、电子战或效应平台的内部改进措施"
        )
    if ancillary_support_positions and not support_focused_query:
        issues.append(
            "S6不得把伪装、假目标、工程构设、效果评估或后勤保障单列为最终能力方向；"
            "除非当前query明确以该类装备为主题，否则只能作为具体战斗装备的横向支撑层"
        )
    if support_focused_query and len(standalone_support_positions) > 1:
        issues.append(
            "即使query明确聚焦支撑装备，S6最终组合也最多单列1项伪装、通信、工程或保障方向，"
            "其余必须回到直接战斗装备"
        )
    if not lethal_weapon_positions:
        issues.append(
            "S6最终组合必须至少包含一项导弹、巡飞弹、弹药、拦截弹、鱼雷、火炮、定向能或"
            "电子压制效应器等杀伤/反杀伤武器装备方向"
        )
    direct_weapon_positions = set(
        unmanned_equipment_positions + lethal_weapon_positions
    )
    if directions and len(direct_weapon_positions) <= len(directions) // 2:
        issues.append(
            "S6具体打击、歼灭、杀伤或反杀伤武器未构成组合主体；"
            "不能用支撑系统或同一装备族重复占位"
        )
    disruptive_text = " ".join(
        " ".join(
            str(direction.get(field, ""))
            for field in (
                "name",
                "function",
                "equipment_form",
                "operational_mechanism",
                "military_value",
                "combat_effect_uplift",
                "strike_chain_contribution",
                "development_path",
                "novelty",
                "foresight",
                "future_trigger",
                "capability_gap",
                "capability_portrait",
            )
        )
        for direction in directions
        if isinstance(direction, Mapping)
    )
    disruptive_groups = disruptive_relationship_groups(disruptive_text)
    for left_index, (left_position, left) in enumerate(portraits):
        if not left:
            continue
        for right_position, right in portraits[left_index + 1 :]:
            similarity = _capability_text_similarity(left, right) if right else 0.0
            left_family = _capability_primary_equipment_family(
                directions_by_position.get(left_position, {})
            )
            right_family = _capability_primary_equipment_family(
                directions_by_position.get(right_position, {})
            )
            same_primary_family = bool(left_family) and left_family == right_family
            if similarity >= 0.90 or (
                similarity >= 0.75 and same_primary_family
            ):
                issues.append(
                    f"S6第{left_position}项与第{right_position}项机制文本完全相同；"
                    "必须由Codex复核其发射域/平台、目标运动包线、"
                    "末制导传感器、授权来源、补击时序和专属验证指标，无法独立验收时应合并或替换"
                )
    for left_index, (left_position, left_process) in enumerate(operational_processes):
        for right_position, right_process in operational_processes[left_index + 1 :]:
            process_similarity = _capability_text_similarity(
                left_process,
                right_process,
            )
            if process_similarity >= 0.72:
                issues.append(
                    f"S6第{left_position}项与第{right_position}项作战流程文本完全相同；"
                    "必须由Codex依据各自主装备、"
                    "发射/释放域、目标、效应触发和结束状态重新形成装备专属流程，禁止只替换名词"
                )
    return list(dict.fromkeys(issues))[:64]


def _s6_delivery_blocking_issues(issues: Sequence[Any]) -> list[str]:
    """Keep deterministic S6 prose diagnostics advisory at delivery time."""

    del issues
    return []


def _s6_portrait_repair_issues(issues: Sequence[Any]) -> list[str]:
    """Return portrait-local findings that justify one bounded repair.

    Candidate identity, naming and portfolio admission remain owned by S3-S5.
    These findings schedule a module edit but never delete a frozen card or
    fail delivery.
    """

    repairable_markers = (
        "装备能力画像缺少治理模块",
        "仍含已废弃",
        "装备能力画像泄露内部执行标签",
    )
    return list(
        dict.fromkeys(
            str(issue)
            for issue in issues
            if any(marker in str(issue) for marker in repairable_markers)
        )
    )[:16]


def _s6_release_gate_state(
    blocking_issues: Sequence[Any],
    nonblocking_warnings: Sequence[Any],
) -> dict[str, Any]:
    """Build a release state in which local diagnostics are advisory only."""

    warnings = list(
        dict.fromkeys(
            [
                *(str(item) for item in blocking_issues),
                *(str(item) for item in nonblocking_warnings),
            ]
        )
    )[:32]
    limited = bool(warnings)
    return {
        "passed": True,
        "failed": False,
        "limited": limited,
        "issues": [],
        "warnings": warnings,
    }


def _recover_invalid_s6_result(
    result: Mapping[str, Any],
    *,
    topic: str,
    handoff: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Replace an invalid S6 portfolio with evidence-bounded direct weapons.

    The recovery reuses only accepted evidence identifiers and category-level
    S4/S5 gap statements. It adds no provider call, no calibrated weapon
    parameters and no relaxed quality threshold.
    """

    evidence_ids: list[str] = []
    if handoff:
        evidence_ids.extend(
            str(item.get("evidence_id", "")).strip()
            for item in handoff.get("public_evidence", [])
            if isinstance(item, Mapping)
        )
    gap_rows: list[str] = []
    for item in result.get("concept_directions", []):
        if not isinstance(item, Mapping):
            continue
        evidence_ids.extend(
            str(ref).strip() for ref in item.get("direct_evidence_refs", [])
        )
        gap = str(item.get("capability_gap", "")).strip()
        if gap:
            gap_rows.append(gap)
    try:
        source_confidence = float(result.get("confidence", 0.0) or 0.0)
    except (TypeError, ValueError):
        source_confidence = 0.0
    directions = build_deadline_weapon_directions(
        topic=topic,
        evidence_ids=list(dict.fromkeys(item for item in evidence_ids if item)),
        evidence_index=(
            [
                dict(item)
                for item in handoff.get("public_evidence", [])
                if isinstance(item, Mapping)
            ]
            if handoff
            else []
        ),
        confidence=max(0.62, min(0.72, source_confidence or 0.62)),
        gap_basis="；".join(gap_rows)[:700],
        candidate_directions=[
            dict(item)
            for item in result.get("concept_directions", [])
            if isinstance(item, Mapping)
        ],
    )
    recovered = dict(result)
    recovered["concept_directions"] = directions
    recovered["capability_image_drafts"] = [
        str(item.get("name", "")) for item in directions
    ]
    recovered["capability_synthesis"] = [
        str(item.get("name", "")) for item in directions
    ]
    recovered["confidence"] = max(0.62, source_confidence)
    recovered["deterministic_quality_recovery"] = True
    issues = _capability_direction_quality_issues(
        recovered,
        handoff=handoff,
    )
    return recovered, issues


def _requires_s6_combat_value_rewrite(issues: Sequence[Any]) -> bool:
    markers = (
        "高阶作战效果",
        "直接作战效应方向",
        "标题包含升级、方向、包或套件等非装备命名",
        "现役升级名称未体现",
        "普通通信、链路、保障",
        "现役升级标题禁止使用",
        "现役升级标题未明确",
        "不得把普通通信",
        "杀伤/反杀伤武器装备方向",
        "不得把伪装、假目标、工程构设",
        "不得机械共用完全相同的direct_evidence_refs",
        "indicator_portrait未形成由本装备机理推导的差异化测量轴",
        "水下/反潜Query场景错误投影",
        "confidence不得机械同值",
    )
    return any(
        marker in str(issue)
        for issue in issues
        for marker in markers
    )


def _s6_repair_targets(
    result: Mapping[str, Any], issues: Sequence[Any]
) -> list[int]:
    """Resolve deterministic S6 issues to the smallest card set to rewrite."""

    directions = [
        item
        for item in result.get("concept_directions", [])
        if isinstance(item, Mapping)
    ]
    targets: set[int] = set()
    issue_text = " ".join(str(item) for item in issues)
    for issue in issues:
        text = str(issue)
        targets.update(int(value) for value in re.findall(r"S6第(\d+)项", text))
        for positions in re.findall(r"涉及位置([0-9、,，和及]+)", text):
            targets.update(int(value) for value in re.findall(r"\d+", positions))
        duplicate = re.search(r"第(\d+)项与第(\d+)项", text)
        if duplicate:
            targets.add(int(duplicate.group(2)))

    if "最终方向名称必须互异" in issue_text:
        positions_by_name: dict[str, list[int]] = {}
        for position, item in enumerate(directions, start=1):
            name = str(item.get("name", "")).strip()
            if name:
                positions_by_name.setdefault(name, []).append(position)
        for positions in positions_by_name.values():
            if len(positions) > 1:
                targets.update(positions[1:])

    def replacement_candidate(*, avoid_unmanned: bool = False) -> int:
        type_counts = Counter(str(item.get("type", "")) for item in directions)
        for position in range(len(directions), 0, -1):
            item = directions[position - 1]
            item_type = str(item.get("type", ""))
            if type_counts[item_type] <= 1:
                continue
            if avoid_unmanned and _is_unmanned_combat_equipment_direction(item):
                continue
            return position
        return max(1, len(directions))

    if "独立导弹或精确制导弹药方向" in issue_text:
        targets.add(replacement_candidate(avoid_unmanned=True))
    if "无人作战装备方向" in issue_text and not any(
        _is_unmanned_combat_equipment_direction(item) for item in directions
    ):
        targets.add(replacement_candidate())
    if "至少需要3类与query因果相关" in issue_text:
        for position in range(len(directions), max(0, len(directions) - 3), -1):
            targets.add(position)
    if not targets and issues:
        targets.add(max(1, len(directions)))
    return sorted(position for position in targets if 1 <= position <= len(directions))[:8]


def _s6_portrait_module_repair_targets(
    result: Mapping[str, Any], issues: Sequence[Any]
) -> dict[int, list[str]]:
    """Map purely portrait-local findings to the smallest authored modules."""

    label_to_key = {label: key for key, label in CAPABILITY_PORTRAIT_MODULES}
    targets: dict[int, set[str]] = {}
    local_markers = (
        "能力画像",
        "画像正文",
        "概述",
        "装备与技术实现",
        "关键作战流程",
        "形成能力与作战效果",
        "制胜逻辑",
        "跨栏重复",
        "同一卡片长句",
    )
    for raw_issue in issues:
        issue = str(raw_issue)
        if not any(marker in issue for marker in local_markers):
            return {}
        positions = {
            int(value)
            for value in re.findall(r"(?:S6)?第(\d+)项", issue)
        }
        if not positions:
            return {}
        module_keys = {
            key for label, key in label_to_key.items() if label in issue
        }
        if "概述" in issue:
            module_keys.add("overview")
        if "关键作战流程" in issue:
            module_keys.add("operational_process")
        if "形成能力与作战效果" in issue:
            module_keys.add("capability_effects")
        if "制胜逻辑" in issue:
            module_keys.add("winning_logic")
        if "装备与技术实现" in issue:
            module_keys.add("technology_implementation")
        if not module_keys or "同一卡片长句" in issue:
            module_keys.update(key for key, _ in CAPABILITY_PORTRAIT_MODULES)
        for position in positions:
            targets.setdefault(position, set()).update(module_keys)
    direction_count = len(result.get("concept_directions", []))
    return {
        position: [
            key
            for key, _ in CAPABILITY_PORTRAIT_MODULES
            if key in module_keys
        ]
        for position, module_keys in sorted(targets.items())
        if 1 <= position <= direction_count
    }


def _merge_s6_portrait_module_repairs(
    result: Mapping[str, Any], repairs: Mapping[str, Any]
) -> dict[str, Any]:
    """Merge only returned portrait modules, preserving card identity and prose."""

    merged = dict(result)
    directions = [
        dict(item) if isinstance(item, Mapping) else item
        for item in result.get("concept_directions", [])
    ]
    for repair in repairs.get("portrait_module_repairs", []):
        if not isinstance(repair, Mapping):
            continue
        try:
            position = int(repair.get("position", 0) or 0)
        except (TypeError, ValueError):
            continue
        if not 1 <= position <= len(directions):
            continue
        current = directions[position - 1]
        if not isinstance(current, Mapping):
            continue
        modules = dict(current.get("capability_portrait_modules", {}))
        if len(modules) != len(CAPABILITY_PORTRAIT_MODULES):
            modules = parse_capability_portrait_modules(
                current.get("capability_portrait", "")
            )
        rows = repair.get("module_repairs", [])
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            key = str(row.get("module", "")).strip()
            content = str(row.get("content", "")).strip()
            if key in {item[0] for item in CAPABILITY_PORTRAIT_MODULES} and content:
                modules[key] = content
        classification = current.get("capability_classification", {})
        if classification:
            modules["capability_classification"] = classification
        portrait = assemble_capability_portrait_modules(modules)
        if portrait:
            current["capability_portrait_modules"] = modules
            current["capability_portrait"] = portrait
    merged["concept_directions"] = directions
    return merged


def _s6_can_use_lightweight_card_repair(
    result: Mapping[str, Any],
    issues: Sequence[Any],
) -> bool:
    """Allow one bounded multi-card repair when a portfolio is fixable in place.

    Title specificity, an unclear in-service upgrade object and insufficient
    direct-weapon differentiation may be repaired together in one provider
    call. Any residual failure is closed deterministically by the caller.
    """

    directions = [
        item
        for item in result.get("concept_directions", [])
        if isinstance(item, Mapping)
    ]
    if not directions:
        return False
    targets = _s6_repair_targets(result, issues)
    if not 1 <= len(targets) <= 5 or len(issues) > 16:
        return False
    # A bounded set of existing cards is cheaper and safer to repair in place,
    # even when the advisory direction count is outside 5—7. Count, diversity
    # and category coverage must not turn a local content/evidence defect into
    # another multi-minute full S6 regeneration.
    return True


def _merge_s6_direction_repairs(
    result: Mapping[str, Any], repairs: Mapping[str, Any]
) -> dict[str, Any]:
    merged = dict(result)
    directions = [
        dict(item) if isinstance(item, Mapping) else item
        for item in result.get("concept_directions", [])
    ]
    for item in repairs.get("direction_repairs", []):
        if not isinstance(item, Mapping):
            continue
        try:
            position = int(item.get("position", 0) or 0)
        except (TypeError, ValueError):
            continue
        direction = item.get("direction")
        if not isinstance(direction, Mapping) or not 1 <= position <= len(directions):
            continue
        current = directions[position - 1]
        repaired = dict(direction)
        if isinstance(current, Mapping):
            locked_name = str(current.get("name", "")).strip()
            if locked_name:
                repaired["name"] = locked_name
        directions[position - 1] = repaired
    merged["concept_directions"] = directions
    return merged


def _s6_portfolio_confidence(
    selected_portfolio: Sequence[Any],
    authored_directions: Sequence[Any],
) -> float:
    """Aggregate existing dynamic-S6 confidence without manufacturing certainty.

    Blind-expert scores are authoritative for a swarm-selected portfolio. If
    they are unavailable, use independently authored card confidences. A zero
    result deliberately keeps the structured gate closed when neither source
    contains a valid calibration.
    """

    expert_scores: list[float] = []
    for item in selected_portfolio:
        if not isinstance(item, Mapping):
            continue
        try:
            score = float(item.get("expert_score"))
        except (TypeError, ValueError):
            continue
        if 0.0 <= score <= 1.0:
            expert_scores.append(score)
    if expert_scores:
        return round(sum(expert_scores) / len(expert_scores), 4)

    card_scores: list[float] = []
    for item in authored_directions:
        if not isinstance(item, Mapping):
            continue
        try:
            score = float(item.get("confidence"))
        except (TypeError, ValueError):
            continue
        if 0.0 <= score <= 1.0:
            card_scores.append(score)
    if card_scores:
        return round(sum(card_scores) / len(card_scores), 4)
    return 0.0


_S6_AUTHORED_EXPOSITION_FIELDS = (
    "function",
    "project_function",
    "feasibility",
    "feasibility_basis",
    "horizon",
    "military_value",
    "depth_mechanism",
    "foresight",
    "novelty",
    "strike_countermeasure_value",
    "operational_mechanism",
    "target_scenario",
    "problem_statement",
    "scientific_principle",
    "enabling_technologies",
    "operational_concept",
    "operational_process",
    "semantic_consistency_check",
    "capability_outcome",
    "winning_mechanism",
    "development_path",
    "future_trigger",
    "adversary_adaptation",
    "failure_boundary",
    "capability_gap",
    "upgrade_package",
    "combat_effect_uplift",
    "strike_chain_contribution",
    "upgrade_boundary",
    "capability_portrait",
    "capability_portrait_modules",
    "confidence",
)


def _s6_weapon_title_is_descriptive_sentence(value: object) -> bool:
    """Detect a platform-plus-loadout sentence masquerading as one weapon name."""

    title = str(value or "").strip()
    return bool(
        re.search(
            r"[，,]\s*(?:并)?(?:集成|搭载|配置|装有|携带|配备)",
            title,
        )
        or (
            "、" in title
            and any(
                term in title
                for term in ("集成", "搭载", "配置", "装有", "携带")
            )
        )
    )


def _merge_dynamic_portfolio_with_s6_authored_cards(
    selected_portfolio: Sequence[Any],
    authored_directions: Sequence[Any],
) -> list[dict[str, Any]]:
    """Keep expert-selected weapon identities while retaining S6 prose.

    The swarm owns which independently reviewed weapons reach S6.  The S6
    Codex sessions own each selected weapon's battlefield scene, operational
    sequence and capability portrait. Indicator and Query-relevance contracts
    remain owned by the pre-S6 S5 handoff. A
    deterministic portfolio projection must never overwrite those authored
    fields after the expensive S6 calls have completed.
    """

    selected = [dict(item) for item in selected_portfolio if isinstance(item, Mapping)]
    authored = [dict(item) for item in authored_directions if isinstance(item, Mapping)]
    authored_by_id = {
        str(item.get("hypothesis_id", "")).strip(): item
        for item in authored
        if str(item.get("hypothesis_id", "")).strip()
    }
    merged_rows: list[dict[str, Any]] = []
    for position, base in enumerate(selected):
        hypothesis_id = str(base.get("hypothesis_id", "")).strip()
        authored_card = authored_by_id.get(hypothesis_id)
        if authored_card is None and position < len(authored):
            authored_card = authored[position]
        merged = dict(base)
        if authored_card is not None:
            base_name = str(base.get("name", "")).strip()
            authored_name = str(authored_card.get("name", "")).strip()
            if (
                authored_name
                and _s6_weapon_title_is_descriptive_sentence(base_name)
                and not _s6_weapon_title_is_descriptive_sentence(authored_name)
            ):
                # The swarm still owns the selected equipment object, while S6
                # may remove a loadout sentence from its visible title.  All
                # identity, form, target and evidence fields remain frozen.
                merged["name"] = authored_name
            for field_name in _S6_AUTHORED_EXPOSITION_FIELDS:
                value = authored_card.get(field_name)
                if value not in (None, "", []):
                    merged[field_name] = value
        merged_rows.append(merged)
    return merged_rows

__all__ = ['_has_combat_effect_signal', '_has_high_order_combat_value', '_is_ordinary_support_direction', '_has_combat_munition_compound', '_has_specific_model_designator', '_direction_name_has_equipment_object', '_is_ancillary_support_equipment_direction', '_query_explicitly_requests_support_equipment', '_weapon_equipment_identity', '_strip_weapon_support_context', '_equipment_direction_categories', '_is_unmanned_combat_equipment_direction', '_is_lethal_weapon_equipment_direction', '_is_missile_precision_munition_direction', '_dedupe_capability_title', '_s6_title_requires_structural_repair', '_capability_title_equipment_anchor', '_capability_upgrade_effect_anchor', '_compact_capability_direction_title', '_uniquify_compacted_capability_titles', '_capability_portrait_alignment_issues', '_capability_language_issues', '_collect_reference_ids', '_normalize_effect_chain_references', '_normalize_concept_direction_priorities', '_normalize_priority_references', '_prioritized_evidence_index', '_compact_s6_prior_outputs', '_evidence_boundary_is_public_semantic', '_query_relevance_issues', '_truncate_complete_text', '_clean_capability_handoff_text', '_capability_handoff_statement', '_capability_synthesis_handoff', '_s6_card_is_reusable', '_s6_first_pass_quality_contract', '_capability_text_similarity', '_capability_primary_equipment_family', '_s6_primary_equipment_object_kind', '_s6_primary_equipment_identity_mismatch', '_build_direction_capability_portrait', '_normalize_s6_deterministic_format', '_equipment_form_identity_text', '_direction_is_defensive_only', '_s6_frontier_evidence_allowance', '_indicator_portrait_is_specific', '_query_relevance_is_specific', '_prepare_pre_s6_card_contract', '_capability_direction_quality_issues', '_s6_delivery_blocking_issues', '_s6_portrait_repair_issues', '_s6_release_gate_state', '_recover_invalid_s6_result', '_requires_s6_combat_value_rewrite', '_s6_repair_targets', '_s6_portrait_module_repair_targets', '_s6_can_use_lightweight_card_repair', '_merge_s6_direction_repairs', '_merge_s6_portrait_module_repairs', '_s6_portfolio_confidence', '_s6_weapon_title_is_descriptive_sentence', '_merge_dynamic_portfolio_with_s6_authored_cards']
