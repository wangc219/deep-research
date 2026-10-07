"""Reporter generation, normalization and quality support.

Kept separate from provider transport and from the S1-S6 workflow.
"""
# ruff: noqa: F821

from __future__ import annotations

from collections.abc import Mapping, Sequence
import os
import re
from pathlib import Path
from typing import Any


_legacy = None
_legacy_syncing = False


def _sync_legacy_globals() -> None:
    """Lazily mirror coordinator helpers without creating an import cycle.

    ``coordinator`` imports this module at its end to expose the report
    helpers, while older callers also import this module directly.  Resolving
    the legacy namespace only after this module's functions are defined keeps
    both directions safe and preserves the historical helper lookup contract.
    """

    global _legacy, _legacy_syncing
    if _legacy_syncing:
        return
    if _legacy is None:
        _legacy_syncing = True
        try:
            from equipment_deep_research.agents.workflows import coordinator

            _legacy = coordinator
        finally:
            _legacy_syncing = False
    if _legacy is not None:
        globals().update(
            {
                name: value
                for name, value in vars(_legacy).items()
                if not name.startswith("__")
            }
        )


_VALID_REPORT_TEMPLATE_MODES = frozenset(
    {"three_layer_nine_item", "project_argument_v1"}
)


def _coerce_report_template_mode(value: Any) -> str:
    mode = str(value or "").strip()
    return mode if mode in _VALID_REPORT_TEMPLATE_MODES else ""


def _report_template_mode(*sources: Mapping[str, Any] | None) -> str:
    """Return the template selected in run config, never a silent rewrite.

    Lookup order is the explicit ``report_template_mode`` on each mapping,
    then the same field nested under generation/report_context/metadata.
    Only when none of those carry a valid choice does the helper fall back
    to the historical three-layer contract, so old records without the field
    keep working.  New UI/API creates already persist the picker value.
    """

    for payload in sources:
        if not isinstance(payload, Mapping):
            continue
        candidates = [payload.get("report_template_mode")]
        for nested_key in ("generation", "report_context", "metadata"):
            nested = payload.get(nested_key)
            if isinstance(nested, Mapping):
                candidates.append(nested.get("report_template_mode"))
        for value in candidates:
            mode = _coerce_report_template_mode(value)
            if mode:
                return mode
    return "three_layer_nine_item"


def _report_capability_cue_handoff_limit() -> int | None:
    """Return an optional handoff portfolio cap without imposing a default quota.

    Capability directions are selected upstream from the Query and S6 evidence.
    The Reporter should receive all of them by default; deployments with a
    deliberately small context window may opt into a positive soft cap through
    ``EQUIPMENT_DR_REPORT_CAPABILITY_CUE_LIMIT``.  Zero, negative and malformed
    values mean unlimited rather than silently dropping directions.
    """

    raw = os.environ.get("EQUIPMENT_DR_REPORT_CAPABILITY_CUE_LIMIT", "").strip()
    if not raw:
        return None
    try:
        limit = int(raw)
    except (TypeError, ValueError):
        return None
    return limit if limit > 0 else None


def _limit_report_capability_cues(value: Sequence[Any]) -> list[Any]:
    """Apply the optional handoff cap while preserving every item by default."""

    limit = _report_capability_cue_handoff_limit()
    rows = list(value)
    return rows if limit is None else rows[:limit]


def _report_canonical_headings(
    payload: Mapping[str, Any],
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    if _report_template_mode(payload) == "project_argument_v1":
        return (
            _PROJECT_REPORT_CANONICAL_H2,
            _PROJECT_REPORT_CANONICAL_H3,
            _PROJECT_REPORT_CANONICAL_H4,
        )
    return _REPORT_CANONICAL_H2, _REPORT_CANONICAL_H3, ()

_REPORT_H3_ALIAS_MARKERS = (
    ("典型作战场景", "作战场景", "场景构造"),
    ("新战法或新概念技术及制胜机理", "新战法", "新概念技术", "制胜机理"),
    ("装备能力特征清单", "装备能力特征", "能力特征清单", "能力指标"),
    ("能力实现途径", "实现途径", "实现路径"),
    ("核心技术清单与攻关优先级", "核心技术清单", "核心技术", "攻关优先级"),
    ("技术耦合与短板风险", "技术耦合", "耦合风险", "短板风险"),
    ("装备能力图像", "能力图像", "能力画像"),
    ("效能贡献评估", "效能贡献", "作战效能"),
    ("发展优先级与近期抓手", "发展优先级", "近期抓手", "演示验证抓手"),
)


def _report_has_complete_canonical_structure(
    text: str,
    payload: Mapping[str, Any] | None = None,
) -> bool:
    if isinstance(payload, Mapping):
        project_mode = _report_template_mode(payload) == "project_argument_v1"
    else:
        project_mode = "## 一、需求分析" in str(text or "")
    h2_values = _PROJECT_REPORT_CANONICAL_H2 if project_mode else _REPORT_CANONICAL_H2
    h3_values = _PROJECT_REPORT_CANONICAL_H3 if project_mode else _REPORT_CANONICAL_H3
    h4_values = _PROJECT_REPORT_CANONICAL_H4 if project_mode else ()
    return all(
        len(
            re.findall(
                rf"^##\s+{re.escape(title)}\s*$",
                str(text or ""),
                flags=re.MULTILINE,
            )
        )
        == 1
        for title in h2_values
    ) and all(
        len(
            re.findall(
                rf"^###\s+{re.escape(title)}\s*$",
                str(text or ""),
                flags=re.MULTILINE,
            )
        )
        == 1
        for title in h3_values
    ) and all(
        len(
            re.findall(
                rf"^####\s+{re.escape(title)}\s*$",
                str(text or ""),
                flags=re.MULTILINE,
            )
        )
        == 1
        for title in h4_values
    )


def _canonical_report_h2(title: str, template_mode: str = "") -> str:
    normalized = re.sub(r"\s+", "", title)
    normalized = re.sub(r"^\d+(?:\.\d+)*[、.．]?", "", normalized)
    project_mode = template_mode == "project_argument_v1"
    three_layer_mode = template_mode == "three_layer_nine_item"
    candidates = (
        _PROJECT_REPORT_CANONICAL_H2
        if project_mode
        else _REPORT_CANONICAL_H2
        if three_layer_mode
        else (*_REPORT_CANONICAL_H2, *_PROJECT_REPORT_CANONICAL_H2)
    )
    for canonical in candidates:
        if normalized == re.sub(r"\s+", "", canonical):
            return canonical
    if not project_mode:
        for index, markers in enumerate(
            (
                ("第一层", "需求挖掘层"),
                ("第二层", "技术攻关层"),
                ("第三层", "能力图像与效能贡献层"),
            )
        ):
            if any(marker in normalized for marker in markers):
                return _REPORT_CANONICAL_H2[index]
    if not three_layer_mode:
        for canonical in _PROJECT_REPORT_CANONICAL_H2:
            label = re.sub(r"^[一二三四五]、", "", canonical)
            if label and label in normalized:
                return canonical
    return ""


def _canonical_report_h3(title: str, template_mode: str = "") -> str:
    normalized = re.sub(r"\s+", "", title).strip("：:、.．")
    project_mode = template_mode == "project_argument_v1"
    three_layer_mode = template_mode == "three_layer_nine_item"
    if not three_layer_mode:
        for canonical in _PROJECT_REPORT_CANONICAL_H3:
            if normalized == re.sub(r"\s+", "", canonical):
                return canonical
    if project_mode:
        # Numbered labels such as ``3. 项目画像`` belong to the five-chapter
        # H4 contract.  Mapping them onto ①–⑨ would rewrite the selected
        # project template into the compatibility outline.
        return ""
    for index, marker in enumerate("①②③④⑤⑥⑦⑧⑨"):
        if normalized.startswith(marker):
            return _REPORT_CANONICAL_H3[index]
    numbered = re.match(r"^(?:第)?([1-9一二三四五六七八九])[项、.．:：]?", normalized)
    if numbered:
        raw = numbered.group(1)
        index = int(raw) if raw.isdigit() else _REPORT_ORDINALS.get(raw, 0)
        if 1 <= index <= len(_REPORT_CANONICAL_H3):
            return _REPORT_CANONICAL_H3[index - 1]
    for index, aliases in enumerate(_REPORT_H3_ALIAS_MARKERS):
        if any(alias in normalized for alias in aliases):
            return _REPORT_CANONICAL_H3[index]
    return ""


def _canonical_report_h4(title: str) -> str:
    normalized = re.sub(r"\s+", "", title).replace("）", ")").replace("（", "(")
    normalized = re.sub(r"^([1-4])[）).、．]", r"\1.", normalized)
    for canonical in _PROJECT_REPORT_CANONICAL_H4:
        candidate = re.sub(r"\s+", "", canonical).replace("）", ")").replace("（", "(")
        if normalized == candidate:
            return canonical
    return ""


def _normalize_report_structure_deterministically(
    text: str,
    payload: Mapping[str, Any] | None = None,
) -> str:
    """Normalize report headings without regenerating or rewriting prose.

    Reporter occasionally emits a report title, a source index, duplicate
    canonical headings, or a semantically equivalent heading label.  Those are
    cheap deterministic presentation defects, so normalize/downgrade only the
    heading line and preserve every substantive body line unchanged.
    When ``payload`` carries a selected ``report_template_mode``, only that
    template's heading contract is applied so a five-chapter draft is never
    rewritten into ①–⑨ and a three-layer draft is never rewritten into 五章.
    """

    template_mode = (
        _report_template_mode(payload) if isinstance(payload, Mapping) else ""
    )
    project_mode = template_mode == "project_argument_v1"
    three_layer_mode = template_mode == "three_layer_nine_item"
    text = re.sub(
        r"(?<=[。！？；])(?=#{2,4}\s*(?:[一二三四五]、|（[一二三四]）|[①-⑨]))",
        "\n\n",
        str(text or ""),
    )
    seen_h2: set[str] = set()
    seen_h3: set[str] = set()
    seen_h4: set[str] = set()
    normalized_lines: list[str] = []
    for raw_line in text.splitlines():
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", raw_line)
        if match is None:
            normalized_lines.append(raw_line)
            continue
        level = len(match.group(1))
        title = match.group(2).strip()
        if level == 1:
            # The delivery layer owns the report title.  Handle it before
            # semantic heading aliases: a long topic title may legitimately
            # contain words such as ``能力画像`` and must not be mistaken for
            # the canonical section ``⑦ 装备能力图像``.
            continue
        canonical_h2 = _canonical_report_h2(title, template_mode)
        canonical_h3 = _canonical_report_h3(title, template_mode)
        canonical_h4 = (
            "" if three_layer_mode else _canonical_report_h4(title)
        )
        treat_as_h4 = canonical_h4 and (
            level >= 4 or (project_mode and level >= 3)
        )
        if treat_as_h4:
            parent_h3 = _PROJECT_REPORT_H4_PARENT.get(canonical_h4, "")
            if parent_h3 and parent_h3 not in seen_h3:
                parent_h2 = _PROJECT_REPORT_H3_PARENT[parent_h3]
                if parent_h2 not in seen_h2:
                    seen_h2.add(parent_h2)
                    normalized_lines.append(f"## {parent_h2}")
                seen_h3.add(parent_h3)
                normalized_lines.append(f"### {parent_h3}")
            if canonical_h4 in seen_h4:
                continue
            seen_h4.add(canonical_h4)
            normalized_lines.append(f"#### {canonical_h4}")
            continue
        if canonical_h2 and not (level == 3 and canonical_h3):
            if canonical_h2 in seen_h2:
                continue
            seen_h2.add(canonical_h2)
            normalized_lines.append(f"## {canonical_h2}")
            continue
        if canonical_h3:
            parent_h2 = (
                _PROJECT_REPORT_H3_PARENT.get(canonical_h3, "")
                if not three_layer_mode
                else ""
            )
            if parent_h2 and parent_h2 not in seen_h2:
                # Reporter occasionally emits a complete project chapter body
                # while omitting only its H2 line (for example, the two
                # solution H3 sections appear directly after chapter two).
                # Restore the uniquely implied parent heading without
                # regenerating, moving, or rewriting any substantive prose.
                seen_h2.add(parent_h2)
                normalized_lines.append(f"## {parent_h2}")
            if canonical_h3 in seen_h3:
                continue
            seen_h3.add(canonical_h3)
            normalized_lines.append(f"### {canonical_h3}")
            continue
        # Extra indexes and explanatory subheads remain visible, but no longer
        # compete with the selected machine-readable template contract.
        normalized_lines.append(f"**{title}**")
    return re.sub(r"\n{3,}", "\n\n", "\n".join(normalized_lines)).strip()


def _report_capability_cues(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    def public_cue(item: Mapping[str, Any]) -> dict[str, Any]:
        cleaned: dict[str, Any] = {}
        for key, value in item.items():
            if isinstance(value, str):
                text = _strip_report_internal_markers(value).strip()
                if str(key) == "direction":
                    text = _REPORTER_CANDIDATE_PREFIX_RE.sub("", text).strip()
                cleaned[str(key)] = text
            elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                cleaned[str(key)] = [
                    _strip_report_internal_markers(nested).strip()
                    if isinstance(nested, str)
                    else nested
                    for nested in value
                ]
            else:
                cleaned[str(key)] = value
        return cleaned

    seed = payload.get("synthesis_seed", {})
    if isinstance(seed, Mapping):
        rows = seed.get("capability_cues", [])
        if isinstance(rows, Sequence) and not isinstance(rows, (str, bytes)):
            # The project report is query-led rather than quota-led.  Keep all
            # substantive directions supplied by the handoff; downstream
            # quality checks decide whether a direction is actually useful,
            # instead of silently dropping the tail of a dynamic portfolio.
            public_rows = [
                public_cue(item) for item in rows if isinstance(item, Mapping)
            ]
            if public_rows:
                return public_rows
    handoff = payload.get("research_handoff", {})
    if isinstance(handoff, Mapping):
        rows = handoff.get("capability_cues", [])
        if isinstance(rows, Sequence) and not isinstance(rows, (str, bytes)):
            return [public_cue(item) for item in rows if isinstance(item, Mapping)]
    return []


def _report_capability_cue_is_substantive(item: Mapping[str, Any]) -> bool:
    """Return whether a cue contains enough equipment-specific matter to project.

    The delivery layer must not turn a skeletal ``{"direction": ...}`` record
    into a canned operation flow, metric list, or verification matrix.  A cue is
    considered usable only when it identifies an equipment/technical anchor and
    also states a mission effect, operation/mechanism, problem, or boundary.
    This is a publication-safety check, not a quality score for the upstream
    research handoff.
    """

    direction = str(item.get("direction", "")).strip()
    if not direction:
        return False

    def has_value(*keys: str) -> bool:
        for key in keys:
            value = item.get(key)
            if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                if any(str(entry).strip() for entry in value):
                    return True
            elif str(value or "").strip():
                return True
        return False

    equipment_anchor = has_value(
        "equipment_form",
        "equipment_hint",
        "capability_portrait",
        "public_equipment_baseline",
        "enabling_technologies",
        "scientific_principle",
    )
    mission_anchor = has_value(
        "mission_effect",
        "target_and_direct_effect",
        "unique_operational_role",
        "capability_outcome",
        "problem_statement",
        "capability_gap",
    )
    operation_anchor = has_value(
        "mechanism_hint",
        "mechanism_chain",
        "non_substitutable_difference",
        "winning_mechanism",
        "operational_concept",
        "operational_process",
        "capability_portrait",
        "boundary",
        "coupling_risk",
        "indicator_portrait",
        "development_path",
        "disruptive_relationship",
    )
    # A direction with only a mission/equipment label is still too thin to
    # project.  Require both a mission fact and an operation/boundary fact;
    # the direction itself supplies the equipment identity when the upstream
    # record omits a repeated platform noun.  This keeps partial cards from
    # triggering invented flow, metric or verification prose.
    return mission_anchor and operation_anchor and bool(
        equipment_anchor or direction
    )


def _report_capability_portrait_markdown(item: Mapping[str, Any]) -> str:
    portrait = str(item.get("capability_portrait", "")).strip()
    # Preserve stored S6 portrait content while repairing the historical
    # duplicated relation prefix caused by queries that already began with
    # ``面向``. This is a mechanical wording fix, not a semantic rewrite.
    portrait = re.sub(r"^(概述：面向)(?:面向)+", r"\1", portrait)
    portrait = re.sub(
        r"\s+(?=- (?:装备与技术实现|关键作战流程|形成能力与作战效果|制胜逻辑机理(?:与对抗边界)?|发展与验证路径|决策与考核口径)：)",
        "\n\n",
        portrait,
    )
    return portrait.strip()


def _remove_empty_report_clauses(line: str) -> str:
    """Drop punctuation-normalized clauses that carry no predicate object."""

    parts = re.split(r"(?<=[。！？!?])", str(line))
    kept = []
    for part in parts:
        stripped = part.strip()
        empty_prompt = bool(
            re.fullmatch(
                r".{1,100}(?:包括|如下|分别为|体现为|主要是|在于|取决于|依赖于)[。.]",
                stripped,
            )
        )
        nominal_stub = bool(
            re.fullmatch(r".{1,100}的(?:概念|实现路径|耦合链条)[。.]", stripped)
        )
        dangling_conditional = False
        # ``当前`` is a normal table/header phrase, not a dangling
        # conditional beginning with ``当``.  Require the conditional form
        # to avoid stripping cells such as ``当前结论`` before fragment
        # validation.
        if re.match(r"^(?:若|如果|一旦|当(?!前))", stripped):
            body = stripped.rstrip("。.!！?")
            pieces = re.split(r"[，,；;]", body, maxsplit=1)
            consequence = pieces[1] if len(pieces) > 1 else body[1:]
            dangling_conditional = not any(
                marker in consequence
                for marker in (
                    "则", "就", "会", "将", "应", "需", "可", "可能", "难以",
                    "无法", "导致", "造成", "触发", "退化", "失效", "下降", "上升",
                    "增加", "降低", "转为", "停止", "中止", "返航", "成立",
                )
            )
        if not (empty_prompt or nominal_stub or dangling_conditional):
            kept.append(part)
    return "".join(kept).strip()


def _normalized_report_reuse_text(value: object) -> str:
    """Normalize a report phrase for deterministic verbatim-reuse checks."""

    text = re.sub(r"https?://\S+", "", str(value or ""))
    text = re.sub(r"[*_`>#\[\](){}‘’“”\"']", "", text)
    return re.sub(r"[\s，,。；;：:！？!?、|—-]+", "", text)


def _report_matrix_verification_mechanism(name: str, mechanism: str) -> str:
    """Project a causal mechanism as matrix-specific verification stages."""

    parts = [
        part.strip().strip("。；.!?！？")
        for part in re.split(r"\s*→\s*", str(mechanism or ""))
        if part.strip().strip("。；.!?！？")
    ]
    if len(parts) <= 1:
        return f"{name}验证观察：{parts[0] if parts else mechanism}"
    labels = ("起始条件", "任务动作", "闭环结果")
    return "；".join(
        f"{labels[index] if index < len(labels) else f'后续环节{index + 1}'}检验：{part}"
        for index, part in enumerate(parts)
    )


def _reflow_long_report_paragraphs(
    text: str,
    *,
    target_chars: int = 900,
    hard_chars: int = 1050,
) -> str:
    """Add Markdown paragraph breaks without deleting or rewriting report content."""

    prepared: list[str] = []
    for raw_line in str(text).splitlines():
        stripped = raw_line.strip()
        if (
            stripped
            and prepared
            and prepared[-1].strip().startswith("#")
            and not stripped.startswith("#")
        ):
            prepared.append("")
        if stripped.startswith(("- ", "* ")) and prepared and prepared[-1].strip():
            prepared.append("")
        prepared.append(raw_line)
    normalized = re.sub(r"\n{3,}", "\n\n", "\n".join(prepared)).strip()

    def split_block(block: str) -> list[str]:
        compact = " ".join(block.split()).strip()
        if not compact or compact.startswith(("#", "|", "- ", "* ")):
            return [block.strip()]
        if len(compact) <= hard_chars:
            return [block.strip()]
        sentences = [
            item.strip()
            for item in re.findall(r".+?(?:[。！？!?；;]|$)", compact)
            if item.strip()
        ]
        units: list[str] = []
        for sentence in sentences:
            if len(sentence) <= hard_chars:
                units.append(sentence)
                continue
            clauses = [
                item
                for item in re.findall(r".+?(?:[，,、：:]|$)", sentence)
                if item
            ]
            for clause in clauses:
                if len(clause) <= hard_chars:
                    units.append(clause)
                else:
                    units.extend(
                        clause[index : index + target_chars]
                        for index in range(0, len(clause), target_chars)
                    )
        paragraphs: list[str] = []
        current = ""
        for unit in units:
            if current and len(current) + len(unit) > target_chars:
                paragraphs.append(current.strip())
                current = unit
            else:
                current += unit
        if current.strip():
            paragraphs.append(current.strip())
        return paragraphs or [block.strip()]

    blocks: list[str] = []
    for block in re.split(r"\n\s*\n", normalized):
        blocks.extend(split_block(block))
    return "\n\n".join(item for item in blocks if item.strip())


def _stabilize_report_delivery_contract(
    text: str,
    payload: Mapping[str, Any],
) -> str:
    """Apply evidence-bound publication fixes before the final quality gate.

    This is not a second report synthesis. It projects Reporter-ready fields
    prepared upstream into sections ⑥/⑦ and closes purely mechanical Markdown
    fragments. No new equipment direction, point estimate, source or military
    conclusion is introduced here.
    """

    project_mode = _report_template_mode(payload) == "project_argument_v1"
    capability_start = (
        r"^###\s*（一）装备图像概述\s*$"
        if project_mode
        else r"^###\s*⑦\s*装备能力图像\s*$"
    )
    capability_end = (
        r"^###\s*（二）作战运用模式\s*$"
        if project_mode
        else r"^###\s*⑧\s*效能贡献评估\s*$"
    )
    # Only project cues that carry an equipment anchor and at least one
    # mission/operation/boundary fact.  A direction label by itself is not a
    # license for the delivery layer to invent a flow, metric or test matrix.
    cues = [
        item
        for item in _report_capability_cues(payload)
        if _report_capability_cue_is_substantive(item)
    ]
    cue_by_name = {
        str(item.get("direction", "")).strip(): dict(item)
        for item in cues
        if str(item.get("direction", "")).strip()
    }
    indicator_by_name = {
        str(item.get("direction", "")).strip(): str(
            item.get("indicator_portrait", "")
        ).strip()
        for item in cues
        if str(item.get("direction", "")).strip()
        and str(item.get("indicator_portrait", "")).strip()
    }
    if project_mode and cues:
        flow_pattern = (
            r"(^####\s*1\.\s*作战运用流程\s*$\n)(?P<body>.*?)"
            r"(?=^####\s*2\.\s*链路闭环分析\s*$)"
        )
        closure_pattern = (
            r"(^####\s*2\.\s*链路闭环分析\s*$\n)(?P<body>.*?)"
            r"(?=^###\s*（三）体系贡献率分析\s*$)"
        )

        def cue_text(item: Mapping[str, Any], *keys: str, fallback: str) -> str:
            for key in keys:
                value = item.get(key)
                if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                    joined = "、".join(
                        _clean_reporter_clue_text(row, max_chars=80)
                        for row in value
                        if _clean_reporter_clue_text(row)
                    )
                    if joined:
                        return joined
                cleaned = _clean_reporter_clue_text(value, max_chars=220)
                if cleaned:
                    return cleaned
            return fallback

        flow_rows: list[str] = []
        closure_rows: list[str] = []
        for item in cues:
            name = cue_text(item, "direction", fallback="具体装备")
            scenario = cue_text(
                item,
                "target_scenario",
                "problem_statement",
                "capability_gap",
                fallback="",
            )
            action = cue_text(
                item,
                "operational_process",
                "operational_concept",
                "mechanism_hint",
                fallback="",
            )
            effect = cue_text(
                item,
                "mission_effect",
                "capability_outcome",
                fallback="",
            )
            boundary = cue_text(
                item,
                "boundary",
                "coupling_risk",
                fallback="",
            )
            # These rows are a last-resort repair only when the model left a
            # section empty.  Keep every clause tied to facts actually present
            # in the cue; never fill missing fields with a universal four-chain
            # sentence or a generic engagement sequence.
            if action and (effect or scenario):
                context = f"在{scenario}下，" if scenario else ""
                outcome = f"，直接效果为{effect}" if effect else ""
                flow_rows.append(f"- **{name}**：{context}{action}{outcome}。")
            if boundary or (action and effect):
                mechanism = f"通过{action}形成{effect}" if action and effect else ""
                limit = f"；失效或中止边界为{boundary}" if boundary else ""
                closure_rows.append(
                    f"- **{name}**：{mechanism}{limit}。".replace("：。", "：待补充装备专属闭环边界。")
                )

        visible_instructions = (
            "按任务准备与装订、平台部署与进入、目标发现确认、火力分配、交战毁伤、效果评估和再组织分阶段说明装备使用方式与指标口径",
            "围绕时间链、信息与精度链、火力链、毁伤评估链分析单点短板、级联风险和制胜机理",
        )

        def replace_instruction_body(
            current: str,
            pattern: str,
            rows: list[str],
        ) -> str:
            match = re.search(pattern, current, flags=re.MULTILINE | re.DOTALL)
            if not match:
                return current
            body = match.group("body")
            if not any(instruction in body for instruction in visible_instructions):
                return current
            # Preserve model-authored prose and remove only the visible
            # instruction line.  A cue-driven repair is allowed only when no
            # substantive line remains; this prevents the delivery layer from
            # rewriting a chapter into a repeated template.
            kept_lines: list[str] = []
            for line in body.splitlines():
                stripped_line = line.strip()
                if not stripped_line:
                    kept_lines.append(line)
                    continue
                if any(instruction in stripped_line for instruction in visible_instructions):
                    residual = stripped_line
                    for instruction in visible_instructions:
                        residual = residual.replace(instruction, "").strip(" ：:；;。")
                    if residual:
                        kept_lines.append(residual)
                else:
                    kept_lines.append(line)
            kept_body = "\n".join(kept_lines).strip()
            if kept_body:
                return current[: match.start("body")] + "\n" + kept_body + "\n\n" + current[match.end("body") :]
            replacement = "\n".join(rows).strip() or "本节暂缺足够的装备专属事实，待前置画像补齐后再形成判断。"
            return (
                current[: match.start("body")]
                + "\n"
                + replacement
                + "\n\n"
                + current[match.end("body") :]
            )

        text = replace_instruction_body(str(text or ""), flow_pattern, flow_rows)
        text = replace_instruction_body(text, closure_pattern, closure_rows)
    elif project_mode:
        # Do not leave a model's writing instruction visible when the handoff
        # contains no usable equipment cue.  Equally, do not replace it with
        # a generic "装订—进入—交战" or four-chain sentence: that would look
        # like a researched conclusion without an equipment basis.  Keep a
        # short, auditable placeholder so a limited delivery remains usable
        # and can be completed after the upstream image is available.
        flow_pattern = (
            r"(^####\s*1\.\s*作战运用流程\s*$\n)(?P<body>.*?)"
            r"(?=^####\s*2\.\s*链路闭环分析\s*$)"
        )
        closure_pattern = (
            r"(^####\s*2\.\s*链路闭环分析\s*$\n)(?P<body>.*?)"
            r"(?=^###\s*（三）体系贡献率分析\s*$)"
        )
        visible_instructions = (
            "按任务准备与装订、平台部署与进入、目标发现确认、火力分配、交战毁伤、效果评估和再组织分阶段说明装备使用方式与指标口径",
            "围绕时间链、信息与精度链、火力链、毁伤评估链分析单点短板、级联风险和制胜机理",
        )

        def clear_unbacked_instruction(
            current: str,
            pattern: str,
            note: str,
        ) -> str:
            match = re.search(pattern, current, flags=re.MULTILINE | re.DOTALL)
            if not match or not any(
                instruction in match.group("body")
                for instruction in visible_instructions
            ):
                return current
            return (
                current[: match.start("body")]
                + f"\n{note}\n\n"
                + current[match.end("body") :]
            )

        text = clear_unbacked_instruction(
            str(text or ""),
            flow_pattern,
            "前置研究未提供可核验装备动作，本节不补造统一流程，待具体装备画像到位后补写。",
        )
        text = clear_unbacked_instruction(
            text,
            closure_pattern,
            "前置研究未提供可核验链路断点，本节不推定统一闭环，仅保留待核验边界。",
        )
    lines = str(text or "").splitlines()
    stabilized: list[str] = []
    in_capability_section = False
    for raw_line in lines:
        stripped = raw_line.strip()
        if re.match(capability_start, stripped):
            in_capability_section = True
        elif re.match(capability_end, stripped):
            in_capability_section = False
        if (
            not project_mode
            and in_capability_section
            and stripped.startswith("|")
            and stripped.endswith("|")
        ):
            cells = [cell.strip() for cell in stripped.strip("|").split("|")]
            if len(cells) >= 5 and cells[0] in indicator_by_name:
                generic = (
                    cells[2] in {"待验证", "待证据校准"}
                    or "射程/响应时间/自主等级/成本量级/规模量级" in cells[2]
                )
                if generic:
                    cells[2] = indicator_by_name[cells[0]]
                    raw_line = "| " + " | ".join(cells) + " |"
        stabilized.append(raw_line)

    result = "\n".join(stabilized)
    coupling_rows: list[tuple[str, str]] = []
    for item in cues:
        name = str(item.get("direction", "")).strip()
        risk = str(item.get("coupling_risk", "")).strip()
        if name and risk:
            coupling_rows.append(
                (name, f"- **{name}**：{risk.rstrip('。；')}。")
            )
    # Project-mode chapters are intentionally model-led.  Do not append a
    # repeated per-equipment risk list when the model has already written the
    # technical section; the handoff is evidence for the model, not a form to
    # be projected back into every section.  The legacy three-layer contract
    # retains its historical compatibility projection below.
    if coupling_rows and not project_mode:
        coupling_pattern = (
            r"(^###\s*（一）关键技术清单与攻关途径\s*$\n)(?P<body>.*?)(?=^##\s*五、研制基础\s*$)"
            if project_mode
            else r"(^###\s*⑥\s*技术耦合与短板风险\s*$\n)(?P<body>.*?)(?=^###\s*⑦\s*装备能力图像\s*$)"
        )
        section_match = re.search(
            coupling_pattern,
            result,
            flags=re.MULTILINE | re.DOTALL,
        )
        if section_match:
            body = section_match.group("body").rstrip()
            missing_rows = [row for name, row in coupling_rows if name not in body]
            if missing_rows:
                addition = (
                    "\n\n逐项耦合校核如下（按装备专属风险补充）：\n"
                    + "\n".join(missing_rows)
                    + "\n\n"
                )
                result = result[: section_match.start("body")] + body + addition + result[section_match.end("body") :]

    final_lines = result.splitlines()
    for index, raw_line in enumerate(final_lines):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith(("#", "|")):
            continue
        next_nonempty = next(
            (item.strip() for item in final_lines[index + 1 :] if item.strip()),
            "",
        )
        # A short ``如下。`` lead-in is complete when it introduces a governed
        # list or table.  Preserve it across repeated stabilization passes;
        # otherwise the first pass closes ``如下：`` mechanically and the
        # second pass mistakes the resulting sentence for an empty clause.
        introduces_structured_content = (
            stripped.endswith(("如下。", "如下."))
            and next_nonempty.startswith(("- ", "* ", "|"))
        )
        cleaned_line = (
            raw_line
            if introduces_structured_content
            else _remove_empty_report_clauses(raw_line)
        )
        if cleaned_line != stripped:
            final_lines[index] = cleaned_line
            raw_line = cleaned_line
            stripped = cleaned_line.strip()
            if not stripped:
                continue
        if stripped.startswith(("- ", "* ")):
            if stripped[-1] not in "。！？；.!?" and not re.search(r"https?://\S+$", stripped):
                final_lines[index] = raw_line.rstrip() + "。"
            continue
        if stripped.endswith("："):
            if next_nonempty.startswith(("- ", "* ", "|")):
                final_lines[index] = raw_line.rstrip("：") + "。"
    layout_lines: list[str] = []
    for raw_line in final_lines:
        stripped = raw_line.strip()
        if stripped.startswith("|") and layout_lines:
            previous = layout_lines[-1].strip()
            if previous and not previous.startswith("|"):
                layout_lines.append("")
        layout_lines.append(raw_line)
    result = re.sub(r"\n{3,}", "\n\n", "\n".join(layout_lines)).strip()
    if not project_mode:
        result = re.sub(
            r"(?m)(^|[；：|]\s*)通过条件(?:为)?(?=\s*(?:[。；|]|$))",
            lambda match: (
                match.group(1)
                + "通过条件需在对应试验场景、基线与统计口径下明确"
            ),
            result,
        )

    # Project content is owned by the Reporter.  Only normalize presentation
    # here; malformed headers, missing weapons and blank concept/effect cells
    # remain visible to the report validator so they trigger a focused model
    # rewrite.  Deterministically rebuilding the table from cue fields hid the
    # original authoring failure and turned the delivery layer into a template
    # generator.
    if project_mode:
        return _strip_report_internal_markers(
            _reflow_long_report_paragraphs(
                _normalize_report_structure_deterministically(
                    re.sub(r"\n{3,}", "\n\n", result).strip(),
                    payload,
                )
            )
        )

    # The legacy three-layer contract continues through the deterministic
    # compatibility projection below.

    # Reporter may invent an extra table column (for example, placing
    # ``作战边界`` where the delivery contract expects ``作战运用概念``).
    # Rebuild section ⑦ from the compact S6 handoff so the table has one
    # canonical semantic layout and every operation concept stays attached to
    # the correct weapon direction.
    capability_match = re.search(
        rf"({capability_start}\n)(?P<body>.*?)(?={capability_end})",
        result,
        flags=re.MULTILINE | re.DOTALL,
    )
    # Section ⑦ now uses one governed comparison table. Do not append the
    # historical per-equipment S6 portrait blocks after that table.
    if capability_match and cue_by_name:
        body_lines = capability_match.group("body").splitlines()
        table_indexes = [
            index
            for index, line in enumerate(body_lines)
            if line.strip().startswith("|") and line.strip().endswith("|")
        ]
        canonical_table = (
            [
                "| 装备系统方向 | 装备平台与方案 | 核心技术 | 形成能力 | 作战概念与主要效果 |",
                "|---|---|---|---|---|",
            ]
            if project_mode
            else [
                "| 装备系统方向 | 能力域 | 指标画像 | 作战运用概念 | 谱系位置 |",
                "|---|---|---|---|---|",
            ]
        )
        for name, item in cue_by_name.items():
            capability_domain = str(
                item.get("mission_effect")
                or item.get("capability_gap")
                or item.get("equipment_hint")
                or "直接作战能力"
            ).strip()
            operation = str(
                item.get("mechanism_hint")
                or "按任务边界完成编组、待机、发射、突防与毁伤后再打击"
            ).strip()
            indicator = str(
                item.get("indicator_portrait")
                or "未提供该装备的专属指标画像，待结合任务与证据确定"
            ).strip()
            lineage = str(
                item.get("development_path")
                or item.get("public_equipment_baseline")
                or "新研直接作战装备方向"
            ).strip()
            technologies = item.get("enabling_technologies", [])
            technology_text = (
                "、".join(str(value) for value in technologies[:5])
                if isinstance(technologies, list)
                else str(technologies)
            )
            project_cells = (
                name,
                str(item.get("equipment_hint") or "具体平台、载荷与任务系统方案"),
                technology_text or str(item.get("scientific_principle") or "核心技术待分解"),
                str(item.get("capability_outcome") or capability_domain),
                f"{item.get('operational_concept') or operation}；{item.get('mission_effect') or capability_domain}",
            )
            legacy_cells = (
                name,
                capability_domain,
                indicator,
                operation,
                lineage,
            )
            selected_cells = project_cells if project_mode else legacy_cells
            canonical_table.append(
                "| "
                + " | ".join(
                    (
                        cell.replace("|", "／")
                        if index == 0 or len(cell) <= 215
                        else _clip_complete_report_phrase(
                            cell.replace("|", "／"),
                            215,
                        )
                    )
                    for index, cell in enumerate(selected_cells)
                )
                + " |"
            )
        # The completed report should show the S6 handoff as a compact
        # comparison table. Replace any prose portrait block, including a
        # model-generated table plus trailing detail cards, rather than
        # preserving the large repeated text that motivated this contract.
        body_lines = list(canonical_table)
        # Keep the short legacy lead-in used by downstream readers.  It is a
        # structural cue for the comparison table, not a generated content
        # sentence; dropping it broke the established delivery contract.
        if not project_mode:
            body_lines = ["能力图像如下。", "", *body_lines]
        rebuilt_body = "\n".join(body_lines).strip() + "\n\n"
        result = (
            result[: capability_match.start("body")]
            + rebuilt_body
            + result[capability_match.end("body") :]
        )

    # A comparison table is useful for scanning but cannot replace a complete
    # equipment argument. Append the governed multi-module portrait for
    # every direction so the formal report and capability cards share the same
    # scenario-to-effect causal source.  Rebuild by marker for idempotence.
    capability_match = re.search(
        rf"({capability_start}\n)(?P<body>.*?)(?={capability_end})",
        result,
        flags=re.MULTILINE | re.DOTALL,
    )
    if capability_match and cue_by_name and not project_mode:
        capability_body = capability_match.group("body").rstrip()
        detail_marker = "逐装备详细能力画像如下"
        marker_index = capability_body.find(detail_marker)
        if marker_index >= 0:
            capability_body = capability_body[:marker_index].rstrip()
        # Historical drafts may already contain one or more partially pruned
        # deterministic portrait blocks before the marker (for example, only
        # the bold equipment titles survived a prior hard-limit pass).  The
        # governed portrait appendix is always the tail of section ⑦, so drop
        # the stale tail from its first exact portrait title and rebuild once.
        orphan_indexes = [
            capability_body.find(f"**{name}｜装备能力画像**")
            for name in cue_by_name
        ]
        orphan_indexes = [index for index in orphan_indexes if index >= 0]
        if orphan_indexes:
            capability_body = capability_body[: min(orphan_indexes)].rstrip()
        detail_rows: list[str] = []
        for name, item in cue_by_name.items():
            portrait = _report_capability_portrait_markdown(item)
            if not portrait:
                continue
            detail_rows.extend(
                [
                    f"**{name}｜装备能力画像**",
                    "",
                    portrait,
                ]
            )
        if detail_rows:
            detail_block = (
                f"\n\n{detail_marker}；以下内容用于逐项说明装备形态、作战流程、形成能力、"
                "直接效果、制胜机理与验证边界。\n\n"
                + "\n\n".join(detail_rows)
                + "\n\n"
            )
            result = (
                result[: capability_match.start("body")]
                + capability_body
                + detail_block
                + result[capability_match.end("body") :]
            )

    # Section ⑧ must name every weapon direction. Group-level prose can be
    # insightful but is not auditable enough to prove each capability's chain
    # contribution, disruptive relationship and failure boundary. Project the
    # already-prepared S6 fields into a compact per-direction appendix without
    # asking Reporter to rewrite the report.
    effect_pattern = (
        r"(^###\s*（三）体系贡献率分析\s*$\n)(?P<body>.*?)(?=^###\s*（四）主要战技指标\s*$)"
        if project_mode
        else r"(^###\s*⑧\s*效能贡献评估\s*$\n)(?P<body>.*?)(?=^###\s*⑨\s*发展优先级与近期抓手\s*$)"
    )
    effect_match = re.search(
        effect_pattern,
        result,
        flags=re.MULTILINE | re.DOTALL,
    )
    # Project reports keep sections （三）/（四） model-authored.  The old
    # projection below turned every S6 cue into the same six-clause sentence,
    # overwriting equipment-specific reasoning with a form.  Legacy
    # three-layer reports still need this compatibility appendix.
    if effect_match and cue_by_name and not project_mode:
        effect_body = effect_match.group("body").rstrip()
        appendix_marker = (
            "逐装备体系贡献、制胜机理与失效边界如下"
            if project_mode
            else "逐项效能、创新关系与失效边界如下"
        )
        marker_index = effect_body.find(appendix_marker)
        if marker_index >= 0:
            # The stabilizer can run once for the model draft and again for a
            # fallback/final delivery check. Remove the prior deterministic
            # appendix before rebuilding it so repeated validation is idempotent
            # and cannot inflate a report by several thousand characters.
            effect_body = effect_body[:marker_index].rstrip()
        rows: list[str] = []

        def inline_clause(value: object) -> str:
            """Embed governed facts without copying whole report sentences."""

            return re.sub(
                r"[。！？!?；;]+",
                "，",
                str(value or "").strip(),
            ).strip("， ")

        for name, item in cue_by_name.items():
            chain_type = str(item.get("chain_type", "")).strip() or "强链"
            effect = str(
                item.get("mission_effect")
                or "对杀伤链形成直接压制、毁伤或再打击贡献"
            ).strip()
            mechanism = str(
                item.get("mechanism_hint")
                or "在任务边界内完成编组、突防、交战与毁伤评估"
            ).strip()
            disruptive = str(
                item.get("disruptive_relationship")
                or "从持续联网依赖转向低信息条件下的任务闭环"
            ).strip()
            boundary = str(
                item.get("boundary")
                or "对手采用诱饵、干扰与针对性拦截时收益下降，具体失效边界待代表性对抗试验验证"
            ).strip()
            indicator = _clean_reporter_clue_text(
                item.get("indicator_portrait")
                or "任务成功率、压制窗口、交换比和再打击周期",
                max_chars=180,
            ).rstrip("。；")
            rows.append(
                f"- **{name}**（{chain_type}）：本装备的任务贡献是{inline_clause(effect)}；"
                f"其作战作用路径是{inline_clause(mechanism)}；相对基线改变为"
                f"{inline_clause(disruptive)}；红队判退边界是{inline_clause(boundary)}。"
                f"{name}的量化验证口径采用{inline_clause(indicator)}；"
                "公开证据不足时不承诺未经校准的点值。"
            )
        appendix = (
            f"\n\n{appendix_marker}；证据不足处均作为待验证方向。\n"
            + "\n\n".join(rows)
            + "\n\n"
        )
        result = (
            result[: effect_match.start("body")]
            + effect_body
            + appendix
            + result[effect_match.end("body") :]
        )

    # Keep the expensive xhigh call focused on synthesis. Section ⑨ receives a
    # deterministic, evidence-bound verification matrix assembled only from
    # S6 fields already present in the Reporter handoff. This adds concrete
    # engineering value (project, indicator, coupling, pass/fail boundary)
    # without a second model call or invented parameters. Rebuild by marker so
    # repeated validation stays idempotent.
    priority_pattern = (
        r"(^###\s*（四）主要战技指标\s*$\n)(?P<body>.*?)(?=^##\s*三、总体方案\s*$)"
        if project_mode
        else r"(^###\s*⑨\s*发展优先级与近期抓手\s*$\n)(?P<body>.*)$"
    )
    priority_match = re.search(
        priority_pattern,
        result,
        flags=re.MULTILINE | re.DOTALL,
    )
    # Do not synthesize a universal validation matrix for project reports.
    # Missing project indicators must be repaired by the Reporter from the
    # equipment mechanism, scenario and evidence, rather than filled with the
    # same development/pass/fail boilerplate for every direction.
    if priority_match and cue_by_name and not project_mode:
        priority_body = priority_match.group("body").rstrip()
        matrix_marker = (
            "逐装备主要战技指标与验证矩阵如下"
            if project_mode
            else "逐装备演示验证矩阵如下"
        )
        marker_index = priority_body.find(matrix_marker)
        if marker_index >= 0:
            priority_body = priority_body[:marker_index].rstrip()
        matrix_rows: list[str] = []
        for name, item in cue_by_name.items():
            priority = _clean_reporter_clue_text(
                item.get("priority", "P1/P2待组合评审"), max_chars=32
            )
            development = _clean_reporter_clue_text(
                item.get("development_path")
                or item.get("public_equipment_baseline")
                or "以现有公开装备类别为基线开展样机和任务级联试",
                max_chars=150,
            ).rstrip("。；")
            indicator = _clean_reporter_clue_text(
                item.get("indicator_portrait")
                or "未提供该装备的专属指标画像，待结合任务与证据确定",
                max_chars=180,
            ).rstrip("。；")
            mechanism = _clean_reporter_clue_text(
                item.get("mechanism_hint")
                or "在受扰任务边界内完成目标确认、火力交战和毁伤后续接",
                max_chars=130,
            )
            verification_mechanism = _report_matrix_verification_mechanism(
                name,
                mechanism,
            )
            coupling = _clean_reporter_clue_text(
                item.get("coupling_risk")
                or "目标信息、末制导、载荷效应和任务授权任一失效都会拖垮闭环",
                max_chars=280,
            ).rstrip("。；")
            boundary = _clean_reporter_clue_text(
                item.get("boundary")
                or "在代表性干扰、诱饵和节点损耗条件下未形成直接毁伤或压制贡献",
                max_chars=120,
            ).rstrip("。；")
            failure_boundary = boundary
            if (
                len(_normalized_report_reuse_text(boundary)) >= 30
                and _normalized_report_reuse_text(boundary)
                in _normalized_report_reuse_text(coupling)
            ):
                # Some S6 cards conservatively carry the same future/foresight
                # boundary in both ``coupling_risk`` and ``boundary``.  The
                # matrix already prints the complete coupling statement, so
                # repeating the complete boundary again as the failure clause
                # creates a third verbatim copy once section ⑧ is considered.
                # Keep the decision meaning and equipment binding while
                # referring to the complete statement immediately above.
                failure_boundary = (
                    f"上述{name}适用场景或反适应边界被触发，且直接作战贡献未达到任务基线"
                )
            matrix_rows.append(
                f"- **{name}**（{priority}）：演示项目沿“{development}”启动；"
                f"作战验证要求为{verification_mechanism}；验收指标方向为{indicator}；"
                f"{name}的关键耦合与单点风险为{coupling}。{name}的通过条件是代表性场景中形成可复核的"
                "打击、猎歼、压制、毁伤、拦截或拒止贡献，并保留任务日志和证据链；"
                f"失败条件是{failure_boundary}。{name}的数值阈值由仿真、半实物联试、综合靶场和红队试验校准，"
                "公开证据不足时不得提前承诺点值。"
            )
        matrix = (
            f"\n\n{matrix_marker}；该矩阵属于正文的一部分，只投影已通过S6门禁的方向和边界。\n"
            + "\n\n".join(matrix_rows)
        )
        result = (
            result[: priority_match.start("body")]
            + priority_body
            + matrix
            + (result[priority_match.end("body") :] if project_mode else "")
        )

    return _strip_report_internal_markers(
        _reflow_long_report_paragraphs(
            _normalize_report_structure_deterministically(
                re.sub(r"\n{3,}", "\n\n", result).strip(),
                payload,
            )
        )
    )


def _report_issues_are_deterministic_format_only(
    issues: Sequence[str],
) -> bool:
    format_markers = (
        "报告格式",
        "三级和四级标题共",
        "不得把深度性、军事价值、前瞻性或新颖性写成独立标题",
    )
    rows = [str(item).strip() for item in issues if str(item).strip()]
    return bool(rows) and all(
        any(row.startswith(marker) for marker in format_markers)
        for row in rows
    )


def _project_argument_report_writer_system_prompt(
    payload: Mapping[str, Any],
) -> str:
    target_chars = _report_target_chars(payload)
    # Keep the visible prompt deliberately small.  The model should reason
    # from the equipment-specific handoff and public evidence instead of
    # mechanically expanding a long checklist.  Structural completeness is
    # enforced by the delivery layer, not by repeating prose instructions in
    # every prompt.
    return (
        "你是中国军事装备项目论证报告作者。只输出中文Markdown正文，不输出一级标题、Agent/流程说明、"
        "内部编号、攻击坐标或无来源精确参数。保留既定五章大标题和小标题及其顺序："
        "一、需求分析（需求概述、国内外现状、建设必要性分析）；二、项目画像（装备图像概述、作战运用模式、"
        "体系贡献率分析、主要战技指标）；三、总体方案（总体架构、子系统方案）；四、关键技术（关键技术清单与攻关途径）；"
        "五、研制基础（参与单位、技术基础）。除此之外不要把提示词扩写成模板。"
        "重要提示：以Query语义、query_analysis和前置高价值证据决定研究对象、作战地域、阶段和论证重点。"
        "当语义涉及未来高强度海空作战、强干扰弱通信、低空/海空对抗、精确火力或反无人威胁时，优先把它们"
        "落实为具体敌我对抗窗口、任务链断点和制胜关系；不相关时不硬套。"
        "围绕Query筛选真正相关的新质军事武器装备，优先解释其如何改变作战关系、任务链或制胜机理；"
        "分析维度由模型结合装备性质自主选择，可以比较构型、载荷、感知、交战方式、作战效果、成本规模、"
        "适用条件或失效边界中的部分维度，不要求逐项罗列、统一顺序或机械填满字段，也不得用同一套句子轮换填充。"
        "论证始终面向未来军事制胜和中国现实需求：结合濒海/低空威胁、强对抗条件下的任务续接、现役改进、"
        "工业化补充、试验鉴定和供应链约束判断建设价值；不得脱离Query凭空扩展战区、型号或能力。"
        "总体方案按Query和装备实际需要下钻到相关硬件、软件、接口、数据流或保障环节，未改变任务结果的层级不要硬填；"
        "关键技术和技术基础按对应装备写真实成熟度/现有基础、瓶颈和专属攻关路径，避免把同一技术或单位描述复制到"
        "所有装备；只有Query或证据确有需要时才给装备专属验证口径、转段或工程判退条件，不设置统一的‘验证指标’套话。"
        "总体方案、子系统方案、关键技术和技术基础必须由模型按装备间因果关系重新组织，不得把capability_cues字段逐格翻译为"
        "固定六列表格，不得为每件装备重复同一句输入输出、证据边界、攻关路径或验证方式。若三件以上装备出现同一长句，"
        "视为本章未完成，必须按各装备的作用介质、部署位置、时间窗口、接口依赖和失效机理重写。"
        "研制基础结合中国现实："
        "参与单位聚焦与装备研发大致相关的承研/配套机构类型（总体设计院所、军工集团/主机厂、电子信息与材料企业、试验鉴定机构、高校科研院所等）；"
        "技术基础聚焦已经比较成熟、可支撑新质装备研发的技术与工程能力，按装备写清可继承基础与缺口；"
        "没有公开依据时不虚构具体单位、型号、状态或数值。Query原文和query_analysis优先于handoff字段，handoff只作"
        "高价值事实与证据种子；不得按字段顺序填空。公开事实、分析判断、目标方向和待核验边界要分清，重复内容只写一次。"
        "正文聚焦军事需求场景、装备能力提升、新技术如何进入武器与任务链、新场景如何被装备能力打开；优先使用中文直述，"
        "少用英文缩写和生僻词，首次出现写明中文含义；删除方法论解释、泛化体系口号、同义复述。"
        "引用策略遵循军事相关性优先：正文只保留与具体装备、作战运用或官方试验判断直接相关的来源定位，"
        "按论证需要选择数量，不在每个段落重复链接；其余来源可集中放入文末来源索引，泛化背景、商业宣传和"
        "与任务链无直接关系的链接不进入正文。"
        f"按上述标题完成正文，篇幅仅作容量规划参考（{target_chars}），是最低深度参照，不是字符上限；"
        "最终报告按证据与论证完整度自然收束，可超过或低于该参考值，不得为凑字数扩写或为压缩而删减关键判断。"
        "不设报告硬超时，论证完成后自然收束。"
        "不要因压缩而删除事实、来源、反证、失效边界或关键取舍；绝不得为了压缩而删去具体装备事实、来源映射、反证、验证边界或项目落地建议。"
    )


_REPORT_PROMPT_DIR = Path(__file__).resolve().parents[1] / "prompts"


def _read_report_prompt(filename: str, *, target_chars: str = "") -> str:
    """Load a report template prompt from the repository prompt resources."""
    prompt = (_REPORT_PROMPT_DIR / filename).read_text(encoding="utf-8")
    return prompt.replace("{target_chars}", str(target_chars))


def _project_argument_report_writer_system_prompt(
    payload: Mapping[str, Any],
) -> str:
    return _read_report_prompt(
        "report_project_argument_v1.md",
        target_chars=_report_target_chars(payload),
    )


def _report_writer_system_prompt(payload: Mapping[str, Any]) -> str:
    if _report_template_mode(payload) == "project_argument_v1":
        return _project_argument_report_writer_system_prompt(payload)
    if not str(payload.get("ablation_scope", "")):
        return _read_report_prompt(
            "report_three_layer_nine_item.md",
            target_chars=_report_target_chars(payload),
        )
    branch = _report_branch(payload)
    target_chars = _report_target_chars(payload)
    ablation_scope = str(payload.get("ablation_scope", ""))
    if ablation_scope.startswith("baseline_only"):
        return (
            "你是独立的军事装备研究Reporter。本次是去制胜机理消融，只能整理输入的基线事实、"
            "证据、冲突、限制和未决问题，并正常完成完整的三层九项研究报告。不得执行或伪装重建"
            "S1-S6、L1-L4，也不得用模型常识补出输入未支持的新因果链、装备结论、性能点值、"
            "成熟度或来源；但可对同一批基线事实进行章节组织、对照归纳和证据边界内的保守推导。"
            "research_handoff中的[B01]等标记是允许引用的基线依据；每个三级章节至少应有一个"
            "相关基线标记，连续论证段可在段首或段末集中标注，不能创造新标记。"
            "research_handoff.capability_cues是由多源基线中的武器装备观察、现役升级需求、新研需求、"
            "作战运用和验证边界确定性投影形成的能力画像，不是S6结论。若输入存在这些记录，③至⑨"
            "优先消费与Query直接相关的装备线索，⑦保留有证据且能独立影响决策的具体装备方向，形成"
            "可比较的装备组合判断；不要求每栏或每个字段都出现，能力差异、作战运用概念和谱系位置由模型按因果价值取舍。"
            "不得把表头当正文、不得只输出空表，也不得因移除制胜"
            "机理而删除能力画像。可说明其仍缺制胜机理验证，但不能把‘未执行S1-S6’等同于‘无装备画像’。"
            "URL只能使用public_sources中给出的地址。正文仅保留1至2条与作战任务、具体装备或官方试验直接相关的关键来源定位，"
            "其余来源集中放入文末来源索引；若基线不足，明确写未知或需进一步核验。"
            f"正文以{target_chars}为写作目标；达到目标且九项闭环后立即收尾。"
            "允许自然超过目标字数，绝不因字数超出而压缩、重写、降级或判定失败。"
            "模型不输出一级标题；严格使用三层九项模板：三个二级标题依次为‘## 第一层：需求挖掘层——"
            "场景·战法/技术·装备能力特征’、‘## 第二层：技术攻关层——能力实现途径与核心技术’、"
            "‘## 第三层：能力图像与效能贡献层’；九个三级标题依次为‘### ① 典型作战场景’、"
            "‘### ② 新战法或新概念技术及制胜机理’、‘### ③ 装备能力特征清单’、‘### ④ 能力实现途径’、"
            "‘### ⑤ 核心技术清单与攻关优先级’、‘### ⑥ 技术耦合与短板风险’、‘### ⑦ 装备能力图像’、"
            "‘### ⑧ 效能贡献评估’、‘### ⑨ 发展优先级与近期抓手’。没有直接基线依据的项目必须明确"
            "说明未形成结论，不得为了填满结构而补写。只输出中文Markdown正文。"
        )
    if ablation_scope == "restricted_generic_baseline_evidence_closed":
        return (
            "你是独立的军事装备研究Reporter。本次是去多源专业基线消融：S1-S6和循环结构仍然存在，"
            "但它们的输出只允许建立在受限通用检索证据上。Query只定义范围，不是事实来源；不得使用"
            "模型常识、训练记忆或外部知识补齐缺失的专业场景、装备谱系、成熟度、性能、制胜机理或"
            "效能数据。必须正常完成完整的三层九项报告，正文以"
            f"{target_chars}为目标；证据不足不等于缺章，应在对应章节完整说明已知事实、可做的保守推导、"
            "不能成立的结论、所缺专业证据及验证路径。不得为了满足预设数量、现役升级、新研装备或定量"
            "指标等生产门禁而虚构方向；方向数量和结论强度必须随输入证据真实收缩。所有URL只能使用"
            "public_sources；正文仅保留1至2条与作战任务、具体装备或官方试验直接相关的关键来源定位，"
            "其余来源集中放入文末来源索引。关键判断必须绑定输入证据或明确标为待验证假设。模型不输出一级标题；只用"
            "三个固定二级标题和九个固定三级标题，依次为第一层①场景②战法/机理③能力特征，第二层"
            "④实现途径⑤核心技术⑥耦合短板，第三层⑦能力图像⑧效能贡献⑨优先级与近期抓手。不得新增"
            "平行章节。每项都应说明当前证据能支持什么、不能支持什么，以及补足证据所需的公开资料、"
            "仿真、半实物或试验验证方向。允许自然超过目标字数，绝不因长度压缩、降级或失败。只输出"
            "完整中文Markdown正文，不输出研究流程、自检过程、攻击步骤、坐标或可执行武器参数。"
        )
    branch_delivery_clause = ""
    if branch == "B":
        branch_delivery_clause = (
            "传统能力缺口分支应把需求卡片、能力全景图、推理链回溯和证据链压缩融入三层九项，"
            "不得另设平行章节；因果链至少贯通背景压力、任务链断点、作战效果、具体待发展武器装备、"
            "装备构型与作战/工程边界。装备需求不得以抽象能力域为主对象，应优先落到与Query直接匹配的"
            "无人作战平台、低空无人机、导弹、巡飞弹、精确制导弹药、拦截弹或其他承担歼灭、打击、"
            "压制、毁伤、拒止和威慑任务的战斗装备。"
        )
    return (
        "你是全新、独立的军事装备市场需求研究Reporter；本次没有历史会话。"
        f"围绕输入Query撰写正文，以{target_chars}为写作目标，吸收{branch or '当前'}分支高价值成果。"
        "核心正文达到约9000字且三层九项已经闭环后，完成当前句和当前段便立即结束，不再扩写旁支。"
        "交接字段只作为事实和边界线索，正文由模型按Query重新组织；你不得为追逐字数重复论证。"
        "正文自然超出目标完全允许；最终报告可随论证完整度自然超过核心正文目标；"
        "绝不因为长度而压缩、重写、降级或判定失败。"
        "first_pass_quality_contract是首次成稿的强制提交合同；必须在同一次调用内完成章节预算、"
        "九项覆盖、段落去重和完整句自检，再输出唯一最终正文，不得输出草稿或自检过程。"
        "达到核心目标后优先快速收束结论，不得删去关键技术、耦合风险、效能贡献或证据边界。"
        "建设优先序必须显式使用高/中/低或P0/P1/P2等可比较等级并给出理由；"
        "前瞻判断必须给出3至10年演进窗口、触发条件和不确定性，不得只写笼统的未来趋势。"
        "Query是最高优先级，research_handoff只是前置处理后的少量高价值研判种子，用于发现矛盾、"
        "校验假设和建立事实边界，不是可直接拼接的草稿。以Query发散思考为主：内部至少比较两种解释框架，"
        "从对手、地域、烈度、时间窗、约束、作战阶段、行动—反行动和未来战争演化重建主矛盾；"
        "用反证、失效边界和公开来源收敛，不输出内部发散过程。禁止沿输入字段顺序逐项展开、禁止复制"
        "前置原句、禁止改写成材料综述、禁止把A-H分支产物作为平行可见模板。"
        "研究对象只聚焦与Query有直接因果关系的军事武器装备：先解析任务对象、威胁形态、作战阶段、地域环境和制胜矛盾，"
        "再决定应观察的具体武器类别。无人化、低空、巡飞弹和远程精确打击只有被Query语义明确触发时才可优先；"
        "未触发时不得进入候选组合或报告目录。优先论证相对现役基线具有差异化机体/弹体构型、"
        "制导感知组合、自主交战边界、突防方式、毁伤机理或低成本规模运用方式的前瞻新研武器。"
        "能力画像标题必须是‘差异化任务/机理特征+具体武器装备’，不能用无人机、巡飞弹、反辐射巡飞弹、"
        "远程导弹或精确制导弹药等大类名直接占位；若Query或证据不支持某方向，不得机械套用或虚构新颖性。"
        "当Query或输入能力方向属于无人远程火力打击装备领域时，首次成稿优先检查领域相关性、具体装备主体、"
        "一是领域属性符合性，正文持续围绕无人平台、远程火力、精确毁伤及其对抗边界，通信/C2/保障"
        "作战效果、对手反适应、失效边界和证据状态；通信/C2/保障只作为相关装备的依赖或边界。"
        "不要求固定的效能分类、字段组合或验证指标列；无证据时写待核验或保留类别级，禁止把推断包装为已实现能力。"
        "成本、平台、时间、毁伤效应、体系和博弈可控仅作为内部反事实镜头：只选择与Query任务对象、"
        "作战阶段和证据直接相关的2至3类进行比较，不得展示六维方法论清单，也不得为覆盖维度机械生成"
        "无关方向。其影响应自然融入②制胜机理、③能力特征、④实现途径、⑦装备能力图像和⑨验证抓手。"
        "不要输出一级标题，平台会统一添加报告标题。正文只使用三个固定二级标题且顺序固定："
        "‘## 第一层：需求挖掘层——场景·战法/技术·装备能力特征’、"
        "‘## 第二层：技术攻关层——能力实现途径与核心技术’、"
        "‘## 第三层：能力图像与效能贡献层’。"
        "三个二级标题下必须依次且仅使用九个固定三级标题：‘### ① 典型作战场景’、"
        "‘### ② 新战法或新概念技术及制胜机理’、‘### ③ 装备能力特征清单’、"
        "‘### ④ 能力实现途径’、‘### ⑤ 核心技术清单与攻关优先级’、"
        "‘### ⑥ 技术耦合与短板风险’、‘### ⑦ 装备能力图像’、‘### ⑧ 效能贡献评估’、"
        "‘### ⑨ 发展优先级与近期抓手’。不得改名、增删、重复或另设三级标题，不使用四级及更深标题。"
        "①必须论证对手、地域、烈度、时间窗和约束条件；②必须解释现有范式为何做不到、新战法或新概念"
        "为何能赢；③必须给出关键能力域、定性特征及射程、响应时间、自主等级、成本量级、规模量级等"
        "定量指标方向。④针对每项能力判断属于沿用改进、集成创新或原理突破；⑤分解到具体技术点，标注"
        "成熟度现状、瓶颈和优先级；无可靠TRL时用定性成熟度或‘待验证’，不得编造等级。⑥必须逐项吸收"
        "capability_cues.coupling_risk，明确技术依赖、级联关系和会拖垮整条能力链的单点短板，不能只写"
        "‘联合校核’。⑦必须横向比较全部可独立立项、研制、改装和试验考核且证据闭环的具体"
        "装备系统，并以直接承担侦察打击、突防、歼灭、压制、拦截、毁伤或区域拒止的武器为主体；"
        "具体类别必须服从Query语义简报，只有被触发时才观察无人作战平台、低空武器、远程精确打击导弹/弹药、"
        "巡飞弹规模毁伤或反无人拦截效应器，未触发类别不得为增加多样性或凑齐目录而生成；"
        "其中新研装备必须说明相对公开基线的新颖构型与前瞻触发条件，并直接产生歼灭、毁伤、压制、突防或拒止效果；"
        "伪装、假目标、通信、工程、恢复、评估和保障原则上只作为相关武器的支撑层，是否单列由Query决定。"
        "逐项形成足以影响作战或研制决策的能力差异、边界、相对基线关系和装备谱系位置；可参考"
        "capability_cues中的指标线索，但由模型选择最有解释力的维度，不要求统一字段、行数或占位句。"
        "⑦优先保留research_handoff.capability_cues中证据闭环的具体装备原名；不得另造‘装备包’、保障节点、"
        "C2/任务网络或其他主体装备。必须用Markdown对比表呈现装备能力图像，每行一个具体装备方向，至少包含装备主体、"
        "作战对象与场景、核心能力组成、关键指标方向、作战边界、相对现役基线差异和证据边界；S6能力画像只作为事实底稿，"
        "Reporter必须重新综合为表格，禁止逐项复制、改写或扩写成同结构画像。弱网、通信、保障、能源、补给和任务软件只允许写入对应武器装备的体系依赖、技术耦合"
        "或使用边界。⑧结合Query选择最能说明杀伤链和体系贡献的比较口径，不能虚构精确提升值。⑨给出有依据的优先级、"
        "排序理由和近期工程抓手；是否需要演示、试验、转段或判退条件由装备成熟度和证据边界决定。"
        "军事价值必须具体落到侦察决策、打击歼灭、压制反制、毁伤、拒止威慑、抗毁恢复或持续作战。"
        "装备类别证据充分时给出公开型号或谱系锚点；证据只能支持类别判断时明确写‘公开证据不足，"
        "保留类别级’，不得虚构型号、参数或效能。关键判断区分事实、推断和假设；不确定性、反证、"
        "来源质量与失效边界嵌入相关九项，不另设附加章节。表格只用于高密度能力、技术、耦合、效能或"
        "优先级比较，最多6列、12行；其余使用短段落或项目符号，同一判断只写一次。"
        + branch_delivery_clause
        + "正文仅在确有必要的位置集中嵌入1至2条与作战任务、具体装备或官方试验直接相关的[来源名](URL)，不要在每个段落或每个判断后重复放链接；其余来源统一放入文末来源索引，只用输入来源，不虚构数字或来源；前置卡片、全景图和映射只做交叉归纳，避免复述。"
        "只输出中文Markdown正文，不写研究流程、内部编号、制造参数、攻击步骤、坐标、目标选择流程或可执行武器参数。"
    )


def _report_repair_system_prompt(payload: Mapping[str, Any]) -> str:
    template_label = (
        "项目论证五章合同"
        if _report_template_mode(payload) == "project_argument_v1"
        else "三层九项合同"
    )
    return (
        _report_writer_system_prompt(payload)
        + f"\n本次只做定向修订：根据Query、{template_label}、分支高价值信息、允许来源、原稿和少量修订要点，"
        "只修复缺项、逻辑断裂、映射断点、重复、残段和证据边界；保留有依据的深度判断与有效引用。"
        "不得复述评测或研究流程，不得添加来源外URL、无依据数字、攻击步骤、坐标或可执行武器参数。"
        "只输出修订后的完整中文Markdown正文。"
    )


def _clean_winning_hypothesis_title(value: Any) -> str:
    title = " ".join(str(value or "").split()).strip()
    return re.sub(
        r"^(?:(?:[A-H]\s*[-/]\s*S\d+(?:\s*[-/]\s*\d+)?)|"
        r"(?:S\d+)(?:\s*[-/]\s*)?(?:候选)?(?:一|二|三|四|五|[A-Z])?|"
        r"(?:竞争分支|候选)(?:一|二|三|四|五|[A-Z]|-?\d+)|"
        r"(?:竞争分支)(?=\s*[：:])|"
        r"[A-H](?=\s*[：:]))\s*[：:—–/-]*\s*",
        "",
        title,
        count=1,
        flags=re.IGNORECASE,
    ).strip()


def _winning_portfolio_title(item: WinningHypothesis) -> str:
    """Preserve the S3/S5 Agent name after removing internal metadata."""

    title = _clean_winning_hypothesis_title(item.title)
    return normalize_weapon_candidate_title(title, item.equipment_forms)


def _winning_combat_scene(
    query: object,
    *,
    equipment_form: object,
    changed_variable: object = "",
) -> str:
    """Carry upstream semantics into S6 without a topic keyword router."""

    topic = " ".join(str(query or "").split()).strip()
    equipment = " ".join(str(equipment_form or "").split()).strip()
    variable = " ".join(str(changed_variable or "").split()).strip()
    parts = [item for item in (topic, variable, equipment) if item]
    return "；".join(parts)[:700]


def _winning_primary_equipment_form(
    item: WinningHypothesis,
    *,
    equipment_family: str = "",
) -> str:
    """Preserve the model-selected primary subject without reclassifying it."""

    del equipment_family
    candidate_title = _winning_portfolio_title(item)
    if candidate_title:
        return candidate_title[:120]
    for raw_form in item.equipment_forms:
        form = " ".join(str(raw_form or "").split()).strip()
        form = re.sub(
            r"^(?:单一主装备(?:对象)?|主体装备)(?:为)?\s*[：:]?\s*",
            "",
            form,
        ).strip()
        form = re.split(r"[；。]", form, maxsplit=1)[0].strip()
        if form:
            return form[:120]
    return candidate_title[:120]


def _winning_title_has_concrete_equipment_identity(value: str) -> bool:
    """Whether a producer supplied a structurally usable identity string."""

    text = " ".join(str(value or "").split())
    return bool(1 <= len(text) <= 120)


def _prioritize_equipment_evidence_refs(values: Sequence[Any]) -> list[str]:
    """Keep stable evidence order while placing object-level weapon refs first."""

    rows = list(
        dict.fromkeys(str(value).strip() for value in values if str(value).strip())
    )
    order = {value: index for index, value in enumerate(rows)}
    return sorted(
        rows,
        key=lambda value: (
            not value.startswith("ev-weapon_equipment-"),
            order[value],
        ),
    )


def _is_remote_precision_portfolio_direction(value: Mapping[str, Any]) -> bool:
    classification = str(
        value.get("portfolio_role")
        or value.get("mission_classification")
        or ""
    ).strip()
    return classification == "remote_precision_strike"


def _report_branch(payload: Mapping[str, Any]) -> str:
    candidates = (
        payload.get("branch_deliverables", {}),
        payload.get("branch_writer_brief", {}),
        payload.get("report_context", {}),
    )
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            continue
        value = candidate.get("branch") or candidate.get("primary_branch")
        branch = str(value or "").strip().upper()
        if branch:
            return branch
    return ""


def _report_target_chars(payload: Mapping[str, Any]) -> str:
    # Reporter owns the high-judgement core argument. The deterministic
    # delivery stabilizer projects already-approved S6 fields into the
    # per-equipment verification matrix, so asking an xhigh model to spend its
    # whole 600-second window padding the same facts is both slow and unstable.
    if _report_template_mode(payload) == "project_argument_v1":
        return "高价值军事决策信息优先、通常4500-7500字的精简正文"
    return "信息闭环优先、通常7000-10000字的核心正文"


def _unbounded_quality_report(payload: Mapping[str, Any]) -> bool:
    return str(payload.get("execution_profile_id", "")).strip() in {
        "swarm_quality_v1",
        "winning_swarm_dynamic_v2",
    }


def _report_hard_max_chars(payload: Mapping[str, Any]) -> int:
    # Quality profiles append governed capability portraits, comparison
    # matrices and coupling rows after Reporter synthesis. A 12k post-assembly
    # ceiling destroyed complete prose, portrait bullets and table cells.
    # These profiles therefore have no character hard gate; model token/time
    # limits and structural quality checks remain the delivery controls.
    if _unbounded_quality_report(payload):
        return 0
    brief = payload.get("branch_writer_brief", {})
    if isinstance(brief, Mapping):
        try:
            value = int(brief.get("hard_max_chars", 0))
        except (TypeError, ValueError):
            value = 0
        if value <= 0:
            return 0
        return max(3000, value)
    return 0


def _clip_complete_report_phrase(text: str, maximum: int) -> str:
    value = str(text).strip()
    if len(value) <= maximum:
        return value
    if maximum <= 1:
        return "。"
    window = value[: max(1, maximum - 1)]
    # A comma or colon is not a complete semantic boundary. Converting one to
    # a full stop manufactured report fragments such as ``一旦触发，后方平台
    # 在链路受阻时。``. Only shorten at a sentence/independent-clause end;
    # otherwise look beyond the editorial target or preserve the full judgment.
    boundary = max(
        window.rfind(mark) for mark in ("。", "！", "？", "!", "?", "；")
    )
    if boundary >= max(24, maximum // 3):
        window = window[: boundary + 1]
    else:
        # Look slightly beyond the editorial target for a real clause ending.
        # If there is none, keep the full judgment rather than manufacturing a
        # semantically broken fragment merely to satisfy a prompt-size hint.
        extended = value[: min(len(value), maximum + 80)]
        following = [
            extended.find(mark, maximum - 1)
            for mark in ("。", "！", "？", "!", "?", "；")
        ]
        following = [index for index in following if index >= 0]
        if following:
            window = extended[: min(following) + 1]
        else:
            return value
    if window.rstrip().endswith(("，", "、", "；", "：", ",", ";", ":")):
        window = window.rstrip("，、；：,;: ") + "。"
    return window


def _compact_report_table_row(line: str, maximum: int) -> str:
    stripped = line.strip()
    if not (stripped.startswith("|") and stripped.endswith("|")):
        return line
    cells = [item.strip() for item in stripped[1:-1].split("|")]
    if not cells or all(re.fullmatch(r":?-{3,}:?", item) for item in cells):
        return line
    cells = [re.sub(r"(?:\.{3,}|…+)$", "。", item) for item in cells]
    if len(line) <= maximum or len(cells) == 1:
        return "| " + " | ".join(cells) + " |"
    first = cells[0]
    remaining = max(32, maximum - len(first) - (3 * len(cells)) - 2)
    per_cell = max(32, remaining // max(1, len(cells) - 1))
    compacted = [first, *(
        _clip_complete_report_phrase(item, per_cell) for item in cells[1:]
    )]
    return "| " + " | ".join(compacted) + " |"


def _normalize_report_line_ending(line: str) -> str:
    stripped = line.rstrip()
    compact = stripped.strip()
    if (
        not compact
        or compact.startswith("#")
        or (compact.startswith("|") and compact.endswith("|"))
        or compact.startswith("```")
    ):
        return stripped
    if re.search(r"(?:，|；|：|、|,|;|:|\.{3,}|…+)$", compact):
        return re.sub(r"(?:，|；|：|、|,|;|:|\.{3,}|…+)$", "。", stripped)
    return stripped


def _enforce_report_hard_max(
    report: str,
    payload: Mapping[str, Any],
) -> str:
    """Bound report length while preserving headings and equipment names."""

    def portrait_line_protection(current_lines: Sequence[str]) -> list[bool]:
        protected: list[bool] = []
        in_portraits = False
        end_pattern = (
            r"^###\s*（二）作战运用模式\s*$"
            if _report_template_mode(payload) == "project_argument_v1"
            else r"^###\s*⑧\s*效能贡献评估\s*$"
        )
        for current in current_lines:
            stripped = current.strip()
            if "逐装备详细能力画像如下" in stripped:
                in_portraits = True
            if in_portraits and re.match(end_pattern, stripped):
                in_portraits = False
            protected.append(in_portraits)
        return protected

    hard_max = _report_hard_max_chars(payload)
    synthesis_seed = payload.get("synthesis_seed", {})
    capability_cues = (
        synthesis_seed.get("capability_cues", [])
        if isinstance(synthesis_seed, Mapping)
        else []
    )
    protected_bullet_names = {
        str(item.get("direction", "")).strip()
        for item in capability_cues
        if isinstance(item, Mapping) and str(item.get("direction", "")).strip()
    }

    def has_protected_equipment_label(line: str) -> bool:
        stripped = line.strip()
        return any(
            stripped.startswith((f"- **{name}**", f"**{name}｜"))
            for name in protected_bullet_names
        )

    text = "\n".join(
        _normalize_report_line_ending(line)
        for line in str(report).strip().splitlines()
    ).strip()
    if hard_max <= 0 or len(text) <= hard_max:
        return text

    lines = text.splitlines()
    table_cap = 640
    prose_cap = 520
    for _ in range(6):
        compacted: list[str] = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("#") or not stripped:
                compacted.append(line.rstrip())
            elif stripped.startswith("|") and stripped.endswith("|"):
                compacted.append(_compact_report_table_row(line, table_cap))
            elif len(line) > prose_cap:
                prefix = "- " if stripped.startswith("- ") else ""
                body = stripped[2:] if prefix else stripped
                compacted.append(
                    prefix + _clip_complete_report_phrase(body, prose_cap - len(prefix))
                )
            else:
                compacted.append(
                    re.sub(r"(?:\.{3,}|…+)$", "。", line.rstrip())
                )
        text = "\n".join(compacted).strip()
        if len(text) <= hard_max:
            return text
        lines = compacted
        table_cap = max(360, table_cap - 60)
        prose_cap = max(220, prose_cap - 60)

    # The remaining excess is normally a long source index. Remove only its
    # tail entries; canonical headings and capability-table rows stay intact.
    while len(text) > hard_max:
        removable = next(
            (
                index
                for index in range(len(lines) - 1, -1, -1)
                if lines[index].lstrip().startswith("- http")
                or lines[index].lstrip().startswith("- [")
            ),
            None,
        )
        if removable is None:
            break
        lines.pop(removable)
        text = "\n".join(lines).strip()
    if len(text) <= hard_max:
        return text

    portrait_protected = portrait_line_protection(lines)
    section = ""
    line_sections: list[str] = []
    bullet_counts: dict[str, int] = {}
    for line in lines:
        if line.startswith("### "):
            section = line
        line_sections.append(section)
        if line.lstrip().startswith("- "):
            bullet_counts[section] = bullet_counts.get(section, 0) + 1
    for index in range(len(lines) - 1, -1, -1):
        if len(text) <= hard_max:
            break
        section = line_sections[index]
        if (
            lines[index].lstrip().startswith("- ")
            and bullet_counts.get(section, 0) > 1
            and not portrait_protected[index]
            and not has_protected_equipment_label(lines[index])
        ):
            lines.pop(index)
            line_sections.pop(index)
            portrait_protected.pop(index)
            bullet_counts[section] -= 1
            text = "\n".join(lines).strip()
    if len(text) <= hard_max:
        return text

    # Last-resort deterministic convergence for reports dominated by many
    # short paragraphs rather than a few long rows.  Prefer shortening the
    # longest non-heading line and keep sentence punctuation; headings and the
    # first-cell equipment names in tables remain intact.
    unshrinkable_indexes: set[int] = set()
    for _ in range(max(1, len(lines) * 6)):
        if len(text) <= hard_max:
            return text
        candidates = [
            (len(line), index)
            for index, line in enumerate(lines)
            if line.strip()
            and not line.lstrip().startswith("#")
            and not portrait_protected[index]
            and not has_protected_equipment_label(line)
            and index not in unshrinkable_indexes
            and len(line) > 36
        ]
        if not candidates:
            break
        _, index = max(candidates)
        line = lines[index]
        excess = len(text) - hard_max
        target = max(36, len(line) - max(12, min(excess + 1, len(line) // 3)))
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            replacement = _compact_report_table_row(line, target)
        else:
            prefix = "- " if stripped.startswith("- ") else ""
            body = stripped[2:] if prefix else stripped
            replacement = prefix + _clip_complete_report_phrase(
                body,
                max(1, target - len(prefix)),
            )
        if len(replacement) >= len(line):
            if stripped.startswith("|") and stripped.endswith("|"):
                # Never raw-slice Markdown tables: doing so can remove the
                # closing pipe and manufacture both an invalid table and a
                # false prose fragment. Move on to another compressible line.
                unshrinkable_indexes.add(index)
                continue
            replacement = line[: max(1, target - 1)].rstrip("，、；：,. ") + "。"
        lines[index] = replacement
        text = "\n".join(lines).strip()

    # Headings alone are far below the contract ceiling.  If an unusual input
    # still exceeds it, remove only complete non-heading lines from the tail so
    # the persisted Markdown never contains a truncated fragment.
    for index in range(len(lines) - 1, -1, -1):
        if len(text) <= hard_max:
            break
        if (
            lines[index].strip()
            and not lines[index].lstrip().startswith("#")
            and not portrait_protected[index]
            and not (
                lines[index].strip().startswith("|")
                and lines[index].strip().endswith("|")
            )
            and not has_protected_equipment_label(lines[index])
        ):
            lines.pop(index)
            portrait_protected.pop(index)
            text = "\n".join(lines).strip()
    return text


def _report_writer_max_chars(payload: Mapping[str, Any]) -> int:
    hard_max = _report_hard_max_chars(payload)
    values = [
        int(value)
        for value in re.findall(r"\d+", _report_target_chars(payload))
    ]
    if not values:
        return hard_max
    if hard_max <= 0:
        return max(values)
    # Keep the editorial target visible, but give the first-pass writer enough
    # room to satisfy dense branch contracts without crossing the hard gate.
    # The prompt separately states the target range and absolute ceiling.
    return min(hard_max, max(max(values), int(hard_max * 0.9)))


def _reporter_output_token_budget(
    payload: Mapping[str, Any],
    *,
    default: int,
) -> int:
    # This is a model-output capacity ceiling, not a requested report length or
    # a character compressor. Keeping the 12k token capacity prevents dense
    # reports from being truncated; quality profiles have no final character
    # hard gate and must never delete evidence or argument merely to fit it.
    return max(1200, int(default))


_REPORTER_HANDOFF_REWRITE_BOUNDARY = "〔改写断点：保留事实但不得照录〕"
_REPORTER_CANDIDATE_PREFIX_RE = re.compile(r"^[A-Ha-h]\s*[.．、:：]\s*")
_REPORTER_VISIBLE_CANDIDATE_PREFIX_RE = re.compile(
    r"(?m)(^|\|\s*|\*\*)[A-Ha-h]\s*[.．、:：]\s*(?=[^\s|*])"
)


def _strip_report_internal_markers(value: object) -> str:
    """Remove handoff-only markers and candidate labels from public prose."""

    text = str(value or "").replace(_REPORTER_HANDOFF_REWRITE_BOUNDARY, "")
    return _REPORTER_VISIBLE_CANDIDATE_PREFIX_RE.sub(
        lambda match: match.group(1),
        text,
    )


def _clean_reporter_clue_text(value: object, *, max_chars: int | None = None) -> str:
    # Handoff fields such as ``operational_process`` and ``verification_plan``
    # are intentionally lists.  Stringifying a list leaks Python repr syntax
    # (``['…', '…']``) into the report and also encourages the caller to wrap
    # every item in the same sentence.  Flatten only at the final text boundary
    # and preserve the authored item order.
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        value = "；".join(
            str(item).strip()
            for item in value
            if str(item).strip()
        )
    text = " ".join(_strip_report_internal_markers(value).split())
    replacements = (
        (r"S1\s*[–—-]\s*S6", "六阶段制胜分析"),
        (r"(?<![A-Za-z0-9])S-?[1-6](?![A-Za-z0-9])", "对应分析阶段"),
        (r"L1\s*[–—-]\s*L4", "分级复核"),
        (r"(?<![A-Za-z0-9])L-?[1-4](?![A-Za-z0-9])", "分级复核"),
        (r"(?<![A-Za-z0-9])Agent(?![A-Za-z0-9])", "专业研判"),
        (r"(?<![A-Za-z0-9])Codex(?![A-Za-z0-9])", "模型综合"),
        (
            r"(?<![A-Za-z0-9])(?:Packet|ClaimBundle|Claim)(?![A-Za-z0-9])",
            "研究结论",
        ),
        (r"(?<![A-Za-z0-9_])(?:ev|packet|cap)-[A-Za-z0-9][A-Za-z0-9._:-]*", "相关公开证据"),
    )
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    text = re.sub(r"(?:相关公开证据[、，;；\s]*){2,}", "相关公开证据组", text)
    return (
        _clip_complete_report_phrase(text, max_chars)
        if max_chars is not None and len(text) > max_chars
        else text
    )


def _mark_reporter_handoff_rewrite_boundaries(value: Any) -> Any:
    """Break long prose spans without deleting any Reporter handoff content.

    Governed S6 portrait fields stay intact: inserting rewrite markers every
    ~56 characters shredded the five 400-character columns and forced the
    parallel Reporter to rewrite thin summaries instead of synthesizing the
    already-reviewed portrait.
    """

    preserve_keys = {
        "capability_portrait",
        "capability_portrait_modules",
        "system_contribution_thesis",
        "indicator_portrait",
        "operational_concept",
        "concise_winning_summary",
        "winning_mechanism",
        "adversary_adaptation",
        "failure_boundary",
        "portrait_module_character_counts",
    }
    if isinstance(value, Mapping):
        marked: dict[Any, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if key_text == "direction" and isinstance(item, str):
                marked[key] = _REPORTER_CANDIDATE_PREFIX_RE.sub("", item).strip()
            elif key_text in preserve_keys:
                marked[key] = item
            else:
                marked[key] = _mark_reporter_handoff_rewrite_boundaries(item)
        return marked
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_mark_reporter_handoff_rewrite_boundaries(item) for item in value]
    if not isinstance(value, str) or len(value) <= 56:
        return value
    chunks: list[str] = []
    remaining = value
    while len(remaining) > 56:
        window = remaining[:56]
        boundary = max(window.rfind(mark) for mark in "。！？；：，、") + 1
        if boundary < 28:
            boundary = 48
        chunks.append(remaining[:boundary])
        remaining = remaining[boundary:]
    if remaining:
        chunks.append(remaining)
    return _REPORTER_HANDOFF_REWRITE_BOUNDARY.join(chunks)


def _sanitize_reporter_output(text: str) -> str:
    result = _strip_report_internal_markers(text).strip()
    fenced = re.fullmatch(
        r"```(?:markdown|md)?\s*\n(?P<body>.*)\n```",
        result,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if fenced:
        result = fenced.group("body").strip()
    # S6 portraits are often copied into a report table or a prose paragraph.
    # Some providers occasionally drop the newline before a governed module
    # label (for example ``回收点 装备与技术实现：``), which makes the following
    # module look like a dangling fragment and causes the format gate to fail.
    # Restore only the five unambiguous ``label:`` boundaries; this does not
    # rewrite the authored prose or invent any content.
    portrait_labels = (
        "装备与技术实现",
        "关键作战流程",
        "形成能力与作战效果",
        "制胜逻辑机理与对抗边界",
        "制胜逻辑机理",
    )
    portrait_label_pattern = "|".join(re.escape(label) for label in portrait_labels)
    result = re.sub(
        rf"(?<!^)(?<!\n)(?=(?:-\s*)?(?:{portrait_label_pattern})\s*[：:])",
        "\n",
        result,
        flags=re.MULTILINE,
    )
    result = re.sub(
        r"^(?:以下(?:为|是)|现提交|报告正文如下|根据(?:上述|输入))[^\n]*\n+",
        "",
        result,
    )
    replacements = (
        (r"S1\s*[–—-]\s*S6", "六阶段制胜分析"),
        (r"(?<![A-Za-z0-9])S-?[1-6](?![A-Za-z0-9])", "对应分析阶段"),
        (r"L1\s*[–—-]\s*L4", "分级复核"),
        (r"(?<![A-Za-z0-9])L-?[1-4](?![A-Za-z0-9])", "分级复核"),
        (r"(?<![A-Za-z0-9])Agent(?![A-Za-z0-9])", "专业研判"),
        (r"(?<![A-Za-z0-9])Codex(?![A-Za-z0-9])", "模型综合"),
        (
            r"(?<![A-Za-z0-9])(?:Packet|ClaimBundle|Claim)(?![A-Za-z0-9])",
            "研究结论",
        ),
        (
            r"(?<![A-Za-z0-9_])(?:ev|packet|cap)-[A-Za-z0-9][A-Za-z0-9._:-]*",
            "相关公开证据",
        ),
    )
    for pattern, replacement in replacements:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    # Lock the public capability-image table contract in code.  The model may
    # occasionally emit an English schema key such as ``direction`` even when
    # all row values are correct; that mechanical variation must never trigger
    # a Reporter repair or fail the exact-direction gate.
    result = re.sub(
        r"^\|\s*(?:direction|equipment\s+direction|weapon\s+direction)\s*\|",
        "| 装备系统方向 |",
        result,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    result = re.sub(
        r"^(#{1,6})\s*([^#\s].*)$",
        lambda match: match.group(1) + " " + match.group(2).strip(),
        result,
        flags=re.MULTILINE,
    )
    result = re.sub(r"[ \t]+$", "", result, flags=re.MULTILINE)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


_REPORT_ORDINALS: dict[str, int] = {
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


def _normalize_branch_report_labels(
    text: str,
    payload: Mapping[str, Any],
) -> str:
    """Normalize branch-required item titles without rewriting report prose.

    Reporter may satisfy a branch contract semantically while choosing natural
    Chinese headings such as ``规律一`` or ``场景（一）``.  The delivery gate
    intentionally requires stable machine-readable labels, but a label-only
    mismatch must not trigger another full model pass.  Keep this transform
    deliberately narrow: it only edits title-like lines and never creates,
    removes, reorders, or expands substantive content.
    """

    brief = payload.get("branch_writer_brief", {})
    if not isinstance(brief, Mapping):
        return text
    branch = str(brief.get("branch", "")).strip().upper()
    if branch != "C":
        return text

    groups = (
        (
            "核心规律",
            (
                "核心案例规律",
                "跨案例规律",
                "案例规律",
                "核心规律",
                "规律",
            ),
            6,
        ),
        (
            "高置信场景",
            (
                "高置信未来场景",
                "未来高置信场景",
                "高置信场景",
                "未来场景",
                "场景",
            ),
            3,
        ),
        (
            "新兴装备类别",
            (
                "新兴装备类别",
                "新兴装备方向",
                "新兴装备",
                "装备类别",
                "装备方向",
            ),
            4,
        ),
    )
    result = text
    for canonical, aliases, count in groups:
        result = _normalize_numbered_report_title_group(
            result,
            canonical=canonical,
            aliases=aliases,
            count=count,
        )
    return result


def _normalize_numbered_report_title_group(
    text: str,
    *,
    canonical: str,
    aliases: Sequence[str],
    count: int,
) -> str:
    alias_pattern = "|".join(
        re.escape(item) for item in sorted(set(aliases), key=len, reverse=True)
    )
    ordinal_pattern = r"(?:0*[1-9]\d*|[一二三四五六七八九十])"
    label_first = re.compile(
        rf"(?P<label>{alias_pattern})\s*(?:第\s*)?[（(]?"
        rf"(?P<ordinal>{ordinal_pattern})[）)]?"
    )
    ordinal_first = re.compile(
        rf"(?:第\s*)?[（(]?(?P<ordinal>{ordinal_pattern})[）)]?"
        rf"\s*(?:条|项|类|种)?\s*(?P<label>{alias_pattern})"
    )

    def ordinal_value(value: str) -> int | None:
        cleaned = value.strip().lstrip("0") or "0"
        if cleaned.isdigit():
            return int(cleaned)
        return _REPORT_ORDINALS.get(cleaned)

    normalized_lines: list[str] = []
    for line in text.splitlines():
        # Search only the title-sized leading fragment. This accepts Markdown
        # headings/list items and plain title lines while leaving prose alone.
        leading = line[:120]
        match = label_first.search(leading) or ordinal_first.search(leading)
        if match is None:
            normalized_lines.append(line)
            continue
        prefix = leading[: match.start()]
        if prefix.strip(" #*-+0123456789.、)（(\t_"):
            normalized_lines.append(line)
            continue
        number = ordinal_value(match.group("ordinal"))
        if number is None or not 1 <= number <= count:
            normalized_lines.append(line)
            continue
        normalized_lines.append(
            line[: match.start()] + f"{canonical}{number}" + line[match.end() :]
        )
    return "\n".join(normalized_lines)


def _reporter_generation_payload(
    payload: Mapping[str, Any],
    reporter_agent: AgentDef | None = None,
) -> dict[str, Any]:
    """Build a bounded, structured handoff for a fresh Reporter process."""

    branch = _report_branch(payload)
    raw_query_brief = payload.get("structured_query_brief", {})
    if not isinstance(raw_query_brief, Mapping):
        blueprint = payload.get("discovery_blueprint", {})
        raw_query_brief = (
            blueprint.get("structured_query_brief", {})
            if isinstance(blueprint, Mapping)
            else {}
        )

    def compact_query_analysis(value: Mapping[str, Any]) -> dict[str, Any]:
        """Pass the semantic query frame without turning it into a form."""

        list_fields = (
            "enemy_target_profile",
            "battle_phase_and_constraints",
            "required_direct_military_effects",
            "weapon_design_variables",
            "query_specific_weapon_architectures",
            "rejected_template_anchors",
        )
        result: dict[str, Any] = {}
        for key in (
            "core_query",
            "combat_problem_frame",
            "equipment_semantic_boundary",
            "supplement_summary",
        ):
            cleaned = _clean_reporter_clue_text(value.get(key, ""), max_chars=700)
            if cleaned:
                result[key] = cleaned
        propositions = value.get("winning_problem_propositions", [])
        if isinstance(propositions, Sequence) and not isinstance(propositions, (str, bytes)):
            compact_props = []
            for item in propositions[:4]:
                if not isinstance(item, Mapping):
                    continue
                row = {
                    key: _clean_reporter_clue_text(item.get(key, ""), max_chars=260)
                    for key in (
                        "target_and_phase",
                        "task_breakpoint",
                        "changeable_variable",
                        "direct_military_result",
                        "exclusion_and_falsification_boundary",
                    )
                    if _clean_reporter_clue_text(item.get(key, ""))
                }
                if row:
                    compact_props.append(row)
            if compact_props:
                result["winning_problem_propositions"] = compact_props
        for key in list_fields:
            value_rows = value.get(key, [])
            if isinstance(value_rows, Sequence) and not isinstance(value_rows, (str, bytes)):
                rows = [
                    _clean_reporter_clue_text(item, max_chars=220)
                    for item in value_rows[:6]
                    if _clean_reporter_clue_text(item)
                ]
                if rows:
                    result[key] = rows
        for key in ("focus_questions", "constraints_and_assumptions"):
            value_rows = value.get(key, [])
            if isinstance(value_rows, Sequence) and not isinstance(value_rows, (str, bytes)):
                rows = [
                    _clean_reporter_clue_text(item, max_chars=220)
                    for item in value_rows[:6]
                    if _clean_reporter_clue_text(item)
                ]
                if rows:
                    result[key] = rows
        return result

    query_analysis = compact_query_analysis(raw_query_brief)
    project_mode = _report_template_mode(payload) == "project_argument_v1"
    brief = payload.get("branch_writer_brief", {})
    required_sections = []
    mandatory_content = []
    # The legacy branch brief contains production quotas (for example a fixed
    # number of cards, indicators, or parallel sections).  Those are useful to
    # the three-layer compatibility contract, but they are actively harmful in
    # the project report: the five-chapter headings are the only structural
    # contract and the model must choose equipment-specific depth from Query,
    # query_analysis, and the high-value handoff.  Do not leak quota language
    # into the project Reporter payload where it can revive mechanical filling.
    if isinstance(brief, Mapping) and not project_mode:
        required_sections = [
            str(item).strip()[:120]
            for item in brief.get("required_sections", [])[:12]
            if str(item).strip()
        ]
        mandatory_content = [
            str(item).strip()[:160]
            for item in brief.get("mandatory_content", [])[:12]
            if str(item).strip()
        ]

    seed = payload.get("synthesis_seed", {})
    research_handoff: dict[str, Any] = {}
    quality_profile = str(payload.get("execution_profile_id", "")) in {
        "swarm_quality_v1",
        "winning_swarm_dynamic_v2",
    }
    if isinstance(seed, Mapping):
        list_limits = (
            {
                "decisive_anchors": (4, 180),
                "mission_chain_breaks": (4, 180),
                "counterevidence_and_limits": (3, 170),
                "priority_signals": (4, 160),
            }
            if quality_profile
            else {
                "decisive_anchors": (2, 150),
                "mission_chain_breaks": (2, 150),
                "counterevidence_and_limits": (1, 140),
                "priority_signals": (1, 130),
            }
        )
        for key, (limit, max_chars) in list_limits.items():
            values = seed.get(key, [])
            if isinstance(values, Sequence) and not isinstance(values, (str, bytes)):
                research_handoff[key] = [
                    _clean_reporter_clue_text(item, max_chars=max_chars)
                    for item in values[:limit]
                    if _clean_reporter_clue_text(item)
                ]
        capability_cues = seed.get("capability_cues", [])
        if isinstance(capability_cues, Sequence) and not isinstance(
            capability_cues, (str, bytes)
        ):
            compact_cues = []
            for item in _limit_report_capability_cues(capability_cues):
                if not isinstance(item, Mapping):
                    continue
                cue_field_limits = [
                    ("direction", 80),
                    ("equipment_form", 100),
                    ("unique_operational_role", 180),
                    ("launch_or_release_domain", 120),
                    ("target_and_direct_effect", 220),
                    ("mechanism_chain", None),
                    ("non_substitutable_difference", 200),
                    ("mission_effect", 130),
                    ("capability_gap", 110),
                    ("mechanism_hint", 120),
                    ("target_scenario", 140),
                    ("problem_statement", 140),
                    ("scientific_principle", 120),
                    ("operational_concept", 150),
                    ("capability_outcome", 120),
                    ("winning_mechanism", 150),
                    ("system_contribution_thesis", 260),
                    ("equipment_hint", 100),
                    ("baseline_system", 130),
                    ("public_equipment_baseline", 110),
                    ("future_trigger", 100),
                    ("disruptive_relationship", 120),
                    ("development_path", 110),
                    ("indicator_portrait", 220),
                    ("validation_plan", 220),
                    ("coupling_risk", 220),
                    ("system_interfaces", 180),
                    ("adversary_adaptation", 180),
                    ("failure_boundary", 200),
                    ("foresight_evidence_status", 120),
                    ("evidence_boundary", 180),
                    ("participant_units", 180),
                    ("responsible_organization", 160),
                    ("domestic_organizations", 180),
                    ("organization", 140),
                    ("developer", 140),
                    ("priority", 24),
                    ("boundary", 100),
                ]
                # The S6 portrait is the authoritative, already-reviewed
                # artifact.  Pass it through in every execution profile so
                # Reporter cannot silently author a second, divergent image.
                cue_field_limits.append(("capability_portrait", None))
                compact_cues.append(
                    {
                        key: _clean_reporter_clue_text(
                            item.get(key, ""),
                            max_chars=max_chars,
                        )
                        for key, max_chars in cue_field_limits
                        if _clean_reporter_clue_text(item.get(key, ""))
                    }
                )
                compact_cues[-1]["enabling_technologies"] = [
                    _clean_reporter_clue_text(value, max_chars=80)
                    for value in item.get("enabling_technologies", [])[:5]
                    if _clean_reporter_clue_text(value)
                ]
                compact_cues[-1]["operational_process"] = [
                    _clean_reporter_clue_text(value, max_chars=100)
                    for value in item.get("operational_process", [])[:6]
                    if _clean_reporter_clue_text(value)
                ]
                compact_cues[-1]["mechanism_chain"] = [
                    _clean_reporter_clue_text(value, max_chars=110)
                    for value in item.get("mechanism_chain", [])[:6]
                    if _clean_reporter_clue_text(value)
                ]
            research_handoff["capability_cues"] = compact_cues
        comparative_status = seed.get("comparative_status", {})
        if isinstance(comparative_status, Mapping):
            research_handoff["comparative_status"] = _compact_prompt_value(
                comparative_status,
                max_string_chars=220,
                max_list_items=8 if quality_profile else 5,
            )
    research_handoff = _mark_reporter_handoff_rewrite_boundaries(
        research_handoff
    )

    # The parallel Reporter needs one immutable, report-level decision spine.
    # Without it, every chapter re-interprets the same handoff independently;
    # that creates cross-chapter fact drift and makes later repair waves repeat
    # the same reasoning.  Keep this spine compact and identity-preserving:
    # it is a shared anchor, not a second report draft.
    report_spine_directions: list[dict[str, Any]] = []
    for index, item in enumerate(research_handoff.get("capability_cues", [])):
        if not isinstance(item, Mapping):
            continue
        direction = _clean_reporter_clue_text(item.get("direction", ""), max_chars=100)
        if not direction:
            continue
        row: dict[str, Any] = {
            "direction_id": f"D{index + 1:02d}",
            "direction": direction,
        }
        for key, limit in (
            ("equipment_form", 140),
            ("capability_gap", 180),
            ("target_scenario", 160),
            ("target_and_direct_effect", 200),
            ("mechanism_chain", None),
            ("public_equipment_baseline", 140),
            ("non_substitutable_difference", 180),
            ("failure_boundary", 180),
            ("evidence_boundary", 180),
            ("priority", 24),
        ):
            value = item.get(key, "")
            if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                values = [
                    _clean_reporter_clue_text(part, max_chars=110)
                    for part in list(value)[:6]
                    if _clean_reporter_clue_text(part)
                ]
                if values:
                    row[key] = values
                continue
            cleaned = _clean_reporter_clue_text(value, max_chars=limit)
            if cleaned:
                row[key] = cleaned
        report_spine_directions.append(row)

    query_frame = query_analysis if isinstance(query_analysis, Mapping) else {}
    def spine_list(key: str, limit: int = 6) -> list[str]:
        values = research_handoff.get(key, [])
        if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
            return []
        return [str(item) for item in list(values)[:limit] if str(item).strip()]

    report_spine: dict[str, Any] = {
        "version": "report-spine-v1",
        "read_only": True,
        "query_boundary": {
            key: query_frame[key]
            for key in (
                "core_query",
                "combat_problem_frame",
                "equipment_semantic_boundary",
            )
            if query_frame.get(key)
        },
        "mission_chain_breaks": spine_list("mission_chain_breaks"),
        "decisive_anchors": spine_list("decisive_anchors"),
        "counterevidence_and_limits": spine_list("counterevidence_and_limits"),
        "directions": report_spine_directions,
        "evidence_policy": (
            "事实、推断、目标方向和待验证边界分层；仅使用交接中的公开来源；"
            "章节不得重新发散候选或把另一栏正文当作事实。"
        ),
        "chapter_handoffs": (
            {
                "chapter_1": "定义威胁、需求缺口、国内外差距和建设必要性",
                "chapter_2": "把同一装备事实落成图像、动作、直接效果、体系贡献和判别性指标",
                "chapter_3": "仅抽象真实共享状态、接口和装备专属子系统方案",
                "chapter_4": "从装备失败模式选择技术断点、成熟基础和验证证据",
                "chapter_5": "从产品责任、接口、试验和供应链反推单位类型与技术基础",
            }
            if project_mode
            else {
                "layer_1": "场景、战法/制胜机理和装备能力特征",
                "layer_2": "实现途径、核心技术和耦合短板",
                "layer_3": "能力图像、效能贡献和发展优先级",
            }
        ),
    }
    sources: list[dict[str, str]] = []
    catalog = payload.get("evidence_catalog", [])
    if isinstance(catalog, Sequence) and not isinstance(catalog, (str, bytes)):
        for item in catalog[: (10 if quality_profile else 6)]:
            if not isinstance(item, Mapping):
                continue
            url = str(item.get("url", "")).strip()
            if not url.startswith(("http://", "https://")):
                continue
            sources.append(
                {
                    "title": _clean_reporter_clue_text(
                        item.get("title", "公开来源"),
                        max_chars=80,
                    ),
                    "url": url,
                    "tier": _clean_reporter_clue_text(
                        item.get("tier", ""),
                        max_chars=12,
                    ),
                    "fact": _clean_reporter_clue_text(
                        item.get("claim", ""),
                        max_chars=120,
                    ),
                }
            )

    evidence_closed = (
        str(payload.get("ablation_scope", ""))
        == "restricted_generic_baseline_evidence_closed"
    )
    pre_submission_checks = [
        "三个固定二级层和九个固定三级项齐全且顺序正确",
        "场景—战法/技术—能力特征—实现途径—核心技术—耦合风险—能力图像—效能贡献—发展抓手形成闭环",
        "分支规定成果已压缩融入九项，不另设平行模板",
        "相同判断不在能力特征、能力图像和效能贡献中重复展开",
        "所有段落以完整句结束且无超过1100字的超长段落；每段至少提供具体装备/项目事实、战场矛盾、因果判断、证据边界、反适应、验证或建设取舍之一",
        "建设优先序使用高/中/低或P0/P1/P2等显式等级并说明排序理由",
        "能力实现途径明确标注沿用改进/集成创新/原理突破",
        "核心技术按装备分别包含成熟度、瓶颈和攻关优先级，效能贡献只写能改变任务结果的关系",
        "⑥吸收capability_cues.coupling_risk，说明具体装备的依赖、级联和单点短板",
        "装备能力图像横向比较有证据且机制互异的具体装备方向，不压缩为抽象主题",
        "⑦保留与Query直接相关的具体装备方向；支撑能力放在相应装备的依赖或边界中",
        "⑦以模型判断为主，交付层只做结构、证据边界和明显重复的确定性清理",
        "⑦表格仅在有助于比较时使用，列和行随装备差异决定，不为凑齐字段或方向新增主体装备",
        "⑦只选与该装备机理相关的指标方向或边界，不把同一组待校准词语复制到所有装备",
        "最终论证优先自然体现与Query相关的多类关系变化，不展示维度方法论清单，"
        "也不为凑数量改写已经成立的具体装备因果链",
        "前瞻判断覆盖3至10年演进窗口、触发条件和不确定性",
        "核心正文达到约9000字且九项闭环后立即收束；任何长度均不触发机械扩写、压缩、降级或失败",
    ]
    if evidence_closed:
        pre_submission_checks = [
            "三个固定二级层和九个固定三级项齐全且顺序正确",
            "每个章节区分输入证据、保守推导、待验证假设和缺失的专业证据",
            "Query仅定义边界，不作为装备现状、性能、成熟度或效能事实来源",
            "不使用模型常识补齐受限通用检索未覆盖的专业结论",
            "方向数量、指标细度和结论强度随证据真实收缩，不为满足生产门禁造项",
            "只引用public_sources中的URL，证据不足时给出验证路径而非空缺章节",
            "正文完整且所有段落以完整句结束，任何长度均不触发降级或失败",
        ]
    if project_mode:
        pre_submission_checks = [
            "五章大标题、既定小标题和必要四级标题齐全且顺序正确",
            "先为每个direction建立独立的场景—对象—动作—机理—结果—基线—失效—证据因果链，再按各章决策问题自主组织正文；因果链不得变成固定输出字段",
            "每件武器的场景、目标、动作、技术、战果、指标、验证和边界均来自同一条capability_cues记录；只有交接明确给出协同时才跨装备引用",
            "装备图像概述使用四列表头且最后一列写出装备专属动作和直接结果；其余表格的列与行由实际比较关系决定，不用空栏或统一占位句填充",
            "体系贡献、战技指标、总体方案、关键技术和研制基础分别由装备自身机理和失败模式推导，不复制统一贡献句、指标组、子系统顺序、验证流程或单位分工",
            "事实、推断、目标方向和待测变量分层；缺少证据时说明具体缺口，不补造型号、成熟度、点值、单位归属或试验结论",
            "相同判断只写一次；删除方法论解释、通用套话、跨章节同义复述以及删除装备名称后仍可互换的长句",
            "达到五章结构和军事决策链闭合后自然收束，不以字数、字段数量或指标数量作为完成条件",
        ]

    canonical_h2, canonical_h3, canonical_h4 = _report_canonical_headings(payload)
    section_budget = (
        {
            "policy": "按Query、证据密度和军事决策价值自适应分配篇幅；不设章节比例或字段配额，五章论证闭合后自然收束。",
        }
        if project_mode
        else {
            "第一层：需求挖掘层": "约34%-40%",
            "第二层：技术攻关层": "约30%-36%",
            "第三层：能力图像与效能贡献层": "约28%-34%",
        }
    )
    report_ready_section_map = (
        {
            "usage": (
                "先逐件理解capability_cues完整记录并建立装备专属因果链，再按章节问题选择证据。"
                "本映射不规定字段顺序、栏目内容或每件装备必须覆盖的项目。"
            ),
            "equipment_record_rule": (
                "同一direction记录内的事实保持共同归属；跨记录内容只有在明确接口或协同证据下才能联合使用。"
            ),
        }
        if project_mode
        else {
            "①": ["decisive_anchors", "mission_chain_breaks", "capability_cues.capability_gap"],
            "②": ["capability_cues.mechanism_hint", "capability_cues.future_trigger", "capability_cues.disruptive_relationship"],
            "③": ["capability_cues.mission_effect", "capability_cues.equipment_hint"],
            "④": ["capability_cues.public_equipment_baseline", "capability_cues.development_path"],
            "⑤": ["capability_cues.equipment_hint", "public_sources.fact"],
            "⑥": ["capability_cues.coupling_risk", "capability_cues.boundary", "counterevidence_and_limits"],
            "⑦": ["capability_cues.direction", "capability_cues.indicator_portrait", "capability_cues.equipment_hint", "capability_cues.public_equipment_baseline", "capability_cues.disruptive_relationship"],
            "⑧": ["capability_cues.mission_effect", "capability_cues.mechanism_hint"],
            "⑨": ["capability_cues.priority", "capability_cues.development_path", "capability_cues.boundary", "capability_cues.disruptive_relationship"],
        }
    )

    return {
        "query": str(payload.get("topic", "")).strip()[:1200],
        **({"query_analysis": query_analysis} if project_mode else {}),
        "branch": branch,
        "report_template_mode": _report_template_mode(payload),
        "target_length": _report_target_chars(payload),
        "length_policy": {
            "model_target": _report_target_chars(payload),
            "delivery_target": (
                "不设字符硬上限；以模板完整、论证深度和句段完整性为交付边界"
                if _unbounded_quality_report(payload)
                else "不设统一字符硬上限；以当前模板与分支合同完整交付"
            ),
            "stop_when": (
                "五章模板、关键证据和军事决策链闭合后，完成当前段并立即收尾；不为达到字数扩写"
                if project_mode
                else "三层九项、关键证据和军事决策链闭合后，完成当前段并立即收尾；不为达到字数扩写"
            ),
            "overrun": "允许；任何长度均不得触发重写、压缩、降级或失败",
        },
        "first_pass_quality_contract": {
            "goal": "single_pass_delivery_without_quality_repair",
            "upstream_preprocessing": (
                "research_handoff.capability_cues已由前置阶段压缩为差距—机理—装备—效能—"
                "颠覆关系—发展路径—边界—优先级的Reporter-ready记录；直接跨卡综合，"
                "不重复发现或逐字段复述。query_analysis是Query语义的作战问题框架，不是填空表；"
                "各栏目按因果价值选择线索，不要求消费全部字段。"
            ),
            "target_length": _report_target_chars(payload),
            "section_budget": section_budget,
            "pre_submission_checks": pre_submission_checks,
        },
        "report_ready_section_map": report_ready_section_map,
        "branch_hard_requirements": {
            "core": _REPORT_BRANCH_MINIMAL_INSTRUCTIONS.get(
                branch,
                "交付驱动依据、场景影响、因果机制、能力需求、装备形态、验证路线和风险边界。",
            ),
            "sections": required_sections,
            "mandatory": mandatory_content,
        },
        "format_contract": {
            "h1": "由系统统一添加，模型不输出",
            "h2": list(canonical_h2),
            "h3": list(canonical_h3),
            "h4": list(canonical_h4),
            "max_heading_depth": 4 if project_mode else 3,
            "template": (
                "固定项目论证五章模板"
                if project_mode
                else "固定三层九项，不新增平行旧模板"
            ),
            "paragraph_policy": "一段一个中心判断，避免残句和超长段落",
            "table_policy": (
                "三、总体方案/（二）子系统方案、四、关键技术/（一）关键技术清单与攻关途径、五、研制基础/（二）技术基础使用正式Markdown表格；每个已确认装备至少一行。列项与单元格内容由装备实际机理、工程关系和证据状态决定，不要求统一字段覆盖；禁止空列、统一占位句和跨装备复制。"
                if project_mode
                else "仅高密度能力、技术、耦合、效能或优先级比较使用；最多6列、12行、单元格不超过220字"
            ),
        },
        "reporter_contract": _reporter_agent_contract(reporter_agent),
        "report_spine": report_spine,
        "research_handoff": research_handoff,
        "public_sources": sources,
        **(
            {"ablation_scope": str(payload.get("ablation_scope", ""))[:80]}
            if str(payload.get("ablation_scope", "")).strip()
            else {}
        ),
    }


def _compact_reporter_branch_products(branch: str, value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    limits = {
        "tactic_concepts": 3,
        "tactic_combinations": 5,
        "capability_domains": 8,
        "capability_indicators": 30,
        "equipment_forms": 8,
        "demand_cards": 8,
        "case_patterns": 6,
        "future_scenarios": 3,
        "emerging_equipment_categories": 4,
    }

    def compact(item: Any, *, depth: int = 0, list_limit: int = 8) -> Any:
        if depth >= 3:
            return _clean_reporter_clue_text(item, max_chars=220)
        if isinstance(item, Mapping):
            return {
                _clean_reporter_clue_text(key, max_chars=60): compact(
                    nested,
                    depth=depth + 1,
                    list_limit=8,
                )
                for key, nested in list(item.items())[:12]
                if nested not in (None, "", [], {})
            }
        if isinstance(item, Sequence) and not isinstance(item, (str, bytes)):
            return [
                compact(nested, depth=depth + 1, list_limit=8)
                for nested in item[:list_limit]
                if nested not in (None, "", [], {})
            ]
        return _clean_reporter_clue_text(item, max_chars=220)

    return {
        str(key): compact(
            item,
            list_limit=limits.get(str(key), 8),
        )
        for key, item in list(value.items())[:14]
        if item not in (None, "", [], {})
    }


def _reporter_repair_payload(
    payload: Mapping[str, Any],
    *,
    draft: str,
    quality_issues: Sequence[str],
    reporter_agent: AgentDef | None = None,
    generation_payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    generation = dict(
        generation_payload
        or _reporter_generation_payload(payload, reporter_agent)
    )
    return {
        "query": generation["query"],
        "query_analysis": generation.get("query_analysis", {}),
        "branch": generation["branch"],
        "report_template_mode": _report_template_mode(generation, payload),
        "target_length": generation["target_length"],
        "length_policy": generation["length_policy"],
        "branch_hard_requirements": generation["branch_hard_requirements"],
        "format_contract": generation["format_contract"],
        "reporter_contract": generation["reporter_contract"],
        "research_handoff": generation["research_handoff"],
        "public_sources": generation["public_sources"],
        "draft": draft,
        "failed_checks": [
            {
                "code": _report_issue_code(item),
                "message": str(item),
            }
            for item in quality_issues[:16]
        ],
        "revision_notes": _reporter_revision_notes(quality_issues),
    }


def _reporter_timeout_retry_payload(
    payload: Mapping[str, Any],
    *,
    reporter_agent: AgentDef | None = None,
    failure: BaseException | None = None,
) -> dict[str, Any]:
    generation = _reporter_generation_payload(payload, reporter_agent)
    handoff = generation.get("research_handoff", {})
    compact_handoff: dict[str, Any] = {}
    if isinstance(handoff, Mapping):
        for key in (
            "decisive_anchors",
            "mission_chain_breaks",
            "counterevidence_and_limits",
            "priority_signals",
        ):
            values = handoff.get(key, [])
            if isinstance(values, Sequence) and not isinstance(values, (str, bytes)):
                compact_handoff[key] = list(values[:1])
        cues = handoff.get("capability_cues", [])
        if isinstance(cues, Sequence) and not isinstance(cues, (str, bytes)):
            compact_handoff["capability_cues"] = _limit_report_capability_cues(cues)
        comparative = handoff.get("comparative_status", {})
        if isinstance(comparative, Mapping):
            compact_handoff["comparative_status"] = _compact_prompt_value(
                comparative,
                max_string_chars=160,
                max_list_items=3,
            )

    evidence_highlights: list[dict[str, str]] = []
    catalog = payload.get("evidence_catalog", [])
    if isinstance(catalog, Sequence) and not isinstance(catalog, (str, bytes)):
        for item in catalog[:3]:
            if not isinstance(item, Mapping):
                continue
            url = str(item.get("url", "")).strip()
            if not url.startswith(("http://", "https://")):
                continue
            evidence_highlights.append(
                {
                    "title": _clean_reporter_clue_text(
                        item.get("title", "公开来源"), max_chars=70
                    ),
                    "evidence": _clean_reporter_clue_text(
                        item.get("claim", ""), max_chars=100
                    ),
                    "url": url,
                }
            )
    contract = generation.get("reporter_contract", {})
    compact_contract = {}
    if isinstance(contract, Mapping):
        for key in ("required_outputs", "evidence_rules"):
            compact_contract[key] = list(contract.get(key, []))[:6]
    failure_text = f"{type(failure).__name__}: {failure}" if failure is not None else ""
    timed_out = isinstance(failure, TimeoutError) or "timed out" in failure_text.lower()
    retry_instruction = (
        "前次调用超时；本次是全新独立写作，不续写、不缩写、不输出降级模板。"
        if timed_out
        else "前次独立写作未成功；本次使用精简输入重新独立构思，不续写、不拼接、不输出降级模板。"
    )
    return {
        "query": generation["query"],
        "query_analysis": generation.get("query_analysis", {}),
        "branch": generation["branch"],
        "report_template_mode": _report_template_mode(generation, payload),
        "target_length": generation["target_length"],
        "length_policy": generation["length_policy"],
        "branch_hard_requirements": generation["branch_hard_requirements"],
        "format_contract": generation["format_contract"],
        "reporter_contract": compact_contract,
        "research_handoff": compact_handoff,
        "evidence_highlights": evidence_highlights,
        "public_sources": list(generation.get("public_sources", []))[:4],
        "retry_instruction": retry_instruction,
    }


def _reporter_agent_contract(agent: AgentDef | None) -> dict[str, Any]:
    if agent is None:
        return {}
    policy = agent.research_policy if isinstance(agent.research_policy, Mapping) else {}
    delivery_method: list[str] = []
    quality_focus: list[str] = []
    if agent.skills:
        primary = agent.skills[0]
        if isinstance(primary, Mapping):
            delivery_method = [
                _clean_reporter_clue_text(item, max_chars=140)
                for item in primary.get("steps", [])[:7]
                if _clean_reporter_clue_text(item)
            ]
            quality_focus = [
                _clean_reporter_clue_text(item, max_chars=140)
                for item in primary.get("quality_gates", [])[:6]
                if _clean_reporter_clue_text(item)
            ]
    output_fields: list[str] = []
    if isinstance(agent.output_contract, Mapping):
        output_fields = [
            str(item)[:80]
            for item in agent.output_contract.get("properties", [])[:10]
            if str(item).strip()
        ]

    def policy_rows(key: str, *, limit: int, max_chars: int) -> list[str]:
        rows = policy.get(key, [])
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
            return []
        return [
            _clean_reporter_clue_text(item, max_chars=max_chars)
            for item in rows[:limit]
            if _clean_reporter_clue_text(item)
        ]

    return {
        "objective": _clean_reporter_clue_text(
            agent.description,
            max_chars=240,
        ),
        "method": delivery_method,
        "required_outputs": policy_rows(
            "required_outputs", limit=8, max_chars=100
        ),
        "writing_priorities": policy_rows(
            "writing_priorities", limit=10, max_chars=100
        ),
        "evidence_rules": policy_rows(
            "evidence_policy", limit=6, max_chars=120
        ),
        "structure_rules": policy_rows(
            "structure_policy", limit=6, max_chars=120
        ),
        "quality_focus": quality_focus,
        "stopping_conditions": policy_rows(
            "stopping_conditions", limit=6, max_chars=120
        ),
        "output_fields": output_fields,
    }


def _reporter_revision_notes(quality_issues: Sequence[str]) -> list[str]:
    joined = "；".join(str(item) for item in quality_issues)
    notes: list[str] = []
    if any(marker in joined for marker in ("最低", "长度", "过短", "硬上限")):
        notes.append("只补充缺失的实质内容；模板、证据和军事决策链闭环后立即收束，不为达到字数扩写或重复字段。")
    if any(marker in joined for marker in ("编号", "三层", "九项", "章节", "缺少")):
        notes.append("严格补齐三层九项：场景、制胜机理、能力特征、实现途径、核心技术、耦合风险、能力图像、效能贡献、发展抓手。")
    if any(marker in joined for marker in ("URL", "引用", "来源", "证据", "事实")):
        notes.append("正文仅保留1至2条最关键的[来源名](允许URL)作为定位，其余来源集中放入文末来源索引；关键判断明确区分事实、推断和待验证假设。")
    if any(marker in joined for marker in ("因果", "任务链", "能力映射", "接口", "实现途径", "核心技术")):
        notes.append("补强场景—战法—能力—技术—效能因果链；每项能力显式映射实现途径、核心技术、耦合风险、装备形态和工程边界。")
    if any(marker in joined for marker in ("军事", "打击", "反制", "威慑", "抗毁")):
        notes.append("把军事价值落实到具体对象、阶段、条件及打击歼灭、反制拒止、威慑或抗毁效果。")
    if any(marker in joined for marker in ("重复", "残缺", "断句", "段落", "标题")):
        notes.append("删除重复和模板化标题，修复残段断句并突出关键判断。")
    if any(marker in joined for marker in ("前置研判", "原句复用", "拼接")):
        notes.append("丢弃前置线索原有措辞和顺序，回到Query重新组织因果链并形成新的综合判断。")
    if any(marker in joined for marker in (
        "颠覆关系",
        "全部高军事价值武器装备方向",
        "支撑层不得替换",
        "第一列必须与输入",
        "擅自新增",
    )):
        notes.append(
            "在②⑦⑨自然写入与Query因果相关的关系变化，并逐项保留全部输入装备方向；"
            "关系类型数量只作表达增强，不得成为交付阻断条件；"
            "不得罗列维度名或用通信保障等支撑项替换主体装备。"
        )
    if any(marker in joined for marker in ("效能", "补链", "强链", "开链", "优先级", "验证")):
        notes.append("在效能贡献中明确补链/强链/开链和可比较方向，在发展抓手中给出显式优先级与转段/判退依据。")
    if any(marker in joined for marker in ("不确定", "反证", "边界", "成熟度", "瓶颈")):
        notes.append("把未知、反证、来源质量、成熟度不确定性和失效边界嵌入对应九项，不另设平行章节。")
    return notes[:6] or ["逐项核对三层九项合同，修复缺项和表达问题。"]


def _report_issue_code(issue: Any) -> str:
    text = str(issue)
    rules = (
        ("length_min", ("最低门槛", "正文仅")),
        ("length_max", ("硬上限", "超过交付")),
        ("report_item_missing", ("九项", "固定三级项", "必需内容", "必需章节")),
        ("format_heading", ("三层", "二级章节", "二级标题", "三级标题", "跨级标题", "标题层级")),
        ("format_markdown", ("强调符号", "反引号", "表格", "残段", "断句")),
        ("upstream_copy", ("原句复用", "前置研判", "拼接")),
        ("evidence", ("来源", "URL", "证据", "事实")),
        ("causal_depth", ("因果", "任务链", "机理")),
        ("military_value", ("军事运用价值", "打击", "反制")),
        ("capability_mapping", ("装备决策", "能力映射", "体系接口", "能力图像")),
        ("disruptive_diversity", ("颠覆关系", "支撑层不得替换", "全部高军事价值武器装备方向")),
        ("technology_path", ("实现途径", "核心技术", "成熟度", "耦合", "短板")),
        ("effectiveness", ("效能贡献", "补链", "强链", "开链")),
        ("uncertainty", ("不确定", "反证", "失效边界", "验证口径")),
    )
    for code, markers in rules:
        if any(marker in text for marker in markers):
            return code
    return "report_contract"


_REPORT_BRANCH_MINIMAL_INSTRUCTIONS: dict[str, str] = {
    "A": "把新战法、战法组合和能力指标压缩融入②③⑦，重点说明相对现有范式的制胜变化、装备能力特征和验证方向。",
    "B": "把需求卡片、能力全景图、现役基线、差距和推理链压缩融入①③⑦⑧，主对象必须是具体军事战斗装备。",
    "C": "把案例规律和未来场景作为①②的证据，把新兴装备方向收敛到③⑦⑨，并保留跨案例迁移边界。",
    "D": "突出技术改变任务机制、成熟度、工程瓶颈、装备形态和验证路线，重点进入④⑤⑥⑨。",
    "E": "沿对手能力形成链构造场景与对冲机理，形成装备需求、效能贡献和建设触发信号。",
    "F": "沿体系脆弱性和级联失效分析补链、强链、替代链需求，并给出压力验证抓手。",
    "G": "沿跨域缝隙、接口、弱网和协同约束形成装备能力、技术短板、效能贡献和降级验证。",
    "H": "围绕威胁扩散与任务冲击形成韧性或非致命装备需求，并嵌入规则边界和验证条件。",
}


_REPORT_BRANCH_INSTRUCTIONS: dict[str, str] = {
    "A": (
        "必须完整形成：3种新战法、5种战法组合、8大能力域、合计30项能力指标和关联装备形态建议。"
        "为支持自动门控，条目标题必须依次使用‘新战法1’至‘新战法3’、‘战法组合1’至‘战法组合5’、"
        "‘能力域1’至‘能力域8’，指标必须使用‘指标1’至‘指标30’连续编号且各出现一次。"
        "三种战法逐项写清制胜矛盾、任务链机制、相对现有战法的实质变化、打击/反制/拒止/威慑价值、"
        "对手适应与边界；五种组合逐项说明组合逻辑、适用场景、能力依赖和失效条件；八个能力域必须"
        "彼此形成体系关系，30项指标按能力域分组并连续编号1至30，使用任务级可验证口径。装备形态必须"
        "由战法与能力反推，区分现役升级、近期新研和中长期预研；智能蜂群母舰、异构协同网关等名称只有"
        "在输入产物或因果机制支持时才能采用。"
    ),
    "B": (
        "必须形成结构化武器装备能力需求图像：逐项需求卡片的主对象必须是与query直接因果匹配的具体"
        "待发展武器装备，而不是抽象能力域或技术标签。优先形成无人机、无人艇、无人潜航器、无人车、"
        "无人僚机、无人集群、导弹、巡飞弹、精确制导弹药、拦截弹、鱼雷、火炮、定向能武器或电子压制"
        "效应器等承担歼灭、打击、猎歼、拦截、拒止和威慑任务的军事战斗装备；通信、数据链、算法、保障"
        "和接口只能作为具体武器装备的内部构型或配套，不得单独成为需求卡片主对象。每卡同时覆盖装备构型、"
        "新研卡片还必须给出相对现役谱系可识别的差异化构型、制导感知、自主边界、突防或毁伤机制，"
        "标题不得停留在无人机、巡飞弹、反辐射巡飞弹、远程导弹等既有大类；"
        "发展方式、关键指标、优先级、支撑场景和证据链，并解释缺口如何切断任务链以及补齐后恢复何种"
        "打击、反制、抗毁或持续作战效果；能力"
        "全景图要说明需求之间的依赖、替代、放大、共同失效和建设先后关系，不得再次逐卡复述；深度报告"
        "必须融合多源业务研判、六步效果链、能力映射和五档差距，区分现役改装、新装备形成与非装备"
        "约束，并给出反证、验证条件和近期至中长期时序。"
    ),
    "C": (
        "必须完整形成6条核心案例规律、3类高置信未来场景和4大新兴装备类别。六条规律逐项写清战例条件、"
        "关键行动或决策机制、结果、跨案例共性、不可迁移因素与证据边界，不能复述战例现象；三类场景"
        "逐项写清触发信号、未来对抗形态、关键任务压力、军事价值、对手适应与置信度；四类装备由案例"
        "规律和未来场景共同反推，说明任务定位、能力组合、现役替代关系、发展窗口和验证路径。为支持自动"
        "门控，条目标题必须依次使用‘核心规律1’至‘核心规律6’、‘高置信场景1’至‘高置信场景3’和"
        "‘新兴装备类别1’至‘新兴装备类别4’。"
    ),
    "D": (
        "以技术改变任务机制为主线，先说明技术解决了哪一段探测、决策、打击、反制、抗扰、机动或保障"
        "瓶颈，再判断其成熟度、可集成性和对抗失效模式。不得从技术热词直接跳到装备名称。按证据收敛"
        "技术机会和装备方向，区分现役升级、近期新研与中长期预研，并给出工程瓶颈、成熟窗口和验证门槛。"
    ),
    "E": (
        "沿对手能力形成链组织正文，区分已形成威胁、正在形成能力和预警信号，解释其如何改变己方侦察、"
        "决策、突防防护、反制和持续作战压力。装备建议必须对应可削弱、延迟、拒止或制衡的具体威胁效果，"
        "并以可观测触发指标决定升级、新研或预研时机。"
    ),
    "F": (
        "以体系节点、链路和资源依赖为主线，形成脆弱性规律、级联失效场景、补链强链替代链组合和需求"
        "卡片。重点说明关键节点受压后哪些任务段会连续退化，以及分布式、可替换、可降级和动态重构能力"
        "如何维持打击、反制和保障闭环；不得用单个平台性能替代体系效果。"
    ),
    "G": (
        "以跨域任务链中的数据、时间、权限、接口和火力协同缝隙为主线，形成协同模式、弱网与跨密域运行"
        "条件、接口装备形态和需求卡片。重点证明融合机制如何提高发现处置连续性、压缩任务链并减少协同"
        "摩擦，同时说明异构协议、数据不可信、带宽退化和权限限制下的最低可用与失效边界。"
    ),
    "H": (
        "围绕新型威胁扩散、任务冲击和高置信场景形成韧性与非致命装备需求。重点说明如何保护关键任务、"
        "人员和基础设施，限制威胁扩散、恢复任务并保持可控反制效果；同步写明法律伦理、技术滥用、军地"
        "协同和规则约束，不得把短期应急方案无条件固化为长期装备方向。"
    ),
}


def _report_capability_image_table_directions(section_text: str) -> list[str]:
    """Extract section ⑦ table rows without treating headers as equipment."""

    directions: list[str] = []
    for raw_line in str(section_text).splitlines():
        line = raw_line.strip()
        if not (line.startswith("|") and line.endswith("|")):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if not cells:
            continue
        first = cells[0]
        if first in {"武器装备", "装备系统方向", "装备方向", "具体装备方向"}:
            continue
        if re.fullmatch(r":?-{3,}:?", first):
            continue
        if first:
            directions.append(first)
    return directions


def _report_equipment_attribution_issues(
    text: str,
    payload: Mapping[str, Any],
) -> list[str]:
    """Detect table rows that mix facts from different equipment records.

    A comparison paragraph may name several weapons legitimately.  A table
    row, however, has one owning equipment identity.  When another complete
    direction name appears in that row's remaining cells, the row is likely a
    material mix-up and should be rewritten by the model instead of being
    repaired deterministically.
    """

    seed = payload.get("synthesis_seed", {})
    cues = seed.get("capability_cues", []) if isinstance(seed, Mapping) else []
    names = [
        str(item.get("direction", "")).strip()
        for item in cues
        if isinstance(item, Mapping) and str(item.get("direction", "")).strip()
    ]
    names = list(dict.fromkeys(name for name in names if len(name) >= 4))
    if len(names) < 2:
        return []
    issues: list[str] = []
    in_table = False
    for line in str(text or "").splitlines():
        stripped = line.strip()
        if not (stripped.startswith("|") and stripped.endswith("|")):
            in_table = False
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) < 2 or cells[0] in {"武器装备", "装备系统方向", "装备方向", "具体装备方向"}:
            in_table = True
            continue
        owner = next((name for name in names if name == cells[0]), "")
        if not owner:
            in_table = True
            continue
        foreign = [name for name in names if name != owner and any(name in cell for cell in cells[1:])]
        if foreign:
            issues.append(
                f"表格行“{owner}”混入其他装备材料（{foreign[0]}），需按direction归属重写"
            )
        in_table = True
    return issues


def _report_fragment_quality_issues(text: str) -> list[str]:
    """Detect objective truncation/Markdown damage only.

    Semantic sentence quality is handled during model generation and review;
    suffix-based word heuristics are deliberately excluded from this gate.
    """

    semantic_clipping_patterns = (
        re.compile(r"(?:…|\.\.\.)"),
        re.compile(r"(?:压制关|远程精确制|现有发为对照|多供应链替代与批)(?=[\s，。；、|]|$)"),
        re.compile(r"(?:效应器及|消耗任务的|为\s*JASSM-ER|拖垮该|候选A的驻)(?=[\s，。；、|]|$)"),
        re.compile(r"(?:的任|的鉴权与)(?=[，、；。])"),
        re.compile(r"(?:接收|目录|形成|实施|继续|发生|经过授权)(?:接|目|形|实|继|发|经)(?=[；。|]|$)"),
        re.compile(r"(?:并以安全|降低攻击)(?=[。；|]|$)"),
        re.compile(r"(?:试验|验证|闭环试验)，确(?=[。；|]|$)"),
        re.compile(r"(?:导航|任务区|通过条件)推进(?=[。；|]|$)"),
        re.compile(r"(?:^|[；：])通过条件(?:为)?(?=[。；|]|$)"),
    )

    def semantic_clipping_sample(value: str) -> str:
        for pattern in semantic_clipping_patterns:
            match = pattern.search(value)
            if match:
                start = max(0, match.start() - 24)
                end = min(len(value), match.end() + 24)
                return value[start:end].strip()
        # Do not infer clipping from ordinary Chinese clause endings.  In
        # particular, valid report prose frequently ends a table cell or
        # sentence with words such as ``当前结论``/``目的``/``能力``.  Those
        # broad suffix heuristics caused healthy parallel chapters to be
        # rejected merely because they used concise editorial phrasing.
        return ""

    samples: list[str] = []
    lines = str(text).splitlines()
    for index, raw_line in enumerate(lines):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        next_nonempty = next(
            (item.strip() for item in lines[index + 1 :] if item.strip()),
            "",
        )
        if line.endswith(("如下。", "如下.")) and next_nonempty.startswith(
            ("- ", "* ", "|")
        ):
            continue
        if line.startswith("|") != line.endswith("|"):
            samples.append(line[:60])
            continue
        candidates = (
            [cell.strip() for cell in line.strip("|").split("|")]
            if line.startswith("|") and line.endswith("|")
            else [line]
        )
        for candidate in candidates:
            candidate = re.sub(r"^(?:[-*]\s+|\d+[\.、]\s*)", "", candidate)
            semantic_sample = semantic_clipping_sample(candidate)
            if semantic_sample:
                samples.append(semantic_sample[:60])
                continue
            for sentence in re.split(r"(?<=[。！？!?])", candidate):
                sentence = sentence.strip(" *_'\"“”‘’")
                if not sentence:
                    continue
                normalized_sentence = _remove_empty_report_clauses(sentence)
                if not normalized_sentence:
                    samples.append(sentence[:60])
                    continue
                if re.fullmatch(
                    r"(?:核心|主要|当前|该)?(?:矛盾|关键|问题|难点|重点|风险)"
                    r"(?:在于|是|为|成立)?。|(?:作战|任务|目标)(?:上|方面|是|为)?。",
                    sentence,
                ) or re.fullmatch(
                    r".{0,36}(?:体现为|包括|主要是|分别为|在于|取决于|依赖于)。",
                    sentence,
                ):
                    samples.append(sentence[:60])
                    continue
            # A Markdown table header is not a prose fragment.  Only apply
            # the terminal-noun heuristic to non-table text; table shape and
            # cell closure are validated separately by _report_table_issues.
            if not line.startswith("|") and (
                len(re.findall(r"[、，；]", candidate)) >= 2
                and re.search(
                    r"(?:目标|任务|能力|指标|技术|平台|系统|链路|装备|方案|"
                    r"场景|风险|约束|条件|接口)[。；]$",
                    candidate,
                )
                and not re.search(
                    r"(?:的能力|的系统|的装备|的方案)[。；]$",
                    candidate,
                )
                and not any(
                    term in candidate
                    for term in (
                        "形成", "实现", "完成", "提升", "降低", "打击", "压制",
                        "猎歼", "支持", "支撑", "应对", "用于", "采用", "具备", "保持", "选择",
                        "识别", "验证", "评估", "部署", "发射", "交战", "毁伤",
                        "表明", "说明", "决定", "依赖", "位于", "贡献", "对应",
                        "中断", "出现",
                    )
                )
            ):
                samples.append(candidate[-60:])
    if not samples:
        return []
    return [
        "正文存在截断残句或未闭合表格单元格："
        + "；".join(dict.fromkeys(samples[:4]))
    ]



def _report_chapter_mechanical_issues(text: str, chapter: str) -> list[str]:
    """Detect chapter-local copy rotation that passes structural checks.

    A chapter can contain all required headings and still be unusable when a
    generic sentence is repeated for every equipment direction.  This check is
    intentionally conservative: it only blocks repeated high-signal phrases in
    the solution/technology/foundation chapters and leaves ordinary recurring
    terminology alone.
    """
    value = str(text or "")
    starts = {
        "chapter_1_demand": "## 一、需求分析",
        "chapter_2_equipment_image": "### （一）装备图像概述",
        "chapter_2_operations": "### （二）作战运用模式",
        "chapter_2_contribution": "### （三）体系贡献率分析",
        "chapter_2_indicators": "### （四）主要战技指标",
        "chapter_3_solution": "## 三、总体方案",
        "chapter_4_technology": "## 四、关键技术",
        "chapter_5_foundation": "## 五、研制基础",
    }
    start = starts.get(chapter)
    if not start:
        return []
    if start in value:
        pos = value.index(start)
    elif re.search(r"^###\s+", value, flags=re.MULTILINE):
        # Single-column Reporter fragments intentionally omit their sibling
        # H3 sections.  Apply the same copy-rotation gate before assembly.
        pos = 0
    else:
        return []
    if chapter == "chapter_2_equipment_image":
        next_markers = ("\n### （二）作战运用模式", "\n## 三、总体方案")
    elif chapter == "chapter_2_operations":
        next_markers = ("\n### （三）体系贡献率分析", "\n## 三、总体方案")
    elif chapter == "chapter_2_contribution":
        next_markers = ("\n### （四）主要战技指标", "\n## 三、总体方案")
    elif chapter == "chapter_2_indicators":
        next_markers = ("\n## 三、总体方案",)
    else:
        next_markers = ("\n## ",)
    next_candidates = [
        value.find(marker, pos + len(start))
        for marker in next_markers
    ]
    next_candidates = [candidate for candidate in next_candidates if candidate >= 0]
    next_pos = min(next_candidates) if next_candidates else -1
    body = value[pos: next_pos if next_pos >= 0 else len(value)]
    # These phrases are valid once as a global boundary, but repeating them for
    # each row is a strong signal that the model copied a form instead of
    # reasoning about the equipment.
    generic = (
        "通过任务级仿真、接口联试和演训验证逐步收敛",
        "公开证据不足的参数不得转化为确定性指标，保留区间与置信度",
        "须回到前置质量门",
        "指标画像尚未由",
        "通过分布式感知、弹性协同和多样化任务效应",
        "公开证据不足的参数不得转化为确定性指标",
        "保留区间与置信度",
        "通过任务级仿真、接口联试和演训验证",
        "指标画像尚未由研究专业研判形成",
        "输入为目标/环境与授权状态",
        "针对该装备开展专属台架、半实物或外场验证",
        "建立载荷、控制与接口闭环",
        "总体设计、平台/载荷、感知火控、任务软件及试验鉴定",
        "需保留可追溯日志",
    )
    issues: list[str] = []
    for phrase in generic:
        count = body.count(phrase)
        if count >= 2:
            issues.append(f"{chapter}存在机械化重复短语：{phrase}（{count}次）")
    # Compare substantial prose/table cells after removing equipment names and
    # punctuation.  Two or more near-identical cells indicate copy rotation.
    chunks = []

    def normalize_equipment_identity(line: str) -> str:
        """Remove the owning equipment name before comparing row skeletons."""

        normalized_line = str(line)
        bullet_owner = re.match(
            r"^\s*[-*]\s+\*\*(?P<owner>.+?)(?:（[^）]+）)?\*\*",
            normalized_line,
        )
        if bullet_owner:
            owner = bullet_owner.group("owner").strip()
            if owner:
                normalized_line = normalized_line.replace(owner, "<装备>")
        return normalized_line

    for line in body.splitlines():
        if line.startswith("|"):
            raw_cells = [cell.strip() for cell in line.strip("|").split("|")]
            owner = raw_cells[0] if raw_cells else ""
            if owner and not re.fullmatch(r":?-{3,}:?", owner) and owner not in {
                "武器装备",
                "装备方向",
                "装备系统方向",
                "具体装备方向",
            }:
                raw_cells = [
                    ("<装备>" if index == 0 else cell.replace(owner, "<装备>"))
                    for index, cell in enumerate(raw_cells)
                ]
            cells = [
                re.sub(r"[|：；，。、、\s]", "", cell)
                for cell in raw_cells
            ]
            chunks.extend(c for c in cells if len(c) >= 28)
        elif line.startswith(("-", "*")) and len(line) >= 45:
            normalized_line = normalize_equipment_identity(line)
            chunks.append(re.sub(r"[：；，。、\s*]", "", normalized_line))
    for paragraph in re.split(r"\n\s*\n", body):
        stripped = paragraph.strip()
        if (
            not stripped
            or stripped.startswith(("#", "|", "- ", "* "))
            or "\n|" in stripped
        ):
            continue
        compact = re.sub(r"[：；，。、\s]", "", stripped)
        if len(compact) >= 60:
            chunks.append(compact)
    duplicates = 0
    def ngram_similarity(left: str, right: str, n: int = 3) -> float:
        if len(left) < n or len(right) < n:
            return 0.0
        left_grams = {left[idx:idx+n] for idx in range(len(left)-n+1)}
        right_grams = {right[idx:idx+n] for idx in range(len(right)-n+1)}
        union = left_grams | right_grams
        return len(left_grams & right_grams) / len(union) if union else 0.0

    for idx, left in enumerate(chunks):
        for right in chunks[idx + 1:]:
            if left == right:
                duplicates += 1
            elif len(left) >= 45 and len(right) >= 45:
                shorter = min(len(left), len(right))
                common = sum(1 for a, b in zip(left[:shorter], right[:shorter]) if a == b)
                if common / shorter >= 0.92:
                    duplicates += 1
                elif shorter >= 60 and ngram_similarity(left, right) >= 0.82:
                    duplicates += 1
    if duplicates >= 1:
        issues.append(f"{chapter}存在装备条目近重复（{duplicates}组），需要按装备机理重新组织")
    return issues


def _report_draft_quality_issues(
    text: str,
    payload: Mapping[str, Any],
) -> list[str]:
    brief = payload.get("branch_writer_brief", {})
    if not isinstance(brief, Mapping) or not brief:
        return []
    branch = str(brief.get("branch", "")).strip().upper()
    if not branch:
        return []
    issues: list[str] = []
    if "**深度能力画像。**" in text:
        issues.append("正文仍在逐项复述能力画像卡片，必须改为跨材料综合")
    project_mode = _report_template_mode(payload) == "project_argument_v1"
    issues.extend(
        _report_project_argument_content_issues(text)
        if project_mode
        else _report_three_layer_content_issues(text)
    )
    if project_mode:
        for chapter in (
            "chapter_2_equipment_image",
            "chapter_2_operations",
            "chapter_2_contribution",
            "chapter_2_indicators",
            "chapter_3_solution",
            "chapter_4_technology",
            "chapter_5_foundation",
        ):
            issues.extend(_report_chapter_mechanical_issues(text, chapter))
        issues.extend(_report_equipment_attribution_issues(text, payload))
    # Keep the detector as audit telemetry for explicit transport damage, but
    # do not let its heuristic findings block a model-written report.
    issues.extend(_report_fragment_quality_issues(text))
    issues.extend(_report_domain_attribute_issues(text, payload))

    seed = payload.get("synthesis_seed", {})
    capability_cues = (
        seed.get("capability_cues", []) if isinstance(seed, Mapping) else []
    )
    expected_direction_names = [
        str(item.get("direction", "")).strip()
        for item in capability_cues
        if isinstance(item, Mapping) and str(item.get("direction", "")).strip()
    ]
    # Legacy three-layer output still audits a fixed capability table.  A
    # project report may use prose, a mixed table, or a deliberately smaller
    # comparison set selected by the model, so only require that at least one
    # concrete handoff direction (or equivalent weapon identity) is grounded.
    image_audit_required = bool(expected_direction_names) and not project_mode
    project_image_audit_required = bool(expected_direction_names) and project_mode
    if image_audit_required or project_image_audit_required:
        section_pattern = (
            r"^###\s*（一）装备图像概述\s*$\n(?P<body>.*?)(?=^###\s*（二）作战运用模式\s*$)"
            if project_mode
            else r"^###\s*⑦\s*装备能力图像\s*$\n(?P<body>.*?)(?=^###\s*⑧\s*效能贡献评估\s*$)"
        )
        section_match = re.search(
            section_pattern,
            text,
            flags=re.MULTILINE | re.DOTALL,
        )
        section_text = section_match.group("body") if section_match else ""
        represented = sum(
            name in section_text for name in expected_direction_names
        )
        if project_mode and represented == 0 and not any(
            marker in section_text
            for marker in (
                "导弹", "弹药", "无人机", "无人艇", "无人僚机", "巡飞弹",
                "拦截弹", "发射车", "火炮", "武器站", "效应器",
            )
        ):
            issues.append(
                "装备图像概述未关联具体武器装备主体；应由Query和证据选择装备，不以抽象能力或支撑节点代替"
            )
        elif not project_mode and represented < len(expected_direction_names):
            issues.append(
                f"装备能力图像仅明确覆盖{represented}/{len(expected_direction_names)}个输入方向，"
                "需逐项保留全部高军事价值武器装备方向，支撑层不得替换或另造主体方向"
            )
        table_direction_names = _report_capability_image_table_directions(
            section_text
        )
        if table_direction_names and not project_mode:
            missing_table_directions = [
                name
                for name in expected_direction_names
                if name not in table_direction_names
            ]
            extra_table_directions = [
                name
                for name in table_direction_names
                if name not in expected_direction_names
            ]
            if (
                missing_table_directions
                or extra_table_directions
                or len(table_direction_names) != len(expected_direction_names)
            ):
                details = []
                if missing_table_directions:
                    details.append(
                        "缺少" + "、".join(missing_table_directions[:4])
                    )
                if extra_table_directions:
                    details.append(
                        "擅自新增" + "、".join(extra_table_directions[:4])
                    )
                issues.append(
                    "装备能力图像表第一列必须与输入的具体武器装备方向完全一致；"
                    + "；".join(details or ["行数不一致"])
                )
    if (
        is_quality_execution_profile_id(payload.get("execution_profile_id", ""))
        and len(expected_direction_names) >= 5
    ):
        density_metrics = _report_military_information_metrics(
            text,
            {
                "require_high_value_military_information": True,
                "expected_capability_directions": expected_direction_names,
            },
        )
        if density_metrics["decision_dense_ratio"] < 0.55:
            issues.append(
                "军事决策信息密度不足：至少55%的正文段落须包含具体装备/项目事实，或同时形成对手反制、作战动作、直接战果、验证判据与建设取舍中的三类信息"
            )
        if density_metrics["generic_filler_ratio"] > 0.25:
            issues.append("通用战略套话段比例过高，删除不改变装备选择、战法或验证决策的段落")
        if (
            density_metrics["repeated_long_unit_ratio"] > 0.08
            or density_metrics["maximum_long_unit_reuse"] > 2
        ):
            issues.append(
                "跨章节长句复用过多：同一完整长句不得出现三次，重复长句实例占比不得超过8%"
            )
        if density_metrics["missing_equipment_bundles"]:
            issues.append(
                "以下装备未成套说明敌方目标/反制、我方作战动作、直接战果与验证判据："
                + "、".join(density_metrics["missing_equipment_bundles"][:5])
            )
    # 总字数和专家型创新判断不属于Reporter发布硬门；信息密度按段落决策价值、
    # 跨章复用和逐装备作战闭环检查，不以篇幅或关键词总量替代质量。
    forbidden_patterns = {
        "Agent": r"\bAgent\b",
        "Codex": r"\bCodex\b",
        "L1-L4": r"\bL[1-4]\b",
        "S1-S6": r"\bS[1-6]\b",
        "内部对象编号": r"(?<![A-Za-z0-9_])(?:ev|packet|cap)-[A-Za-z0-9]",
        "内部附件名": r"(?:branch_deliverables|capability_images|demand_cards|reasoning_traceability)\.json",
        "Reporter改写断点": re.escape(_REPORTER_HANDOFF_REWRITE_BOUNDARY),
        "候选分支前缀": (
            r"(?m:(?:^|\|\s*|\*\*)[A-Ha-h]\s*[.．、:：]\s*(?=[^\s|*]))"
        ),
        "委托方口吻": r"\u7532\u65b9",
    }
    for label, pattern in forbidden_patterns.items():
        if re.search(pattern, text, flags=re.IGNORECASE):
            issues.append(f"正文仍包含过程性或内部表达：{label}")
    catalog = payload.get("evidence_catalog", [])
    allowed_urls = {
        str(item.get("url", "")).strip().rstrip("/")
        for item in catalog
        if isinstance(item, Mapping) and str(item.get("url", "")).strip()
    }
    cited_urls = {
        item.rstrip("/)")
        for item in re.findall(r"https://[^\s)]+", text)
    }
    if allowed_urls:
        unknown_urls = sorted(
            item for item in cited_urls if item.rstrip("/") not in allowed_urls
        )
        if unknown_urls:
            issues.append("正文引用了来源目录之外的URL：" + ", ".join(unknown_urls[:4]))
    label_heading = re.search(
        r"^#{3,4}\s*.*(?:深度性|军事价值性?|前瞻性|新颖性|创新性)\s*$",
        text,
        flags=re.MULTILINE,
    )
    if label_heading:
        issues.append("不得把深度性、军事价值、前瞻性或新颖性写成独立标题")
    heading_count = len(re.findall(r"^#{3,4}\s+", text, flags=re.MULTILINE))
    heading_limit = 24 if project_mode else 9
    if heading_count > heading_limit:
        issues.append(
            f"三级和四级标题共{heading_count}个，超过所选报告模板上限{heading_limit}个"
        )
    issues.extend(_report_markdown_structure_issues(text, payload))
    issues.extend(_report_seed_copy_issues(text, payload))
    if (
        is_quality_execution_profile_id(payload.get("execution_profile_id", ""))
        and not project_mode
    ):
        issues.extend(_report_v2_benchmark_issues(text))
    return issues


def _report_project_argument_content_issues(text: str) -> list[str]:
    issues: list[str] = []
    def has_any(*markers: str, body: str = text) -> bool:
        return any(marker in body for marker in markers)

    def group_count(groups: Sequence[Sequence[str]], *, body: str = text) -> int:
        return sum(1 for group in groups if has_any(*group, body=body))

    template_instruction_patterns = (
        "按任务准备与装订、平台部署与进入、目标发现确认、火力分配、交战毁伤、效果评估和再组织分阶段说明装备使用方式与指标口径",
        "围绕时间链、信息与精度链、火力链、毁伤评估链分析单点短板、级联风险和制胜机理",
    )
    if any(pattern in text for pattern in template_instruction_patterns):
        issues.append("正式报告仍包含写作指令或模板占位句，必须改写为具体军事场景、装备动作、直接战果和失效边界")
    # Keep the background/problem/need/project closure, but accept natural
    # Chinese wording instead of forcing five literal tokens into one passage.
    if group_count(
        (
            ("国际", "国内", "战略", "态势", "战场", "作战"),
            ("问题", "断点", "矛盾", "威胁", "短板", "难点"),
            ("需求", "需要", "建设", "应当", "亟需"),
            ("项目", "装备", "方案", "系统", "构型"),
        )
    ) < 3:
        issues.append("项目论证模板的需求概述未形成背景—问题—需求—项目画像闭环")
    status_section = re.search(
        r"^###\s*（二）国内外现状\s*$\n(?P<body>.*?)(?=^###\s*（三）建设必要性分析\s*$)",
        text,
        flags=re.MULTILINE | re.DOTALL,
    )
    status_body = status_section.group("body") if status_section else ""
    if not (
        "国外情况" in status_body
        and "国内现状（中国）" in status_body
        and has_any("型号", "装备", "项目", "平台", "弹药", body=status_body)
        and has_any(
            "技术方案",
            "技术途径",
            "核心技术",
            "技术路线",
            "制导",
            "感知",
            "工艺",
            body=status_body,
        )
        and has_any(
            "指标",
            "参数",
            "性能",
            "公开资料不足",
            "待核验",
            "证据",
            "成熟度",
            body=status_body,
        )
    ):
        issues.append("国内外现状需分别给出国外和中国案例，并覆盖问题解决、技术途径、指标与证据边界")
    if not all(
        term in text
        for term in (
            "作战使用角度",
            "装备能力提升角度",
            "领域占位角度",
            "综合效益",
        )
    ):
        issues.append("建设必要性分析缺少作战使用、装备提升、领域占位或综合效益维度")
    # A project image is a causal chain, not a required sentence skeleton.
    # Accept equivalent terms for scene, problem, principle/technology, action,
    # capability and effect; require most groups, not every literal token.
    if group_count(
        (
            ("面向", "针对场景", "作战场景", "威胁场景", "在……条件下"),
            ("针对", "解决", "应对", "任务断点", "瓶颈", "难题"),
            ("利用", "依靠", "基于", "原理", "采用", "技术", "构型"),
            ("关键作战流程", "作战流程", "作战运用", "部署", "发射", "交战", "任务链"),
            ("形成", "实现", "获得", "提升", "保持", "能力"),
            ("制胜逻辑", "直接效果", "作战效果", "战果", "毁伤", "压制", "拒止"),
        )
    ) < 5:
        issues.append("项目画像未按场景—问题—原理—技术—作战流程—能力—效果—制胜机理展开")
    if not (
        has_any("时间链", "精度链", "信息链", "火力链", "授权链", "任务链", "决策链", "评估链")
        and has_any(
            "任务准备",
            "部署",
            "搜索",
            "发现",
            "确认",
            "交战",
            "毁伤评估",
            "效果评估",
            "再组织",
            "补击",
            "中止",
        )
    ):
        issues.append("作战运用模式缺少分阶段流程或链路闭环分析")
    if group_count(
        (
            ("耗弹量", "单位成本", "成本交换", "产能", "补充"),
            ("突防效能", "拦截效果", "毁伤", "压制", "拒止", "生存"),
            ("任务成功率", "任务完成率", "命中", "有效作战"),
            ("闭环时间", "响应时间", "决策周期", "反应时间"),
            ("交换比", "持续波次", "覆盖", "规模", "驻留"),
        )
    ) < 2:
        issues.append("体系贡献率分析缺少与具体装备和任务相称的可比较效能方向")
    # The architecture must reach an implementable boundary, but not every
    # weapon needs a seven-layer inventory.  A missile, a low-altitude
    # unmanned platform and an interceptor expose different useful depths;
    # accept any two complementary implementation groups and let the model
    # omit layers that do not change the mission result.
    architecture_groups = (
        ("硬件", "平台", "载荷", "产品", "组件", "架构"),
        ("软件", "任务系统", "算法", "控制", "火控", "接口", "数据流"),
        ("子系统", "集成", "输入输出", "保障", "测试", "发射", "战斗部"),
    )
    if sum(has_any(*group) for group in architecture_groups) < 2:
        issues.append("总体方案未落到足以改变任务结果的装备、软件、接口或集成边界")
    if not (
        has_any("技术名称", "核心技术", "技术点", "关键技术")
        and has_any("技术内涵", "技术原理", "实现机理", "解决", "作用对象", "关键难点")
        and has_any("攻关途径", "技术路线", "研发路径", "研制路径", "攻关", "试验")
    ):
        issues.append("关键技术需逐项给出技术名称、技术内涵和攻关途径")
    if not all(term in text for term in ("参与单位", "技术基础")):
        issues.append("研制基础缺少参与单位或技术基础")
    return issues


def _report_three_layer_content_issues(text: str) -> list[str]:
    issues: list[str] = []
    scenario_groups = (
        ("对手", "敌方", "威胁", "目标"),
        ("地域", "海空", "低空", "空域", "海域", "战区", "地形"),
        ("烈度", "高强度", "强对抗", "持续作战", "战损"),
        ("时间窗", "时敏", "窗口", "响应时间", "短时暴露"),
        ("约束", "强干扰", "弱通信", "断链", "带宽", "环境限制"),
    )
    missing_scenario = [
        "/".join(group[:2])
        for group in scenario_groups
        if not any(marker in text for marker in group)
    ]
    if len(missing_scenario) > 2:
        issues.append("三层九项中典型作战场景缺少足够的对手、环境、阶段或约束信息")

    if not (
        any(marker in text for marker in ("现有范式", "现有模式", "现有战法", "现有技术", "传统方案", "现役基线", "原方案"))
        and any(marker in text for marker in ("不足", "做不到", "难以", "失效", "受限", "断点", "瓶颈"))
        and any(marker in text for marker in ("制胜", "能赢", "优势", "取胜", "改善", "恢复", "直接效果"))
    ):
        issues.append("三层九项中制胜机理未说明现有范式为何不足及新概念为何能赢")

    capability_indicator_groups = (
        ("射程", "覆盖", "作用半径", "驻留"),
        ("响应时间", "响应", "决策周期", "反应时间"),
        ("自主等级", "自主边界", "自治", "授权"),
        ("成本量级", "单位成本", "交换比", "产能"),
        ("规模量级", "规模", "并发", "波次", "数量"),
        ("精度", "命中", "定位", "末制导"),
        ("生存力", "抗扰", "突防", "隐身", "抗毁"),
    )
    if sum(any(marker in text for marker in group) for group in capability_indicator_groups) < 2:
        issues.append("三层九项中装备能力特征缺少足够的定量指标方向")

    if not any(
        marker in text
        for marker in (
            "沿用改进", "集成创新", "原理突破", "升级改进", "系统集成", "组合创新",
            "新机理", "新构型", "突破", "采用现有技术", "自主研制",
        )
    ):
        issues.append("三层九项中能力实现途径未标注沿用改进、集成创新或原理突破")

    missing_technology = [
        label
        for label, markers in (
            ("具体技术点", ("制导律", "材料体系", "算法", "架构", "技术点", "技术清单", "传感器", "火控", "推进", "能源")),
            ("成熟度", ("成熟度", "TRL", "工程化", "样机", "现役", "在研", "基础")),
            ("瓶颈", ("瓶颈", "卡脖子", "短板", "约束", "难点", "风险")),
            ("优先级", ("P0", "P1", "P2", "高优先级", "中优先级", "低优先级", "优先级")),
        )
        if not any(marker in text for marker in markers)
    ]
    if len(missing_technology) >= 3:
        issues.append("三层九项中核心技术清单缺少：" + "、".join(missing_technology))

    if not (
        any(marker in text for marker in ("耦合", "依赖", "制约", "接口", "级联", "单点"))
        and any(marker in text for marker in ("卡脖子", "短板", "拖垮", "级联", "失效", "风险", "边界"))
    ):
        issues.append("三层九项中技术耦合与短板风险不完整")

    image_groups = (
        ("能力域", "能力方向", "形成能力", "作战能力"),
        ("指标画像", "指标谱", "指标特征", "射程", "响应", "成本", "规模", "边界"),
        ("谱系位置", "装备谱系", "相对现有装备", "现有装备体系", "基线", "替代关系"),
    )
    if sum(any(marker in text for marker in group) for group in image_groups) < 2:
        issues.append("三层九项中装备能力图像缺少能力域、指标画像或谱系位置")

    if not any(
        marker in text
        for marker in ("补链", "强链", "开链", "杀伤链", "任务链", "体系贡献", "替代链", "放大效应", "恢复能力")
    ):
        issues.append("三层九项中效能贡献未明确补链、强链或开链")
    if not any(
        marker in text
        for marker in ("突防率", "拦截率", "交换比", "决策周期", "闭环时间", "任务成功率", "压缩量级", "提升量级", "改善量级", "持续波次", "单位成本")
    ):
        issues.append("三层九项中效能贡献缺少可量化评估方向")

    if not (
        any(marker in text for marker in ("P0", "P1", "P2", "高优先级", "中优先级", "低优先级"))
        and any(marker in text for marker in ("演示验证", "验证项目", "演示项目", "样机验证", "试验", "试制", "近期抓手", "工程推进"))
        and any(marker in text for marker in ("通过条件", "失败条件", "判据", "验收指标", "失效边界", "适用边界", "判退", "待验证", "证据边界"))
    ):
        issues.append("三层九项中发展优先级或近期演示验证抓手不完整")
    return issues


def _report_domain_attribute_issues(
    text: str,
    payload: Mapping[str, Any],
) -> list[str]:
    """Keep an explicitly requested equipment domain visible without forcing a catalogue."""

    seed = payload.get("synthesis_seed", {})
    cues = seed.get("capability_cues", []) if isinstance(seed, Mapping) else []
    context = " ".join(
        [
            str(payload.get("topic", "")),
            str(payload.get("supplemental_information", "")),
            " ".join(
                str(item.get("direction", ""))
                for item in cues
                if isinstance(item, Mapping)
            ),
        ]
    )
    domain_required = (
        any(term in context for term in ("无人", "巡飞弹", "蜂群", "无人僚机"))
        and any(
            term in context
            for term in ("远程", "远域", "防区外", "精确打击", "精确制导", "火力")
        )
    )
    if not domain_required:
        return []

    issues: list[str] = []
    if not (
        any(term in text for term in ("无人", "巡飞弹", "无人僚机", "无人集群", "无人平台"))
        and any(term in text for term in ("远程", "远域", "防区外", "纵深", "战区", "前出"))
        and any(term in text for term in ("精确打击", "精确制导", "毁伤", "压制", "歼灭", "拒止", "拦截", "打击"))
    ):
        issues.append("领域属性不符合无人远程火力打击装备研究，或被通信/C2/保障内容稀释")

    project_mode = _report_template_mode(payload) == "project_argument_v1"
    capability_pattern = (
        r"^###\s*（一）装备图像概述\s*$\n(?P<body>.*?)(?=^###\s*（二）作战运用模式\s*$)"
        if project_mode
        else r"^###\s*⑦\s*装备能力图像\s*$\n(?P<body>.*?)(?=^###\s*⑧\s*效能贡献评估\s*$)"
    )
    section = re.search(
        capability_pattern,
        text,
        flags=re.MULTILINE | re.DOTALL,
    )
    capability_body = section.group("body") if section else ""
    capability_directions = _report_capability_image_table_directions(capability_body)
    image_text = capability_body or text
    if not (
        (len(capability_directions) >= 1 or any(term in image_text for term in ("无人", "巡飞弹", "无人平台", "导弹", "弹药")))
        and any(
            term in image_text
            for term in (
                "能力域", "形成能力", "指标画像", "指标特征", "指标谱", "作战效果", "毁伤", "压制", "突防",
            )
        )
        and sum(
            term in image_text
            for term in ("作战运用", "运用概念", "编组", "波次", "待机", "部署", "发射", "突防", "交战", "巡飞")
        ) >= 1
    ):
        issues.append("装备能力图像需包含至少一项具体武器装备，并同时给出能力域、指标画像和作战运用概念")

    # Three-track labels are an optional analytical lens; require only a
    # query-specific comparison or effect change, not all three slogans.
    if not (
        any(term in text for term in ("现役效能跃升", "效能跃升", "战力跃升", "相对基线", "相较现役", "相对现有"))
        and any(term in text for term in ("作战效果", "直接效果", "任务成功", "突防", "毁伤", "压制", "拒止", "成本交换"))
    ):
        issues.append("制胜效能需说明相对现有基线改变了何种作战效果或交换关系")

    if not (
        any(term in text for term in ("创新", "新增机制", "新能力", "新研", "改进", "构型变化", "技术路线"))
        and any(term in text for term in ("相较", "相比", "相对基线", "传统", "从", "转向", "替代", "改变"))
        and any(term in text for term in ("颠覆", "重构", "突破", "改变", "新增机制", "关系变化", "效能变化"))
        and any(term in text for term in ("对手反适应", "反适应", "失效边界", "失败条件", "适用边界", "工程边界", "证据边界"))
    ):
        issues.append("创新性需说明相对基线改变的作战关系，并给出对手反适应或失效边界")

    if not (
        any(term in text for term in ("成熟度", "TRL", "工程化", "样机", "现役改装", "基础", "在研"))
        and any(term in text for term in ("瓶颈", "短板", "工程风险", "集成风险", "约束", "难点"))
        and any(term in text for term in ("公开证据", "证据不足", "待验证", "待核验", "事实", "推断", "假设", "来源"))
        and any(term in text for term in ("试验验证", "演示验证", "验证指标", "通过条件", "失败条件", "失效边界", "适用边界", "判退", "证据边界", "反适应"))
    ):
        issues.append("可实现性论证需给出成熟度、瓶颈、证据边界和装备专属判退/适用边界，杜绝无证据结论")
    return issues


def _report_markdown_structure_issues(
    text: str,
    payload: Mapping[str, Any],
) -> list[str]:
    issues: list[str] = []
    project_mode = _report_template_mode(payload) == "project_argument_v1"
    canonical_h2, canonical_h3, canonical_h4 = _report_canonical_headings(payload)
    headings = [
        (len(match.group(1)), match.group(2).strip())
        for match in re.finditer(r"^(#{1,6})\s+(.+?)\s*$", text, flags=re.MULTILINE)
    ]
    h1 = [title for level, title in headings if level == 1]
    if h1:
        issues.append("报告格式不应输出一级标题，标题由交付层统一添加")
    maximum_depth = 4 if project_mode else 3
    if any(level > maximum_depth for level, _ in headings):
        issues.append(f"报告格式标题层级超过{maximum_depth}级，需合并碎片化小节")
    raw_h2 = [title for level, title in headings if level == 2]
    h2 = [
        re.sub(r"^\d+(?:\.\d+)*[、.．]?\s*", "", title).strip()
        for title in raw_h2
    ]
    if raw_h2 != h2:
        issues.append("报告格式固定二级标题不得添加数字序号")
    missing = [title for title in canonical_h2 if title not in h2]
    if missing:
        issues.append("报告格式缺少固定二级章节：" + "、".join(missing))
    unexpected = [title for title in h2 if title not in canonical_h2]
    if unexpected:
        issues.append("报告格式存在契约外二级标题：" + "、".join(unexpected))
    if len(h2) != len(canonical_h2):
        issues.append(
            f"报告格式二级标题应恰好{len(canonical_h2)}个，实际{len(h2)}个"
        )
    positions = [h2.index(title) for title in canonical_h2 if title in h2]
    if positions != sorted(positions):
        issues.append("报告格式二级章节顺序混乱")
    duplicate_h2 = sorted({title for title in h2 if h2.count(title) > 1})
    if duplicate_h2:
        issues.append("报告格式存在重复二级标题：" + "、".join(duplicate_h2))
    h3 = [title for level, title in headings if level == 3]
    missing_h3 = [title for title in canonical_h3 if title not in h3]
    if missing_h3:
        issues.append("报告格式缺少固定三级项：" + "、".join(missing_h3))
    unexpected_h3 = [title for title in h3 if title not in canonical_h3]
    if unexpected_h3:
        issues.append("报告格式存在契约外三级标题：" + "、".join(unexpected_h3))
    if len(h3) != len(canonical_h3):
        issues.append(
            f"报告格式三级标题应恰好{len(canonical_h3)}个，实际{len(h3)}个"
        )
    h3_order_ok = (
        h3 == list(canonical_h3)
        if project_mode
        else [h3.index(title) for title in canonical_h3 if title in h3]
        == sorted(h3.index(title) for title in canonical_h3 if title in h3)
    )
    if not h3_order_ok:
        issues.append("报告格式九个三级项顺序混乱")
    duplicate_h3 = sorted(
        {
            title
            for title in h3
            if h3.count(title) > list(canonical_h3).count(title)
        }
    )
    if duplicate_h3:
        issues.append("报告格式存在重复三级标题：" + "、".join(duplicate_h3))
    h4 = [title for level, title in headings if level == 4]
    if project_mode:
        missing_h4 = [title for title in canonical_h4 if title not in h4]
        unexpected_h4 = [title for title in h4 if title not in canonical_h4]
        if missing_h4:
            issues.append("报告格式缺少固定四级项：" + "、".join(missing_h4))
        if unexpected_h4:
            issues.append("报告格式存在契约外四级标题：" + "、".join(unexpected_h4))
        if len(h4) != len(canonical_h4):
            issues.append(
                f"报告格式四级标题应恰好{len(canonical_h4)}个，实际{len(h4)}个"
            )
        h4_positions = [h4.index(title) for title in canonical_h4 if title in h4]
        if h4_positions != sorted(h4_positions):
            issues.append("报告格式固定四级项顺序混乱")
    previous_level = 0
    for level, _ in headings:
        if previous_level and level > previous_level + 1:
            issues.append("报告格式存在跨级标题")
            break
        previous_level = level
    if headings and headings[0] != (2, canonical_h2[0]):
        issues.append(
            f"报告格式正文必须从“## {canonical_h2[0]}”开始"
        )
    normalized_headings = [
        (level, re.sub(r"\s+", "", title)) for level, title in headings
    ]
    expected_heading_counts = {
        (2, re.sub(r"\s+", "", title)): list(canonical_h2).count(title)
        for title in canonical_h2
    }
    expected_heading_counts.update(
        {
            (3, re.sub(r"\s+", "", title)): list(canonical_h3).count(title)
            for title in canonical_h3
        }
    )
    expected_heading_counts.update(
        {
            (4, re.sub(r"\s+", "", title)): list(canonical_h4).count(title)
            for title in canonical_h4
        }
    )
    duplicate_headings = sorted(
        {
            title
            for level, title in normalized_headings
            if normalized_headings.count((level, title))
            > expected_heading_counts.get((level, title), 1)
        }
    )
    if duplicate_headings:
        issues.append("报告格式存在重复标题：" + "、".join(duplicate_headings[:6]))
    h3_count = sum(level == 3 for level, _ in headings)
    if h3_count > len(canonical_h3):
        issues.append(
            f"报告格式三级标题共{h3_count}个，超过所选模板上限{len(canonical_h3)}个"
        )
    if _unbalanced_report_markdown(text):
        issues.append("报告格式存在未闭合的强调符号、代码标记或链接")
    # The project contract keeps Markdown structurally safe but leaves the
    # comparison shape to the model.  Legacy three-layer reports retain the
    # historical compact-table limits for backwards compatibility.
    issues.extend(_report_table_issues(text, project_mode=project_mode))
    return issues


def _unbalanced_report_markdown(text: str) -> bool:
    without_fences = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    emphasis = re.sub(r"\\\*", "", without_fences)
    if emphasis.count("**") % 2:
        return True
    inline_code = re.sub(r"\\`", "", without_fences)
    if inline_code.count("`") % 2:
        return True
    links = re.findall(r"\[[^\]]*\]\([^)]*$", without_fences, flags=re.MULTILINE)
    return bool(links)


def _report_table_issues(
    text: str,
    *,
    project_mode: bool = False,
) -> list[str]:
    issues: list[str] = []
    tables: list[list[str]] = []
    current: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("|") and line.endswith("|"):
            current.append(line)
            continue
        if current:
            tables.append(current)
            current = []
    if current:
        tables.append(current)
    for index, table in enumerate(tables, start=1):
        widths = [len(row.strip("|").split("|")) for row in table]
        if len(set(widths)) > 1:
            issues.append(f"报告格式第{index}个表格列数不一致")
        if not project_mode and widths and max(widths) > 6:
            issues.append(f"报告格式第{index}个表格超过6列")
        separator_valid = bool(
            len(table) >= 2
            and all(
                re.fullmatch(r":?-{3,}:?", cell.strip())
                for cell in table[1].strip("|").split("|")
            )
        )
        if not separator_valid:
            issues.append(f"报告格式第{index}个表格缺少合法Markdown分隔行")
        if len(table) < 3:
            issues.append(f"报告格式第{index}个表格没有数据行")
        data_rows = max(0, len(table) - 2) if separator_valid else 0
        if not project_mode and data_rows > 12:
            issues.append(f"报告格式第{index}个表格超过12行数据")
        cells = [
            cell.strip()
            for row in table
            for cell in row.strip("|").split("|")
        ]
        if any(len(cell) > 220 for cell in cells):
            issues.append(f"报告格式第{index}个表格存在超过220字的单元格")
        if project_mode and table:
            header = [cell.strip() for cell in table[0].strip("|").split("|")]
            if "作战概念与主要效果" in header:
                expected = ["武器装备", "核心技术", "形成能力", "作战概念与主要效果"]
                if header != expected:
                    issues.append("装备图像概述表头必须合并为四列：武器装备、核心技术、形成能力、作战概念与主要效果")
                elif any(width != 4 for width in widths):
                    issues.append("装备图像概述表必须保持四列，分隔行和数据行不得多列或少列")
                else:
                    column_labels = (
                        "武器装备",
                        "核心技术",
                        "形成能力",
                        "作战概念与主要效果",
                    )
                    for row_number, row in enumerate(
                        table[2:] if separator_valid else (),
                        start=1,
                    ):
                        row_cells = [cell.strip() for cell in row.strip("|").split("|")]
                        for column, label in enumerate(column_labels):
                            if not row_cells[column]:
                                issues.append(
                                    f"装备图像概述第{row_number}件武器的{label}为空"
                                )
    return issues


def _is_report_seed_copy_issue(issue: object) -> bool:
    text = str(issue).strip()
    return "前置研判" in text and "复用" in text


def _report_seed_copy_issues(
    text: str,
    payload: Mapping[str, Any],
) -> list[str]:
    seed = payload.get("synthesis_seed", {})
    if not isinstance(seed, Mapping):
        return []
    body = re.sub(r"[\s，。；：、,.!?！？‘’“”()（）\[\]【】]+", "", text)
    candidates: list[str] = []

    def visit(value: Any) -> None:
        if isinstance(value, str):
            cleaned = _clean_reporter_clue_text(value)
            normalized = re.sub(
                r"[\s，。；：、,.!?！？‘’“”()（）\[\]【】]+",
                "",
                cleaned,
            )
            if len(normalized) >= 72:
                candidates.append(normalized)
            return
        if isinstance(value, Mapping):
            for nested in value.values():
                visit(nested)
            return
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            for nested in value:
                visit(nested)

    visit(seed)
    matched_short_fragments: set[str] = set()
    for candidate in candidates:
        for start in range(0, max(1, len(candidate) - 95), 24):
            fragment = candidate[start : start + 96]
            if len(fragment) == 96 and fragment in body:
                return ["报告存在前置研判长段原句复用，应回到Query重构论证而非拼接材料"]
        for start in range(0, max(1, len(candidate) - 63), 24):
            fragment = candidate[start : start + 64]
            if len(fragment) == 64 and fragment in body:
                matched_short_fragments.add(fragment)
                if len(matched_short_fragments) >= 3:
                    return [
                        "报告多处复用前置研判原句，应回到Query重构论证而非拼接材料"
                    ]
    return []


def _report_v2_benchmark_issues(text: str) -> list[str]:
    """Check the legacy three-layer benchmark using semantic equivalents.

    This benchmark is advisory for quality profiles.  It should detect a
    missing argument, not force the Reporter to repeat a fixed vocabulary or a
    universal validation column.
    """

    issues: list[str] = []
    section_groups = {
        "场景约束": ("对手", "地域", "烈度", "时间窗", "约束条件"),
        "制胜机理": ("新战法", "新概念技术", "制胜机理"),
        "能力特征": ("能力特征", "能力域", "指标方向"),
        "实现途径": ("沿用改进", "集成创新", "原理突破"),
        "核心技术": ("核心技术", "技术点", "成熟度"),
        "耦合风险": ("耦合", "短板", "卡脖子"),
        "能力图像": ("能力图像", "谱系位置", "指标画像"),
        "效能贡献": ("补链", "强链", "开链", "效能贡献"),
        "发展抓手": ("发展优先级", "演示验证", "近期抓手"),
    }
    for label, markers in section_groups.items():
        if not any(marker in text for marker in markers):
            issues.append(f"三层九项报告缺少{label}实质内容")

    mapping_groups = {
        "任务效果": ("任务效果", "作战效果", "军事效果"),
        "功能组成": ("功能", "功能组成"),
        "性能或约束": ("性能", "约束", "边界条件"),
        "体系接口": ("体系接口", "接口"),
        "装备形态": ("装备形态", "装备建议", "装备需求"),
        "验证指标": (
            "验证指标",
            "验证口径",
            "验证路径",
            "关键指标",
            "试验指标",
            "考核指标",
            "验证边界",
            "失效边界",
            "适用边界",
            "判退",
            "证据边界",
            "待核验",
        ),
    }
    missing_mapping = [
        label
        for label, markers in mapping_groups.items()
        if not any(marker in text for marker in markers)
    ]
    if missing_mapping:
        issues.append("三层九项能力映射链缺项：" + "、".join(missing_mapping))

    if not any(marker in text for marker in ("事实", "公开资料", "公开来源", "来源", "据此", "资料显示")):
        issues.append("三层九项报告未明确标识事实依据")
    if not any(marker in text for marker in ("分析推断", "推断", "假设", "置信度", "判断", "预计", "推测")):
        issues.append("三层九项报告未区分推断、假设或置信度")

    uncertainty_markers = sum(
        marker in text
        for marker in (
            "未知",
            "证据边界",
            "关键假设",
            "替代解释",
            "冲突信息",
            "反证",
            "失效条件",
            "失效边界",
            "适用边界",
            "待核验",
            "不确定性",
            "工程约束",
        )
    )
    if uncertainty_markers < 2:
        issues.append("三层九项报告需至少覆盖两类未知、假设、替代解释、冲突或反证")

    prose_rows = []
    for block in re.split(r"\n\s*\n", text.strip()):
        row = " ".join(block.split()).strip()
        if not row or row.startswith(("#", "|", "- ", "* ")):
            continue
        if len(row) >= 100:
            prose_rows.append(row)
    normalized_rows = [
        re.sub(r"\[([^\]]+)\]\(https?://[^)]+\)", r"\1", row)
        for row in prose_rows
    ]
    if len(set(normalized_rows)) < len(normalized_rows):
        issues.append("报告格式存在完整段落重复")
    if any(len(row) > 1100 for row in prose_rows):
        issues.append("报告格式存在超过1100字的超长段落，应拆分主次")
    incomplete = [
        row
        for row in prose_rows
        if row[-1] in "，、（([【“‘："
        or row.endswith(("包括", "如下", "例如", "即", "以及", "并且", "从而"))
    ]
    if incomplete:
        issues.append("报告格式发现疑似未完成段落或断句")
    return issues


def _report_issues_require_fallback(issues: Sequence[str]) -> bool:
    """Return whether unresolved issues are substantive delivery blockers."""

    return bool(_report_delivery_blocking_issues(issues))


def _report_delivery_blocking_issues(issues: Sequence[str]) -> list[str]:
    """Block only publication-contract failures, not expert-style prose scoring."""

    advisory_prefixes = (
        "报告格式不应输出一级标题",
        "报告格式固定二级标题不得添加数字序号",
        "报告格式分支条目编号未完全标准化",
        "三层九项中",
        "项目论证模板",
        "国内外现状需",
        "建设必要性分析",
        "项目画像未",
        "作战运用模式",
        "体系贡献率分析",
        "总体方案未",
        "关键技术需",
        "研制基础缺少",
        "以下装备未成套说明敌方目标/反制、我方作战动作、直接战果与验证判据",
        "领域属性不符合",
        "装备能力图像需包含",
        "制胜效能需",
        "创新性需",
        "可实现性论证需",
        "报告仅自然体现",
        # Broad density/style findings remain advisory. Chapter-local copied
        # equipment prose is handled as a rewrite trigger by the model paths.
        "军事决策信息密度不足",
        "通用战略套话段比例过高",
        "跨章节长句复用过多",
    )
    return [
        str(issue).strip()
        for issue in issues
        if str(issue).strip()
        and not str(issue).strip().startswith(advisory_prefixes)
    ]


def _report_nonnegotiable_delivery_issues(issues: Sequence[str]) -> list[str]:
    """Return only failures that make a model-written report unsafe to deliver."""

    hard_markers = (
        "缺少新战法连续编号",
        "缺少战法组合连续编号",
        "缺少能力域连续编号",
        "缺少指标连续编号",
        "缺少传统能力缺口分支必需内容",
        "缺少核心规律连续编号",
        "缺少高置信场景连续编号",
        "缺少新兴装备类别连续编号",
        "缺少案例规律向未来战争迁移",
        "缺少当前分支必需章节",
        "正文仍包含过程性或内部表达",
        "正文引用了来源目录之外的URL",
        "未闭合",
        "疑似未完成段落或断句",
    )
    return [
        str(issue).strip()
        for issue in issues
        if str(issue).strip()
        and any(marker in str(issue) for marker in hard_markers)
    ]


def _branch_delivery_is_complete(payload: Mapping[str, Any]) -> bool:
    deliverables = payload.get("branch_deliverables", {})
    return (
        isinstance(deliverables, Mapping)
        and str(deliverables.get("delivery_status", "")).strip().lower()
        == "complete"
    )


def _c_branch_product_semantically_present(
    text: str,
    payload: Mapping[str, Any],
    *,
    label: str,
    expected: int,
) -> bool:
    """Accept C-branch wording variation when upstream products are complete."""

    key_and_markers = {
        "核心规律": ("case_patterns", ("核心规律", "案例规律", "跨案例规律")),
        "高置信场景": (
            "future_scenarios",
            ("高置信场景", "未来场景", "场景预测"),
        ),
        "新兴装备类别": (
            "emerging_equipment_categories",
            ("新兴装备类别", "新兴装备", "装备类别", "装备方向"),
        ),
    }
    product_key, markers = key_and_markers[label]
    deliverables = payload.get("branch_deliverables", {})
    if not isinstance(deliverables, Mapping):
        return False
    products = deliverables.get("products", {})
    if not isinstance(products, Mapping):
        return False
    rows = products.get(product_key, [])
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        return False
    if len([item for item in rows if str(item).strip()]) < expected:
        return False
    return any(marker in text for marker in markers)


def _report_required_section_present(text: str, requirement: str) -> bool:
    if requirement in text:
        return True
    known_markers = (
        "技术驱动",
        "任务机制",
        "技术机会",
        "成熟度",
        "可集成",
        "颠覆场景",
        "对抗失效",
        "未来窗口",
        "技术牵引",
        "装备形态",
        "能力需求",
        "需求卡片",
        "工程瓶颈",
        "建设时序",
        "验证路径",
        "对手能力",
        "威胁场景",
        "对冲机理",
        "触发信号",
        "体系脆弱",
        "级联失效",
        "补链强链",
        "替代链",
        "跨域缝隙",
        "协同模式",
        "弱网",
        "降级验证",
        "威胁扩散",
        "任务冲击",
        "高置信场景",
        "韧性",
        "非致命",
        "规则边界",
        "法律伦理",
        "军地协同",
    )
    expected = [marker for marker in known_markers if marker in requirement]
    if expected:
        required_hits = 1 if len(expected) == 1 else 2
        return sum(marker in text for marker in expected) >= required_hits
    parts = [
        item.strip()
        for item in re.split(r"[、，,；;与及/（）()]", requirement)
        if len(item.strip()) >= 3
    ]
    if not parts:
        return False
    required_hits = 1 if len(parts) == 1 else 2
    return sum(item in text for item in parts) >= required_hits


def _has_numbered_report_label(text: str, label: str, index: int) -> bool:
    return re.search(
        rf"{re.escape(label)}\s*[（(]?\s*0*{index}\s*[）)]?",
        text,
    ) is not None


def _report_evidence_ids(value: Any) -> list[str]:
    rows: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key).startswith("ev-"):
                rows.append(str(key))
            if isinstance(item, Mapping):
                candidate = item.get("evidence_id") or item.get("id")
                if candidate:
                    rows.append(str(candidate))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for item in value:
            if isinstance(item, Mapping):
                candidate = item.get("evidence_id") or item.get("id")
                if candidate:
                    rows.append(str(candidate))
            elif str(item).startswith("ev-"):
                rows.append(str(item))
    return list(dict.fromkeys(item for item in rows if item))


def _normalize_report_summary(text: str) -> str:
    """报告摘要必须是可读Markdown。

    模型偶尔会输出结构化JSON（artifact_type/report_body等）。此时提取正文
    字段拼成可读文本，避免JSON直接进入 report.md 执行摘要。
    """
    stripped = text.strip()
    while stripped.startswith("#"):
        first_line, separator, remainder = stripped.partition("\n")
        heading = first_line.lstrip("#").strip()
        if heading not in {"执行摘要", "综合研判摘要", "能力画像研究报告"}:
            break
        stripped = remainder.lstrip() if separator else ""
    if not stripped.startswith("{"):
        return _limit_report_summary(stripped)
    payload = _parse_json_object(stripped)
    if not payload:
        return stripped
    parts: list[str] = []
    for key in ("executive_summary", "report_body"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    if not parts:
        # 找不到已知正文字段则保留原文本
        return _limit_report_summary(stripped)
    return _limit_report_summary("\n\n".join(parts))


def _limit_report_summary(text: str, *, max_chars: int = 16_000) -> str:
    stripped = text.strip()
    if len(stripped) <= max_chars:
        return stripped
    cut = max(
        (stripped.rfind(marker, 0, max_chars) for marker in ("。", "；", "\n")),
        default=-1,
    )
    if cut < max_chars // 2:
        cut = max_chars
    return stripped[: cut + 1].rstrip() + "\n\n（分支深度正文已按报告长度上限截取。）"


# Resolve the legacy coordinator namespace only after every support helper has
# been defined.  This is safe both when coordinator imports us at module tail
# and when an embedding imports reporting_support directly.
_sync_legacy_globals()

__all__ = ['_report_template_mode', '_coerce_report_template_mode', '_report_canonical_headings', '_report_has_complete_canonical_structure', '_canonical_report_h2', '_canonical_report_h3', '_canonical_report_h4', '_normalize_report_structure_deterministically', '_report_capability_cues', '_report_capability_cue_is_substantive', '_report_capability_portrait_markdown', '_limit_report_capability_cues', '_remove_empty_report_clauses', '_normalized_report_reuse_text', '_report_matrix_verification_mechanism', '_reflow_long_report_paragraphs', '_stabilize_report_delivery_contract', '_report_issues_are_deterministic_format_only', '_project_argument_report_writer_system_prompt', '_report_writer_system_prompt', '_report_repair_system_prompt', '_clean_winning_hypothesis_title', '_winning_portfolio_title', '_winning_combat_scene', '_winning_primary_equipment_form', '_winning_title_has_concrete_equipment_identity', '_prioritize_equipment_evidence_refs', '_is_remote_precision_portfolio_direction', '_report_branch', '_report_target_chars', '_unbounded_quality_report', '_report_hard_max_chars', '_clip_complete_report_phrase', '_compact_report_table_row', '_normalize_report_line_ending', '_enforce_report_hard_max', '_report_writer_max_chars', '_reporter_output_token_budget', '_strip_report_internal_markers', '_clean_reporter_clue_text', '_mark_reporter_handoff_rewrite_boundaries', '_sanitize_reporter_output', '_normalize_branch_report_labels', '_normalize_numbered_report_title_group', '_reporter_generation_payload', '_compact_reporter_branch_products', '_reporter_repair_payload', '_reporter_timeout_retry_payload', '_reporter_agent_contract', '_reporter_revision_notes', '_report_issue_code', '_report_capability_image_table_directions', '_report_equipment_attribution_issues', '_report_fragment_quality_issues', '_report_draft_quality_issues', '_report_project_argument_content_issues', '_report_three_layer_content_issues', '_report_domain_attribute_issues', '_report_markdown_structure_issues', '_unbalanced_report_markdown', '_report_table_issues', '_is_report_seed_copy_issue', '_report_seed_copy_issues', '_report_v2_benchmark_issues', '_report_issues_require_fallback', '_report_delivery_blocking_issues', '_report_nonnegotiable_delivery_issues', '_branch_delivery_is_complete', '_c_branch_product_semantically_present', '_report_required_section_present', '_has_numbered_report_label', '_report_evidence_ids', '_normalize_report_summary', '_limit_report_summary']
