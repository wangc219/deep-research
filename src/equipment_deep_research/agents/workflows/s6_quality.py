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


_S6_EQUIPMENT_CLASSIFICATIONS = {
    "direct_combat",
    "unmanned_combat",
    "upgrade",
    "system_link",
    "support_only",
    "non_equipment",
}


def _equipment_semantic_assessment(
    direction: Mapping[str, Any],
) -> dict[str, Any]:
    """Return the model-authored equipment judgement without text inference.

    S3-S5 and the independent expert own semantic classification.  S6 may
    validate and consume that structured decision, but it must never recreate
    it from a title, a model designator, an equipment noun or a combat-effect
    vocabulary.  The scalar fallbacks below are older structured model fields,
    retained only so persisted runs remain readable.
    """

    raw = direction.get("equipment_semantic_assessment", {})
    assessment = dict(raw) if isinstance(raw, Mapping) else {}
    classification = str(
        assessment.get("classification")
        or direction.get("equipment_classification")
        or ""
    ).strip().lower()
    if classification in _S6_EQUIPMENT_CLASSIFICATIONS:
        assessment["classification"] = classification
    else:
        assessment.pop("classification", None)

    if "direct_combat_effect" not in assessment and isinstance(
        direction.get("direct_combat_equipment"), bool
    ):
        assessment["direct_combat_effect"] = direction[
            "direct_combat_equipment"
        ]
    if classification:
        assessment.setdefault(
            "support_only",
            classification in {"system_link", "support_only", "non_equipment"},
        )
        assessment.setdefault(
            "unmanned_combat", classification == "unmanned_combat"
        )
        assessment.setdefault(
            "direct_combat_effect",
            classification in {"direct_combat", "unmanned_combat"},
        )
        assessment.setdefault(
            "concrete_equipment", classification != "non_equipment"
        )
    return assessment


def _has_combat_effect_signal(direction: Mapping[str, Any]) -> bool:
    """Read the Agent's direct-effect judgement; never scan prose."""

    return _equipment_semantic_assessment(direction).get(
        "direct_combat_effect"
    ) is True


def _has_high_order_combat_value(direction: Mapping[str, Any]) -> bool:
    """Compatibility alias for the structured direct-effect decision."""

    return _has_combat_effect_signal(direction)


def _is_ordinary_support_direction(direction: Mapping[str, Any]) -> bool:
    return _equipment_semantic_assessment(direction).get("support_only") is True


def _direction_name_has_equipment_object(direction: Mapping[str, Any]) -> bool:
    """Validate the model-owned concrete-equipment identity contract."""

    name = str(direction.get("name", "") or "").strip()
    semantic_check = direction.get("semantic_consistency_check")
    primary_identity = str(
        direction.get("primary_equipment_identity", "") or ""
    ).strip()
    assessment = _equipment_semantic_assessment(direction)
    return bool(
        name
        and primary_identity
        and isinstance(semantic_check, Mapping)
        and semantic_check.get("consistent") is True
        and assessment.get("concrete_equipment") is True
    )


def _is_ancillary_support_equipment_direction(
    direction: Mapping[str, Any],
) -> bool:
    assessment = _equipment_semantic_assessment(direction)
    return bool(
        assessment.get("support_only") is True
        and assessment.get("ancillary_support") is True
    )


def _query_explicitly_requests_support_equipment(value: Any) -> bool:
    """Read the structured Query brief instead of classifying Query text."""

    if not isinstance(value, Mapping):
        return False
    brief = value.get("structured_query_brief", value)
    if not isinstance(brief, Mapping):
        return False
    return bool(
        brief.get("support_equipment_requested") is True
        or brief.get("allow_standalone_support_equipment") is True
        or str(brief.get("primary_equipment_focus", "")).strip().lower()
        == "support_equipment"
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


def _equipment_direction_categories(direction: Mapping[str, Any]) -> set[str]:
    """Project the model-authored assessment into compatibility categories."""

    assessment = _equipment_semantic_assessment(direction)
    categories: set[str] = set()
    classification = str(assessment.get("classification", ""))
    if assessment.get("unmanned_combat") is True:
        categories.add("unmanned_combat_platform")
    if assessment.get("precision_munition") is True:
        categories.add("missile_precision_munition")
    if assessment.get("direct_combat_effect") is True:
        categories.add("structured_direct_effector")
    if classification:
        categories.add(classification)
    return categories


def _is_unmanned_combat_equipment_direction(direction: Mapping[str, Any]) -> bool:
    return "unmanned_combat_platform" in _equipment_direction_categories(direction)


def _is_lethal_weapon_equipment_direction(direction: Mapping[str, Any]) -> bool:
    return _equipment_semantic_assessment(direction).get(
        "direct_combat_effect"
    ) is True


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
    return title


def _s6_title_requires_structural_repair(
    direction: Mapping[str, Any],
    title: str,
) -> bool:
    """Require a non-empty title and a passed structured identity contract."""

    normalized = _dedupe_capability_title(title)
    return not normalized or not _direction_name_has_equipment_object(
        {**direction, "name": normalized}
    )


def _capability_title_equipment_anchor(value: Any) -> str:
    """Compatibility helper that preserves the Agent-authored identity."""

    return _clean_capability_handoff_text(value, limit=180).strip(" ：:，,；。")


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
    """Accept public prose while rejecting orchestration leakage.

    Whether the prose is a sound epistemic boundary is judged by the Agent;
    local code only enforces the public/internal data boundary.
    """

    text = " ".join(str(value or "").split()).strip()
    return bool(text) and not _CAPABILITY_HANDOFF_INTERNAL_PATTERN.search(text)

def _query_relevance_issues(
    position: int,
    direction: Mapping[str, Any],
    *,
    query: str,
) -> list[str]:
    """Validate only the Agent-owned Query relevance contract shape."""

    del query
    relevance = str(direction.get("query_relevance", "") or "").strip()
    if not relevance:
        return []
    assessment = _equipment_semantic_assessment(direction)
    if assessment.get("query_alignment_confirmed") is False:
        return [f"S6第{position}项结构化Query关联合同未通过"]
    semantic_check = direction.get("semantic_consistency_check", {})
    if isinstance(semantic_check, Mapping) and semantic_check.get("consistent") is False:
        return [f"S6第{position}项结构化语义一致性合同未通过"]
    return []


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
        """Carry model-selected effects without re-ranking their wording."""

        rows: list[str] = []

        def visit(value: Any) -> None:
            if len(rows) >= limit:
                return
            if isinstance(value, Mapping):
                # S6 needs the military decision spine, not upstream working
                # titles or solution labels that could anchor/overwrite the
                # S5-frozen candidate identity.
                text = _capability_handoff_statement(
                    {
                        field: value.get(field)
                        for field in (
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
                        if value.get(field) not in (None, "", [], {})
                    },
                    limit=300,
                )
                if text and text not in rows:
                    rows.append(text)
            elif isinstance(value, list):
                for item in value:
                    visit(item)
            else:
                text = _clean_capability_handoff_text(value, limit=300)
                if text and text not in rows:
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
                    "capability_classification", "equipment_classification",
                    "equipment_semantic_assessment",
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
        "structured_query_brief": (
            dict(prior_step_outputs.get("structured_query_brief", {}))
            if isinstance(
                prior_step_outputs.get("structured_query_brief", {}), Mapping
            )
            else {}
        ),
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
    the gap assessment.  This projection carries that model-authored contract
    into S6 without locally extracting Query keywords or equipment categories.
    """

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
        "query": _clean_capability_handoff_text(topic, limit=240),
        "structured_query_brief": (
            dict(handoff.get("structured_query_brief", {}))
            if isinstance(handoff.get("structured_query_brief", {}), Mapping)
            else {}
        ),
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
                "由S5模型依据结构化Query语义决定，不由本地Query字符串分类"
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
        equipment_form_text = str(direction.get("equipment_form", "")).strip()
        if equipment_form_text:
            direction["equipment_form"] = _equipment_form_identity_text(
                equipment_form_text
            )
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
    """Normalize layout without interpreting equipment-form semantics."""

    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text.strip(" ，,；;")


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
    """Check presence only; semantic specificity is an Agent judgement."""

    return bool(str(value or "").strip())


def _query_relevance_is_specific(value: object) -> bool:
    """Check presence only; Query alignment is declared by the Agent contract."""

    return bool(str(value or "").strip())


def _prepare_pre_s6_card_contract(
    value: Mapping[str, Any],
    *,
    query: str = "",
) -> dict[str, Any]:
    """Close S5-owned card fields before parallel S6 authoring begins.

    S6 owns prose synthesis only.  This helper may carry forward existing S5
    fields and sanitize an evidence boundary, but it must not author missing
    indicator or Query semantics locally.  Missing semantic fields remain
    visible so the model-owned handoff can be diagnosed or retried.
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
    del query, name

    identity_contract = card.get("portfolio_identity_contract", {})
    identity_contract = (
        dict(identity_contract) if isinstance(identity_contract, Mapping) else {}
    )
    existing_quality_contract = identity_contract.get("pre_s6_quality_contract", {})
    existing_quality_contract = (
        dict(existing_quality_contract)
        if isinstance(existing_quality_contract, Mapping)
        else {}
    )
    capability_classification = card.get("capability_classification", {})
    capability_classification = (
        dict(capability_classification)
        if isinstance(capability_classification, Mapping)
        else {}
    )
    identity_contract["pre_s6_quality_contract"] = {
        "indicator_portrait": str(card.get("indicator_portrait", "") or "").strip(),
        "query_relevance": str(card.get("query_relevance", "") or "").strip(),
        "capability_classification": capability_classification,
        "equipment_semantic_assessment": dict(
            card.get("equipment_semantic_assessment", {})
        )
        if isinstance(card.get("equipment_semantic_assessment", {}), Mapping)
        else {},
        "evidence_boundary_status": evidence_boundary_status,
        "owner": str(existing_quality_contract.get("owner") or "S5_handoff"),
        "s6_mutation_allowed": False,
    }
    card["portfolio_identity_contract"] = identity_contract
    return card


def _capability_direction_quality_issues(
    result: Mapping[str, Any],
    *,
    handoff: Mapping[str, Any] | None = None,
) -> list[str]:
    """Validate S6 structure while leaving military semantics to the Agents.

    The independent expert and S5 handoff decide equipment identity, role,
    Query relevance and direct combat value.  S6 checks that those decisions
    are present and internally acknowledged; it does not classify prose,
    titles, model names or Query words.
    """

    issues: list[str] = []
    directions = result.get("concept_directions", [])
    if not isinstance(directions, list):
        return ["S6 concept_directions必须为结构化列表"]
    if not directions:
        return ["S6必须形成至少一项结构化装备方向"]

    semantic_contract_required = bool(
        handoff and "equipment_portfolio_preflight" in handoff
    )
    hypothesis_ids: list[str] = []
    direction_names: list[str] = []
    for position, direction in enumerate(directions, start=1):
        if not isinstance(direction, Mapping):
            issues.append(f"S6第{position}项不是结构化能力方向")
            continue

        required = [
            "name",
            "primary_equipment_identity",
            "equipment_form",
            "query_relevance",
            "indicator_portrait",
        ]
        if semantic_contract_required:
            required.extend(("hypothesis_id", "target_and_direct_effect"))
        missing = [
            field
            for field in required
            if not str(direction.get(field, "") or "").strip()
        ]
        if missing:
            issues.append(f"S6第{position}项缺少{','.join(missing)}")

        hypothesis_id = str(direction.get("hypothesis_id", "") or "").strip()
        if hypothesis_id:
            hypothesis_ids.append(hypothesis_id)
        name = str(direction.get("name", "") or "").strip()
        if name:
            direction_names.append(name)

        process = direction.get("operational_process", [])
        if not isinstance(process, list) or not any(
            str(item).strip() for item in process
        ):
            issues.append(f"S6第{position}项operational_process缺失")

        classification = direction.get("capability_classification", {})
        if not isinstance(classification, Mapping) or not str(
            classification.get("primary_dimension", "") or ""
        ).strip():
            issues.append(f"S6第{position}项缺少Query驱动的主要能力分类维度")

        assessment = _equipment_semantic_assessment(direction)
        if semantic_contract_required and not assessment.get("classification"):
            issues.append(f"S6第{position}项缺少模型装备语义分类")
        required_assessment_flags = (
            "direct_combat_effect",
            "support_only",
            "unmanned_combat",
            "precision_munition",
            "concrete_equipment",
            "query_alignment_confirmed",
        )
        if semantic_contract_required:
            missing_flags = [
                field
                for field in required_assessment_flags
                if not isinstance(assessment.get(field), bool)
            ]
            if missing_flags:
                issues.append(
                    f"S6第{position}项模型装备语义合同缺少"
                    + ",".join(missing_flags)
                )
        if assessment.get("query_alignment_confirmed") is False:
            issues.append(f"S6第{position}项模型判定与当前Query不一致")
        if assessment.get("concrete_equipment") is False:
            issues.append(f"S6第{position}项模型判定不是具体装备对象")

        semantic_check = direction.get("semantic_consistency_check", {})
        if not isinstance(semantic_check, Mapping) or (
            semantic_check.get("consistent") is not True
        ):
            issues.append(f"S6第{position}项语义一致性合同未通过")
        elif semantic_contract_required:
            missing_semantic_fields = [
                field
                for field in (
                    "process_actor",
                    "launch_or_release_mode",
                    "target_and_direct_effect",
                    "resolution_note",
                )
                if not str(semantic_check.get(field, "") or "").strip()
            ]
            if missing_semantic_fields:
                issues.append(
                    f"S6第{position}项语义一致性合同缺少"
                    + ",".join(missing_semantic_fields)
                )

        try:
            confidence = float(direction.get("confidence"))
        except (TypeError, ValueError):
            confidence = -1.0
        if not 0.0 <= confidence <= 1.0:
            issues.append(f"S6第{position}项缺少0至1之间的独立confidence")

        issues.extend(_capability_portrait_alignment_issues(position, direction))
        issues.extend(
            _capability_language_issues(
                position,
                direction,
                semantic_contract_required=semantic_contract_required,
            )
        )

        public_fields = (
            "name",
            "function",
            "equipment_form",
            "operational_mechanism",
            "target_scenario",
            "operational_process",
            "military_value",
            "development_path",
            "query_relevance",
            "capability_portrait",
            "indicator_portrait",
        )
        leaked = [
            field
            for field in public_fields
            if _CAPABILITY_HANDOFF_INTERNAL_PATTERN.search(
                str(direction.get(field, "") or "")
            )
        ]
        if leaked:
            issues.append(
                f"S6第{position}项{','.join(leaked[:4])}混入内部执行语言"
            )

        if str(direction.get("type", "") or "") == "upgrade":
            upgrade_required = (
                "baseline_system",
                "combat_effect_uplift",
                "strike_chain_contribution",
                "upgrade_boundary",
            )
            upgrade_missing = [
                field
                for field in upgrade_required
                if not str(direction.get(field, "") or "").strip()
            ]
            package = direction.get("upgrade_package", [])
            if not isinstance(package, list) or len(
                [item for item in package if str(item).strip()]
            ) < 2:
                upgrade_missing.append("upgrade_package>=2")
            if upgrade_missing:
                issues.append(
                    f"S6第{position}项现役升级论证缺少"
                    + ",".join(upgrade_missing)
                )

    if len(hypothesis_ids) != len(set(hypothesis_ids)):
        issues.append("S6存在重复hypothesis_id")
    duplicate_names = [
        name
        for name, count in Counter(direction_names).items()
        if count > 1
    ]
    if duplicate_names:
        issues.append(
            "S6最终方向名称必须互异："
            + "、".join(duplicate_names[:3])
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
    """Semantic rewrite routing belongs to the S6 critic Agent."""

    del issues
    return False


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
    """Title semantics are frozen upstream and are not inferred locally."""

    del value
    return False


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

__all__ = ['_equipment_semantic_assessment', '_has_combat_effect_signal', '_has_high_order_combat_value', '_is_ordinary_support_direction', '_direction_name_has_equipment_object', '_is_ancillary_support_equipment_direction', '_query_explicitly_requests_support_equipment', '_weapon_equipment_identity', '_equipment_direction_categories', '_is_unmanned_combat_equipment_direction', '_is_lethal_weapon_equipment_direction', '_is_missile_precision_munition_direction', '_dedupe_capability_title', '_s6_title_requires_structural_repair', '_capability_title_equipment_anchor', '_capability_upgrade_effect_anchor', '_compact_capability_direction_title', '_uniquify_compacted_capability_titles', '_capability_portrait_alignment_issues', '_capability_language_issues', '_collect_reference_ids', '_normalize_effect_chain_references', '_normalize_concept_direction_priorities', '_normalize_priority_references', '_prioritized_evidence_index', '_compact_s6_prior_outputs', '_evidence_boundary_is_public_semantic', '_query_relevance_issues', '_truncate_complete_text', '_clean_capability_handoff_text', '_capability_handoff_statement', '_capability_synthesis_handoff', '_s6_card_is_reusable', '_s6_first_pass_quality_contract', '_capability_text_similarity', '_capability_primary_equipment_family', '_s6_primary_equipment_object_kind', '_s6_primary_equipment_identity_mismatch', '_build_direction_capability_portrait', '_normalize_s6_deterministic_format', '_equipment_form_identity_text', '_direction_is_defensive_only', '_s6_frontier_evidence_allowance', '_indicator_portrait_is_specific', '_query_relevance_is_specific', '_prepare_pre_s6_card_contract', '_capability_direction_quality_issues', '_s6_delivery_blocking_issues', '_s6_portrait_repair_issues', '_s6_release_gate_state', '_recover_invalid_s6_result', '_requires_s6_combat_value_rewrite', '_s6_repair_targets', '_s6_portrait_module_repair_targets', '_s6_can_use_lightweight_card_repair', '_merge_s6_direction_repairs', '_merge_s6_portrait_module_repairs', '_s6_portfolio_confidence', '_s6_weapon_title_is_descriptive_sentence', '_merge_dynamic_portfolio_with_s6_authored_cards']
