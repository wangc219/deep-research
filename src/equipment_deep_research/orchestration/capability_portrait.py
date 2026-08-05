from __future__ import annotations

from collections.abc import Sequence
import re


_EQUIPMENT_TITLE_TERMS = (
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
    "定向能效应器",
    "武器站",
    "作战平台",
    "任务系统",
    "效应器",
    "弹药",
)

_FIELD_LABEL_RE = re.compile(
    r"^(?:概述|主装备对象|装备形态|作战运用|未来触发|对手反适应|失效边界|"
    r"通过条件|验证重点|建设路径|依据[^：:]{0,18})\s*[：:]\s*"
)

_GENERIC_WEAPON_TITLES = {
    "无人机",
    "无人作战平台",
    "巡飞弹",
    "反辐射巡飞弹",
    "远程导弹",
    "精确制导弹药",
    "拦截弹",
    "电子压制效应器",
}

_MODEL_LED_TITLE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9./-]{2,}")


def _chinese_weapon_title(identity: str) -> str:
    """Translate a public-model-led identity into a Chinese equipment thesis.

    Public model names remain useful evidence anchors, but the visible title
    should answer what weapon China needs to develop rather than foregrounding
    a foreign product designation.
    """

    lowered = identity.lower()
    if "jassm" in lowered:
        if (
            any(marker in identity for marker in ("失联", "断链", "链路中断"))
            and any(marker in identity for marker in ("复核", "再确认"))
            and any(marker in identity for marker in ("拒打", "等待", "目标包时效"))
        ):
            return "失联复核远程巡航弹"
        return "空射隐身防区外抗扰巡航导弹补击"
    if "prsm" in lowered or "precision strike missile" in lowered:
        return "地射远程机动目标精确毁伤导弹"
    if "harop" in lowered or "harpy" in lowered:
        if any(marker in identity for marker in ("证据缓存", "重新授权", "间歇链路")):
            return "间歇链路证据缓存巡飞猎歼弹药"
        if any(marker in identity for marker in ("失辐射", "关机", "等待")):
            return "失辐射等待反辐射巡飞弹"
        return "自主猎杀反辐射巡飞弹"
    if "aargm" in lowered:
        return "关机目标再捕获反辐射导弹"
    if "barracuda" in lowered:
        return "低成本批量巡航效应器"
    if "mald" in lowered:
        return "空射可消耗电子攻击压制效应器"
    if "launched effects" in lowered or "launched effect" in lowered:
        return "低空可消耗察打一体无人机"
    if "switchblade" in lowered:
        return "低空巡飞猎歼弹药"
    if "coyote" in lowered:
        return "低成本反无人拦截弹"
    return ""


def build_capability_title(
    *, name: object, equipment_form: object, effect: object = ""
) -> str:
    """Return a short title led by a concrete weapon/equipment form."""

    title = re.sub(r"\s+", "", str(name or "")).strip(" ，,；;。:：")
    title = re.sub(r"^\d+\s*[：:、.．)）-]\s*", "", title)
    title = re.sub(r"^[A-Ha-h]\s*[：:、.．)）-]\s*", "", title)
    title = re.sub(r"(?:能力)?升级(?:方向)?$", "", title).rstrip(" ，,；;。:：")
    form = re.sub(r"\s+", "", str(equipment_form or "")).strip()
    effect_text = re.sub(r"\s+", "", str(effect or "")).strip()
    abstract_markers = ("证据链", "任务链", "信息链", "杀伤链", "闭环")
    abstract_suffixes = (
        "窗口",
        "续接",
        "协同",
        "支撑",
        "再捕获",
        "补击",
        "补射",
    )
    identity = f"{title}{form}{effect_text}"
    primary_identity = f"{title}{form}"
    if any(
        marker in primary_identity
        for marker in (
            "无人空中弹舱机",
            "空中弹舱机",
            "无人母弹舱",
            "无人空中弹舱",
            "无人载弹母机",
            "载弹母机",
        )
    ):
        return (
            title
            if any(marker in title for marker in ("弹舱机", "载弹母机"))
            else "长航时无人空中弹舱机"
        )
    if any(
        marker in primary_identity
        for marker in ("巡航母弹", "运输母弹", "远程母弹")
    ) and any(
        marker in primary_identity
        for marker in (
            "子效应器",
            "子弹药",
            "子弹",
            "异构载荷",
            "分时释放",
            "内置诱饵",
            "诱骗子弹",
            "电子压制子弹",
            "侦察确认子弹",
        )
    ):
        return "异构子效应器巡航母弹"
    if any(
        marker in primary_identity
        for marker in (
            "无人半潜平台",
            "半潜无人平台",
            "无人半潜航行体",
            "半潜无人航行体",
            "半潜火力舱",
            "半潜导弹火力舱",
        )
    ) and any(
        marker in identity
        for marker in ("远程反舰", "反舰导弹", "远程弹药", "巡航弹", "导弹发射", "火力舱")
    ):
        return "半潜预置反舰导弹火力舱" if "反舰" in identity else "半潜预置远程导弹火力舱"
    if any(term in identity for term in ("无人艇", "无人水面艇", "无人水面")) and any(
        marker in identity
        for marker in (
            "巡航弹舱",
            "巡航弹发射",
            "释放巡航弹",
            "远程弹药发射",
            "远火发射",
            "海上分布弹舱",
            "海上远程火力",
        )
    ):
        return "半潜预置巡航弹无人艇" if "半潜" in identity else "低特征预置巡航弹无人艇"
    if (
        any(
            marker in primary_identity
            for marker in ("栖岛弹舱", "岛岸弹舱", "岛礁弹舱", "巡飞弹发射舱")
        )
        and any(marker in identity for marker in ("助推", "短轨", "巡飞弹", "巡飞攻击弹"))
    ):
        return "栖岛助推巡飞弹发射舱"
    chinese_model_title = _chinese_weapon_title(identity)
    if (
        "箱式发射长航时巡飞弹药" in identity
        and any(term in identity for term in ("首击后", "再确认", "补射", "补击"))
    ):
        return "箱式发射长航时巡飞补射弹药"
    if _MODEL_LED_TITLE_RE.match(title) and chinese_model_title:
        return chinese_model_title[:24]
    if (
        4 <= len(title) <= 24
        and any(term in title for term in _EQUIPMENT_TITLE_TERMS)
        and not any(marker in title for marker in abstract_markers)
        and not title.endswith(abstract_suffixes)
        and "用于" not in title
        and "制造" not in title
        and title not in _GENERIC_WEAPON_TITLES
    ):
        return title

    if chinese_model_title:
        return chinese_model_title[:24]
    if "无人" in identity and "察打一体" in identity:
        modifiers = ""
        if "箱式" in identity:
            modifiers += "箱式发射"
        if "低空" in identity:
            modifiers += "低空"
        if "可消耗" in identity:
            modifiers += "可消耗"
        return f"{modifiers}察打一体无人机"[:24]
    if "无人" in identity and any(term in identity for term in ("固定翼", "复合翼", "垂直起降")):
        modifiers = "前沿节点" if "前沿" in identity else "低空"
        expendable = "可消耗" if "可消耗" in identity else ""
        airframe = "复合翼" if any(term in identity for term in ("复合翼", "垂直起降")) else "固定翼"
        return f"{modifiers}{expendable}{airframe}无人机"[:24]
    if "可消耗" in identity and any(
        term in identity for term in ("诱打", "诱导", "低空拦截", "攻击载荷族", "毁伤弹药族")
    ):
        return "可消耗诱打毁伤弹药族"
    if "巡飞弹" in identity:
        if "反辐射" in identity:
            endurance = "长航时" if "长航时" in identity else ""
            if any(term in identity for term in ("末端确认", "光电确认", "光电复核", "多模", "红外复核")):
                return f"{endurance}多模复核反辐射巡飞猎歼弹"[:24]
            if any(term in identity for term in ("短时开机", "短脉冲", "间歇", "断续")):
                return f"{endurance}断续辐射源猎杀巡飞弹"[:24]
            return f"{endurance}自主猎杀反辐射巡飞弹"[:24]
        modifiers = "低信息侦打" if any(
            term in identity for term in ("低信息", "弱通信", "断链")
        ) else "精确打击"
        return f"{modifiers}巡飞弹"[:24]
    if "无人携弹平台" in identity:
        modifiers = "批量可消耗" if all(term in identity for term in ("批量", "可消耗")) else "可消耗"
        low_altitude = "低空" if "低空" in identity else ""
        return f"{modifiers}{low_altitude}无人携弹平台"[:24]
    if any(term in identity for term in ("导弹", "制导弹药")):
        if "反辐射" in identity:
            if any(term in identity for term in ("关机", "再捕获", "目标记忆")):
                return "关机目标再捕获反辐射弹药"
            return "远域反辐射精确制导弹药"
        if "反舰" in identity:
            return "远程精确反舰导弹"
        if "防空" in identity or "拦截" in identity:
            return "低成本防空拦截弹"
        return "远程精确制导弹药"
    if "无人僚机" in identity:
        return "远域压制无人僚机" if "压制" in identity else "协同突击无人僚机"
    if "无人艇" in identity:
        return "海上察打无人艇" if "察打" in identity else "海上突击无人艇"
    if "无人潜航器" in identity:
        return "水下侦打一体无人潜航器"
    if any(term in identity for term in ("定向能", "高能激光", "高功率微波")):
        return "抗饱和定向能拦截效应器"

    candidates = [
        item.strip("的与和及、，；。")
        for item in re.split(r"[、，,；。]|以及|包括|或", form)
        if item.strip()
    ]
    concrete = next(
        (
            item
            for item in candidates
            if any(term in item for term in _EQUIPMENT_TITLE_TERMS)
        ),
        "",
    )
    if concrete:
        return concrete[:24].rstrip("的与和及、，；")
    return title[:24] or "具体武器装备方向"


def _clean_clause(value: object, fallback: str) -> str:
    text = re.sub(r"\s+", " ", str(value or ""))
    text = (
        text.replace("。；", "；")
        .replace("；。", "；")
        .replace("。。", "。")
        .replace("；；", "；")
        .replace("“", "")
        .replace("”", "")
    )
    text = _FIELD_LABEL_RE.sub("", text).strip(" ，,；;。:：")
    return text or fallback


def _clip_clause(value: object, fallback: str, *, limit: int) -> str:
    text = _clean_clause(value, fallback)
    if len(text) <= limit:
        return text
    clipped = text[:limit]
    boundary = max(
        (clipped.rfind(marker) for marker in ("；", "，", "。")),
        default=-1,
    )
    if boundary >= 10:
        candidate = clipped[:boundary].rstrip(" ，、；：")
        if candidate and not candidate.endswith(("的", "与", "和", "及", "为", "向", "把", "将")):
            return candidate
    # A slightly over-budget complete clause is preferable to a short but
    # semantically broken phrase such as ``为JASSM-ER`` or ``任务的``.  The
    # portrait-level budgeter can shorten other governed rows safely.
    if len(text) <= max(limit + 36, int(limit * 1.8)):
        return text
    return fallback or text


def _concise_clause(
    value: object,
    fallback: str,
    *,
    limit: int,
    max_parts: int = 2,
) -> str:
    """Keep complete semantic clauses instead of cutting a legacy field mid-sentence."""

    source = _clean_clause(value, "")
    if not source:
        return fallback
    parts = [
        _clean_clause(part, "")
        for part in re.split(r"[；;。]+", source)
        if _clean_clause(part, "")
    ]
    selected: list[str] = []
    for part in parts:
        candidate = "；".join([*selected, part])
        if selected and len(candidate) > limit:
            break
        if len(part) > limit and not selected:
            selected.append(_clip_clause(part, fallback, limit=limit))
            break
        selected.append(part)
        if len(selected) >= max_parts:
            break
    return "；".join(selected).rstrip(" ，、；：。") or fallback


def _problem_clause(problem: object, capability: object, scenario: str) -> str:
    source = _clean_clause(problem, "")
    source = re.sub(r"^面向.{0,220}?[，,]针对", "", source)
    source = re.split(r"[；;]该方向装备基线[：:]", source, maxsplit=1)[0]
    # Some historical S6 rows put the proposed mechanism after the actual gap,
    # then the new portrait builder added its governed principle once more.
    # Keep only the problem side of that sentence; the mechanism belongs in the
    # dedicated principle and operational-concept clauses below.
    source = re.split(
        r"[，,；;](?=(?:利用|通过|采用|把|将).{0,120}?重构任务闭环)",
        source,
        maxsplit=1,
    )[0]
    # Older artifacts often stored the complete baseline, variable change and
    # outcome in problem_statement. Repeating that bundle makes the overview
    # unreadable, so reconstruct the actual gap from the governed outcome.
    if len(source) > 120 and "；" in source and "尚不能在" not in source:
        first_clause = source.split("；", 1)[0]
        if 12 <= len(first_clause) <= 110:
            return _concise_clause(
                first_clause,
                "关键任务链存在断点且现有装备难以持续形成有效作战效果",
                limit=82,
                max_parts=1,
            )
    if any(
        marker in source
        for marker in ("现有基线", "尚不能在", "尚不能", "变化后稳定形成")
    ):
        if "低空拦截" in source or "混合屏障" in source:
            return "低空拦截、近程防空与电子战混合屏障使续接平台难以持续滞空并形成可信目标解"
        if any(
            marker in source
            for marker in (
                "诱饵辐射",
                "反辐射",
                "AARGM",
                "电磁指挥节点",
                "假发射源",
            )
        ):
            return "现役反辐射弹药难以跨越关机窗口、排除诱饵辐射源并续接压制真实节点"
        if "PrSM" in source or "陆基" in source:
            return "目标坐标过期、导航受扰和末端不可确认使陆基纵深火力难以安全续接"
        if "低成本" in source or "批量库存" in source or "Barracuda" in source:
            return "高端远程弹药数量和补充速度不足，受扰后难以维持多波次防区外精确毁伤"
        return "现有装备依赖持续链路和外部目标更新，受扰后难以完成目标复核、交战与毁伤评估"
    return _concise_clause(source, "关键任务链存在断点且现有装备难以持续形成有效作战效果", limit=82)


def _operational_concept_clause(value: object) -> str:
    text = _clean_clause(value, "")
    if "实施" in text:
        text = text.rsplit("实施", 1)[-1]
    return _concise_clause(
        text,
        "任务装订、分散部署、受控交战、效应评估和战损后再组织",
        limit=72,
        max_parts=2,
    )


def _development_clause(value: object, technology_text: str = "") -> str:
    text = _clean_clause(value, "")
    milestone = next(
        (marker for marker in ("近期", "中期", "远期", "最终") if marker in text),
        "",
    )
    if milestone:
        text = text[text.find(milestone) :]
    elif "工程样机" in text:
        technical_focus = _concise_clause(
            technology_text,
            "关键子系统",
            limit=30,
            max_parts=1,
        )
        return (
            f"近期完成{technical_focus}工程样机与接口联试，中期开展半实物和实装对抗，"
            "远期依据任务收益、误击/拒打和成本结果固化型号谱系"
        )
    elif "开展" in text:
        text = "近期完成接口改装与任务级样机，中期" + text[text.find("开展") :]
    return _concise_clause(
        text,
        "近期完成任务级仿真和关键接口联试，中期形成样机并开展半实物、实装与红蓝对抗验证",
        limit=72,
        max_parts=2,
    )


def _equipment_landing_clause(value: object, fallback: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip(" ，,；;。:：")
    text = re.sub(r"^以+(?=[A-Za-z\u3400-\u9fff])", "", text).strip()
    text = re.sub(r"^(?:单一主体|主装备对象)(?:为|是)", "", text).strip()
    text = re.sub(
        r"^具备.{0,48}?能力的(?=.*(?:导弹|巡飞弹|弹药|无人机|无人携弹平台|效应器))",
        "",
        text,
    ).strip()
    labeled: dict[str, str] = {}
    for part in re.split(r"[；;]+", text):
        match = re.match(r"^(主装备对象|装备形态|作战运用)\s*[：:]\s*(.+)$", part.strip())
        if match:
            labeled[match.group(1)] = match.group(2).strip(" ，,；;。:：")
    equipment_object = _concise_clause(
        labeled.get("主装备对象", ""),
        "",
        limit=28,
        max_parts=1,
    )
    equipment_form = _concise_clause(
        labeled.get("装备形态", ""),
        "",
        limit=38,
        max_parts=1,
    )
    if equipment_object and equipment_form:
        return f"{equipment_object}，采用{equipment_form}"
    if equipment_object or equipment_form:
        return equipment_object or equipment_form
    return _concise_clause(text, fallback, limit=58, max_parts=1)


def _verification_clause(plan: object, development_path: object) -> str:
    direct_rows = _clean_items(plan, limit=8)
    development_rows = _clean_items(development_path, limit=8)
    candidates = [*direct_rows, *development_rows]
    preferred: list[str] = []
    for markers in (
        ("环境", "条件", "场景", "注入", "受扰", "受限", "退化"),
        ("比较", "基线", "对照"),
        ("通过条件", "预注册", "淘汰条件", "门槛", "停止转段"),
        ("半实物", "实装", "试验", "验证", "测量", "校准"),
    ):
        for item in candidates:
            if any(marker in item for marker in markers):
                cleaned = re.sub(
                    r"^(?:通过条件为|验证重点为|在|开展|构建)", "", item
                ).strip()
                if cleaned and cleaned not in preferred:
                    preferred.append(cleaned)
                break
    if not preferred:
        preferred = [
            "强干扰、低带宽、节点损耗、目标状态过期与授权中断组合场景",
            "与未改装或串行任务链基线比较任务完成率和尾部风险",
            "预注册通过与淘汰门槛",
        ]
    labels = ("环境", "对照", "决策")
    return "；".join(
        f"{label}：{re.sub(r'^(?:在|开展|构建)', '', _concise_clause(item, '', limit=58))}"
        for label, item in zip(labels, preferred[:3], strict=False)
    )


def _scenario_clause(value: object) -> str:
    text = _clean_clause(value, "")
    # The governed overview already supplies the ``面向`` relation. Queries
    # commonly begin with the same word, so retaining it here produced the
    # mechanical phrase ``面向面向……`` in every projected portrait.
    text = re.sub(r"^(?:面向)+", "", text).strip(" ，,；;。:：")
    if "对手水面编队" in text and any(
        marker in text for marker in ("反舰", "海上目标", "远海")
    ):
        # Keep the adversary and countermeasures inside the overview's short
        # scenario budget instead of clipping immediately before “对手”.
        return "远海反舰齐射后，对手水面编队以机动、诱饵和分层防空反制"
    if all(marker in text for marker in ("强电磁压制", "短时火力窗口")):
        return "强电磁压制下的短时火力窗口"
    return _concise_clause(text, "典型高对抗作战场景", limit=34, max_parts=1)


def _baseline_clause(value: object) -> str:
    text = _clean_clause(value, "")
    text = re.sub(r"^以+(?=[A-Za-z\u3400-\u9fff])", "", text)
    text = re.sub(r"^(?:最近)?公开基线(?:必须同时核对两类|可准确落到)?", "", text)
    text = text.split("；", 1)[0]
    text = text.split("以及", 1)[0]
    return _technology_clause(text, limit=38) or "公开资料支持的现役或类别级装备基线"


def _principle_clause(value: object) -> str:
    text = _clean_clause(value, "")
    text = re.sub(
        r"^(?:利用|采用|通过|依托|借助|以)(?=[A-Za-z\u3400-\u9fff])",
        "",
        text,
    ).strip()
    change_marker = next(
        (
            marker
            for marker in ("改变为", "转变为", "收窄为", "改为", "转为")
            if marker in text
        ),
        "",
    )
    if change_marker:
        target = text.rsplit(change_marker, 1)[-1]
        target = re.sub(r"^(?:利用|通过|由)", "", target).strip()
        parts = [part.strip() for part in target.split("、") if part.strip()]
        selected: list[str] = []
        for part in parts:
            candidate = "、".join([*selected, part])
            if selected and len(candidate) > 38:
                break
            selected.append(part)
        target_text = "、".join(selected)
        text = target_text
    text = re.sub(r"S[1-6](?:中的?|阶段的?)?", "", text)
    text = text.replace("首击后目标区附近是否已有", "首击后在目标区附近预置")
    text = text.replace("首击后电磁压制窗口内是否仍有", "在首击后电磁压制窗口内保持")
    return _concise_clause(
        text,
        "任务闭环压缩、功能重组与体系协同原理",
        limit=42,
        max_parts=1,
    )


def _technology_clause(value: object, *, limit: int) -> str:
    text = _clean_clause(value, "")
    text = text.split("，", 1)[0].strip()
    parts = [part.strip() for part in text.split("、") if part.strip()]
    selected: list[str] = []
    for part in parts:
        candidate = "、".join([*selected, part])
        if selected and len(candidate) > limit:
            break
        if len(part) > limit and not selected:
            if len(part) <= max(48, limit * 2):
                return part.rstrip(" ，、；：。")
            return _clip_clause(part, "", limit=limit)
        selected.append(part)
    return "、".join(selected).rstrip(" ，、；：。")


def _process_clause(value: object) -> str:
    text = _clean_clause(value, "")
    text = text.split("；", 1)[0].strip()
    if "链路恢复后" in text and "授权" in text:
        return "链路恢复后回传低带宽证据摘要，由人在回路复核并重新授权"
    if "末段传感证据" in text and any(marker in text for marker in ("拒打", "中止")):
        return "末段证据满足类别和区域门槛则交战，否则安全拒打或中止"
    if "本机传感器" in text and any(marker in text for marker in ("补射", "毁伤")):
        return "以本机传感器完成目标再确认和毁伤观察，并按授权门槛实施补射"
    if text.startswith("发现") and any(marker in text for marker in ("补射", "毁伤载荷")):
        return "发现漏毁、转移或短时暴露目标后，完成复核并实施受控补射"
    parts = [part.strip() for part in text.split("，") if part.strip()]
    if not parts:
        return "执行受控任务动作"
    if parts[0].startswith(("多个", "多批次", "编组")) and "闭环" in text:
        return f"{parts[0]}，维持最低侦察—确认—打击闭环"
    selected = parts[:2]
    result = "，".join(selected)
    if len(result) > 72 and parts[0].startswith(("若", "当")) and len(parts) > 1:
        result = parts[1]
    return result if len(result) <= 72 else _concise_clause(
        text,
        "执行装备专属战斗动作",
        limit=72,
        max_parts=2,
    )


def _winning_mechanism_clause(
    value: object,
    principle: object,
    identity: str,
) -> str:
    source = _clean_clause(value, "")
    parts = _clean_items(source, limit=10)
    preferred = next(
        (
            part
            for part in parts
            if any(
                marker in part
                for marker in (
                    "拟议增量",
                    "相较传统",
                    "创新点",
                    "任务时序",
                    "成本交换",
                    "关机",
                    "再捕获",
                    "重新授权",
                    "证据缓存",
                )
            )
            and not part.startswith("通过")
        ),
        "",
    )
    text = preferred or _principle_clause(principle)
    text = re.sub(r"^拟议增量(?:仅是|只聚焦|仅聚焦)", "以", text).strip()
    text = re.sub(r"^该分支", "该装备", text).strip()
    text = text.replace("本候选", "该装备")
    text = re.sub(r"S[1-6](?:中的?|阶段的?)?", "", text)
    return _concise_clause(
        text,
        "把任务所需功能前推到可生存节点，压缩闭环并改变对手的时间与成本交换关系",
        limit=84,
        max_parts=1,
    )


def _capability_family(identity: str) -> str:
    """Classify by the equipment's positive anchor before secondary mentions.

    Portrait inputs often contain negative comparisons such as "不与MALD复合"
    or generic interfaces such as "地面发射".  Treating any mentioned token as
    the primary family caused Harop and Barracuda cards to inherit another
    weapon's overview, process, metrics and verification contract.
    """

    primary = identity.split("；", 1)[0]
    if "高功率微波" in primary or "微波巡飞" in primary:
        return "high_power_microwave"
    if any(
        marker in primary
        for marker in (
            "无人空中弹舱机",
            "空中弹舱机",
            "无人母弹舱",
            "无人空中弹舱",
            "空中弹药库",
            "无人载弹母机",
            "载弹母机",
        )
    ):
        return "airborne_arsenal_carrier"
    if "无人僚机" in primary and any(
        marker in primary
        for marker in ("武装", "察打", "压制", "反辐射", "精确弹", "毁伤")
    ):
        return "armed_unmanned_wingman"
    if (
        any(marker in primary for marker in ("短距起降", "短距起飞"))
        and any(
            marker in primary
            for marker in ("无人机", "无人平台", "无人母机", "火力母机")
        )
        and any(
            marker in identity
            for marker in ("诱饵", "巡航弹", "巡飞弹", "载架", "挂载", "释放")
        )
    ):
        return "short_takeoff_unmanned_fire_carrier"
    if any(
        marker in primary for marker in ("巡航母弹", "运输母弹", "远程母弹")
    ) and any(
        marker in primary
        for marker in (
            "子效应器",
            "子弹药",
            "子弹",
            "异构载荷",
            "分时释放",
            "内置诱饵",
            "诱骗子弹",
            "电子压制子弹",
            "侦察确认子弹",
        )
    ):
        return "cruise_mother_munition"
    if "任务桥" in primary and any(
        marker in primary for marker in ("巡航弹", "可消耗", "空中")
    ):
        return "expendable_mission_bridge"
    if (
        any(
            marker in primary
            for marker in (
                "无人半潜平台",
                "半潜无人平台",
                "无人半潜航行体",
                "半潜无人航行体",
                "半潜无人艇",
                "低活动半潜无人艇",
                "无人潜浮",
                "潜浮弹舱",
                "浮潜弹舱",
                "半潜火力舱",
                "半潜导弹火力舱",
            )
        )
        or ("半潜" in primary and any(marker in primary for marker in ("火力舱", "弹舱")))
    ) and any(
        marker in identity
        for marker in (
            "远程反舰",
            "反舰导弹",
            "远程弹药",
            "巡航弹",
            "远射巡飞弹",
            "巡飞弹发射",
            "导弹发射",
            "火力舱",
        )
    ):
        return "unmanned_surface_missile_launcher"
    if "半潜储射" in primary and any(
        marker in identity for marker in ("远程弹药", "巡航弹", "储射", "远程火力")
    ):
        return "unmanned_surface_missile_launcher"
    if any(marker in primary for marker in ("无人艇", "无人水面艇", "无人水面")):
        if any(
            marker in identity
            for marker in (
                "巡航弹舱",
                "巡航弹发射",
                "释放巡航弹",
                "远程弹药发射",
                "远火发射",
                "远程火力节点",
                "海上火力缓存",
                "海上分布弹舱",
                "海上远程火力",
            )
        ):
            return "unmanned_surface_missile_launcher"
        return "unmanned_surface_ambush"
    if any(
        marker in primary
        for marker in (
            "巡飞弹发射车",
            "巡飞弹药发射车",
            "无人巡飞火力舱",
            "巡飞弹发射巢",
            "巡飞弹巢",
            "密封发射巢",
            "栖岛弹舱",
            "岛岸弹舱",
            "岛礁弹舱",
            "巡飞弹发射舱",
        )
    ):
        return "land_loitering_launcher"
    if (
        any(marker in primary for marker in ("反无人", "反蜂群", "护射"))
        or (
            "节点" in primary
            and "拦截弹" in primary
            and any(marker in identity for marker in ("无人机", "巡飞弹", "自卫"))
        )
    ) and any(
        marker in primary
        for marker in ("拦截弹车", "拦截车", "防空车", "拦截弹", "拦截系统")
    ):
        return "counter_unmanned_launcher"
    if any(
        marker in primary
        for marker in ("反舰发射车", "岸基反舰", "NMESIS", "海岸导弹发射车")
    ):
        return "shore_anti_ship_launcher"
    if "反舰" in primary and any(
        marker in primary for marker in ("巡飞", "猎歼")
    ):
        return "anti_ship_loitering"
    if "反舰" in primary and any(
        marker in primary
        for marker in ("导弹", "巡航弹药", "巡航导弹", "巡航弹")
    ):
        return "anti_ship_cruise"
    if any(marker in primary for marker in ("导弹车", "导弹发射车", "远程精确发射车")):
        return "land_mobile_precision_launcher"
    if any(
        marker in primary
        for marker in ("共同推进", "共享飞行弹体", "多任务弹药", "共架")
    ) and any(marker in primary for marker in ("飞行弹体", "弹药")):
        return "common_airframe"
    if "反辐射" in primary or "AARGM" in primary:
        return "anti_radiation"
    if any(
        marker in primary
        for marker in (
            "MALD",
            "诱饵",
            "诱扰",
            "电子攻击",
            "电子压制",
            "伴随干扰",
            "干扰载荷",
        )
    ):
        return "electronic_attack"
    if any(marker in primary for marker in ("Barracuda", "规模生产", "批量库存")) or (
        "低成本" in primary
        and not any(marker in primary for marker in ("诱骗", "诱饵", "诱扰", "压制", "反无人"))
    ):
        return "low_cost_effecter"
    if any(marker in primary for marker in ("低空无人", "低空巡飞", "无人携弹", "无人机", "无人作战", "察打一体")) or (
        "巡飞弹药" in primary
        and any(marker in identity for marker in ("本地再确认", "目标再确认", "直接补射", "补射或压制"))
    ):
        return "low_altitude_unmanned"
    if any(marker in primary for marker in ("PrSM", "多模末制导", "末段再捕获")):
        return "prsm"
    if any(marker in primary for marker in ("JASSM", "空射", "防区外巡航")):
        return "jassm"
    if "巡航弹" in primary and any(
        marker in identity
        for marker in ("失联", "断链", "目标包时效", "拒打", "毁伤摘要")
    ):
        return "jassm"
    if any(marker in identity for marker in ("证据缓存", "重新授权", "链路恢复")):
        return "evidence_cache"
    if (
        "反辐射" in identity
        or "AARGM" in identity
        or all(marker in identity for marker in ("关机", "辐射"))
    ):
        return "anti_radiation"
    if any(marker in identity for marker in ("Barracuda", "规模生产", "批量库存")):
        return "low_cost_effecter"
    if any(marker in identity for marker in ("MALD", "电子攻击", "电子压制")):
        return "electronic_attack"
    if any(marker in identity for marker in ("低空无人", "无人携弹", "察打一体", "本地再确认", "补射")):
        return "low_altitude_unmanned"
    if any(marker in identity for marker in ("PrSM", "多模末制导", "末段再捕获")):
        return "prsm"
    if any(marker in identity for marker in ("JASSM", "防区外巡航")):
        return "jassm"
    if any(
        marker in identity
        for marker in ("反舰发射车", "岸基反舰", "NMESIS", "海岸导弹发射车")
    ):
        return "shore_anti_ship_launcher"
    return "generic"


def _is_sealed_loitering_nest(identity: str) -> bool:
    primary = identity.split("；", 1)[0]
    return any(
        marker in primary
        for marker in ("巡飞弹发射巢", "巡飞弹巢", "密封发射巢")
    )


_FAMILY_PROBLEM_CLAUSES = {
    "unmanned_surface_missile_launcher": (
        "前沿机场与固定岸基发射点同时受毁或持续暴露后，缺少可在岛链海域分散待机、"
        "按授权释放远程弹药并射后转移的替代释能轴线"
    ),
    "unmanned_surface_ambush": (
        "远程火力失去舰队实时航迹后仍能保留海峡、补给通道和机动出口等慢变空间约束，"
        "但现有远程弹药难以把这些约束转化为近距伏击和直接拦截"
    ),
    "airborne_arsenal_carrier": (
        "前沿机场受毁后空基火力再出动链中断，缺少可由后方或幸存机场升空、"
        "在岛链外防区外长时待机并按授权分批释放防区外弹药的空中库存节点"
    ),
    "armed_unmanned_wingman": (
        "前沿机场受毁和有人机难以前出后，远程火力缺少能够在岛链外缘持续被动搜索、复核机动防空节点，"
        "并在短时授权窗口内自行压制或引导补击的低特征武装无人僚机"
    ),
    "short_takeoff_unmanned_fire_carrier": (
        "前沿机场主跑道受毁且有人载机出动受限后，现有空射诱饵和轻型打击弹药缺少可从滑行道、道路或"
        "简易场地分散出动，并在人工授权下抵达释放区完成混载释能的无人母平台"
    ),
    "cruise_mother_munition": (
        "前沿机场和固定发射阵地受毁后，单功能诱饵、侦察、压制与毁伤弹药仍需多次独立起射和"
        "连续链路协同，难以用一个后方发射窗口在岛链外缘形成分时多效应火力入口"
    ),
    "expendable_mission_bridge": (
        "前沿机场受毁且主数据链间歇后，分散远火射手缺少可从岸海节点释放、"
        "在目标区短时获取并转发目标摘要的可消耗空中任务节点"
    ),
    "land_loitering_launcher": (
        "机场出动链断裂后，岛岸火力缺少可短停展开、分批释放巡飞弹药并在敌侦察重访前"
        "转移的无人值守机动发射节点"
    ),
    "land_mobile_precision_launcher": (
        "固定机场与岸基发射阵地受压后，岛上道路网内缺少能够隐蔽机动、短停发射、"
        "射后撤收并由相邻车组接替补击的远程精确火力节点"
    ),
    "counter_unmanned_launcher": (
        "分布式远火发射车、补弹点和临时阵地暴露后，缺少能够伴随机动并以可承受成本"
        "拦截敌侦察无人机与巡飞弹的近域自防装备"
    ),
    "high_power_microwave": (
        "敌方低空无人集群和电子节点以数量、分散与快速恢复压缩远火窗口，"
        "传统逐目标拦截或单点毁伤难以形成可重复的区域功能压制"
    ),
    "shore_anti_ship_launcher": (
        "机场与固定岸防阵地受压后，岛岸道路网内缺少可分散隐蔽、短停释放反舰火力并"
        "在敌侦察重访前转移的机动海上拒止节点"
    ),
    "anti_ship_loitering": (
        "外部反舰航迹中断后，后方火力难以持续保管机动水面目标并在其再次暴露时完成身份复核和直接攻击"
    ),
    "anti_ship_cruise": (
        "目标航迹在远程飞行中陈旧，外部更新中断后搜索扇区易重复、多弹可能追逐同一疑似舰艇，"
        "末段身份确认不足又会放大诱饵和商船混杂风险"
    ),
    "common_airframe": (
        "专用诱饵、猎辐射和毁伤弹药库存彼此不能替代，威胁结构变化后容易出现某类构型不足、"
        "其他构型闲置并压缩可用齐射规模"
    ),
    "evidence_cache": (
        "短时暴露目标的候选轨迹、时间戳、传感摘要和授权状态会在断链中丢失，"
        "链路恢复后只能重新搜索和重新关联"
    ),
    "anti_radiation": (
        "现役反辐射弹药难以跨越关机窗口、排除诱饵辐射源并续接压制真实节点"
    ),
    "low_cost_effecter": (
        "高端远程弹药库存与补充速度不足，受扰和拦截消耗后难以维持多轴多波次纵深毁伤"
    ),
    "electronic_attack": (
        "对手分层防空探测与火控链压缩主攻武器突防窗口，现有高价值平台难以持续诱导其暴露和错配资源"
    ),
    "low_altitude_unmanned": (
        "首击漏毁、临机转移目标的外部毁伤评估与再确认链在强扰中中断，后方串行补射难以赶上短时窗口"
    ),
    "prsm": (
        "目标坐标过期、导航受扰和末端不可确认使陆基纵深火力难以安全续接"
    ),
    "jassm": (
        "导航欺骗、目标包过期和末端身份不确定使空射防区外弹药难以安全闭合纵深补击"
    ),
}


def _family_problem_clause(
    identity: str,
    problem_text: str,
    *,
    raw_problem: object,
) -> str:
    """Keep the gap local to the primary equipment family.

    Legacy dynamic-swarm artifacts wrapped the proposed variable change inside
    ``capability_gap``.  They therefore no longer contained a clean problem and
    could also inherit the previous card's anti-radiation sentence.  A family
    fallback is safer and more specific than presenting that stale mechanism as
    the battlefield difficulty.
    """

    family = _capability_family(identity)
    fallback = _FAMILY_PROBLEM_CLAUSES.get(family)
    primary = identity.split("；", 1)[0]
    if family == "anti_ship_loitering" and "空射" in primary:
        fallback = (
            "空射载机投放窗口短且释放轴线、进入时序和接替关系单一，"
            "弹群容易被外围拦截幕集中消耗并在目标机动后失去持续保管"
        )
    elif family == "anti_ship_loitering" and "射频复核" in primary:
        fallback = (
            "舰队以静默、间歇辐射、诱饵和外围无人拦截幕掩护机动，"
            "单一射频或成像观测难以形成可授权舰艇身份"
        )
    elif family == "anti_ship_cruise" and "协同去重" in primary:
        fallback = (
            "外部更新中断后多弹各自扩展搜索容易出现扇区重复、追逐同一疑似舰艇和重复释放毁伤，"
            "可用弹量因此不能有效转化为齐射覆盖"
        )
    elif family == "anti_ship_cruise" and "有限区搜索" in primary:
        fallback = (
            "目标航迹在远程飞行中陈旧，单弹必须在剩余航程、导引头视场和目标可能机动范围约束下"
            "完成有限搜索与身份确认，否则只能沿旧解攻击或无效耗尽"
        )
    elif any(
        marker in primary
        for marker in (
            "巡飞弹发射车",
            "巡飞弹药发射车",
            "无人巡飞火力舱",
            "巡飞弹发射巢",
            "巡飞弹巢",
            "密封发射巢",
        )
    ):
        fallback = (
            "机场出动链断裂后，岛上分队缺少可长期密封预置、低活动待机并按授权分批释放巡飞弹药的隐蔽火力缓存"
            if _is_sealed_loitering_nest(identity)
            else (
                "机场出动链断裂后，岛岸火力缺少可短停展开、分批释放巡飞弹药并在敌侦察重访前"
                "转移的无人值守机动发射节点"
            )
        )
    if not fallback:
        return problem_text

    raw = _clean_clause(raw_problem, "")
    legacy_wrapper = any(
        marker in raw
        for marker in (
            "变化后稳定形成",
            "重构任务闭环",
            "现有基线“",
            "现有基线\"",
        )
    )
    evidence_framed = any(
        raw.startswith(marker)
        for marker in (
            "公开资料",
            "公开基线",
            "公开证据",
            "公开产品",
            "公开项目",
            "现有公开",
        )
    )
    conflict_markers = {
        "unmanned_surface_missile_launcher": (
            "目标坐标过期", "陆基纵深火力", "现役反辐射", "关机窗口"
        ),
        "unmanned_surface_ambush": (
            "巡航效应器", "纵深固定", "准固定节点", "空投多轴", "反辐射"
        ),
        "airborne_arsenal_carrier": (
            "反辐射",
            "关机窗口",
            "批次合格率",
            "近距撞击",
            "箱式分批释放",
            "多路径低空进入",
            "本地搜索",
            "近区补击",
        ),
        "counter_unmanned_launcher": (
            "目标区附近在位察打",
            "本机光电/红外目标复核",
            "局部毁伤评估",
            "首击后再确认",
        ),
        "armed_unmanned_wingman": ("弹舱库存", "单机损失载荷集中度", "批次合格率", "近距撞击"),
        "short_takeoff_unmanned_fire_carrier": (
            "批次合格率",
            "固定或准固定节点多波次",
            "箱式分批释放",
            "本机搜索补射",
        ),
        "cruise_mother_munition": ("载机长时在位", "单机损失载荷", "批次合格率", "近距撞击"),
        "land_loitering_launcher": ("反辐射", "关机窗口", "批次合格率"),
        "land_mobile_precision_launcher": ("反辐射", "关机窗口", "空射", "批次合格率"),
        "counter_unmanned_launcher": ("纵深固定节点", "关机目标", "空射诱饵", "批次合格率"),
        "high_power_microwave": ("关机目标再捕获", "直接撞击", "批次合格率"),
        "shore_anti_ship_launcher": ("反辐射", "关机窗口", "空射诱饵", "批次合格率"),
        "anti_ship_loitering": (
            "诱饵辐射", "主攻波次开窗", "跨越关机窗口", "纵深固定节点"
        ),
        "anti_ship_cruise": (
            "现役反辐射", "关机窗口", "诱饵辐射源", "库存错配"
        ),
        "common_airframe": (
            "现役反辐射", "跨越关机窗口", "关机目标再捕获", "纵深固定节点"
        ),
        "evidence_cache": ("反辐射", "关机窗口", "诱饵辐射", "低空拦截"),
        "low_altitude_unmanned": (
            "反辐射", "关机窗口", "诱饵辐射", "证据缓存", "目标坐标过期"
        ),
        "anti_radiation": ("串行补射", "首击漏毁", "批次合格率"),
        "prsm": ("反辐射", "诱饵辐射", "首击漏毁"),
        "jassm": ("反辐射", "诱饵辐射", "批次合格率"),
        "low_cost_effecter": ("反辐射", "关机窗口", "重新授权"),
        "electronic_attack": ("首击漏毁", "目标坐标过期", "重新授权"),
    }
    family_conflict = any(
        marker in problem_text for marker in conflict_markers.get(family, ())
    )
    if legacy_wrapper or evidence_framed or family_conflict:
        return fallback
    return problem_text


def _family_equipment_subject(identity: str, equipment_text: str) -> str:
    """Keep public foreign models as comparisons, not the portrait subject."""

    family = _capability_family(identity)
    if family == "armed_unmanned_wingman":
        return "长航时低可探测武装无人僚机及其被动射频/光电侦察、小型精确毁伤、诱骗压制与受控交战组件"
    if family == "short_takeoff_unmanned_fire_carrier":
        return "短距起降低特征无人火力母机及其模块化载架、诱饵与小型巡航/巡飞弹挂载、抗扰导航和人在回路释放组件"
    if family == "cruise_mother_munition":
        return "远程异构子效应器巡航母弹及其安全分离、载荷状态管理、分时释放与低带宽窗口通报组件"
    if family == "expendable_mission_bridge":
        return "可消耗巡航弹式空中任务桥及其被动射频、简化成像、短窗低概率截获转发与安全终止组件"
    if family == "anti_radiation":
        primary = identity.split("；", 1)[0]
        if any(marker in primary for marker in ("巡飞", "长航时", "失辐射等待")):
            return "长航时多模复核反辐射巡飞猎歼弹"
        return "多模关机目标猎杀反辐射导弹"
    if family == "anti_ship_loitering" and any(
        marker in equipment_text for marker in ("诱饵", "电子压制", "压制载荷")
    ):
        return "长航时多模反舰巡飞猎歼弹药及其被动射频/光电复核、目标摘要与直接毁伤组件"
    if family == "high_power_microwave" and "巡飞" in identity.split("；", 1)[0]:
        return "高功率微波巡飞压制弹及其脉冲源、定向辐射、效应判定与安全闭锁组件"
    if family == "shore_anti_ship_launcher" and any(
        marker.lower() in equipment_text.lower() for marker in ("NMESIS", "NSM")
    ):
        return "岛岸机动反舰导弹发射车及其被动任务接收、短停发射与射后转移组件"
    if not any(
        marker.lower() in equipment_text.lower()
        for marker in (
            "JASSM",
            "PrSM",
            "Harop",
            "Harpy",
            "AARGM",
            "Barracuda",
            "MALD",
            "Launched Effect",
            "Switchblade",
            "Coyote",
        )
    ):
        return equipment_text
    subjects = {
        "evidence_cache": "间歇链路证据缓存巡飞猎歼弹药及其任务状态保持、低带宽摘要与重新授权组件",
        "anti_radiation": "关机目标再捕获反辐射巡飞弹药及其被动射频搜索、目标记忆与末端复核组件",
        "low_cost_effecter": "面向规模生产的低成本批量巡航效应器及其共用发射与任务规划接口",
        "electronic_attack": "空射可消耗诱饵与电子攻击效应器及其载机任务、威胁库与窗口通报接口",
        "low_altitude_unmanned": "箱式发射低空可消耗察打一体无人携弹平台及其本机复核、授权中止与毁伤载荷组件",
        "prsm": "地射远程精确制导导弹及其目标更新、任务规划和多模末制导升级组件",
        "jassm": "空射隐身防区外巡航导弹及其抗扰导航、末端复核与任务规划升级组件",
    }
    return subjects.get(family, equipment_text)


def _family_winning_thesis(
    identity: str,
    winning_text: str,
    *,
    raw_winning: object,
) -> str:
    """Replace evidence-management or model-comparison stubs with combat logic."""

    raw = _clean_clause(raw_winning, "")
    comparison_source = f"{winning_text}；{raw}"
    lowered = comparison_source.lower()
    comparison_stub = (
        winning_text.startswith(("不把", "相对", "保持"))
        or raw.startswith(("不把", "相对", "保持"))
        or "公开产品" in comparison_source
        or any(
            marker in lowered
            for marker in (
                "jassm",
                "prsm",
                "harop",
                "aargm",
                "barracuda",
                "mald",
                "anduril",
                "iai",
            )
        )
    )
    if not comparison_stub:
        return winning_text
    theses = {
        "unmanned_surface_missile_launcher": "以分散海上预置和异步受控发射，把机场与固定阵地损失转化为对手持续搜剿大量低特征射手的负担",
        "unmanned_surface_ambush": "以低特征海面待机把广域追踪问题压缩为关键航路内的局部遭遇，迫使舰队绕行、降速或投入清剿力量",
        "airborne_arsenal_carrier": "把机场尚可用时的一次起飞转化为多个战术释放窗口，以防区外在位库存延续诱骗、压制、侦察和精确毁伤节奏",
        "armed_unmanned_wingman": "把有人机或后方指挥节点的持续目标更新需求前推到低特征无人僚机，以在位复核和有限自带火力压缩机动防空节点的暴露—转移周期",
        "short_takeoff_unmanned_fire_carrier": "把完整跑道和有人载机从空射诱骗与轻型打击的必要条件降为可替代条件，以简易场地分散起降和混载释放维持空中释能节奏",
        "cruise_mother_munition": "把后方一次起射转化为岛链外缘多个时点、多个方位的诱骗、侦察、压制和有限毁伤动作，并以释放门槛保留未用子效应器",
        "expendable_mission_bridge": "把连续宽带目标更新需求压缩为可消耗节点的短时在位感知与低带宽摘要转发，使分散射手在链路间歇时仍能获得一次合法补射窗口",
        "land_loitering_launcher": "以无人值守短停发射和多阵位接替，把敌方对固定机场与阵地的压制收益转化为持续搜索岛岸机动射手的成本",
        "land_mobile_precision_launcher": "以道路网分散、短停发射和射后撤收维持机场外远程精击，使对手必须持续搜索大量临时阵位而不能靠首轮毁伤清空火力",
        "counter_unmanned_launcher": "以伴随近域分层拦截保护远火射手和补弹点，用较低成本自防效应器对冲敌低成本侦打一体消耗",
        "high_power_microwave": "以短时区域电磁效应同时压低多个无人或电子节点的功能可用性，为后续火力制造可测量的进入与补击窗口",
        "shore_anti_ship_launcher": "以岛岸道路机动和短停反舰齐射迫使海上编队扩大警戒、压缩机动空间并持续投入侦察与先发压制资源",
        "anti_ship_loitering": "把目标保管、近距复核和有限直接攻击前推到舰队可能区，压缩机动目标脱离搜索区和恢复编组的时间",
        "anti_ship_cruise": "把航迹陈旧度转化为受约束搜索负荷，以末段多模身份门控和弹间去重减少诱饵吸引、重复攻击与错误毁伤",
        "common_airframe": "以共同弹体库存和任务前载荷重配扩大可用齐射，使威胁变化不再直接转化为专用构型缺弹和任务取消",
        "evidence_cache": "把断链前形成的目标状态保持为可审计证据，并以人在回路重新授权压缩任务恢复时间",
        "anti_radiation": "用关机前目标记忆与末端独立复核跨越失辐射窗口，使真实压制节点不能仅凭静默解除猎歼压力",
        "low_cost_effecter": "以可预测批产、多轴多波次到达和快速补充，把对手拦截库存消耗转化为不可持续成本",
        "electronic_attack": "用可消耗诱饵诱发探测与火控响应并同步压制，为主攻武器制造可利用的时间—方位窗口",
        "low_altitude_unmanned": "把察、认、评、打前推至目标邻近空域，抢在对手转移、修复与伪装前完成受控补射",
        "prsm": "以目标有效期和末段多模证据控制再捕获或拒打，压缩机动目标依靠坐标过期获得的逃逸收益",
        "jassm": "以低可探测防区外投送、抗扰导航和末端复核缩短对手预警拦截时间并闭合纵深补击",
    }
    return theses.get(_capability_family(identity), winning_text)


def _family_overview_scenario(identity: str, scenario_text: str) -> str:
    """Replace research-topic wording with an equipment-local combat scene."""

    generic_scene = (
        any(marker in scenario_text for marker in ("装备研究", "任务阶段", "典型作战场景"))
        or scenario_text in {
            "强电磁压制下的短时火力窗口",
            "强电磁压制下短时目标暴露与链路间歇阶段",
        }
    )
    family = _capability_family(identity)
    family_scene_conflict = (
        family == "unmanned_surface_ambush"
        and not any(marker in scenario_text for marker in ("航路", "海峡", "通道", "水面"))
    ) or (
        family == "common_airframe"
        and not any(marker in scenario_text for marker in ("库存", "连续波次", "威胁变化"))
    ) or (
        family == "expendable_mission_bridge"
        and not any(
            marker in scenario_text
            for marker in ("敌", "对手", "防空", "机动", "诱饵", "干扰", "拦截")
        )
    )
    if not generic_scene and not family_scene_conflict:
        return scenario_text
    scenes = {
        "unmanned_surface_missile_launcher": (
            "前沿机场与固定岸基发射点受毁后，岛链海域仍需保持间歇纵深补击和海上拒止，"
            "敌方同时以海空侦察搜剿分散射手的场景"
        ),
        "unmanned_surface_ambush": (
            "岛链海峡、补给通道或舰队机动出口内，远程反舰链已失去实时航迹，"
            "对手水面编队仍必须在有限航路和时间窗内通过的场景"
        ),
        "airborne_arsenal_carrier": (
            "战役开端至前沿机场受毁后数小时，后方或幸存机场仍能完成一次起飞，"
            "但返场、补弹和再次出动链即将中断的场景"
        ),
        "armed_unmanned_wingman": (
            "前沿机场反复受毁、有人航空兵难以前出后的持续压制阶段，敌机动防空和电子战车辆短时开机、"
            "关机转移并以诱饵和近程反无人火力掩护重组的场景"
        ),
        "short_takeoff_unmanned_fire_carrier": (
            "前沿机场主跑道局部受毁、滑行道或简易场地仍可短时使用，而有人战机难以持续出动，"
            "敌防空与电磁压制继续封锁空射火力入口的场景"
        ),
        "cruise_mother_munition": (
            "前沿机场和固定发射阵地受毁后的首轮续击阶段，后方机动射手仅获得短时起射窗口，"
            "敌一体化防空以雷达静默、假源、机动转移和近程拦截压缩跨岛链火力入口的场景"
        ),
        "expendable_mission_bridge": (
            "前沿机场受毁、主数据链间歇且有人侦察平台不宜前出时，敌防空与机动目标持续改变位置，"
            "并以频谱静默、诱饵和近程拦截压缩感知窗口，岸海分散射手需要一次短时目标更新和任务转交窗口的场景"
        ),
        "land_loitering_launcher": (
            "前沿机场受毁后，岛岸临时发射地域遭无人侦察和远程火力反复重访，"
            "巡飞弹射手必须短停释放并多阵位接替的场景"
        ),
        "land_mobile_precision_launcher": (
            "第一岛链岛屿与临时前沿作战点内，机场和固定阵地遭持续压制，"
            "地面远程火力依托道路网隐蔽机动并等待短时授权窗口的场景"
        ),
        "counter_unmanned_launcher": (
            "岛基远火发射车、补弹点和临时阵地刚完成释能即遭小型无人机、"
            "巡飞弹和电子定位链连续追击的近域防护场景"
        ),
        "high_power_microwave": (
            "敌低空无人集群、通信中继或电子战节点密集活动，传统逐目标拦截难以维持成本交换，"
            "后续远火急需短时功能压制窗口的场景"
        ),
        "shore_anti_ship_launcher": (
            "机场和固定岸防阵地受压后，敌海上补给、两栖支援或编队外缘舰艇穿越岛链通道，"
            "岛岸射手依托道路网短停反舰交战的场景"
        ),
        "anti_ship_loitering": (
            "岛链外缘反舰交战中，外部航迹被压制后水面编队机动、施放诱饵并组织近程拦截，"
            "前沿火力需要持续保管目标并等待可授权攻击窗口的场景"
        ),
        "anti_ship_cruise": (
            "远海反舰齐射飞行期间，外部航迹更新中断、目标编队机动并以诱饵和商船混杂掩护的场景"
        ),
        "common_airframe": (
            "高强度连续火力战，敌防空工作方式和目标优先级快速变化，"
            "己方有限弹药库存必须临机生成诱饵、猎辐射与直接毁伤混合齐射的场景"
        ),
        "evidence_cache": (
            "联合火力追击机动发射车、雷达和指挥节点时，目标仅短时暴露，"
            "侦察平台刚形成候选轨迹即遭数据链压制、授权链被迫中断的场景"
        ),
        "anti_radiation": (
            "联合空中进攻进入敌一体化防空区前，预警与火控雷达间歇开机、关机转移并释放诱饵，"
            "主攻火力急需获得时间—方位突防走廊的场景"
        ),
        "low_cost_effecter": (
            "高强度持续火力战中，对手以多层防空保护纵深固定和准固定节点，"
            "己方高端远程弹药库存与补充速度不足以支撑连续波次的场景"
        ),
        "electronic_attack": (
            "联合空中突击主攻波次进入敌一体化防空区前，预警、跟踪和火控雷达保持分层警戒，"
            "必须先诱发响应、错配拦截资源并压低局部火控质量的场景"
        ),
        "low_altitude_unmanned": (
            "远程火力首击后，漏毁目标在强干扰与烟尘中短时再暴露，"
            "后方补射难赶上其修复转移窗口的场景"
        ),
        "prsm": (
            "联合火力战中，对手机动发射车、防空节点和战役指挥所短时暴露后迅速转移，"
            "地面远程火力必须在侦察解过期前完成射击与末段确认的场景"
        ),
        "jassm": (
            "联合战役首轮纵深突击后，对手一体化防空仍在恢复、卫星导航欺骗持续生效，"
            "空中编队需要从防区外续击防空指挥所、远程火力节点与保障枢纽的场景"
        ),
    }
    return scenes.get(family, scenario_text)


def _family_overview_outcome(
    identity: str,
    capability_text: str,
    effect_text: str,
) -> tuple[str, str]:
    """State the operationally valuable capability and battlefield result."""

    primary = identity.split("；", 1)[0]
    family = _capability_family(identity)
    if family == "unmanned_surface_ambush":
        return (
            "在海峡、补给通道和机动出口内低特征待机，近距识别并拦截经授权水面目标",
            "迫使舰队绕行、降速、改变编队或投入航空与反水面力量清剿伏击区，并为远程反舰火力重新捕获目标争取时间",
        )
    if family == "unmanned_surface_missile_launcher":
        return (
            "在岛链海域低特征预置、按人工授权释放远程弹药并射后转移接替",
            "在跑道和固定阵地受毁后保留间歇纵深补击与区域拒止火力，并迫使对手扩大海空搜剿范围",
        )
    if family == "airborne_arsenal_carrier":
        return (
            "由后方或幸存机场一次起飞，在岛链外防区外待机并管理弹药库存，按授权分批释放防区外弹药且保留未用载荷",
            "依据战果摘要补射、重新占位或退出，使机场受毁后仍保留可接替的空基远程打击入口",
        )
    if family == "armed_unmanned_wingman":
        return (
            "在岛链外缘长时低特征待机，以被动射频和光电复核机动防空、电子战及远程火力节点，并在人工授权下自行有限攻击或引导后续远火",
            "迫使敌机动防空缩短开机时间、增加转移频次并投入近程反无人资源；目标证据不足时保持跟踪或拒打，避免把察打僚机退化为失控自主猎杀平台",
        )
    if family == "short_takeoff_unmanned_fire_carrier":
        return (
            "由滑行道、道路或简易场地短距起飞，低电磁航行至授权释放区并先后释放诱饵与小型巡航/巡飞弹",
            "在有人战机和完整跑道不可持续使用时维持诱骗、压制和轻型打击架次，为后续远火制造突防窗口并迟滞敌防空重组",
        )
    if family == "cruise_mother_munition":
        return (
            "由后方机动射手一次起射，在岛链外缘按威胁响应分时释放诱饵、被动侦察、电子压制和有限毁伤子效应器",
            "诱出或压低敌防空火控、复核可攻击节点并向后续精打通报时间—方位窗口；授权或目标证据不足时保留载荷或安全终止",
        )
    if family == "expendable_mission_bridge":
        return (
            "由岸海分散节点释放后，在目标区外缘短时获取被动射频或简化成像证据，并向授权射手转发带时间戳、置信度和有效期的目标摘要",
            "在连续链路不可用时恢复一次目标确认、火力转交和补射决策窗口；证据过期、身份冲突或转发失败时安全终止而不自行攻击",
        )
    if family == "land_loitering_launcher":
        if _is_sealed_loitering_nest(identity):
            return (
                "由多个岛上密封发射巢长期低活动预置、按人工授权分批释放巡飞弹并由未暴露节点接替",
                "在车辆和道路发射链受压后仍能搜索、复核和补击漏毁或转移目标，并迫使对手持续清剿大量疑似弹巢",
            )
        return (
            "在岛岸道路网内无人值守短停展开、分批释放巡飞弹并由多阵位接替",
            "前沿机场失能后仍保持对漏毁、转移和再次暴露目标的持续搜索与补击，并降低发射节点被重访摧毁的概率",
        )
    if family == "land_mobile_precision_launcher":
        return (
            "由岛上道路机动发射车隐蔽待机、短停释放远程精确导弹并射后撤收接替",
            "在机场出动链被压制时持续威胁敌防空、指挥、集结、港口和远程火力节点，维持机场外纵深破击",
        )
    if family == "counter_unmanned_launcher":
        return (
            "伴随远火射手群对侦察无人机、巡飞弹和低空攻击节点实施有人监督的动能或非动能分层拦截",
            "保护发射车、补弹点和临时阵地完成撤收与下一射击周期，提高远火节点的发射后生存和再释能机会",
        )
    if family == "high_power_microwave":
        return (
            "对任务区内多个低空无人或电子节点实施可控短时功能压制并判定恢复窗口",
            "降低蜂群与电子节点的同步工作能力，为后续巡航弹、巡飞弹或机动火力进入和补击制造可重复利用的时间窗口",
        )
    if family == "shore_anti_ship_launcher":
        return (
            "由岛岸机动发射车在低特征阵位短停释放反舰导弹并射后快速转移",
            "在机场和固定岸防节点受毁后继续威胁敌补给、两栖支援和编队外缘舰艇，压缩其岛链通道机动自由",
        )
    if family == "anti_ship_loitering":
        if "空射" in primary:
            return (
                "由载机防区外分批投放、弹药多轴错时进入并接替目标保管",
                "压缩载机暴露并分散拦截压力，由存活弹药复核后直接攻击",
            )
        if "射频复核" in primary:
            return (
                "以被动射频与成像交叉确认机动水面目标并由存活节点直接攻击",
                "降低静默、诱饵和外围拦截造成的错误关联与无效消耗",
            )
        return (
            "在舰队可能区持续搜索并保管机动水面目标，以被动射频和视觉证据完成身份复核、局部毁伤评估与受控直接攻击",
            "更新后续反舰弹搜索区、续接反舰火力，并在授权成立时直接毁伤水面目标，压缩其脱离接触和恢复编组的时间",
        )
    if family == "anti_ship_cruise":
        if "协同去重" in primary:
            return (
                "在外部更新中断后由弹群分配搜索扇区、交换有限目标摘要并避免多弹重复攻击同一疑似舰艇",
                "把有限齐射弹量转化为更大的有效搜索覆盖和更多独立毁伤机会，同时以失联预案控制误击与重复消耗",
            )
        if "有限区搜索" in primary:
            return (
                "由单枚远程反舰巡航弹按航迹陈旧度、剩余能量和目标机动包线生成有限搜索区并完成多模身份复核",
                "在不依赖持续中段更新时直接毁伤经授权水面舰艇，证据或能量不足时安全拒打以避免沿旧航迹误击",
            )
        return (
            "在外部更新中断后按目标可能区完成受约束搜索、身份复核、弹间去重与直接反舰毁伤",
            "降低机动舰艇借航迹过期和诱饵获得的逃逸收益，并减少多弹重复攻击造成的火力浪费",
        )
    if family == "common_airframe":
        return (
            "用共同弹体库存按任务前威胁判断生成诱饵、猎辐射或直接毁伤构型的混合齐射",
            "降低专用弹药库存错配导致的任务取消和齐射规模下降，同时增加对手早期分类负担",
        )

    outcomes = {
        "evidence_cache": (
            "断链条件下保持短时暴露目标证据、恢复后快速重关联并受控续接交战",
            "把链路恢复后的任务起点由重新搜索前移到复核授权，抢回机动目标再次隐蔽前的补击时间",
        ),
        "anti_radiation": (
            "对间歇辐射、关机转移和诱饵掩护下的防空雷达与火控节点持续猎歼压制",
            "直接摧毁或压制预警雷达、火控雷达和电子战车辆，打断防空目标分配与导弹制导，形成局部防空盲区并掩护后续突击火力歼灭指挥所、导弹阵地和保障枢纽",
        ),
        "low_cost_effecter": (
            "以可规模补充的巡航效应器对纵深固定和准固定节点实施多轴多波次压制毁伤",
            "消耗对手高价拦截库存、保持连续火力波次，并把高端弹药集中用于高难度突防和高价值目标",
        ),
        "electronic_attack": (
            "在主攻武器进入前诱骗、干扰和压制敌防空探测与火控链",
            "制造可利用的时间—方位突防走廊，迫使对手暴露雷达、错配火控或在静默中丢失空情",
        ),
        "low_altitude_unmanned": (
            "在目标邻近空域持续完成漏毁目标再发现、本机复核、局部毁伤评估和受控补射",
            "在对手转移、修复和重新伪装前完成二次毁伤，维持远程火力首击后的连续瘫痪节奏",
        ),
        "prsm": (
            "由分散地面火力对战役纵深机动发射车、防空节点和指挥保障目标实施快速再捕获与精确补击",
            "压缩目标暴露至毁伤时间，在导航受扰和坐标过期时减少错误区域攻击并阻断对手机动火力再组织",
        ),
        "jassm": (
            "在一体化防空与导航欺骗叠加条件下对战役纵深固定、准固定高价值节点实施受控突防毁伤与快速补击",
            "压缩敌防空体系恢复、远程火力再装填和保障枢纽修复时间，保持联合战役纵深破击节奏",
        ),
    }
    return outcomes.get(
        _capability_family(identity),
        (capability_text, effect_text),
    )


def _exchange_effect_clause(identity: str) -> str:
    family = _capability_family(identity)
    if family == "unmanned_surface_missile_launcher":
        return "把摧毁机场和固定阵地的单点收益转化为搜索、识别并压制大量低特征海上发射节点的持续成本"
    if family == "unmanned_surface_ambush":
        return "把舰队可选航路、通过时间和清剿需求转化为可计量的机动与防护成本"
    if family == "airborne_arsenal_carrier":
        return "把机场的一次出动转化为多个释放窗口和可保留的剩余载荷，同时显式计入母机被发现后的集中损失风险"
    if family == "armed_unmanned_wingman":
        return "把后方串行再发现与补击改为目标区外缘的在位复核和有限自带火力，压缩对手机动、关机与重组时间"
    if family == "short_takeoff_unmanned_fire_carrier":
        return "把空射诱饵和轻型弹药对完整跑道、有人载机的依赖转化为对手必须同时搜索简易起降点、低特征母机和多类释放载荷的防护成本"
    if family == "cruise_mother_munition":
        return "把后方一次起射转化为多个分时子效应器窗口，并以母弹被拦截的集中损失风险约束载荷规模与释放时机"
    if family == "expendable_mission_bridge":
        return "把持续占用高价值侦察平台和宽带链路的需求转化为可消耗节点的一次短窗目标更新，并以射手获得的有效补射机会衡量交换收益"
    if family == "land_loitering_launcher":
        if _is_sealed_loitering_nest(identity):
            return "把集中车辆发射改为大量密封节点长期预置、分批释放和未暴露弹巢接替"
        return "把固定阵地一次性齐射改为多阵位短停释放、射后转移和弹群在位接替"
    if family == "land_mobile_precision_launcher":
        return "把固定发射阵地的单点脆弱性转化为道路网内的搜索、定位、压制与再搜索成本"
    if family == "counter_unmanned_launcher":
        return "以较低成本近域拦截换取远火射手、补弹点和剩余弹药的后续射击周期"
    if family == "high_power_microwave":
        return "把逐目标拦截转化为区域内多节点短时功能压制，并以恢复时间和后续突防增益约束效应价值"
    if family == "shore_anti_ship_launcher":
        return "把海上编队的机动自由转化为持续警戒、航路调整、先发压制与护航资源投入"
    if family == "anti_ship_loitering":
        primary = identity.split("；", 1)[0]
        if "空射" in primary:
            return "把载机单轴一次释放改为防区外多轴错时投放、目标区在位保管和后续批次接替"
        if "射频复核" in primary:
            return "把单源疑似发现改为被动射频—成像交叉确认，并由抗拦截存活节点在授权后直接攻击"
        return "把等待后方航迹恢复改为目标可能区内的持续保管、近距复核和受控攻击"
    if family == "anti_ship_cruise":
        primary = identity.split("；", 1)[0]
        if "协同去重" in primary:
            return "把多弹重复搜索和重复攻击转化为扇区分工、摘要交换与失联去重规则"
        if "有限区搜索" in primary:
            return "把航迹陈旧和剩余能量约束转化为单弹有限搜索区、身份复核与安全拒打选择"
        return "把航迹过期和多弹重复追踪转化为受约束搜索、目标去重与安全拒打选择"
    if family == "common_airframe":
        return "以任务前载荷重配和共同库存改变专用品种、可用弹量与防御方分类资源的交换关系"
    if family == "anti_radiation":
        return "迫使对手在持续辐射暴露与关机失去探测、火控能力之间选择"
    if family == "evidence_cache":
        return "把断链后的目标丢失转化为可审计的证据保持和再授权延迟"
    if family == "low_cost_effecter":
        return "以冻结构型、批产一致性和多波次补充速度改变高价拦截弹与巡航效应器的成本交换"
    if family == "electronic_attack":
        return "迫使对手在持续开机暴露、火控资源错配与保持静默导致探测效能下降之间选择"
    if family == "low_altitude_unmanned":
        return "把等待后方重组改为目标区附近在位确认和补射，压缩对手转移、修复与伪装时间"
    if family == "prsm":
        return "把目标机动与坐标过期风险转化为受约束再捕获和安全拒打选择"
    return "压缩发现、确认、交战与再组织时间，并提高对手维持防护的资源代价"


def _effect_metric_clause(identity: str) -> str:
    family = _capability_family(identity)
    if family == "unmanned_surface_missile_launcher":
        return "海上待机可用率、授权与弹舱状态复核正确率、受控发射成功率、射后脱离率和连续补击波次数"
    if family == "unmanned_surface_ambush":
        return "航路覆盖率、近距识别正确率、有效拦截率、伏击区清剿成本和目标绕行时间"
    if family == "airborne_arsenal_carrier":
        return "防区外在位可用率、载荷任务匹配正确率、受控释放成功率、释放窗口响应时间和单机损失载荷集中度"
    if family == "armed_unmanned_wingman":
        return "外缘在位可用率、被动射频—光电复核正确率、授权交战时延、自带弹药直接毁伤率和后续火力引导成功率"
    if family == "short_takeoff_unmanned_fire_carrier":
        return "简易场地出动成功率、混载安全分离率、授权释放时延、诱饵开窗有效率、小型打击弹任务完成率和单架次载荷损失"
    if family == "cruise_mother_munition":
        return "母弹到达任务区外缘率、子效应器安全分离率、载荷任务匹配正确率、有效压制/毁伤窗口和母弹损失载荷集中度"
    if family == "expendable_mission_bridge":
        return "任务区到达率、目标摘要正确率、摘要转交时延、授权射手有效补射率和错误转发触发安全终止率"
    if family == "land_loitering_launcher":
        if _is_sealed_loitering_nest(identity):
            return "长期封存可用率、授权释放成功率、单巢暴露率、弹群接替覆盖时间和有效补射闭环时间"
        return "阵位进入成功率、短停释放成功率、射后脱离率、弹群接替覆盖时间和补射闭环时间"
    if family == "land_mobile_precision_launcher":
        return "阵位转换成功率、短停发射成功率、射后脱离率、相邻车组补射接替时间和补弹恢复周期"
    if family == "counter_unmanned_launcher":
        return "低空目标分类正确率、分层拦截成功率、单位有效拦截成本、被护节点生存率和再发射保持率"
    if family == "high_power_microwave":
        return "有效作用节点数、功能压制确认率、恢复时间分布、附带影响边界和后续火力突防增益"
    if family == "shore_anti_ship_launcher":
        return "短停发射成功率、射后脱离率、目标航迹时效、反舰毁伤成功率和多阵位接替时间"
    if family == "anti_ship_loitering":
        primary = identity.split("；", 1)[0]
        if "空射" in primary:
            return "载机释放窗口、投放轴线覆盖率、进入时序离散度、目标保管接替成功率和直接攻击成功率"
        if "射频复核" in primary:
            return "射频—成像一致率、诱饵错误接受率、拦截幕下存活搜索时间、身份复核正确率和直接攻击成功率"
        return "目标保管时间、身份复核正确率、搜索区更新时延、直接攻击成功率和安全拒打率"
    if family == "anti_ship_cruise":
        primary = identity.split("；", 1)[0]
        if "协同去重" in primary:
            return "扇区重复率、目标摘要一致率、重复攻击率、独立目标覆盖数和失联安全拒打率"
        if "有限区搜索" in primary:
            return "有限搜索区覆盖率、单弹再捕获率、身份复核正确率、剩余能量裕度和安全拒打率"
        return "目标再捕获率、重复攻击率、安全拒打率和单位有效毁伤成本"
    if family == "common_airframe":
        return "任务可用弹量、换装周期、混合齐射适配率和共同弹体性能折衷"
    if family == "anti_radiation":
        return "关机目标再捕获率、诱饵误接受率、安全拒打率和有效压制窗口"
    if family == "evidence_cache":
        return "目标轨迹保持率、重新授权时延、正确拒打率和目标重关联时间"
    if family == "low_cost_effecter":
        return "批次合格率、任务完成率、单位有效毁伤成本和补充周期"
    if family == "electronic_attack":
        return "威胁雷达响应率、有效压制窗口、后续突防增益和单位诱饵任务成本"
    if family == "low_altitude_unmanned":
        return "目标再发现率、补射时延、单位有效毁伤成本和平台损耗率"
    if family == "prsm":
        return "末段再捕获率、错误接受率、正确拒打率和单位有效毁伤成本"
    project = _identity_project_label(identity)
    return (
        f"{project}任务完成率、{project}任务闭环时间、单位任务代价和"
        "关键节点受损后的任务保持率"
    )


def _identity_project_label(identity: str) -> str:
    """Return a short project-local label for generic portrait contracts."""

    primary = _clean_clause(identity.split("；", 1)[0], "")
    first_token = re.split(r"\s+", primary, maxsplit=1)[0].strip()
    if first_token:
        return first_token[:24]
    title = build_capability_title(name=primary, equipment_form=primary)
    return title if title != "具体武器装备方向" else "该装备"


def _family_module_focus(identity: str) -> dict[str, str]:
    """Return equipment-specific combat arguments for the five modules."""

    family = _capability_family(identity)
    primary = identity.split("；", 1)[0]
    if family == "land_loitering_launcher" and _is_sealed_loitering_nest(identity):
        return {
            "technology": (
                "战斗构型由可长期封存的密封箱体、巡飞弹弹巢、环境与弹药健康监测、低截获任务终端、"
                "远程安全闭锁、伪装/诱饵外形和分批释放控制组成；发射巢负责保存与释放，已释放巡飞弹负责搜索和毁伤"
            ),
            "effect": (
                "多个发射巢战前分散预置并保持低活动，收到带有效期的任务包和人工授权后分批释放巡飞弹；"
                "弹群搜索、复核并补击漏毁或转移目标，未暴露的邻近弹巢按余弹与战果接替"
            ),
            "winning": (
                "把敌方摧毁道路车辆和固定阵地的收益转化为持续发现、识别并逐个清除大量伪装密封节点的成本；"
                "单巢暴露或损失不应中断其他弹巢的授权释放和接替"
            ),
            "development": (
                "先验证长期封存、环境健康监测、远程安全闭锁和分批释放，再在地面搜索、电子诱骗、假目标、"
                "节点暴露和补装填受限条件下开展多巢接替，以封存可用率和授权释放成功率决定转段"
            ),
        }
    if family == "unmanned_surface_ambush":
        return {
            "technology": (
                "战斗构型围绕低特征艇体、海面长时待机、非GNSS航路保持、被动声学/射频/光电近距识别、"
                "避碰与禁击区约束、直接撞击或战斗部毁伤和安全自毁状态机展开"
            ),
            "effect": (
                "把最后可靠情报中的海峡、补给通道和机动出口转化为局部伏击区，水面目标进入后完成近距识别、"
                "受控拦截和毁伤；未满足授权门槛时保持隐蔽、转移或终止任务"
            ),
            "winning": (
                "以空间占据压缩舰队可选航路，迫使其在绕行延误、降低航速、扩大护航警戒或投入清剿力量之间取舍；"
                "无人艇不承担纵深巡航弹对固定节点的多波次打击任务"
            ),
            "development": (
                "先验证海况适应、航路保持、避碰与目标分类，再开展商船混杂、电子干扰、航空巡逻和反水面清剿对抗，"
                "以授权目标有效拦截、误击/拒打和迫使绕行的任务结果决定转段"
            ),
        }
    if family == "anti_ship_loitering":
        if "空射" in primary:
            return {
                "technology": (
                    "战斗构型聚焦载机任务装订与安全分离接口、防区外分批投放、非GNSS低空进入、多轴航路去冲突、"
                    "目标保管接替和直接毁伤战斗部；载机只承担投放，不持续遥控末段交战"
                ),
                "effect": (
                    "载机在短暂安全窗口从不同方位错时投放，弹药分散进入舰队可能区并由前后批次接替目标保管；"
                    "身份与授权成立的节点以自身战斗部直接攻击，后续批次依据目标丢失或局部BDA改搜、补击或拒打"
                ),
                "winning": (
                    "以防区外投放压缩载机暴露时间，用多轴错时进入分散外围拦截资源，并迫使对手在扩大警戒扇区、"
                    "持续机动和保留近程拦截库存之间分配资源"
                ),
                "development": (
                    "先验证载机接口、安全分离和投放误差，再比较单轴齐投、多轴错时和前后批接替三种方案，"
                    "以载机暴露、目标区有效到达、保管接替与直接攻击结果决定空射增量是否成立"
                ),
            }
        if "射频复核" in primary:
            return {
                "technology": (
                    "战斗构型聚焦低截获被动射频、成像复核、跨模态时空关联、传感器暴露控制、抗拦截自主规避、"
                    "身份置信门和直接毁伤战斗部；不得把诱发辐射或电子压制作为主流程"
                ),
                "effect": (
                    "遭遇间歇辐射、诱饵和外围拦截幕时，各节点控制传感器暴露并独立规避；存活节点以被动射频和"
                    "成像完成交叉确认，达到身份与授权门槛后直接攻击舰艇或舰载高价值部位，否则继续观察或拒打"
                ),
                "winning": (
                    "把对手依靠静默、诱饵和外围拦截制造的单源不确定性转化为跨模态交叉确认门槛，迫使其同时维持"
                    "多个传感维度的一致欺骗并投入更多拦截资源"
                ),
                "development": (
                    "先在间歇辐射、离舰诱饵和中立航运背景下盲测射频—成像关联，再逐级增加无人拦截密度，"
                    "以跨模态一致、错误接受、存活搜索时间和授权后直接毁伤结果决定转段"
                ),
            }
        return {
            "technology": (
                "战斗构型围绕长航时飞行、被动射频与光电视觉目标分类、航迹连续性维护、目标质量摘要、"
                "抗扰导航、直接毁伤战斗部和受控拒打状态机展开；诱饵与电子压制不得替代主猎歼闭环"
            ),
            "effect": (
                "在外部航迹中断后于舰队可能区持续搜索和保管目标，向后续反舰弹更新搜索区、身份置信度与局部BDA；"
                "授权成立时由自身战斗部直接攻击，条件不足时继续观察或安全拒打"
            ),
            "winning": (
                "用前沿在位时间压缩水面编队脱离接触、重构队形和恢复防护的窗口，并迫使其持续开启近程警戒与拦截；"
                "若只能诱骗雷达或为主攻波次开窗，则应归入伴随诱饵而非本装备"
            ),
            "development": (
                "先验证目标保管、海面身份复核、摘要更新和直接毁伤四个增量，再在诱饵、商船混杂、断链和近程拦截下"
                "比较目标保管时间、后续反舰弹搜索收益与自身攻击结果，主任务不能独立成立时停止转段"
            ),
        }
    if family == "anti_ship_cruise":
        if "协同去重" in primary:
            return {
                "technology": (
                    "战斗构型围绕弹群搜索扇区生成、低带宽目标摘要、摘要置信度与时间戳、重复目标判定、"
                    "链路可用时协同去重和失联时预置独立扇区状态机展开；单弹导引性能只作为共同基线"
                ),
                "effect": (
                    "多弹进入目标可能区后优先覆盖不同搜索扇区，发现疑似舰艇时只交换最小身份摘要；"
                    "满足一致性与授权门槛的弹药实施毁伤，其余弹药改搜、拒打或转向独立目标，避免火力堆叠"
                ),
                "winning": (
                    "把齐射数量优势从同一路径重复保险转化为并行搜索覆盖和独立目标攻击机会，迫使对手同时制造"
                    "跨扇区一致诱饵或切断摘要交换；单纯吸引一枚弹药不再能耗尽整次齐射"
                ),
                "development": (
                    "先用数字靶场验证扇区分配与重复目标判定，再开展链路可用、间歇和全失联三组多弹飞行试验，"
                    "以独立目标覆盖、重复攻击、摘要冲突和失联拒打结果判定协同增量是否成立"
                ),
            }
        if "有限区搜索" in primary:
            return {
                "technology": (
                    "战斗构型聚焦单弹目标包时效、航迹误差椭圆、剩余能量与导引头视场联合生成有限搜索区，"
                    "并用被动射频/成像互证、商船避让和安全弃攻闭合从搜索到直接反舰毁伤的单弹增量"
                ),
                "effect": (
                    "弹药不等待新的中段航迹，而按最后可信区域和目标最大机动包线搜索；发现候选舰艇后完成身份"
                    "复核并直接毁伤，搜索区过大、剩余能量不足或证据冲突时拒打，不承担弹群角色分配"
                ),
                "winning": (
                    "压缩机动舰艇利用航迹过期逃逸的时间窗口，同时以明确拒打边界迫使对手投入更高强度的诱饵、"
                    "商船混杂和机动资源才能把搜索能力反转为误击风险；收益来自单弹闭环而非弹间通信"
                ),
                "development": (
                    "先联合校准航迹年龄—搜索面积—剩余能量—再捕获概率曲线，再在不同目标机动、诱饵和商船"
                    "密度下开展单弹盲试，以直接毁伤、正确拒打和能量耗尽样本决定转段"
                ),
            }
        return {
            "technology": (
                "战斗构型围绕抗扰组合导航、目标包时效管理、受约束概率搜索、多模舰艇身份复核、"
                "弹间目标摘要与安全弃攻状态机展开，分别闭合单弹再捕获和多弹去重两个可归因增量"
            ),
            "effect": (
                "在舰队机动、诱饵拖曳和外部更新中断后，将最后可信目标区域压缩为可搜索扇区，"
                "按授权门槛选择毁伤、改搜或拒打，并用局部摘要减少多弹追逐同一疑似目标"
            ),
            "winning": (
                "把对手机动造成的航迹陈旧度转化为弹上可计量搜索负荷，并通过身份证据门和去重规则"
                "压缩诱饵吸引、重复攻击与错误释放毁伤的收益"
            ),
            "development": (
                "先分别验证导航误差—搜索区—剩余能量包线和末段多模身份复核，再开展断链、诱饵、"
                "商船混杂与多弹失联对抗，以再捕获、去重、拒打和直接毁伤结果决定转段"
            ),
        }
    if family == "common_airframe":
        return {
            "technology": (
                "共同弹体必须冻结机械安装面、电气母线、数据接口、质量重心、功率热耗散、射频隔离"
                "和飞行包线；每种任务载荷超出任一边界即淘汰共享方案而不是向共同平台转嫁风险"
            ),
            "effect": (
                "任务前按最新威胁从共同库存配置诱饵、被动猎辐射或直接毁伤载荷，在不增加专用品种的"
                "条件下形成可用混合齐射，并降低某一专用构型库存不足导致的任务取消"
            ),
            "winning": (
                "用载荷重配增加防御方早期分类与拦截分配难度，同时把己方库存结构由多个专用品种"
                "转为共同弹体池；若性能折衷抵消可用弹量收益，则专用异构弹药仍应优先"
            ),
            "development": (
                "先完成接口控制文件、载荷替代件和换装后结构分离试验，再比较共同弹体与专用异构基线的"
                "任务可用弹量、换装周期和混合齐射适配率，以共同化净收益决定是否型号化"
            ),
        }
    profiles = {
        "unmanned_surface_missile_launcher": {
            "technology": (
                "战斗构型由半潜低特征艇体、模块化巡航弹舱、非GNSS航位保持、被动警戒、"
                "低截获授权终端、发射安全闭锁和弃置封控组件组成，艇体只承担海上预置、"
                "受控发射与转移，不以近距撞击作为主毁伤方式"
            ),
            "effect": (
                "在前沿机场和固定阵地受毁后，由分散海上节点按授权向敌纵深指挥、保障、"
                "远程火力或海上编队释放巡航弹，发射后转移或沉默等待下一任务包，续接岸基"
                "与空基远火空窗"
            ),
            "winning": (
                "把敌方摧毁跑道和固定阵地的收益转化为搜索大量低特征海上发射节点的成本；"
                "对手若扩大海空搜剿会分散防空与反舰资源，若不搜剿则必须承受异步补击"
            ),
            "development": (
                "先验证长期海上待机、弹舱环境、安全封控和非GNSS航位保持，再开展海况发射、"
                "弱网授权、发射后转移以及反无人水面搜剿条件下的多节点连续释能试验"
            ),
        },
        "airborne_arsenal_carrier": {
            "technology": (
                "战斗构型由大航程无人固定翼母平台、防区外弹药挂架/弹舱与安全分离装置、岛链外待机航路、"
                "低带宽任务接收、弹药库存管理和人工授权释放组件组成；平台只负责携载与分批释放防区外弹药，"
                "不前出执行末端察打闭环"
            ),
            "effect": (
                "由后方或幸存机场升空后在岛链外防区外等待，按授权和目标时效分批释放防区外弹药，"
                "保留未用载荷；接收战果摘要后补射、转入备用等待区重新占位或退出返航"
            ),
            "winning": (
                "把一次起飞拆分为多个战术释放窗口，迫使对手持续搜索更大空域并长期维持远程防空警戒；"
                "若母机损失导致载荷集中损失超过节奏收益，则应缩小单机载荷或改为多平台分散"
            ),
            "development": (
                "先验证长航时在位、弹舱环境、安全分离和载荷任务管理，再开展强扰、远程防空搜索、"
                "短窗授权与母机战损条件下的分批释放对抗，以在位可用率和载荷集中损失决定转段"
            ),
        },
        "armed_unmanned_wingman": {
            "technology": (
                "战斗构型由长航时低可探测无人固定翼平台、被动射频与光电传感器、小型精确弹、"
                "有限诱骗/电子压制载荷、抗扰导航、低带宽任务终端和人工授权/安全拒打组件组成；"
                "僚机必须以自身传感和自带火力形成可归因战果"
            ),
            "effect": (
                "从后方或临时场地起飞进入岛链外缘待机，持续复核短时开机的防空、电子战和远程火力车辆；"
                "授权成立时自行有限攻击或引导远程弹药，证据不足时跟踪、诱骗、退出或拒打"
            ),
            "winning": (
                "把目标再发现、身份复核和有限补击前推到目标邻近空域，迫使对手在开机暴露、频繁转移、"
                "投入近程反无人资源或放弃局部防空覆盖之间选择"
            ),
            "development": (
                "先验证长航时低特征飞行、被动射频—光电交叉复核和安全授权，再在强扰、假源、关机机动、"
                "近程拦截和临时场地保障条件下比较自行毁伤与引导补击收益"
            ),
        },
        "short_takeoff_unmanned_fire_carrier": {
            "technology": (
                "战斗构型由短距起降低特征无人固定翼平台、模块化内外载架、诱饵与小型巡航/巡飞弹、"
                "抗扰被动导航、载荷安全分离、低带宽任务终端和人在回路释放组件组成；母机负责把载荷送至释放区，"
                "不得被描述成巡航弹或巡飞弹本体"
            ),
            "effect": (
                "分散航空分队从滑行道、道路或简易场地起飞，低电磁进入释放区后按人工授权先投放诱饵、"
                "再释放小型打击弹药，并依据威胁和余油选择转场、退出或执行可消耗任务"
            ),
            "winning": (
                "把有人机和完整机场的集中出动链拆成多个简易场地无人架次，使对手必须同时压制起降点、母机航路和释放载荷；"
                "若载荷过小、生存性不足或维护负担接近有人机，则该平台逻辑不成立"
            ),
            "development": (
                "先验证简易场地短距起降、诱饵与小型弹药混载安全分离、弱网人在回路释放和转场保障，"
                "再在低空预警、近程防空、强扰和起降点反复受击条件下比较架次替代率与有效释能结果"
            ),
        },
        "cruise_mother_munition": {
            "technology": (
                "战斗构型由远程巡航母弹、模块化子舱、安全分离装置、载荷健康管理、抗扰组合导航、"
                "被动威胁感知、分时释放状态机和低带宽窗口通报组件组成；母弹负责运输与释放，"
                "各子效应器保持独立任务边界和安全终止逻辑"
            ),
            "effect": (
                "后方机动射手一次起射后，母弹进入岛链外缘并先释放诱饵和被动侦察子效应器；"
                "根据敌防空响应再释放压制或有限毁伤载荷，并把可利用窗口交给后续远程精打火力"
            ),
            "winning": (
                "把原本需要多平台、多次起射和连续协同的诱骗—复核—压制—毁伤时序压入一枚远程母弹，"
                "迫使对手在提前拦截母弹、持续静默或向多类子效应器分配火控之间选择"
            ),
            "development": (
                "先验证子舱环境、飞行包线和安全分离，再开展GNSS拒止、链路间歇、假源、雷达静默、"
                "母弹中途被拦截和子效应器损耗条件下的分时释放，以安全分离率和后续突防增益决定转段"
            ),
        },
        "expendable_mission_bridge": {
            "technology": (
                "战斗构型由可消耗巡航弹式飞行体、被动射频与简化成像/电子支援载荷、"
                "抗扰航路控制、目标摘要生成、短窗低概率截获转发和安全终止状态机组成；"
                "任务桥只产生并转交目标证据，不携带主攻毁伤载荷"
            ),
            "effect": (
                "从岸基、海上或半潜节点释放后，在目标区外缘短时获取带时间戳和置信度的目标证据，"
                "只向授权射手转发低带宽摘要，使远火单元完成一次发射、拒打或补射选择"
            ),
            "winning": (
                "把高价值侦察平台持续在位和宽带回传需求压缩为可消耗节点的一次短窗任务转交；"
                "只有当摘要确实提高授权射手有效补射率并保持错误转发安全终止时才形成交换优势"
            ),
            "development": (
                "先验证被动感知、摘要生成、低概率截获转发和安全终止，再在GNSS拒止、诱饵污染、"
                "链路间歇、目标机动和节点损耗条件下开展射手转交试验，以有效补射率而非自身毁伤率决定转段"
            ),
        },
        "land_loitering_launcher": {
            "technology": (
                "战斗构型由无人驾驶或遥控底盘、模块化箱式巡飞弹发射单元、非GNSS定位校核、"
                "低截获任务装订、远程安全闭锁、射后自主转移和多阵位接替任务软件组成"
            ),
            "effect": (
                "发射车在岛岸道路网内隐蔽待机，短窗接收任务包后分批释放巡飞弹药并立即转移；"
                "弹群前出搜索、复核和补击漏毁或转移目标，邻近阵位按余弹和战果接替下一波次"
            ),
            "winning": (
                "把固定阵地的一次性齐射改为多阵位短停释放和弹群在位接替，迫使对手持续重访道路网、"
                "同时分配对发射车和已释放弹群的侦察拦截资源"
            ),
            "development": (
                "先验证无人底盘、发射安全、任务装订和射后转移，再在道路受阻、GNSS拒止、无人侦察重访、"
                "弹群损耗和补弹受限条件下开展多阵位连续释能试验"
            ),
        },
        "land_mobile_precision_launcher": {
            "technology": (
                "战斗构型由轮式或履带式远程精确导弹发射车、被动定位与航向校核、低截获任务终端、"
                "短停发射控制、分散补弹车和射后撤收状态机组成，保持发射车与导弹任务边界可归因"
            ),
            "effect": (
                "车组战前分散进入岛上隐蔽地域，收到目标摘要和人工授权后短停发射并立即撤收；"
                "战果不足时由相邻车组、海上节点或空中库存补击敌防空、指挥、港口和远程火力节点"
            ),
            "winning": (
                "利用道路网和多阵位接替把对手首轮压制固定阵地的收益转化为持续搜索、定位和重复打击成本，"
                "同时以短停发射压缩敌反击窗口"
            ),
            "development": (
                "先完成道路机动、定位校核、任务终端与发射控制联试，再在阵位暴露、道路受阻、补弹受压、"
                "GNSS欺骗和无人侦察重访条件下比较发射后生存与下一射击周期恢复"
            ),
        },
        "counter_unmanned_launcher": {
            "technology": (
                "战斗构型由机动底盘、近程低辐射传感器、小型拦截弹、可选非动能效应器、"
                "有人监督火控分配和伴随远火节点转移接口组成，动能与非动能拦截必须共享敌我识别边界"
            ),
            "effect": (
                "伴随导弹车、弹药补充点和临时阵地保持近域警戒，发现侦察无人机或巡飞弹后分级确认威胁，"
                "选择动能或非动能方式拦截并掩护被护节点完成撤收、补弹或下一次发射"
            ),
            "winning": (
                "用成本较低的近域拦截保护高价值远火射手和剩余弹药，迫使对手增加来袭密度、"
                "多方向协同与电子压制投入；若自防负荷挤占主要火力机动和补弹能力，则交换关系不成立"
            ),
            "development": (
                "先验证低空探测分类、有人监督火控和动能/非动能切换，再开展多方向饱和、诱饵群、"
                "友邻混杂与强干扰对抗，以被护节点生存和再发射保持率决定型号化"
            ),
        },
        "high_power_microwave": {
            "technology": (
                "战斗构型围绕可消耗巡飞或机动载体、高功率脉冲源、定向辐射与安全闭锁、"
                "效应区规划、目标电子活动感知、作用后功能状态判定和附带影响约束展开"
            ),
            "effect": (
                "进入敌无人集群、通信中继或电子战节点活动区后，在授权作用区内实施短时定向微波压制，"
                "记录功能失效与恢复状态并向后续巡航弹、巡飞弹或机动射手通报可利用窗口"
            ),
            "winning": (
                "以一次作用覆盖多个暴露电子节点，压缩蜂群协同与电子支援的同步性；"
                "若效果不能确认、恢复过快或附带影响边界不可控，则不能以名义辐射功率替代实际战果"
            ),
            "development": (
                "先在屏蔽靶场标定不同目标的功能失效、恢复和附带影响边界，再开展载体进入、指向控制、"
                "红蓝对抗和后续火力利用试验，以可重复窗口而非单次异常决定转段"
            ),
        },
        "shore_anti_ship_launcher": {
            "technology": (
                "战斗构型由岛岸机动发射车、反舰导弹箱组、被动目标任务接收、航迹时效校核、"
                "短停发射安全控制、射后转移和分散补弹接口组成，不把持续高带宽外部遥控作为前提"
            ),
            "effect": (
                "发射车在岛岸道路网分散隐蔽，收到经授权的海上目标摘要后短停齐射并立即转移，"
                "由其他阵位依据航迹时效、局部毁伤摘要和剩余弹量接替补击"
            ),
            "winning": (
                "用多阵位反舰威胁压缩敌补给、两栖支援和编队外缘舰艇的机动自由，迫使其持续投入航空侦察、"
                "先发压制、护航防空和航路调整资源"
            ),
            "development": (
                "先完成目标任务接收、航迹时效、短停发射和射后转移联试，再在商船混杂、目标机动、"
                "数据链间歇和道路网受压条件下开展多阵位反舰交战"
            ),
        },
        "evidence_cache": {
            "technology": (
                "战斗构型围绕弹上传感处理、带时间戳的证据缓存、目标位置不确定区、低带宽摘要和重新授权令牌展开，"
                "使在位弹药保存短时暴露目标的来源、时效与身份置信度，而不是只保存一个容易过期的坐标点"
            ),
            "effect": (
                "在首击后链路被压制、机动发射车或雷达再次短时暴露时，保留可供火力单元复核的目标证据，"
                "把恢复链路后的任务起点从重新搜索前移到目标重关联与授权判断，缩短补击准备并降低错击诱饵风险"
            ),
            "winning": (
                "把对手通过压制数据链清空目标状态的收益压缩为可计量的再授权延迟；对手若继续机动和施放诱饵，"
                "必须同时改变外形、轨迹与时序特征，若保持真实任务活动则增加被重关联的概率"
            ),
            "development": (
                "先以真实传感记录回放验证证据缓存与目标重关联，再开展链路随机中断、目标机动和诱饵注入的"
                "硬件在环试验，最后进入有人授权条件下的多波次飞行验证；任何失联自主释放毁伤均判为越界"
            ),
        },
        "anti_radiation": {
            "technology": (
                "战斗构型由宽带被动射频侦测、辐射源类别判别、关机前方位与不确定区记忆、失辐射等待、"
                "末端光电/红外复核和安全拒打状态机组成，重点闭合从发现辐射到确认真实作战节点的证据链"
            ),
            "effect": (
                "在防空雷达短时开机、频率捷变、诱饵辐射和关机转移条件下持续猎歼，直接摧毁或压制预警雷达、"
                "火控雷达和电子战车辆，切断目标分配与制导链，制造局部防空盲区，掩护后续巡航导弹、地射远火"
                "和低空无人突击火力歼灭指挥所、导弹阵地与保障枢纽"
            ),
            "winning": (
                "迫使对手在开机维持空情与火控、关机失去探测射击机会之间选择；末端独立复核又提高诱饵成本，"
                "使简单关机或廉价假辐射源难以同时保住节点生存和体系效能"
            ),
            "development": (
                "先完成射频目标库、失辐射状态机和末端复核载荷联试，再在持续开机、间歇开机、关机机动、"
                "多诱饵与友邻辐射源混杂场景中逐级对抗，以安全拒打和真实节点压制窗口共同决定转段"
            ),
        },
        "low_cost_effecter": {
            "technology": (
                "战斗构型冻结弹体、动力、制导与战斗部接口，采用共用发射箱、任务软件版本控制、批次一致性监测"
                "和可替换目标任务包，把性能边界、制造节拍与库存补充纳入同一型号基线"
            ),
            "effect": (
                "面向固定和准固定纵深节点组织多轴、多波次压制毁伤，使高端弹药集中承担高难度突防与高价值目标，"
                "低成本巡航效应器承担重复压制、诱导拦截和补击消耗，提升持续波次与库存恢复能力"
            ),
            "winning": (
                "以可预测的批产节拍和单位有效毁伤成本对冲对手高价拦截弹消耗，迫使其在放行目标、暴露防空阵位"
                "和提前耗尽拦截库存之间分配资源，制胜点是工业补充速度与任务分工而非单弹峰值性能"
            ),
            "development": (
                "先冻结最小可用构型并完成发射与任务接口联试，再用跨批次抽检、强扰航路和多层拦截试验校准"
                "任务完成率与单位有效毁伤成本，最后以连续生产和多波次补充演示验证规模化是否真实成立"
            ),
        },
        "electronic_attack": {
            "technology": (
                "战斗构型围绕可消耗空射平台、威胁库、受保护平台特征模拟、诱饵航路、被动响应感知、"
                "电子攻击载荷和低带宽窗口通报接口展开，保持诱骗压制与主攻毁伤武器的弹体边界"
            ),
            "effect": (
                "在主攻编队进入前多轴诱导防空雷达开机、跟踪和分配拦截资源，同时压低局部探测与火控质量，"
                "为巡航导弹、反辐射弹药和无人突击平台创造可利用的时间—方位突防窗口"
            ),
            "winning": (
                "迫使对手在持续开机暴露电磁特征、保持静默丢失空情、或向假目标消耗火控与拦截资源之间选择；"
                "只有后续主攻武器突防率和末段更新质量同步改善，电子攻击收益才成立"
            ),
            "development": (
                "先验证载机释放、威胁库和载荷功耗散热边界，再在不同雷达工作方式、被动探测、火控静默和"
                "低成本拦截条件下开展红蓝对抗，以对后续主攻波次的可重复增益决定型号化"
            ),
        },
        "prsm": {
            "technology": (
                "升级构型聚焦目标包有效期管理、火力单元快速重规划、组合导航可信评估、受约束末段搜索、"
                "多模目标再捕获和安全弃攻接口，并保持发射车、火控与基础弹体边界可归因"
            ),
            "effect": (
                "由分散机动地面火力对战役纵深固定、准固定及有限机动节点实施快速分配与补击，在目标坐标过期"
                "或导航受骗时避免沿旧解消耗弹药，提高高价值目标再次暴露后的地面火力响应质量"
            ),
            "winning": (
                "把对手依靠机动、伪装和坐标过期逃逸的时间收益压缩到末段再捕获窗口内，并以安全拒打控制错误"
                "接受，使其必须提高转移频率、伪装成本和防空覆盖密度才能维持生存"
            ),
            "development": (
                "先在不改动基础弹体的条件下完成目标更新、导航与导引段半实物试验，再开展机动目标、近禁击区、"
                "诱饵和PNT欺骗组合试验；若弹上算力、导引头或火控接口余量不足，则转入新弹研制"
            ),
        },
        "jassm": {
            "technology": (
                "升级构型围绕空射任务规划、目标包有效期、组合导航可信评估、低可探测航路边界保持、末段身份"
                "复核、可弃攻航路和毁伤摘要回灌展开，保留既有弹体与载机防区外释放优势"
            ),
            "effect": (
                "在防空拦截、GNSS欺骗和目标包过期叠加条件下维持战役纵深固定与准固定节点的受控突防毁伤，"
                "并把单次命中结果转化为可供空地火力判断补击、改派或停止消耗的任务状态"
            ),
            "winning": (
                "以低可探测防区外投送压缩对手预警与拦截时间，以导航可信评估和末端复核抵消欺骗收益，再用"
                "毁伤摘要加快补击决策，迫使对手同时投入纵深防空、导航欺骗、伪装与快速修复资源"
            ),
            "development": (
                "先完成任务软件、导航可信评估和末段复核接口的地面与半实物联试，再在多层防空、导航欺骗、"
                "目标转移和禁击区邻近场景中开展任务级试验；无法安全弃攻或增量不能独立归因时停止改装"
            ),
        },
        "low_altitude_unmanned": {
            "technology": (
                "战斗构型由箱式或机动发射平台、低空可消耗机体、本机光电/红外目标复核、预装目标包、"
                "低速率授权与中止链路、毁伤载荷和多波次接替任务软件组成，强调目标区附近在位察打"
            ),
            "effect": (
                "在远程火力首击后前出搜索漏毁、转移和再次暴露目标，就地完成目标复核、局部毁伤评估和受控补射，"
                "把等待后方侦察恢复与再次发射的串行链压缩为目标邻近空域内的连续察打链"
            ),
            "winning": (
                "以低成本在位火力抢占目标修复、转移和伪装前的短时窗口，并用分散航路与多波次接替吸收局部战损；"
                "迫使对手扩大低空防空覆盖和持续值班，从而提高其保护纵深节点的资源消耗"
            ),
            "development": (
                "先验证低空导航、本机复核、授权/中止和毁伤载荷接口，再在烟尘遮蔽、假目标、近程防空、链路间歇"
                "与平台损耗条件下开展多波次对抗，以再发现率、补射时延和单位有效毁伤成本决定扩编"
            ),
        },
    }
    return profiles.get(
        family,
        {
            "technology": (
                f"{_identity_project_label(identity)}的构型必须围绕其项目功能，逐项闭合主平台、任务载荷、"
                "目标传感、火控、任务软件与安全授权接口，并明确哪一部件直接产生战果"
            ),
            "effect": (
                f"{_identity_project_label(identity)}须在代表性对抗场景中直接改变其指定敌方目标的状态，"
                "并把发现、确认、交战、评估与再组织各环节的增量分别归因到本装备"
            ),
            "winning": (
                f"{_identity_project_label(identity)}只有在压缩该目标的反应时间、增加对应防护资源投入或"
                "降低己方同类任务重组代价时，才形成可独立验收的交换优势"
            ),
            "development": (
                f"{_identity_project_label(identity)}按部件样机、系统联试、针对性红蓝对抗和任务级实装验证递进，"
                "每一阶段均以该项目的失败样本、直接战果和停止转段条件决定是否型号化"
            ),
        },
    )


def _family_overview_contract(identity: str) -> tuple[str, str, str] | None:
    family = _capability_family(identity)
    primary = identity.split("；", 1)[0]
    if family == "unmanned_surface_missile_launcher":
        return (
            "以分布式海上预置和异步发射替代受毁机场与固定阵地的远火释能原理",
            "半潜低特征艇体、模块化巡航弹舱、非GNSS航位保持、被动警戒、低截获授权与发射安全封控技术",
            "危机期分散布放—低特征海上待机—接收任务边界—发射前状态与授权复核—受控释放巡航弹/拒打—转移沉默—补射接替",
        )
    if family == "unmanned_surface_ambush":
        return (
            "以慢变航路约束替代持续精确航迹，并以局部伏击压缩广域追踪问题的空间拒止原理",
            "低特征海面待机、非GNSS航路保持、被动近距识别、避碰与禁击区约束、直接毁伤和安全自毁技术",
            "候选航路装订—分散预置—隐蔽待机—近距识别—受控拦截/拒打—转移或伏击区再组织",
        )
    if any(
        marker in primary
        for marker in ("巡飞弹发射巢", "巡飞弹巢", "密封发射巢")
    ):
        return (
            "以长期密封预置、低活动待机、分批释放和多巢接替续接受毁机场与车辆发射链的岛上火力缓存原理",
            "长储密封箱体、弹药健康监测、低截获任务装订、远程安全闭锁、伪装诱饵、分批释放与节点接替技术",
            "分散隐蔽预置—低活动健康监测—短窗接收任务包—授权与弹药状态复核—分批释放巡飞弹—未暴露弹巢接替",
        )
    if any(
        marker in primary
        for marker in ("巡飞弹发射车", "巡飞弹药发射车", "无人巡飞火力舱")
    ):
        return (
            "以无人值守短停发射、弹车分离和多阵位接替续接受毁机场后的岛岸远火释能原理",
            "无人驾驶底盘、模块化箱式发射单元、非GNSS定位校核、低截获任务装订、远程安全闭锁与射后转移技术",
            "隐蔽阵位待机—短窗口接收任务包—发射前授权与状态复核—分批释放巡飞弹药—发射车转移—弹群搜索复核与补射接替",
        )
    if family == "anti_ship_loitering":
        if "空射" in primary:
            return (
                "以载机防区外分批投放、多轴错时进入和前后批目标保管接替续接断链反舰任务的空射猎歼原理",
                "载机任务装订与安全分离、非GNSS低空进入、多轴航路去冲突、目标保管接替、身份复核与直接毁伤技术",
                "载机任务装订—释放窗口选择—分批投放—多轴错时进入—目标保管接替—身份复核—直接攻击/拒打",
            )
        if "射频复核" in primary:
            return (
                "以传感器暴露控制、被动射频与成像交叉确认抵消静默诱饵和外围拦截的多模猎歼原理",
                "低截获被动射频、成像复核、跨模态时空关联、抗拦截自主规避、身份置信门与直接毁伤技术",
                "目标区分散搜索—传感器暴露控制—拦截规避—被动射频发现—成像交叉确认—直接攻击/拒打",
            )
        return (
            "以前沿在位搜索和航迹连续性维护续接断链反舰目标保管的猎歼原理",
            "长航时抗扰飞行、被动射频与光电视觉分类、目标质量摘要、局部毁伤评估、直接攻击与安全拒打技术",
            "目标可能区装订—前沿待机搜索—航迹关联与身份复核—搜索区/摘要更新—受控直接攻击或拒打—局部BDA",
        )
    if family == "anti_ship_cruise":
        if "协同去重" in primary:
            return (
                "以搜索扇区分工和最小目标摘要交换把多弹齐射转化为并行覆盖，并以失联预案避免重复毁伤的协同去重原理",
                "扇区生成、目标摘要时间戳与置信度、重复目标判定、低带宽交换、失联独立搜索与安全拒打技术",
                "齐射扇区分配—抗扰进入—局部目标发现—摘要交换与重复判定—独立毁伤/改搜/拒打—覆盖重评",
            )
        if "有限区搜索" in primary:
            return (
                "以航迹时效、目标机动包线和剩余能量共同约束单弹搜索与毁伤释放的有限区再捕获原理",
                "航迹误差椭圆、搜索区生成、抗扰组合导航、导引头视场管理、多模身份复核与安全弃攻技术",
                "目标有效期装订—搜索区与能量校核—单弹抗扰进入—有限区搜索—身份复核—直接毁伤或拒打",
            )
        return (
            "以目标信息时效、概率搜索和多模身份门控续接断链反舰齐射的受控再捕获原理",
            "抗扰组合导航、目标包时效管理、受约束概率搜索、多模身份复核、弹间摘要与安全弃攻技术",
            "目标包装订—抗扰进入—分区搜索—身份复核与去重—受控毁伤/拒打—补击再组织",
        )
    if family == "common_airframe":
        return (
            "以共同弹体和任务前载荷重配改变弹药库存结构与齐射生成逻辑的模块化武器原理",
            "统一机械电气数据接口、质量重心控制、功率热管理、射频隔离、载荷识别与换装鉴定技术",
            "威胁判读—载荷选配—接口检查—混合齐射生成—任务执行—库存与构型再平衡",
        )
    contracts = {
        "airborne_arsenal_carrier": (
            "以战前起飞和防区外长时在位把机场出动能力转换为可分批调用的时间库存原理",
            "大航程无人母平台、防区外弹药挂架/弹舱、安全分离、弹药库存管理、岛链外待机、低带宽任务接收与人工授权释放技术",
            "后方或幸存机场起飞—岛链外防区外待机—接收目标与威胁摘要—弹药库存匹配—人工授权分批释放/保留未用载荷—战果摘要驱动补射、重新占位或退出",
        ),
        "armed_unmanned_wingman": (
            "以目标区外缘在位被动搜索、跨模态复核和有限自带火力压缩机动节点重组时间的察打僚机原理",
            "长航时低可探测无人平台、被动射频/光电复核、小型精确弹、有限诱骗压制、抗扰导航、低带宽任务终端与人工授权拒打技术",
            "后方或临时场地起飞—岛链外缘低特征待机—被动射频发现—光电身份复核—人工授权自行有限攻击/引导远火/拒打—局部BDA与接替",
        ),
        "short_takeoff_unmanned_fire_carrier": (
            "以短距起降和模块化混载释放替代完整跑道与有人载机依赖的分散空中释能原理",
            "短距起降低特征无人平台、模块化内外载架、诱饵与小型巡航/巡飞弹、安全分离、抗扰被动导航、低带宽任务监管与人在回路释放技术",
            "简易场地分散起飞—低电磁进入授权释放区—人在回路复核载荷与威胁边界—先释放诱饵—再释放小型巡航/巡飞弹—转场、退出或消耗",
        ),
        "cruise_mother_munition": (
            "以远程母载运输和分时释放把一次起射转换为诱骗、侦察、压制与有限毁伤连续动作的异构释能原理",
            "远程巡航母弹、模块化子舱、安全分离、载荷状态管理、抗扰导航、被动威胁感知、分时释放状态机与低带宽窗口通报技术",
            "后方机动起射—母弹抗扰进入—先遣诱饵/侦察释放—敌防空响应复核—授权压制或有限毁伤释放/保留—窗口通报与后续精打接替",
        ),
        "expendable_mission_bridge": (
            "可消耗节点短时在位感知与低带宽任务转交替代连续前出和宽带回传的任务桥原理",
            "可消耗巡航飞行体、被动射频与简化成像、目标摘要生成、低概率截获转发、抗扰航路控制和无毁伤载荷安全终止技术",
            "岸海节点释放—目标区外缘短时感知—证据时效与身份复核—向授权射手转发低带宽目标摘要—射手发射/拒打/补射—任务桥退出或安全终止",
        ),
        "land_mobile_precision_launcher": (
            "以道路网分散、短停发射和射后撤收续接受毁机场与固定阵地的陆基远程精击原理",
            "机动导弹发射车、被动定位与航向校核、低截获任务终端、短停发射控制、分散补弹与射后撤收技术",
            "隐蔽地域分散—短窗接收任务摘要—授权与弹车状态复核—短停发射—立即撤收—相邻车组补射接替",
        ),
        "counter_unmanned_launcher": (
            "以伴随近域分层拦截保护远火射手和下一射击周期的反杀伤原理",
            "机动底盘、低辐射近程传感、小型拦截弹、非动能效应器、有人监督火控分配与伴随转移技术",
            "伴随进入—近域警戒—目标分类与威胁分级—有人监督选择动能/非动能拦截—效果确认—掩护远火节点撤收或再发射",
        ),
        "high_power_microwave": (
            "以受控短时电磁作用同时压低多个暴露电子节点功能可用性的区域压制原理",
            "高功率脉冲源、定向辐射、安全闭锁、效应区规划、电子活动感知、功能状态判定与附带影响约束技术",
            "作用区与禁限边界装订—载体进入或巡飞待机—目标电子活动确认—受控微波作用—功能失效与恢复判定—窗口通报与后续火力利用",
        ),
        "shore_anti_ship_launcher": (
            "以岛岸道路机动、短停反舰齐射和多阵位接替维持海上拒止的分布射手原理",
            "机动发射车、反舰导弹箱组、被动任务接收、航迹时效校核、短停发射安全控制、射后转移与分散补弹技术",
            "道路网分散隐蔽—接收海上目标摘要—航迹时效与授权复核—短停反舰齐射—射后转移—多阵位补击接替",
        ),
        "evidence_cache": (
            "弹上任务状态保持与人在回路重新授权原理",
            "弹上传感处理、带时间戳证据缓存、目标不确定区维护、低带宽摘要与重新授权令牌技术",
            "前沿在位搜索—断链证据保持—链路恢复复核—重新授权交战—毁伤摘要接替",
        ),
        "anti_radiation": (
            "以对手辐射暴露换取被动定位，并用多模证据约束交战的反压制原理",
            "宽带被动射频侦测、辐射源记忆区、失辐射等待、末端光电/红外复核与安全拒打技术",
            "压制区外缘待机—被动发现—关机目标保持—末端复核—受控猎歼或拒打",
        ),
        "low_cost_effecter": (
            "以任务分工和工业补充速度改变高价拦截成本交换的规模作战原理",
            "冻结构型、共用发射接口、批次一致性控制、受扰航路制导与任务软件版本管理技术",
            "构型与目标包冻结—机动分批发射—多轴多波次突防—固定/准固定节点毁伤—库存快速补充",
        ),
        "electronic_attack": (
            "以可消耗诱饵塑造威胁响应并错配对手火控资源的电子攻击原理",
            "平台特征模拟、威胁库、诱饵航路生成、被动响应感知、电子攻击载荷与窗口通报技术",
            "防区外多轴释放—诱导雷达响应—受控电子压制—窗口判定—主攻波次利用",
        ),
        "prsm": (
            "以目标信息时效约束和末段多模证据门控远程火力释放的受控再捕获原理",
            "目标包有效期管理、组合导航可信评估、受约束末段搜索、多模再捕获与安全弃攻技术",
            "分散火力接令—目标时效复核—机动发射—末段再捕获/拒打—射后转移与补击",
        ),
        "jassm": (
            "以导航可信度和末段目标证据共同约束低可探测防区外突防的受控补击原理",
            "目标包有效期管理、组合导航可信评估、低可探测航路保持、末段身份复核与毁伤摘要回灌技术",
            "载机防区外多轴释放—低可探测突防—末段身份复核—毁伤/弃攻—摘要驱动后续补击",
        ),
        "low_altitude_unmanned": (
            "以目标区附近在位察打压缩首击后再确认与补射时间的前置火力原理",
            "低空组合导航、本机光电/红外复核、预装目标包、低速率授权/中止链路与多波次接替技术",
            "箱式分批释放—多路径低空进入—本地搜索复核—受控补射—局部毁伤评估与下一波接替",
        ),
    }
    return contracts.get(family)


def _effect_clause(value: object, capability: str) -> str:
    parts = _clean_items(value, limit=4)
    distinct = [
        part
        for part in parts
        if part.rstrip("能力") not in capability
        and capability.rstrip("能力") not in part
    ]
    source = "；".join(distinct[:2] if distinct else parts[:1])
    if source.startswith("把") and "从" in source and source.endswith("节点"):
        source += "转变为可独立续接任务的作战单元"
    if "创造短时突防" in source or "创造短时" in source and "末段" in source:
        return "为后续远程精确弹药创造短时突防和末段更新窗口"
    if "多批次" in source and "分配资源" in source:
        return "迫使对手在持续压制、暴露防空火力和保护关键节点间分配资源"
    return _concise_clause(
        source,
        "缩短发现至毁伤闭环并提高持续交战和再打击效能",
        limit=34,
        max_parts=2,
    )


def _overview_clause(
    *,
    scenario: str,
    problem: str,
    principle: str,
    technologies: str,
    operational_concept: str,
    operational_process: str,
    equipment: str,
    capability: str,
    effect: str,
    identity: str,
) -> str:
    """Synthesize one concise, weapon-specific combat thesis."""

    del operational_process
    family = _capability_family(identity)
    principle_phrase = principle
    if principle_phrase.startswith(("把", "将")):
        principle_phrase = f"“{principle_phrase}”所描述的任务变量转换原理"
    elif not principle_phrase.endswith(("原理", "机理", "规律", "关系")):
        principle_phrase = f"{principle_phrase}原理"
    scenario_phrase = _concise_clause(
        scenario,
        "典型高对抗战斗阶段",
        limit=72 if family == "expendable_mission_bridge" else 30,
        max_parts=2 if family == "expendable_mission_bridge" else 1,
    )
    problem_phrase = _concise_clause(
        problem, "关键目标复获与直接交战链存在断点", limit=46, max_parts=1
    )
    technology_phrase = _concise_clause(
        technologies, "抗扰导航、目标复核与安全中止技术", limit=42, max_parts=1
    )
    equipment_phrase = _concise_clause(
        equipment, "具体武器装备", limit=48, max_parts=1
    )
    concept_phrase = _concise_clause(
        operational_concept,
        "分散进入、搜索复核与受控交战",
        limit=42,
        max_parts=1,
    )
    capability_phrase = _concise_clause(
        capability, "受扰条件下的直接作战", limit=42, max_parts=1
    )
    effect_phrase = _concise_clause(
        effect, "压缩交战闭环并保持直接毁伤", limit=62, max_parts=1
    )
    process_phrase = (
        "按部署—进入—证据获取—摘要转发—火力转交/安全终止组织战斗"
        if family == "expendable_mission_bridge"
        else "按部署—进入—搜索复核—交战/拒打—毁伤评估与补射接替组织战斗"
    )
    return (
        f"面向{scenario_phrase}，针对{problem_phrase}，以{equipment_phrase}为主装备，"
        f"利用{principle_phrase}，采用{technology_phrase}，通过{concept_phrase}，"
        f"{process_phrase}，"
        f"形成{capability_phrase}能力，实现{effect_phrase}作战效果。"
    )


def _clean_items(values: Sequence[object] | object, *, limit: int) -> list[str]:
    if isinstance(values, Sequence) and not isinstance(values, (str, bytes)):
        rows = list(values)
    elif values not in (None, ""):
        rows = re.split(r"[；;。]", str(values))
    else:
        rows = []
    cleaned: list[str] = []
    for item in rows:
        text = _clean_clause(item, "")
        if text and text not in cleaned:
            cleaned.append(text)
        if len(cleaned) >= limit:
            break
    return cleaned


def normalize_capability_problem(value: object, *, fallback: str) -> str:
    """Keep one complete, equipment-local problem statement."""

    source = _clean_clause(value, "")
    source = re.split(r"[；;]该方向装备基线[：:]", source, maxsplit=1)[0]
    candidates = [
        item.strip(" ，,；;。:：")
        for item in re.split(r"[；;。]+", source)
        if item.strip(" ，,；;。:：")
    ]
    incomplete_endings = (
        "并",
        "及",
        "与",
        "和",
        "或",
        "但",
        "且",
        "的",
        "为",
        "使",
        "把",
        "将",
        "由",
        "通过",
    )
    for candidate in candidates:
        if len(candidate) < 12 or candidate.endswith(incomplete_endings):
            continue
        return _concise_clause(candidate, fallback, limit=140, max_parts=1)
    return _concise_clause(
        fallback,
        "关键任务链存在可验证的装备能力断点",
        limit=140,
    )


def _tailored_operational_process(identity: str) -> list[str]:
    family = _capability_family(identity)
    if family == "unmanned_surface_missile_launcher":
        return [
            "危机期将半潜巡航弹无人艇分散布放至岛链间预定待机海域，装订目标类别、禁击区、授权规则和任务有效期",
            "平台以非GNSS航位保持和被动警戒维持低特征待机，周期核验弹舱环境、航行状态与发射安全闭锁",
            "收到任务边界后复核授权、目标包时效和艇弹状态，条件满足时受控释放巡航弹，任一门槛不足即拒绝发射",
            "发射后转移、沉默或进入备用待机区，回传最低限度任务摘要并由其他海上、岸基或空基节点接替补击",
        ]
    if family == "unmanned_surface_ambush":
        return [
            "任务前装订海峡、补给通道或机动出口，明确授权目标、商船避碰区、禁击区和自毁边界",
            "无人艇分散预置并以非GNSS导航保持伏击区，在低特征海面待机中用被动传感器近距警戒",
            "目标进入局部感知范围且身份与授权门槛同时满足时实施拦截、撞击或战斗部毁伤，否则规避、转移或拒打",
            "汇总拦截、绕行和清剿活动，组织剩余无人艇转移、接替或终止伏击，并向远程反舰火力回传接触摘要",
        ]
    if family == "airborne_arsenal_carrier":
        return [
            "战役初期由后方或幸存机场起飞，装订待机空域、载荷清单、任务边界、人工授权规则和退出条件",
            "平台进入岛链外防区外等待区并管理弹药健康与剩余库存，低带宽接收带时间戳和置信度的目标、威胁摘要",
            "依据目标时效和威胁边界完成人工授权，分批释放防区外弹药；条件不足时保留未用载荷",
            "接收战果摘要后决定补射、转入备用等待区重新占位或退出返航，并评估单机战损造成的库存集中损失",
        ]
    if family == "armed_unmanned_wingman":
        return [
            "后方基地或临时场地起飞前装订巡逻区、目标类别、禁击区、人工授权、失联动作和返航/安全终止条件",
            "无人僚机进入岛链外缘低特征待机，以被动射频搜索短时开机节点并用光电证据复核车辆身份与活动状态",
            "链路可用且授权成立时以自带小型精确弹实施有限攻击或向后续远火发送目标摘要；证据不足时保持跟踪、诱骗、退出或拒打",
            "完成局部毁伤评估并更新目标可能区，由其他僚机、海上节点或远程弹药接替；保障或剩余油弹不足时退出",
        ]
    if family == "short_takeoff_unmanned_fire_carrier":
        return [
            "分散航空分队在滑行道、道路或简易场地完成短距起飞准备，装订释放区、诱饵与小型打击弹载荷清单、人工授权和失联处置边界",
            "无人火力母机以低电磁方式进入授权释放区，持续校核导航可信度、威胁边界、载荷状态和可用转场点",
            "人在回路授权成立后先释放诱饵塑造防空响应，再按任务包释放小型巡航弹或巡飞弹；授权、分离或目标条件不足时保留载荷并退出",
            "依据威胁响应和打击摘要选择转场、返回备用场地或执行可消耗任务，由下一架母机接替后续诱骗与轻型打击架次",
        ]
    if family == "cruise_mother_munition":
        return [
            "后方机动发射单元或大型载机装订任务区、子效应器清单、释放门槛、禁击区、授权规则和母弹终止条件",
            "母弹以抗扰导航进入岛链外缘，在安全分离包线内先释放诱饵与被动侦察子效应器并保留压制、毁伤载荷",
            "根据敌雷达响应、目标复核和人工授权分时释放电子压制或有限毁伤子效应器；证据、授权或分离状态不足即拒绝释放",
            "汇总各子效应器状态与效果摘要，向后续精打火力通报时间—方位窗口，并决定补放、保留载荷或母弹安全终止",
        ]
    if family == "expendable_mission_bridge":
        return [
            "岸基、海上或半潜射手装订任务区、目标类别、摘要格式、转发对象、有效期和安全终止边界",
            "任务桥以抗扰航路进入目标区外缘，使用被动射频、简化成像或电子支援载荷形成候选目标证据",
            "证据满足来源、时间戳和置信度门槛时，只向授权射手转发低带宽目标摘要，任务桥不得自行攻击；身份冲突或链路异常时保持静默或终止",
            "射手依据摘要完成发射、拒打或补射选择，任务桥回传转交状态后退出、自毁或由下一节点接替",
        ]
    if family == "land_loitering_launcher":
        if _is_sealed_loitering_nest(identity):
            return [
                "多个密封巡飞弹巢战前分散预置于岛上隐蔽点，装订目标类别、禁击区、授权边界和节点接替规则",
                "弹巢保持低活动并周期核验环境与弹药健康，短窗收到任务包后复核有效期、定位和安全闭锁",
                "授权与状态满足时分批释放巡飞弹；弹群在目标区完成搜索复核、受控攻击或拒打并形成局部战果摘要",
                "已暴露弹巢停止活动，未暴露节点依据余弹、战果和敌清剿方向接替下一波次，补装填暴露风险过高时停止补充",
            ]
        return [
            "无人值守发射车分散进入岛岸隐蔽阵位，装订目标包、禁击区、授权边界、弹群接替规则和射后转移路线",
            "短窗接收任务摘要后复核定位、弹箱状态和远程安全闭锁，条件满足时分批释放巡飞弹药",
            "发射车立即转移，已释放弹群在目标区完成搜索复核、受控攻击或拒打，并形成局部毁伤摘要",
            "邻近阵位依据余弹、目标状态和敌侦察重访情况接替下一波次，补弹受阻时降低齐射规模或停止暴露",
        ]
    if family == "land_mobile_precision_launcher":
        return [
            "发射车与补弹车战前分散进入岛上隐蔽地域，装订候选阵位、目标类别、禁击区和撤收路线",
            "低带宽接收目标摘要和人工授权，复核航迹时效、弹车状态与定位可信度后进入短停发射阵位",
            "发射远程精确导弹后立即撤收；目标证据或授权不满足时拒绝发射并转入备用阵位",
            "依据战果摘要由相邻车组、海上节点或空中库存补击，并组织补弹、再次隐蔽和下一射击周期",
        ]
    if family == "counter_unmanned_launcher":
        return [
            "拦截弹车伴随远火发射车或弹药补充点进入临时地域，划定自防扇区、友邻航路和低辐射警戒规则",
            "发现低空小目标后融合近程传感证据，分类为侦察、诱饵或攻击威胁并评估来袭密度",
            "由有人监督选择小型拦截弹或非动能效应器实施分层拦截，敌我识别不足时保持跟踪并拒绝释放毁伤",
            "确认拦截效果并掩护被护节点撤收、补弹或再次发射；弹药和持续功率不足时优先保存远火射手",
        ]
    if family == "high_power_microwave":
        return [
            "任务前装订作用区、目标电子类别、禁限边界、授权规则和附带影响停止条件",
            "载体进入或巡飞待机，以被动或低暴露方式确认无人集群、通信中继或电子战节点的活动窗口",
            "授权成立时实施定向微波作用并同步记录目标功能状态；效果不可确认或边界冲突时停止作用或拒打",
            "判定功能失效与恢复时间，向后续火力通报可利用窗口，并依据恢复速度决定补作用、接替或退出",
        ]
    if family == "shore_anti_ship_launcher":
        return [
            "岛岸发射车战前分散进入道路网隐蔽地域，装订海上目标类别、商船避让区、候选阵位和射后转移路线",
            "短窗接收带时间戳和置信度的海上目标摘要，复核航迹时效、人工授权与弹车状态后进入发射阵位",
            "对经授权的补给、两栖支援或编队外缘舰艇短停发射反舰导弹，证据过期或商船混杂时拒打",
            "发射后立即转移，由其他阵位依据目标丢失、局部毁伤摘要和剩余弹量补击、改搜或停止消耗",
        ]
    if family == "anti_ship_loitering":
        primary = identity.split("；", 1)[0]
        if "空射" in primary:
            return [
                "载机在防区外装订目标可能区、投放轴线、批次间隔、商船避让区、授权规则和任务有效期",
                "多个载机或同一载机按不同方位错时投放，巡飞猎歼弹以非GNSS低空航路分散进入并控制到达间隔",
                "前批在目标可能区持续搜索和保管舰艇，后批依据目标摘要、丢失状态或局部BDA接替、改搜或补击",
                "身份与授权门槛满足时由自身战斗部直接攻击，否则继续保管或安全拒打，并统计载机暴露与接替结果",
            ]
        if "射频复核" in primary:
            return [
                "进入最后可信目标区域后分散搜索并控制主动传感器暴露，以被动射频形成候选方位和时间连续性",
                "遭遇外围无人拦截幕时各节点独立规避、重分搜索区或中止高暴露动作，保留存活搜索时间",
                "存活节点用成像对射频候选实施跨模态交叉确认，满足舰艇身份和授权门槛后由自身战斗部直接攻击",
                "统计射频—成像一致、诱饵错误接受、拦截幕下存活和直接毁伤结果，驱动补射、接替或拒打",
            ]
        return [
            "发射前装订舰队最后可信区域、目标类别、商船避让区、授权规则和任务有效期",
            "弹药进入目标可能区后以被动射频和光电搜索维持航迹连续性，形成带时间戳的目标质量摘要",
            "身份与授权门槛满足时由自身战斗部直接攻击，条件不足时继续保管、更新后续反舰弹搜索区或安全拒打",
            "完成局部毁伤评估并发布目标丢失、毁伤或继续跟踪状态，组织补射、接替或停止消耗",
        ]
    if family == "anti_ship_cruise":
        primary = identity.split("；", 1)[0]
        if "协同去重" in primary:
            return [
                "齐射前按最后可信目标区域为各弹分配互补搜索扇区，装订目标类别、商船避让区和失联去重规则",
                "多弹以抗扰航路进入各自扇区；链路可用时只交换带时间戳与置信度的目标摘要，不传输完整传感器流",
                "摘要指向同一疑似舰艇时保留满足身份和攻击条件的弹药，其余弹药改搜、转向独立目标或拒打",
                "统计独立目标覆盖、扇区重叠、重复攻击和失联处置结果，重分配后续齐射或停止协同增量",
            ]
        if "有限区搜索" in primary:
            return [
                "发射前装订最后可信目标区域、航迹有效期、目标最大机动包线、商船避让区和禁击区",
                "单弹依据航迹年龄、剩余能量和导引头视场生成有限搜索区，并以抗扰组合导航进入",
                "在有限区内完成被动射频/成像身份复核，证据与能量满足门槛时直接反舰毁伤，否则安全弃攻",
                "回传单弹搜索覆盖、再捕获、拒打和能量余度，校准后续任务包与是否继续该构型",
            ]
        return [
            "发射前装订最后可信目标区域、目标类别、商船避让区、禁击区和航迹有效期",
            "弹药以抗扰组合导航进入目标可能区，并按航迹陈旧度和剩余能量分配独立搜索扇区",
            "末段多模证据满足舰艇身份门槛时交战；弹间链路可用时交换摘要去重，失联时按预置扇区独立搜索或拒打",
            "汇总再捕获、重复攻击、拒打和毁伤结果，驱动后续齐射补击、扇区重分配或停止消耗",
        ]
    if family == "common_airframe":
        return [
            "任务前依据威胁结构和库存状态选择诱饵、被动猎辐射或直接毁伤载荷，并冻结对应接口控制文件",
            "完成机械、电气、数据、质量重心、功率热与射频边界检查后，从共同弹体库存生成任务适配混合齐射",
            "各构型按独立授权规则执行诱骗、猎辐射或直接毁伤任务，不以对手必然开机或跨型号精确同步为前提",
            "汇总可用弹量、换装周期、任务完成和性能折衷，重平衡库存；共同化净收益不足时退回专用异构组合",
        ]
    if family == "anti_radiation":
        return [
            "联合空中突击群进入敌一体化防空区前，由防空压制分队装订预警雷达、火控雷达、电子战车辆、禁击区和交战授权规则",
            "载机或机动发射单元在防区外释放巡飞猎歼弹，弹群沿突击航路前缘分散占位，被动截获间歇开机信号并保持关机目标记忆区",
            "敌雷达为搜索或制导再次开机或末端光电/红外确认真实雷达车与天线阵位后，弹药立即俯冲摧毁目标；识别为诱饵、民用辐射源或证据冲突时继续待机或拒打",
            "存活弹药接替追猎转移节点并回传局部毁伤摘要，突击编队随即利用防空盲区突入并由后续火力补击残存导弹阵地、指挥所和保障枢纽",
        ]
    if family == "evidence_cache":
        return [
            "任务前装订目标类别、地理围栏、禁击规则和失联不得攻击状态机",
            "进入任务区后保持候选轨迹、时间戳、传感摘要和位置不确定度",
            "链路恢复后回传低带宽证据摘要，由人在回路复核并重新授权",
            "形成毁伤摘要并按门槛决定补射、接替或安全中止",
        ]
    if family == "low_cost_effecter":
        return [
            "任务规划阶段冻结构型版本、目标类别、发射接口和单批次验收状态",
            "机动发射单元按库存与威胁压力组织多波次投送，并记录批次差异和任务边界",
            "效应器在受扰航路内按预装订规则攻击固定或准固定节点，证据不足时拒打或安全中止",
            "汇总任务完成、拦截消耗和补充周期，决定继续批产、调整构型或停止规模化转段",
        ]
    if family == "electronic_attack":
        return [
            "任务前装订威胁库版本、诱饵航路、电子攻击规则和终止条件",
            "多轴释放后模拟受保护平台特征并诱导对手雷达开机、跟踪或分配拦截资源",
            "弹上被动提示与预鉴定响应选择器满足门槛时启用既有干扰载荷，否则保持诱饵任务",
            "汇总威胁响应与压制窗口，向后续突防和精确打击单元发布低带宽任务摘要",
        ]
    if family == "prsm":
        return [
            "发射前装订授权目标类别、受约束搜索区、禁击区和任务有效期",
            "飞行中评估PNT可信度并在受扰条件下维持进入目标区的航迹边界",
            "末段多模证据一致时再捕获并交战，证据冲突时拒打或转入安全航路",
            "回传低带宽毁伤与任务状态摘要，组织射后转移、补射和弹药再分配",
        ]
    if family == "jassm":
        return [
            "任务规划阶段装订目标有效期、航路威胁区、禁击边界和备选末段进入方案",
            "载机在防区外多轴释放，弹药以组合导航维持低可探测突防和任务边界",
            "末段复核目标身份与位置置信度，满足授权门槛后毁伤，否则弃攻或改入安全航路",
            "回传任务与毁伤摘要，驱动后续空地火力补击和载机再出动组织",
        ]
    if family == "low_altitude_unmanned":
        return [
            "箱式或机动发射单元装订目标包、禁击区、授权边界和失联规则后分批释放",
            "平台沿多路径低空进入目标区外缘，以本机传感器完成局部搜索和目标再确认",
            "发现漏毁、转移或短时暴露目标后回传证据摘要并按授权门槛实施受控补射",
            "完成局部BDA、剩余平台重组和下一波次接替，链路失效时安全降级或中止",
        ]
    return [
        "任务前装订目标、禁击区、授权规则、任务有效期和失联处置边界",
        "平台分散进入任务区域并持续评估导航、目标与链路可信度",
        "证据满足门槛时实施受控交战，条件不足时拒打、降级或中止",
        "形成毁伤与任务状态摘要，组织接替、补射、再装填和战损后再组织",
    ]


def normalize_operational_process(
    values: Sequence[object] | object,
    *,
    equipment_identity: object,
) -> list[str]:
    """Clean a model-authored mission process without changing its equipment.

    Equipment-family recognition is a semantic task owned by the Codex S5/S6
    contracts.  This delivery helper therefore never selects a process template
    from words found in the title, baseline or payload description.  In
    particular, a public baseline must not silently turn a platform-neutral or
    land/sea-launched card into an air-launched flow, and a carried payload must
    not replace the carrier as the actor of the process.

    The helper performs only deterministic presentation work: remove internal
    labels and incomplete fragments, preserve chronological model rows, and
    cap the delivered sequence.  Missing or short processes remain visibly
    short so the S6 structural gate can reject them before delivery instead of
    inventing military semantics locally.
    """

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
                "规模化机制不是",
                "不是增强通信背景",
                "本候选主体",
            )
        )
    ]
    rows = [
        item
        for item in rows
        if not item.startswith(("对手", "敌方", "威胁"))
        and not item.endswith(("并", "及", "与", "和", "或", "但", "且", "的"))
    ]
    del equipment_identity
    return rows[:6]


def normalize_verification_plan(
    values: Sequence[object] | object,
    *,
    equipment_identity: object,
    failure_boundary: object = "",
) -> list[str]:
    """Return an environment, comparator and decision gate for the equipment."""

    rows = _clean_items(values, limit=8)
    identity = _clean_clause(equipment_identity, "")
    metrics = _effect_metric_clause(identity)
    family = _capability_family(identity)
    if family == "unmanned_surface_missile_launcher":
        environment = "在不同海况、GNSS拒止、链路间歇、弹舱状态异常、海空搜剿和多节点战损条件下开展海上预置发射与补击试验"
    elif family == "unmanned_surface_ambush":
        environment = "在不同海况、商船混杂、GNSS拒止、低可探测警戒、航空巡逻和反水面清剿条件下开展航路伏击对抗"
    elif family == "airborne_arsenal_carrier":
        environment = "在机场窗口关闭、链路间歇、远程防空搜索、载荷状态异常和母机战损条件下开展防区外长时在位与分批释放试验"
    elif family == "armed_unmanned_wingman":
        environment = "在前沿机场失能、临时场地起降、GNSS拒止、链路间歇、假辐射源、关机机动和近程反无人拦截条件下开展外缘察打试验"
    elif family == "short_takeoff_unmanned_fire_carrier":
        environment = "在主跑道受毁、滑行道或简易场地可用、GNSS拒止、链路间歇、低空预警、近程防空、混载分离异常和转场点受压条件下开展分散起降与载荷释放试验"
    elif family == "cruise_mother_munition":
        environment = "在GNSS拒止、链路间歇、雷达静默与假源、近程拦截、子舱故障和母弹中途被拦截条件下开展分时异构释能试验"
    elif family == "expendable_mission_bridge":
        environment = "在GNSS拒止、链路间歇、目标机动、诱饵污染、低概率截获转发受压和节点损耗条件下开展目标摘要获取与火力转交试验"
    elif family == "land_loitering_launcher":
        environment = (
            "在长期封存、环境循环、地面搜索、电子诱骗、节点暴露、巡飞弹群损耗和多巢接替条件下开展连续释能试验"
            if _is_sealed_loitering_nest(identity)
            else "在道路受阻、GNSS拒止、无人侦察重访、巡飞弹群损耗、补弹受限和多阵位接替条件下开展连续释能试验"
        )
    elif family == "land_mobile_precision_launcher":
        environment = "在道路网受压、阵位暴露、GNSS欺骗、目标包过期、无人侦察重访和补弹受阻条件下开展机动发射与补击试验"
    elif family == "counter_unmanned_launcher":
        environment = "在低可探测小目标、诱饵群、多方向饱和、强干扰、友邻混杂和拦截弹药受限条件下开展伴随自防试验"
    elif family == "high_power_microwave":
        environment = "在不同电子目标、作用距离、指向误差、屏蔽与恢复条件及附带影响边界下开展功能压制和后续火力利用试验"
    elif family == "shore_anti_ship_launcher":
        environment = "在海上航迹陈旧、目标机动、商船混杂、链路间歇、道路网受压和多阵位接替条件下开展岛岸反舰试验"
    elif family == "anti_ship_loitering":
        environment = "在航迹陈旧、商船与诱饵混杂、断链、强电磁干扰和近程拦截条件下开展目标保管与直接攻击试验"
    elif family == "anti_ship_cruise":
        environment = "在不同航迹陈旧度、目标机动、诱饵与商船混杂、弹间失联和多层拦截条件下开展反舰齐射试验"
    elif family == "common_airframe":
        environment = "在威胁结构变化、库存受限、载荷换装和质量重心、功率热、射频边界压力下开展共同弹体与专用异构对照试验"
    elif family == "anti_radiation":
        environment = "在持续开机、关机固定、关机机动、诱饵辐射和频谱欺骗组合场景下注入目标状态变化"
    elif family == "low_cost_effecter":
        environment = "在批次材料与供应波动、强扰航路、多层拦截、连续补充和多波次投送条件下开展制造—任务联合试验"
    elif family == "electronic_attack":
        environment = "在多型威胁雷达、收发隔离约束、功耗散热限制和对手被动探测条件下开展硬件在环与实装试验"
    elif family == "low_altitude_unmanned":
        environment = "在弱网、PNT受扰、低空拦截、平台损耗、目标机动和补给受限条件下开展多波次对抗"
    else:
        environment = "在通信降级、GNSS压制与欺骗、目标包过期、诱饵和禁击区邻近条件下开展半实物与实装试验"
    comparator = f"与未改装或串行任务链基线比较{metrics}，记录均值、尾部风险和失败样本"
    if isinstance(failure_boundary, Sequence) and not isinstance(
        failure_boundary, (str, bytes)
    ):
        raw_boundary_rows = [str(item) for item in failure_boundary]
    else:
        raw_boundary_rows = re.split(r"[；;。]", str(failure_boundary or ""))
    preferred_boundary = next(
        (
            row
            for row in raw_boundary_rows
            if row.strip().startswith("失效边界")
        ),
        "",
    )
    if not preferred_boundary:
        preferred_boundary = next(
            (
                row
                for row in raw_boundary_rows
                if not row.strip().startswith(("未来触发", "依据"))
                and any(
                    marker in row
                    for marker in ("不能", "无法", "失效", "超过", "不一致", "不足", "不可接受")
                )
            ),
            "",
        )
    boundary = normalize_capability_problem(
        preferred_boundary,
        fallback="关键目标证据、导航可信度或安全授权边界不能闭合",
    )
    boundary = re.sub(r"^(?:若|当|如果|一旦)", "", boundary).strip(" ，,；;。:：")
    boundary = boundary.removesuffix("时").rstrip(" ，,；;。")
    if "停止转段" in boundary:
        decision = f"预注册通过与淘汰门槛；若{boundary}"
    elif "则" in boundary or re.search(
        r"[，,](?:必须|应当|应|需|不得|不能|无法|仅|只)", boundary
    ):
        decision = (
            f"预注册通过与淘汰门槛；若{boundary}，"
            "并停止转段并回退到拒打、降级或重新校准"
        )
    else:
        decision = (
            f"预注册通过与淘汰门槛；若{boundary}，"
            "则停止转段并回退到拒打、降级或重新校准"
        )
    marker_groups = (
        ("环境", "条件下", "场景", "注入"),
        ("比较", "基线", "对照"),
        ("淘汰", "门槛", "停止转段", "拒打", "降级"),
    )
    fallbacks = (environment, comparator, decision)
    metric_markers = [
        item.strip()
        for item in re.split(r"[、和]", metrics)
        if len(item.strip()) >= 4
    ]
    environment_conflicts = {
        "unmanned_surface_missile_launcher": ("航路伏击", "近距识别", "目标绕行"),
        "unmanned_surface_ambush": ("弹舱状态", "受控发射", "连续补击"),
        "airborne_arsenal_carrier": ("批次材料", "关机机动", "航路伏击"),
        "armed_unmanned_wingman": ("弹舱库存", "批次材料", "航路伏击", "海上预置"),
        "short_takeoff_unmanned_fire_carrier": (
            "批次材料",
            "制造—任务",
            "航路伏击",
            "弹舱库存",
            "本机搜索补射",
        ),
        "cruise_mother_munition": ("长时在位", "载机返场", "批次材料", "航路伏击"),
        "land_loitering_launcher": ("载机", "航路伏击", "批次材料"),
        "land_mobile_precision_launcher": ("载机", "航路伏击", "批次材料"),
        "counter_unmanned_launcher": ("关机机动", "航路伏击", "批次材料"),
        "high_power_microwave": ("关机机动", "航路伏击", "批次材料"),
        "shore_anti_ship_launcher": ("关机机动", "批次材料", "低空拦截"),
        "electronic_attack": ("批次材料", "制造—任务", "航路伏击"),
    }
    ordered: list[str] = []
    used_indexes: set[int] = set()
    for group_index, (markers, fallback) in enumerate(
        zip(marker_groups, fallbacks, strict=True)
    ):
        selected = next(
            (
                (index, row)
                for index, row in enumerate(rows)
                if index not in used_indexes
                and any(marker in row for marker in markers)
            ),
            None,
        )
        if selected is None:
            ordered.append(fallback)
            continue
        index, row = selected
        if family != "generic":
            if group_index == 0 and (
                "在通信降级、GNSS压制与欺骗、目标包过期" in row
                or any(
                    marker in row
                    for marker in environment_conflicts.get(family, ())
                )
            ):
                ordered.append(fallback)
                continue
            if group_index == 1 and not any(
                marker in row for marker in metric_markers
            ):
                ordered.append(fallback)
                continue
            if group_index == 2:
                ordered.append(fallback)
                continue
        used_indexes.add(index)
        ordered.append(row)
    return ordered


def _bounded_portrait(lines: Sequence[str], *, minimum: int = 0) -> str:
    rows = [line.strip() for line in lines if line and line.strip()]
    del minimum
    return "\n".join(rows)


_PORTRAIT_MODULE_MARKERS = (
    "概述：",
    "装备与技术实现：",
    "关键作战流程：",
    "形成能力与作战效果：",
    "制胜逻辑机理与对抗边界：",
)


def resolve_capability_portrait(
    existing: object,
    **portrait_fields: object,
) -> str:
    """Preserve a complete model-written S6 portrait, otherwise rebuild it.

    High-quality S6 prose is authoritative once it contains all five governed
    modules and enough depth to pass the S6 gate. Historical short/template
    portraits are rebuilt from structured fields so old runs benefit from the
    improved overview and validation structure.
    """

    text = str(existing or "").strip()
    text = re.sub(
        r"\s+(?=- (?:装备与技术实现|关键作战流程|形成能力与作战效果|制胜逻辑机理与对抗边界|发展与验证路径)：)",
        "\n",
        text,
    )
    has_deprecated_development_section = "发展与验证路径：" in text
    internal_markers = ("Agent", "Codex", "Harness", "Packet", "Claim", "S1", "S6")
    overview = text.split("\n", 1)[0]
    causal_markers = ("面向", "针对", "利用", "采用", "通过", "形成", "实现")
    equipment_terms = (
        "导弹",
        "巡飞弹",
        "弹药",
        "无人机",
        "无人携弹平台",
        "无人艇",
        "无人潜航器",
        "鱼雷",
        "拦截弹",
        "火炮",
        "发射车",
        "反舰车",
        "效应器",
        "火控系统",
        "电子战系统",
        "雷达",
    )
    # Cross-field equipment identity is reviewed by Codex against the complete
    # card before submission.  This renderer intentionally does not infer a
    # process family or reject prose through an ever-growing keyword matrix.
    overview_family_conflict = False
    overview_is_research_framed = (
        any(marker in overview for marker in ("装备研究中的", "任务研究中的", "任务阶段，针对"))
        or any(marker in overview for marker in ("针对公开资料", "针对公开基线"))
    )
    if (
        all(marker in text for marker in _PORTRAIT_MODULE_MARKERS)
        and all(marker in overview for marker in causal_markers)
        and all(overview.count(marker) == 1 for marker in causal_markers)
        and any(term in overview for term in equipment_terms)
        and any(marker in overview for marker in ("为主装备", "为主体"))
        and "重构任务闭环，利用" not in overview
        and not overview_family_conflict
        and not overview_is_research_framed
        and not has_deprecated_development_section
        and text[-1] in "。！？；”’」』）)"
        and not any(marker in text for marker in internal_markers)
    ):
        return text
    return build_capability_portrait(**portrait_fields)


def build_capability_portrait(
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
    """Render a detailed, decision-oriented capability portrait without hard clipping."""

    raw_technology_rows = [
        re.sub(r"^(?:与|及|和)(?=[A-Za-z\u3400-\u9fff])", "", item).strip()
        for item in _clean_items(technologies, limit=8)
        if not item.startswith(("单一主装备", "主装备对象", "装备形态", "指标方向"))
    ]
    technology_rows = [
        item
        for item in raw_technology_rows
        if any(
            marker in item
            for marker in (
                "接口",
                "导航",
                "PNT",
                "传感",
                "识别",
                "制导",
                "数据链",
                "任务管理",
                "任务规划",
                "火控",
                "算法",
                "自治",
                "抗干扰",
            )
        )
    ][:3]
    if not technology_rows:
        technology_rows = raw_technology_rows[:3]
    step_rows = [
        row
        for row in _clean_items(operational_steps, limit=8)
        if not any(
            marker in row
            for marker in (
                "S1增量",
                "S2增量",
                "S3增量",
                "S4增量",
                "S5增量",
                "S6增量",
                "规模化机制不是",
                "不是增强通信背景",
                "不把通信、算法",
                "本候选主体",
            )
        )
    ]
    if isinstance(failure_boundary, Sequence) and not isinstance(
        failure_boundary, (str, bytes)
    ):
        raw_boundary_values = [str(item) for item in failure_boundary]
    else:
        raw_boundary_values = re.split(r"[；;。]", str(failure_boundary or ""))
    preferred_boundary_values = [
        row
        for row in raw_boundary_values
        if row.strip().startswith("失效边界")
    ]
    if not preferred_boundary_values:
        preferred_boundary_values = [
            row
            for row in raw_boundary_values
            if row.strip().startswith("对手反适应")
        ]
    boundary_rows = _clean_items(
        preferred_boundary_values or raw_boundary_values,
        limit=3,
    )
    boundary_rows = boundary_rows[:3]
    technology_text = "、".join(
        _technology_clause(item, limit=14) for item in technology_rows[:2]
    ) or "任务系统集成、受控自治与抗扰协同技术"
    if step_rows:
        first_step = step_rows[0]
        if len(step_rows) > 1 and (
            first_step.startswith(("对手", "敌", "威胁"))
            or any(
                marker in first_step
                for marker in (
                    "切断",
                    "削弱",
                    "失去稳定",
                    "造成中断",
                    "导致退化",
                    "容易被",
                    "链路不稳定",
                    "难以及时",
                )
            )
        ):
            step_rows = step_rows[1:]
        for continuation in (
            "形成低带宽毁伤摘要并回传任务状态",
            "按授权门槛决定补射、接替或安全中止",
        ):
            if len(step_rows) >= 4:
                break
            step_rows.append(continuation)
        phase_names = ("平台进入", "目标复核", "交战处置", "持续续接", "再组织", "复盘")
        process_text = "；".join(
            f"{index}.{phase_names[index - 1]}：{_process_clause(row)}"
            for index, row in enumerate(step_rows[:4], start=1)
        )
    else:
        concept_step = _process_clause(_operational_concept_clause(operational_concept))
        process_text = (
            "1.任务准备：完成目标与规则装订；2.平台进入：分散部署并保持协同；"
            f"3.交战处置：{concept_step}；4.持续续接：毁伤评估与再组织"
        )

    scenario_text = _scenario_clause(scenario)
    capability_text = _concise_clause(
        capability,
        "在受扰、节点受损条件下仍可考核的装备作战",
        limit=36,
        max_parts=1,
    ).removesuffix("能力")
    capability_text = re.sub(r"^在[^，；]{0,18}下", "", capability_text)
    capability_text = re.sub(r"^(?:形成|具备|实现)", "", capability_text).strip()
    effect_text = _effect_clause(effect, capability_text)
    effect_text = re.sub(r"^(?:实现|使|形成)", "", effect_text).strip()
    principle_text = _principle_clause(principle)
    baseline_text = _baseline_clause(baseline)
    equipment_text = _equipment_landing_clause(equipment_form, baseline_text)
    concept_text = _concise_clause(
        _operational_concept_clause(operational_concept),
        "受控任务闭环",
        limit=34,
        max_parts=1,
    )
    identity_seed = "；".join(
        str(item or "")
        for item in (
            " ".join(
                item
                for item in (str(name or "").strip(), str(equipment_form or "").strip())
                if item
            ),
            principle,
            winning_mechanism,
            capability,
            operational_concept,
            baseline,
        )
    )
    equipment_text = _family_equipment_subject(identity_seed, equipment_text)
    problem_text = _family_problem_clause(
        identity_seed,
        _problem_clause(problem, capability, scenario_text),
        raw_problem=problem,
    )
    identity_text = "；".join(
        str(item or "")
        for item in (
            " ".join(
                item
                for item in (str(name or "").strip(), str(equipment_form or "").strip())
                if item
            ),
            problem_text,
            principle_text,
            winning_mechanism,
            capability_text,
        )
    )
    governed_steps = normalize_operational_process(
        operational_steps,
        equipment_identity=identity_text,
    )
    phase_names = (
        ("任务准备", "部署进入", "证据与摘要", "转交与终止")
        if _capability_family(identity_text) == "expendable_mission_bridge"
        else ("任务准备", "部署进入", "目标复核", "交战与再组织")
    )
    process_text = "；".join(
        f"{index}.{phase_names[index - 1]}：{_process_clause(row)}"
        for index, row in enumerate(governed_steps[:4], start=1)
    )
    family_focus = _family_module_focus(identity_text)
    overview_contract = _family_overview_contract(identity_text)
    overview_principle = (
        overview_contract[0] if overview_contract else principle_text
    )
    overview_principle = re.sub(
        r"^以(?=[A-Za-z\u3400-\u9fff])", "", overview_principle
    ).strip()
    overview_technologies = (
        overview_contract[1] if overview_contract else technology_text
    )
    overview_concept = overview_contract[2] if overview_contract else concept_text
    module_principle_relation = (
        "通过"
        if overview_principle.startswith(("把", "将", "不把", "在"))
        else "利用"
    )
    winning_text = _winning_mechanism_clause(
        winning_mechanism,
        principle,
        identity_text,
    )
    winning_text = re.sub(
        r"^(?:直接效果是|核心机理是|制胜逻辑是)", "", winning_text
    ).strip()
    winning_text = _family_winning_thesis(
        identity_text,
        winning_text,
        raw_winning=winning_mechanism,
    )
    exchange_effect_text = _exchange_effect_clause(identity_text)
    effect_metric_text = _effect_metric_clause(identity_text)
    overview_scenario = _family_overview_scenario(identity_text, scenario_text)
    overview_capability, overview_effect = _family_overview_outcome(
        identity_text,
        capability_text,
        effect_text,
    )
    overview_text = _overview_clause(
        scenario=overview_scenario,
        problem=problem_text,
        principle=overview_principle,
        technologies=overview_technologies,
        operational_concept=overview_concept,
        operational_process=process_text,
        equipment=equipment_text,
        capability=overview_capability,
        effect=overview_effect,
        identity=identity_text,
    )
    process_gap_text = _concise_clause(
        problem_text,
        "关键任务链断点",
        limit=28,
        max_parts=1,
    )
    if "反辐射" in problem_text and "关机窗口" in problem_text:
        process_gap_text = "关机窗口、诱饵排除和真实节点续接"
    elif "目标坐标过期" in problem_text:
        process_gap_text = "目标时效、受扰导航和末端确认断点"
    boundary_text = "；".join(
        _concise_clause(item, "", limit=42, max_parts=1) for item in boundary_rows[:1]
    ) or "目标信息可信度不足、关键节点连续损失或体系依赖成本超过可承受范围时，能力收益将显著下降"
    boundary_core = boundary_text.rstrip("。；，")
    direct_effect_text = re.sub(r"^直接", "", effect_text).strip()
    has_explicit_consequence = any(
        marker in boundary_core
        for marker in (
            "失效",
            "退化",
            "下降",
            "不足",
            "不能",
            "无法",
            "不得",
            "不成立",
            "消失",
            "不可接受",
            "只允许",
            "只能",
        )
    )
    boundary_core = re.sub(r"(?<=不可接受)时$", "", boundary_core)
    family = _capability_family(identity_text)
    if family == "expendable_mission_bridge":
        bridge_boundary = re.sub(r"时安全终止$", "", boundary_core).rstrip("，；。")
        bridge_boundary = re.sub(r"^(?:当|若|如果|一旦)", "", bridge_boundary)
        boundary_action = (
            f"当{bridge_boundary}时，任务桥不得自行攻击，并应保持静默或安全终止"
        )
    elif boundary_core.startswith(("当", "若", "如果", "一旦")):
        boundary_action = f"{boundary_core}，应降级或重新校准"
    elif "时，" in boundary_core and has_explicit_consequence:
        boundary_action = f"当{boundary_core}，应降级或重新校准"
    elif boundary_core.endswith("时"):
        boundary_action = f"当{boundary_core}应降级或重新校准"
    elif has_explicit_consequence:
        boundary_action = f"当{boundary_core}，应降级或重新校准"
    else:
        boundary_action = f"当{boundary_core}时应降级或重新校准"

    process_assurance = (
        f"{equipment_text}各阶段必须明确目标证据从哪里产生、摘要何时形成、向哪一授权射手转发、"
        "何种条件保持静默或安全终止；任务桥不得自行攻击，转交结果只触发授权射手发射、拒打、补射或接替。"
        if family == "expendable_mission_bridge"
        else (
            f"{equipment_text}各阶段必须明确目标证据从哪里产生、由谁完成交战授权、何时释放毁伤、"
            "何种条件转入拒打/降级，以及毁伤评估如何触发补射、接替或停止消耗。"
        )
    )

    return _bounded_portrait(
        [
            f"概述：{overview_text}",
            (
                f"- 装备与技术实现：型号落点为{equipment_text}；以{baseline_text}为公开对照，"
                f"{module_principle_relation}{overview_principle}，采用{overview_technologies}，"
                "闭合载荷、火控、任务软件和指挥接口。"
                f"{family_focus['technology']}。"
            ),
            (
                f"- 关键作战流程：以{equipment_text}执行{concept_text}，围绕“{process_gap_text}”闭合任务链并组织战斗行动："
                f"{process_text}。{process_assurance}"
            ),
            (
                f"- 形成能力与作战效果：形成{capability_text}能力，直接实现{direct_effect_text}；"
                f"具体战果表现为{family_focus['effect']}；以{effect_metric_text}验收，并分别比较首轮、补击、"
                "连续波次和关键节点受损条件下的任务保持度。"
            ),
            (
                f"- 制胜逻辑机理与对抗边界：核心机理是{winning_text}；"
                f"{exchange_effect_text}。在具体对抗中，{family_focus['winning']}。"
                "对手可用诱饵、强干扰和近程拦截反制；也可通过机动转移与频谱静默削弱收益；"
                f"{boundary_action}。"
            ),
        ]
    )


__all__ = [
    "build_capability_portrait",
    "build_capability_title",
    "normalize_capability_problem",
    "normalize_operational_process",
    "normalize_verification_plan",
    "resolve_capability_portrait",
]
