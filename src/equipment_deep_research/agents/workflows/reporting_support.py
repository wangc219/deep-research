"""Reporter generation, normalization and quality support.

Kept separate from provider transport and from the S1-S6 workflow.
"""
# ruff: noqa: F821

from __future__ import annotations

from equipment_deep_research.agents.workflows import coordinator as _legacy


def _sync_legacy_globals() -> None:
    globals().update(
        {
            name: value
            for name, value in vars(_legacy).items()
            if not name.startswith("__")
        }
    )


_sync_legacy_globals()

def _report_template_mode(payload: Mapping[str, Any]) -> str:
    value = str(payload.get("report_template_mode", "")).strip()
    return value if value in {"three_layer_nine_item", "project_argument_v1"} else "three_layer_nine_item"


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


def _report_has_complete_canonical_structure(text: str) -> bool:
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


def _canonical_report_h2(title: str) -> str:
    normalized = re.sub(r"\s+", "", title)
    normalized = re.sub(r"^\d+(?:\.\d+)*[、.．]?", "", normalized)
    for canonical in (*_REPORT_CANONICAL_H2, *_PROJECT_REPORT_CANONICAL_H2):
        if normalized == re.sub(r"\s+", "", canonical):
            return canonical
    for index, markers in enumerate(
        (
            ("第一层", "需求挖掘层"),
            ("第二层", "技术攻关层"),
            ("第三层", "能力图像与效能贡献层"),
        )
    ):
        if any(marker in normalized for marker in markers):
            return _REPORT_CANONICAL_H2[index]
    for canonical in _PROJECT_REPORT_CANONICAL_H2:
        label = re.sub(r"^[一二三四五]、", "", canonical)
        if label in normalized:
            return canonical
    return ""


def _canonical_report_h3(title: str) -> str:
    normalized = re.sub(r"\s+", "", title).strip("：:、.．")
    for canonical in _PROJECT_REPORT_CANONICAL_H3:
        if normalized == re.sub(r"\s+", "", canonical):
            return canonical
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


def _normalize_report_structure_deterministically(text: str) -> str:
    """Normalize report headings without regenerating or rewriting prose.

    Reporter occasionally emits a report title, a source index, duplicate
    canonical headings, or a semantically equivalent heading label.  Those are
    cheap deterministic presentation defects, so normalize/downgrade only the
    heading line and preserve every substantive body line unchanged.
    """

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
        canonical_h2 = _canonical_report_h2(title)
        canonical_h3 = _canonical_report_h3(title)
        canonical_h4 = _canonical_report_h4(title)
        if level >= 4 and canonical_h4:
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
            parent_h2 = _PROJECT_REPORT_H3_PARENT.get(canonical_h3, "")
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
            public_rows = [
                public_cue(item) for item in rows if isinstance(item, Mapping)
            ][:12]
            if public_rows:
                return public_rows
    handoff = payload.get("research_handoff", {})
    if isinstance(handoff, Mapping):
        rows = handoff.get("capability_cues", [])
        if isinstance(rows, Sequence) and not isinstance(rows, (str, bytes)):
            return [public_cue(item) for item in rows if isinstance(item, Mapping)][:12]
    return []


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
        if re.match(r"^(?:若|如果|一旦|当)", stripped):
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
    cues = _report_capability_cues(payload)
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
    lines = str(text or "").splitlines()
    stabilized: list[str] = []
    in_capability_section = False
    for raw_line in lines:
        stripped = raw_line.strip()
        if re.match(capability_start, stripped):
            in_capability_section = True
        elif re.match(capability_end, stripped):
            in_capability_section = False
        if in_capability_section and stripped.startswith("|") and stripped.endswith("|"):
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
    if coupling_rows:
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
                    "\n\n逐项耦合校核如下；这些判断只规定验证关系，不替代试验数据。\n"
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
    result = re.sub(
        r"(?m)(^|[；：|]\s*)通过条件(?:为)?(?=\s*(?:[。；|]|$))",
        lambda match: (
            match.group(1)
            + "通过条件需在对应试验场景、基线与统计口径下明确"
        ),
        result,
    )

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
                or "覆盖、响应、自主边界、成本、规模与生存性按装备任务分别校准"
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
        if table_indexes:
            table_start, table_end = min(table_indexes), max(table_indexes)
            body_lines = [
                *body_lines[:table_start],
                *canonical_table,
                *body_lines[table_end + 1 :],
            ]
        else:
            detail_indexes = [
                index
                for index, line in enumerate(body_lines)
                if "逐装备详细能力画像如下" in line
                or any(
                    f"**{name}｜装备能力画像**" in line
                    for name in cue_by_name
                )
            ]
            detail_index = min(detail_indexes) if detail_indexes else len(body_lines)
            insertion = [*canonical_table, ""]
            if detail_index > 0 and body_lines[detail_index - 1].strip():
                insertion.insert(0, "")
            body_lines = [
                *body_lines[:detail_index],
                *insertion,
                *body_lines[detail_index:],
            ]
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
    if capability_match and cue_by_name:
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
    if effect_match and cue_by_name:
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
    if priority_match and cue_by_name:
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
                or "按覆盖、响应、自主边界、单位任务成本、并发规模和生存性设置指标",
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
                re.sub(r"\n{3,}", "\n\n", result).strip()
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
    quality_profile = str(payload.get("execution_profile_id", "")) in {
        "swarm_quality_v1",
        "winning_swarm_dynamic_v2",
    }
    query_led_clause = (
        "本次属于质量集群/动态蜂群报告收敛：Query是论证主轴，前置集群交接是已经筛选的高价值"
        "证据与机理种子，不是待复述的提纲。写作前在内部围绕Query形成3至5个相互竞争的解释框架，"
        "至少比较任务链续接、对手行动—反行动、成本交换、规模补充和接口闭合中的相关框架，再用"
        "research_handoff中的决定性锚点、断点、能力方向、反证和公开来源收敛为一条主论证。"
        "每节必须回答‘矛盾为何成立—现有方案为何不足—项目如何改变任务结果—怎样验证—何时失效’，"
        "不得输出‘需补充资料’‘以某字段交接为准’‘形成一体化方案’等可套用于任意课题的模板句。"
        "写作目标只是最低深度参照，不是字符上限；允许报告随证据和论证完整度自然增长，绝不得为了"
        "压缩而删去具体装备事实、逐项能力画像、来源映射、反证、验证边界或项目落地建议。"
        if quality_profile
        else ""
    )
    return (
        "你是独立的军事装备项目论证报告Reporter。只输出中文Markdown正文，不输出一级标题、"
        "研究流程、Agent名称、内部编号、攻击坐标、可执行打击步骤或无来源精确参数。"
        + query_led_clause
        + f"正文以{target_chars}作为容量规划参考而非最低字数，按以下五章模板完整写作，二级、三级、四级标题必须逐字一致且顺序固定。"
        "报告质量以军事战场决策信息密度衡量，不以篇幅衡量：每段必须提供具体装备/项目事实、战场矛盾、"
        "因果结论、证据与不确定性、对手反适应、验证判据或建设取舍中的至少一项；通用形势套话、重复背景、"
        "跨章节同义复述和只扩写字段的段落必须删除。能用更短篇幅闭合论证时立即收束。"
        "第一章‘## 一、需求分析’包含‘### （一）需求概述’、‘### （二）国内外现状’、"
        "‘### （三）建设必要性分析’。需求概述下必须依次使用‘#### 1. 背景分析’、"
        "‘#### 2. 需求阐述’、‘#### 3. 项目画像’：背景分析从国际形势、军事战略与装备竞争顶层展开；"
        "需求阐述从问题、难点和任务需求引出项目内涵；项目画像概述项目特点、总体方案和关键技术如何解题。"
        "国内外现状下必须依次使用‘#### 1. 国外情况’、‘#### 2. 国内现状（中国）’、"
        "‘#### 3. 对比小结’。国外优先美国、俄罗斯等军事技术强国，中国国内单列；每个具体案例自成一段，"
        "同时写清所解决问题/难点、装备或项目、参与单位、状态、技术方案途径、核心技术、带条件的公开指标、"
        "实证来源和证据边界；有可用图片URL时以Markdown图片或链接呈现，不得虚构图片。国外与国内均须分别"
        "从‘问题/难点如何解决’和‘核心技术/技术途径研究情况’两个方面组织。对比小结分别概括双方优势、"
        "短板并凸显本项目的差异化优势。若公开资料不足，明确写‘公开资料不足/待核验’，不得造型号、单位或指标。"
        "建设必要性下必须依次使用‘#### 1. 作战使用角度’、‘#### 2. 装备能力提升角度’、"
        "‘#### 3. 领域占位角度’、‘#### 4. 综合效益’，每个维度至少形成一个完整论证段，并可展开多条。"
        "第二章‘## 二、项目画像’包含‘### （一）装备图像概述’、‘### （二）作战运用模式’、"
        "‘### （三）体系贡献率分析’、‘### （四）主要战技指标’。装备图像概述逐项保留全部能力方向原名，"
        "围绕五列表格所需的‘装备系统方向、装备平台与方案、核心技术、形成能力、作战概念与主要效果’形成"
        "短而有比较价值的装备组合判断。表格和已通过S6硬门的逐装备‘精简概述+四个受控分点’画像由交付层"
        "按capability_cues.direction原名确定性重建与注入，Reporter不得复制、改写或扩写画像全文；"
        "应把模型篇幅用于比较发射域/平台、目标运动包线、末制导传感器、授权来源、补击时序、专属指标和建设取舍。"
        "能力方向标题必须以中文具体武器装备为主体，英文型号仅作为公开基线或括号对照，不得位于标题开头。"
        "标题只命名最终形成的具体武器装备及其差异化构型/任务特征，禁止以升级、能力、体系、方向、包或套件收尾；"
        "现役改进关系只在谱系、公开基线和改装内容中说明，不得替代装备名称。"
        "作战运用模式下必须依次使用"
        "‘#### 1. 作战运用流程’和‘#### 2. 链路闭环分析’；流程按任务准备、部署进入、目标发现/确认、"
        "火力分配、交战毁伤、评估与再组织等阶段说明装备如何使用、何时发挥作用及指标口径；链路闭环围绕"
        "时间链、信息/精度链、火力链、毁伤评估链等关键链路说明制胜逻辑。体系贡献率把项目嵌入现有装备体系，"
        "与原方案比较耗弹量、突防效能、任务成功率、闭环时间、交换比、持续波次等可校准指标；无数据只给"
        "计算口径、基线、变量、验证方法和待校准边界。主要战技指标以表格列出指标名称、定义、目标方向、"
        "测试条件、验证方法和证据状态，不得补造点值。"
        "第三章‘## 三、总体方案’包含‘### （一）总体架构’和‘### （二）子系统方案’，"
        "先给平台—载荷—感知—火控—通信—任务软件—保障/测试的总架构，再把方案落到硬件产品、软件系统、"
        "接口、数据流、关键输入输出和集成边界。第四章‘## 四、关键技术’包含"
        "‘### （一）关键技术清单与攻关途径’，逐项给出技术名称、技术内涵、成熟度/基础、瓶颈、攻关途径、"
        "验证指标和失败条件。第五章‘## 五、研制基础’包含‘### （一）参与单位’和‘### （二）技术基础’，"
        "参与单位只能使用输入和公开来源支持的单位；无依据时列出所需单位类型与待明确项，不得虚构。技术基础"
        "结合各方已有平台、样机、算法、试验设施、产线或供应链基础说明对项目的支撑关系。"
        "能力画像概述建议保持简洁，必须逐项按‘面向场景—针对问题—具体武器装备主体—利用原理—"
        "采用技术—通过作战概念及关键流程—形成能力—实现效果’完整展开；七个因果节点均须填入该装备专属内容，"
        "详细制胜机理、边界和验证放入后续分点。"
        "概述中的场景必须是真实战役/战斗阶段和作战地域，至少写清敌方目标/威胁与反制动作、我方具体"
        "发射或运用主体、时敏交战流程和直接战场结果；不得把‘装备研究中的任务阶段’或‘公开资料/公开基线"
        "不能证明’写成场景与问题，证据不足只能放在对抗边界、验证路径或证据状态中。"
        "research_handoff.capability_cues用于装备画像、流程、指标、"
        "总体方案和关键技术；research_handoff.comparative_status用于国内外现状；public_sources是唯一"
        "允许新增引用的URL目录。相同判断只写一次，事实、推断、假设、指标目标和待验证项必须明确分层。"
    )


def _report_writer_system_prompt(payload: Mapping[str, Any]) -> str:
    if _report_template_mode(payload) == "project_argument_v1":
        return _project_argument_report_writer_system_prompt(payload)
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
            "必须完整消费，尤其⑦必须逐项保留direction原名，形成装备系统方向、能力域、指标画像、"
            "作战运用概念和谱系位置的横向表；不得把表头当正文、不得只输出空表，也不得因移除制胜"
            "机理而删除能力画像。可说明其仍缺制胜机理验证，但不能把‘未执行S1-S6’等同于‘无装备画像’。"
            "URL只能使用public_sources中给出的地址。若基线不足，明确写未知或需进一步核验。"
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
            "public_sources。关键判断必须绑定输入证据或明确标为待验证假设。模型不输出一级标题；只用"
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
            "装备构型与验证指标。装备需求不得以抽象能力域为主对象，应优先落到与Query直接匹配的"
            "无人作战平台、低空无人机、导弹、巡飞弹、精确制导弹药、拦截弹或其他承担歼灭、打击、"
            "压制、毁伤、拒止和威慑任务的战斗装备。"
        )
    return (
        "你是全新、独立的军事装备市场需求研究Reporter；本次没有历史会话。"
        f"围绕输入Query撰写正文，以{target_chars}为写作目标，吸收{branch or '当前'}分支高价值成果。"
        "核心正文达到约9000字且三层九项已经闭环后，完成当前句和当前段便立即结束，不再扩写旁支。"
        "交付层会把输入中已经确定的逐装备验证字段合并进正文，最终报告可随论证完整度自然超过核心正文目标；"
        "你不得为追逐字数重复论证。"
        "正文自然超出目标完全允许；绝不因为长度而压缩、重写、降级或判定失败。"
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
        "当Query或输入能力方向属于无人远程火力打击装备领域时，首次成稿还必须通过五项领域硬门："
        "一是领域属性符合性，正文持续围绕无人平台、远程火力、精确毁伤及其对抗边界，通信/C2/保障"
        "只能作为内嵌依赖；二是装备能力图像同时给出具体装备能力、指标画像和作战运用概念；三是⑧中"
        "明确区分‘现役效能跃升’、‘传统赛道跨代优势’和‘新概念赛道开辟’三类制胜贡献；四是说明"
        "创新方向改变的传统关系、对手反适应和失效边界；五是成熟度、实现路径、工程瓶颈、公开证据"
        "边界和待验证指标成套出现，无证据时写待验证或保留类别级，禁止把推断包装为已实现能力。"
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
        "伪装、假目标、通信、工程、恢复、评估和保障原则上只能作为横向支撑层，只有Query明确聚焦时"
        "才可最多单列1项。逐项形成能力域、指标画像、边界、颠覆的传统关系及相对现有装备谱系位置；"
        "指标画像必须优先使用capability_cues.indicator_portrait，使不同装备分别突出射程/覆盖、响应、"
        "自主边界、成本、规模、驻留或生存性，允许各自写待试验校准，但禁止所有行复制同一占位句。"
        "不得只给两个抽象能力方向。⑦必须逐项使用research_handoff.capability_cues中的direction原名；"
        "表格第一列的行数和名称必须与输入完全一致，不得另造‘装备包’、保障节点、C2/任务网络或其他"
        "主体装备。已通过S6的capability_cues.capability_portrait由交付层确定性注入；Reporter不得复制、"
        "改写、扩写或另写一套逐装备画像。弱网、通信、保障、能源、补给和任务软件只允许写入对应武器装备的体系依赖、技术耦合"
        "或使用边界。⑧按补链、"
        "强链、开链评估对杀伤链和体系的贡献，并给出突防率、交换比、决策周期等可量化方向，不能虚构"
        "精确提升值。⑨给出P0/P1/P2或高/中/低优先级、排序理由和近期演示验证项目构想，写清场景、样机"
        "范围、关键考核指标、通过/失败条件、依赖和风险。"
        "军事价值必须具体落到侦察决策、打击歼灭、压制反制、毁伤、拒止威慑、抗毁恢复或持续作战。"
        "装备类别证据充分时给出公开型号或谱系锚点；证据只能支持类别判断时明确写‘公开证据不足，"
        "保留类别级’，不得虚构型号、参数或效能。关键判断区分事实、推断和假设；不确定性、反证、"
        "来源质量与失效边界嵌入相关九项，不另设附加章节。表格只用于高密度能力、技术、耦合、效能或"
        "优先级比较，最多6列、12行；其余使用短段落或项目符号，同一判断只写一次。"
        + branch_delivery_clause
        + "正文嵌入3至6条[来源名](URL)，只用输入来源，不虚构数字或来源；前置卡片、全景图和映射只做交叉归纳，避免复述。"
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
    """Break long prose spans without deleting any Reporter handoff content."""

    if isinstance(value, Mapping):
        marked: dict[Any, Any] = {}
        for key, item in value.items():
            if str(key) == "direction" and isinstance(item, str):
                marked[key] = _REPORTER_CANDIDATE_PREFIX_RE.sub("", item).strip()
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
    brief = payload.get("branch_writer_brief", {})
    required_sections = []
    mandatory_content = []
    if isinstance(brief, Mapping):
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
            for item in capability_cues[:12]:
                if not isinstance(item, Mapping):
                    continue
                cue_field_limits = [
                    ("direction", 80),
                    ("mission_effect", 130),
                    ("capability_gap", 110),
                    ("mechanism_hint", 120),
                    ("target_scenario", 140),
                    ("problem_statement", 140),
                    ("scientific_principle", 120),
                    ("operational_concept", 150),
                    ("capability_outcome", 120),
                    ("winning_mechanism", 150),
                    ("equipment_hint", 100),
                    ("public_equipment_baseline", 110),
                    ("future_trigger", 100),
                    ("disruptive_relationship", 120),
                    ("development_path", 110),
                    ("indicator_portrait", 220),
                    ("coupling_risk", 220),
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
    project_mode = _report_template_mode(payload) == "project_argument_v1"
    pre_submission_checks = [
        "三个固定二级层和九个固定三级项齐全且顺序正确",
        "场景—战法/技术—能力特征—实现途径—核心技术—耦合风险—能力图像—效能贡献—发展抓手形成闭环",
        "分支规定成果已压缩融入九项，不另设平行模板",
        "相同判断不在能力特征、能力图像和效能贡献中重复展开",
        "所有段落以完整句结束且无超过1100字的超长段落；每段至少提供具体装备/项目事实、战场矛盾、因果判断、证据边界、反适应、验证或建设取舍之一",
        "建设优先序使用高/中/低或P0/P1/P2等显式等级并说明排序理由",
        "能力实现途径明确标注沿用改进/集成创新/原理突破",
        "核心技术逐项包含成熟度、瓶颈和攻关优先级，效能贡献明确补链/强链/开链",
        "⑥逐项使用capability_cues.coupling_risk说明依赖、级联和会拖垮任务闭环的单点短板",
        "装备能力图像横向比较输入中全部具体且机制互异、证据闭环的武器装备方向，不得压缩为抽象主题",
        "⑦逐项保留输入中的全部具体装备方向；支撑能力放在表外，不得替换或另造主体方向",
        "⑦只写横向比较与综合判断；逐装备‘精简概述+四个受控分点’由交付层从S6权威画像确定性注入，Reporter不得复制、改写、扩写或另写",
        "⑦若使用表格，第一列必须逐字使用capability_cues.direction，行数与输入方向数完全一致；禁止新增装备包、保障节点、C2/网络或其他主体方向",
        "⑦第三列逐项使用capability_cues.indicator_portrait形成不同的射程/覆盖、响应、自主、成本、规模或生存指标方向；不得六行统一写待校准",
        "最终论证优先自然体现与Query相关的多类关系变化，不展示维度方法论清单，"
        "也不为凑数量改写已经成立的具体装备因果链",
        "前瞻判断覆盖3至10年演进窗口、触发条件和不确定性",
        "核心正文达到约9000字且九项闭环后立即收尾；交付层使用既有S6字段补齐逐装备验证矩阵，任何长度均不触发重写、压缩、降级或失败",
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
            "五个固定二级章、十二个固定三级节和十二个固定四级项齐全且顺序正确",
            "需求概述完整覆盖背景分析、需求阐述和项目画像",
            "国内外现状分别覆盖国外和中国国内具体案例，每例含问题、技术途径、核心技术、指标、来源与边界",
            "建设必要性覆盖作战使用、装备能力提升、领域占位和综合效益四个维度",
            "项目画像逐项保留全部具体装备方向，标题以中文具体武器装备对象为主体且不得以升级、能力、体系、方向、包或套件收尾；已通过S6硬门的精简概述与四个受控分点由交付层按方向原名确定性注入，Reporter不得再次复制或改写全文，只负责横向差异、作战运用、体系贡献和指标取舍的高价值综合",
            "每张装备画像必须有不可由其他卡替代的差异变量，至少区分发射域/平台、目标运动包线、末制导传感器、授权来源、补击时序和专属验证指标中的两项；同一目标、同一再捕获机理和同一战果不得重复占位，无法独立验收时合并或替换",
            "并行章节不以字数为质量目标；每段至少形成一项军事战场决策信息，删除通用战略套话、重复背景和跨章节同义复述",
            "作战运用流程按阶段说明装备使用方式、作用节点和指标口径，链路闭环至少分析时间链、精度/信息链或火力链",
            "体系贡献率明确原方案基线、对比变量、计算口径、验证方法和证据边界，不虚构点值",
            "总体方案下钻到硬件产品、软件系统、接口、数据流及子系统输入输出",
            "关键技术逐项包含技术内涵、成熟度/基础、瓶颈、攻关途径、验证指标和失败条件",
            "参与单位不虚构；证据不足时只列单位类型和待明确项，技术基础说明现有工作如何支撑项目",
            "事实、推断、目标指标和待验证假设明确分层；URL只来自允许目录",
        ]

    canonical_h2, canonical_h3, canonical_h4 = _report_canonical_headings(payload)
    section_budget = (
        {
            "一、需求分析": "约34%-40%",
            "二、项目画像": "约25%-30%",
            "三、总体方案": "约14%-18%",
            "四、关键技术": "约10%-14%",
            "五、研制基础": "约8%-12%",
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
            "需求概述": ["decisive_anchors", "mission_chain_breaks", "capability_cues.problem_statement"],
            "国内外现状": ["comparative_status.foreign_cases", "comparative_status.domestic_cases", "comparative_status.comparative_findings", "public_sources"],
            "建设必要性": ["capability_cues.capability_gap", "capability_cues.mission_effect", "capability_cues.disruptive_relationship"],
            "装备图像概述": ["capability_cues.direction", "capability_cues.target_scenario", "capability_cues.scientific_principle", "capability_cues.enabling_technologies", "capability_cues.capability_outcome", "capability_cues.winning_mechanism"],
            "作战运用模式": ["capability_cues.operational_concept", "capability_cues.operational_process", "capability_cues.mechanism_hint"],
            "体系贡献率分析": ["capability_cues.mission_effect", "capability_cues.indicator_portrait", "capability_cues.public_equipment_baseline"],
            "主要战技指标": ["capability_cues.indicator_portrait", "capability_cues.boundary"],
            "总体方案": ["capability_cues.equipment_hint", "capability_cues.enabling_technologies", "capability_cues.development_path"],
            "关键技术": ["capability_cues.scientific_principle", "capability_cues.enabling_technologies", "capability_cues.coupling_risk"],
            "研制基础": ["comparative_status", "public_sources", "capability_cues.public_equipment_baseline"],
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
                "不重复发现或逐字段复述。"
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
            "table_policy": "仅高密度能力、技术、耦合、效能或优先级比较使用；最多6列、12行、单元格不超过220字",
        },
        "reporter_contract": _reporter_agent_contract(reporter_agent),
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
        "branch": generation["branch"],
        "report_template_mode": generation.get(
            "report_template_mode", "three_layer_nine_item"
        ),
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
            compact_handoff["capability_cues"] = list(cues[:12])
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
        "branch": generation["branch"],
        "report_template_mode": generation.get(
            "report_template_mode", "three_layer_nine_item"
        ),
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
        notes.append("只补充缺失的实质内容；模板、证据和军事决策链闭环后立即收尾，不为达到字数扩写，最终逐装备验证矩阵由交付层合并。")
    if any(marker in joined for marker in ("编号", "三层", "九项", "章节", "缺少")):
        notes.append("严格补齐三层九项：场景、制胜机理、能力特征、实现途径、核心技术、耦合风险、能力图像、效能贡献、发展抓手。")
    if any(marker in joined for marker in ("URL", "引用", "来源", "证据", "事实")):
        notes.append("保留并嵌入3至6条[来源名](允许URL)，关键判断明确区分事实、推断和待验证假设。")
    if any(marker in joined for marker in ("因果", "任务链", "能力映射", "接口", "实现途径", "核心技术")):
        notes.append("补强场景—战法—能力—技术—效能因果链；每项能力显式映射实现途径、核心技术、耦合风险、装备形态和验证指标。")
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
        notes.append("在效能贡献中明确补链/强链/开链和可量化方向，在发展抓手中给出显式优先级与演示验证通过/失败条件。")
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
        if first in {"装备系统方向", "装备方向", "具体装备方向"}:
            continue
        if re.fullmatch(r":?-{3,}:?", first):
            continue
        if first:
            directions.append(first)
    return directions


def _report_fragment_quality_issues(text: str) -> list[str]:
    """Reject punctuation-normalized fragments and clipped Markdown rows."""

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
        for clause in re.split(r"[；。|]", value):
            compact = clause.strip(" *_'\"“”‘’，、：:；。")
            if len(compact) >= 12 and compact.endswith(
                ("的", "与", "及", "把", "将", "该")
            ) and not compact.endswith(("参与", "赋予")):
                return compact[-60:]
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
                locative_only = bool(
                    re.fullmatch(
                        r"(?:在|于|从|对|面向|围绕|针对).{1,36}(?:中|下|上|内|方面|阶段|条件下)。",
                        sentence,
                    )
                ) and not any(
                    term in sentence
                    for term in (
                        "可拆成", "可分为", "分成", "分为", "形成", "呈现", "说明",
                        "表明", "决定", "改变", "压缩", "恢复", "支撑", "实现",
                    )
                )
                if locative_only or re.fullmatch(
                    r"(?:核心|主要|当前|该)?(?:矛盾|关键|问题|难点|重点|风险)"
                    r"(?:在于|是|为|成立)?。|(?:作战|任务|目标)(?:上|方面|是|为)?。",
                    sentence,
                ) or re.fullmatch(
                    r".{0,36}(?:体现为|包括|主要是|分别为|在于|取决于|依赖于)。",
                    sentence,
                ):
                    samples.append(sentence[:60])
                    continue
            if (
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
    ][:12]
    if len(expected_direction_names) >= 5:
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
        if represented < len(expected_direction_names):
            issues.append(
                f"装备能力图像仅明确覆盖{represented}/{len(expected_direction_names)}个输入方向，"
                "需逐项保留全部高军事价值武器装备方向，支撑层不得替换或另造主体方向"
            )
        table_direction_names = _report_capability_image_table_directions(
            section_text
        )
        if table_direction_names:
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
    if not all(term in text for term in ("国际", "军事", "问题", "需求", "项目")):
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
        and any(term in status_body for term in ("型号", "装备", "项目"))
        and any(term in status_body for term in ("技术方案", "技术途径", "核心技术"))
        and any(term in status_body for term in ("指标", "参数", "公开资料不足", "待核验"))
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
    if not all(
        term in text
        for term in ("面向", "针对", "利用", "采用", "关键作战流程", "形成", "实现", "制胜逻辑")
    ):
        issues.append("项目画像未按场景—问题—原理—技术—作战流程—能力—效果—制胜机理展开")
    if not (
        any(term in text for term in ("时间链", "精度链", "信息链", "火力链"))
        and any(term in text for term in ("任务准备", "部署", "目标发现", "交战", "毁伤评估", "再组织"))
    ):
        issues.append("作战运用模式缺少分阶段流程或链路闭环分析")
    if sum(
        term in text
        for term in ("耗弹量", "突防效能", "任务成功率", "闭环时间", "交换比", "持续波次")
    ) < 3:
        issues.append("体系贡献率分析至少需给出三类可校准对比指标")
    if not (
        any(term in text for term in ("硬件", "平台", "载荷"))
        and any(term in text for term in ("软件", "任务系统", "算法"))
        and "子系统" in text
    ):
        issues.append("总体方案未下钻到硬件产品、软件系统和子系统层级")
    if not all(term in text for term in ("技术名称", "技术内涵", "攻关途径")):
        issues.append("关键技术需逐项给出技术名称、技术内涵和攻关途径")
    if not all(term in text for term in ("参与单位", "技术基础")):
        issues.append("研制基础缺少参与单位或技术基础")
    return issues


def _report_three_layer_content_issues(text: str) -> list[str]:
    issues: list[str] = []
    scenario_markers = ("对手", "地域", "烈度", "时间窗", "约束")
    missing_scenario = [marker for marker in scenario_markers if marker not in text]
    if missing_scenario:
        issues.append("三层九项中典型作战场景缺少：" + "、".join(missing_scenario))

    if not (
        any(marker in text for marker in ("现有范式", "现有模式", "现有战法", "现有技术"))
        and any(marker in text for marker in ("不足", "做不到", "难以", "失效"))
        and any(marker in text for marker in ("制胜", "能赢", "优势", "取胜"))
    ):
        issues.append("三层九项中制胜机理未说明现有范式为何不足及新概念为何能赢")

    capability_indicator_signals = sum(
        marker in text
        for marker in ("射程", "响应时间", "自主等级", "成本量级", "规模量级", "精度", "生存力")
    )
    if capability_indicator_signals < 3:
        issues.append("三层九项中装备能力特征缺少足够的定量指标方向")

    if not any(marker in text for marker in ("沿用改进", "集成创新", "原理突破")):
        issues.append("三层九项中能力实现途径未标注沿用改进、集成创新或原理突破")

    missing_technology = [
        label
        for label, markers in (
            ("具体技术点", ("制导律", "材料体系", "算法", "架构", "技术点", "技术清单")),
            ("成熟度", ("成熟度", "TRL", "工程化", "样机", "试验验证")),
            ("瓶颈", ("瓶颈", "卡脖子", "短板")),
            ("优先级", ("P0", "P1", "P2", "高优先级", "中优先级", "低优先级", "优先级")),
        )
        if not any(marker in text for marker in markers)
    ]
    if missing_technology:
        issues.append("三层九项中核心技术清单缺少：" + "、".join(missing_technology))

    if not (
        any(marker in text for marker in ("耦合", "依赖", "制约"))
        and any(marker in text for marker in ("卡脖子", "短板", "拖垮", "级联"))
    ):
        issues.append("三层九项中技术耦合与短板风险不完整")

    if not (
        "能力域" in text
        and any(marker in text for marker in ("指标画像", "指标谱", "指标特征"))
        and any(marker in text for marker in ("谱系位置", "装备谱系", "相对现有装备", "现有装备体系"))
    ):
        issues.append("三层九项中装备能力图像缺少能力域、指标画像或谱系位置")

    if not any(marker in text for marker in ("补链", "强链", "开链")):
        issues.append("三层九项中效能贡献未明确补链、强链或开链")
    if not any(
        marker in text
        for marker in ("突防率", "交换比", "决策周期", "压缩量级", "提升量级", "改善量级")
    ):
        issues.append("三层九项中效能贡献缺少可量化评估方向")

    if not (
        any(marker in text for marker in ("P0", "P1", "P2", "高优先级", "中优先级", "低优先级"))
        and any(marker in text for marker in ("演示验证", "验证项目", "演示项目", "样机验证"))
        and any(marker in text for marker in ("通过条件", "失败条件", "判据", "验收指标"))
    ):
        issues.append("三层九项中发展优先级或近期演示验证抓手不完整")
    return issues


def _report_domain_attribute_issues(
    text: str,
    payload: Mapping[str, Any],
) -> list[str]:
    """Hard gates for unmanned long-range firepower research reports."""

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
        any(term in text for term in ("无人机", "无人平台", "巡飞弹", "无人僚机", "无人集群"))
        and any(term in text for term in ("远程", "远域", "防区外", "战役纵深"))
        and any(term in text for term in ("精确打击", "精确制导", "毁伤", "压制", "歼灭", "拒止"))
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
    if not (
        len(capability_directions) >= 1
        and (
            ("装备平台与方案" in capability_body and "形成能力" in capability_body)
            if project_mode
            else (
                "能力域" in capability_body
                and any(term in capability_body for term in ("指标画像", "指标特征", "指标谱"))
            )
        )
        and sum(
            term in capability_body
            for term in ("作战运用", "运用概念", "编组", "波次", "待机", "发射", "突防", "交战", "巡飞")
        ) >= 2
    ):
        issues.append("装备能力图像需包含至少一项具体武器装备，并同时给出能力域、指标画像和作战运用概念")

    if not all(
        any(term in text for term in alternatives)
        for alternatives in (
            ("现役效能跃升", "效能跃升", "战力跃升"),
            ("传统赛道跨代优势", "跨代优势", "代际优势"),
            ("新概念赛道开辟", "开辟新赛道", "新概念赛道"),
        )
    ):
        issues.append("制胜效能需区分现役效能跃升、传统赛道跨代优势和新概念赛道开辟")

    if not (
        any(term in text for term in ("创新", "新增机制", "新能力", "新研"))
        and any(term in text for term in ("相较", "相比", "相对基线", "传统", "从", "转向"))
        and any(term in text for term in ("颠覆", "重构", "突破", "改变", "新增机制"))
        and disruptive_relationship_groups(text)
        and any(term in text for term in ("对手反适应", "反适应", "失效边界", "失败条件", "适用边界"))
    ):
        issues.append("创新性需说明相对基线改变的作战关系，并给出对手反适应或失效边界")

    if not (
        any(term in text for term in ("成熟度", "TRL", "工程化", "样机", "现役改装"))
        and any(term in text for term in ("瓶颈", "短板", "工程风险", "集成风险"))
        and any(term in text for term in ("公开证据", "证据不足", "待验证", "事实", "推断", "假设"))
        and any(term in text for term in ("试验验证", "演示验证", "验证指标", "通过条件", "失败条件"))
    ):
        issues.append("可实现性论证需成套给出成熟度、瓶颈、证据边界和验证指标，杜绝无证据结论")
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
    issues.extend(_report_table_issues(text))
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


def _report_table_issues(text: str) -> list[str]:
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
        if widths and max(widths) > 6:
            issues.append(f"报告格式第{index}个表格超过6列")
        data_rows = max(0, len(table) - 2)
        if data_rows > 12:
            issues.append(f"报告格式第{index}个表格超过12行数据")
        cells = [
            cell.strip()
            for row in table
            for cell in row.strip("|").split("|")
        ]
        if any(len(cell) > 220 for cell in cells):
            issues.append(f"报告格式第{index}个表格存在超过220字的单元格")
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
    """Check the final draft against the three-layer, nine-item benchmark."""

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
        ),
    }
    missing_mapping = [
        label
        for label, markers in mapping_groups.items()
        if not any(marker in text for marker in markers)
    ]
    if missing_mapping:
        issues.append("三层九项能力映射链缺项：" + "、".join(missing_mapping))

    if not any(marker in text for marker in ("事实", "公开资料", "证据显示", "公开来源")):
        issues.append("三层九项报告未明确标识事实依据")
    if not any(marker in text for marker in ("分析推断", "推断", "假设", "置信度")):
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

__all__ = ['_report_template_mode', '_report_canonical_headings', '_report_has_complete_canonical_structure', '_canonical_report_h2', '_canonical_report_h3', '_canonical_report_h4', '_normalize_report_structure_deterministically', '_report_capability_cues', '_report_capability_portrait_markdown', '_remove_empty_report_clauses', '_normalized_report_reuse_text', '_report_matrix_verification_mechanism', '_reflow_long_report_paragraphs', '_stabilize_report_delivery_contract', '_report_issues_are_deterministic_format_only', '_project_argument_report_writer_system_prompt', '_report_writer_system_prompt', '_report_repair_system_prompt', '_clean_winning_hypothesis_title', '_winning_portfolio_title', '_winning_combat_scene', '_winning_primary_equipment_form', '_winning_title_has_concrete_equipment_identity', '_prioritize_equipment_evidence_refs', '_is_remote_precision_portfolio_direction', '_report_branch', '_report_target_chars', '_unbounded_quality_report', '_report_hard_max_chars', '_clip_complete_report_phrase', '_compact_report_table_row', '_normalize_report_line_ending', '_enforce_report_hard_max', '_report_writer_max_chars', '_reporter_output_token_budget', '_strip_report_internal_markers', '_clean_reporter_clue_text', '_mark_reporter_handoff_rewrite_boundaries', '_sanitize_reporter_output', '_normalize_branch_report_labels', '_normalize_numbered_report_title_group', '_reporter_generation_payload', '_compact_reporter_branch_products', '_reporter_repair_payload', '_reporter_timeout_retry_payload', '_reporter_agent_contract', '_reporter_revision_notes', '_report_issue_code', '_report_capability_image_table_directions', '_report_fragment_quality_issues', '_report_draft_quality_issues', '_report_project_argument_content_issues', '_report_three_layer_content_issues', '_report_domain_attribute_issues', '_report_markdown_structure_issues', '_unbalanced_report_markdown', '_report_table_issues', '_is_report_seed_copy_issue', '_report_seed_copy_issues', '_report_v2_benchmark_issues', '_report_issues_require_fallback', '_report_delivery_blocking_issues', '_report_nonnegotiable_delivery_issues', '_branch_delivery_is_complete', '_c_branch_product_semantically_present', '_report_required_section_present', '_has_numbered_report_label', '_report_evidence_ids', '_normalize_report_summary', '_limit_report_summary']
