"""Evidence-bounded S6 fallback portfolio for deadline finalization.

The fallback is intentionally equipment-first.  It is used only when the
independent S6 model cannot return a complete structured result before the
runtime deadline.  It never invents calibrated performance numbers or claims
that an unverified concept is already operational.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from equipment_deep_research.orchestration.capability_portrait import (
    build_capability_portrait,
    normalize_operational_process,
    normalize_verification_plan,
)


def build_deadline_weapon_directions(
    *,
    topic: str,
    evidence_ids: Sequence[str] = (),
    evidence_index: Sequence[Mapping[str, Any]] = (),
    confidence: float = 0.62,
    gap_basis: str = "",
) -> list[dict[str, Any]]:
    """Return six concrete, mutually distinct combat-equipment directions."""

    query = " ".join(str(topic or "").split())
    evidence = list(dict.fromkeys(str(item) for item in evidence_ids if str(item)))
    evidence_rows = [dict(item) for item in evidence_index if isinstance(item, Mapping)]
    offensive_focus = any(
        term in query
        for term in (
            "远程火力打击",
            "火力打击装备",
            "远程精确打击",
            "远程精确火力",
            "突防",
            "歼灭",
            "纵深毁伤",
            "压制毁伤",
        )
    )
    defensive_focus = not offensive_focus and any(
        term in query for term in ("防空", "反无人", "拦截", "要地防护", "低空防御")
    )

    def ids_for(*keywords: str, limit: int = 3) -> list[str]:
        """Bind a fallback card only to evidence about its own equipment family."""

        matches: list[str] = []
        lowered = tuple(keyword.lower() for keyword in keywords if keyword)
        for item in evidence_rows:
            evidence_id = str(item.get("evidence_id", "")).strip()
            if not evidence_id:
                continue
            searchable = " ".join(
                str(item.get(field, ""))
                for field in (
                    "source_title",
                    "title",
                    "claim",
                    "excerpt",
                    "source_url",
                    "url",
                )
            ).lower()
            if any(keyword in searchable for keyword in lowered):
                matches.append(evidence_id)
            if len(matches) >= limit:
                break
        if matches:
            return list(dict.fromkeys(matches))
        # Existing unit and legacy call sites may only supply accepted ids.
        # Preserve that compatibility, but do not cross-bind unrelated cards
        # when a searchable evidence index was explicitly supplied.
        return [] if evidence_rows else evidence[:limit]

    def has_object_evidence(*keywords: str) -> bool:
        """Return whether the accepted evidence names the requested family."""

        lowered = tuple(keyword.lower() for keyword in keywords if keyword)
        return any(
            any(
                keyword
                in " ".join(
                    str(item.get(field, ""))
                    for field in (
                        "source_title",
                        "title",
                        "claim",
                        "excerpt",
                        "source_url",
                        "url",
                    )
                ).lower()
                for keyword in lowered
            )
            for item in evidence_rows
        )

    launched_effects_evidence = has_object_evidence(
        "launched effects",
        "launched effect",
        "lasso",
        "low altitude stalking",
    )
    switchblade_evidence = has_object_evidence("switchblade")
    offensive_low_altitude_family = (
        "launched_effects"
        if launched_effects_evidence or not switchblade_evidence
        else "switchblade"
    )
    common_boundary = (
        "公开资料不能证明代表性强干扰条件下的联合性能；若目标识别、末制导、平台载荷余量"
        "或任务级对抗试验不能闭合，应下调成熟度和建设优先级"
    )
    common_trigger = (
        "未来3至10年强电磁对抗、低成本无人化、目标短时暴露和高消耗作战持续增强"
    )
    common_verification = (
        "以任务级仿真、半实物联试和受控对抗试验验证断链任务完成、目标确认、突防/毁伤闭合、"
        "成本交换和安全中止；无公开校准数据时只记录区间和通过/失败条件"
    )

    specs: list[dict[str, Any]] = [
        {
            "name": "空射隐身防区外抗扰巡航导弹补击",
            "type": "upgrade",
            "equipment_form": "JASSM-ER类空射低可探测防区外巡航导弹及其任务规划、导航与末制导升级组件",
            "baseline_system": "公开产品资料所示JASSM/JASSM-ER空射防区外精确打击巡航导弹",
            "function": "在防空拦截和导航欺骗压力下维持对战役纵深固定及准固定高价值节点的突防毁伤与补击能力",
            "capability_gap": "公开基线能够证明远程空射精确打击对象存在，但不能证明强欺骗、链路间歇和目标信息过期条件下的任务闭合质量",
            "operational_mechanism": "保留空射防区外投送和低可探测突防基线，重点验证多源导航可信评估、任务边界保持、末段目标复核和毁伤摘要驱动的后续补击",
            "military_value": "强链战役纵深精确毁伤与再打击闭环，为后续无人火力和地射火力持续压制关键节点创造窗口",
            "strike_countermeasure_value": "降低空射远程火力对持续外部更新的刚性依赖，并提高复杂防空环境下的突防任务韧性",
            "novelty": "不把JASSM-ER与地射导弹混成一类，而是在既有空射巡航导弹边界内验证抗骗突防和补击闭环升级",
            "development_path": "近期完成任务软件、导航可信评估和末制导接口的地面与半实物验证，中期开展代表性干扰和多层拦截条件下的任务级试验",
            "upgrade_package": ["多模PNT与抗欺骗末制导", "任务边界装订与安全中止", "毁伤摘要回灌与再打击规划"],
            "combat_effect_uplift": "增强空射防区外巡航导弹在受扰条件下的突防毁伤和补击组织能力，增量须由对抗试验校准",
            "strike_chain_contribution": "强链空中投送—防区外发射—突防—末端确认—毁伤评估—补击链条",
            "upgrade_boundary": "若现役弹体计算、能源、导引头或任务接口余量不足，则停止增量改装并转入新弹研制",
            "evidence_keywords": ("jassm", "agm-158"),
            "confidence_delta": 0.07,
            "feasibility": 4,
            "horizon": "near",
        },
        {
            "name": "地射远程机动目标精确毁伤导弹",
            "type": "upgrade",
            "equipment_form": "PrSM类地面机动发射远程精确制导导弹及其目标更新、任务规划和火力单元接口升级",
            "baseline_system": "美国陆军公开交付信息所示Precision Strike Missile地射远程精确打击项目",
            "function": "由分散地面火力单元对战役纵深固定、准固定和有限机动目标实施快速火力分配、精确毁伤与后续补击",
            "capability_gap": "公开资料可证明PrSM项目交付和地射远程火力属性，但不能证明强电磁对抗下对有限机动目标的目标更新与毁伤闭合水平",
            "operational_mechanism": "以地面机动发射和现役火力体系接入为基线，分别验证目标信息时效约束、火力单元任务重规划、受扰导航降级和补击授权闭环",
            "military_value": "强链地面远程火力对纵深火力、防空和保障节点的持续毁伤，降低单一空中投送通道受限对战役节奏的影响",
            "strike_countermeasure_value": "以分散机动地射火力扩大对手防区压力，并通过快速补击缩短高价值目标重新暴露后的响应周期",
            "novelty": "把PrSM作为独立地射导弹对象论证，不与JASSM-ER的空射平台、飞行任务和升级边界混写",
            "development_path": "近期完成目标信息时效、任务规划和发射单元接口联试，中期在机动目标、导航受扰和战损接替条件下开展任务级验证",
            "upgrade_package": ["目标信息时效与任务更新", "受扰导航与任务降级", "火力单元补击授权接口"],
            "combat_effect_uplift": "提升地射远程导弹对纵深目标的快速分配、持续毁伤和补击能力，实际增益须由对抗数据校准",
            "strike_chain_contribution": "强链地面发现移交—火力分配—机动发射—纵深毁伤—毁伤评估—补击链条",
            "upgrade_boundary": "若目标更新链、发射单元接口或弹上处理余量不能满足任务时效，则不得把软件设想表述为已具备能力",
            "evidence_keywords": ("prsm", "precision strike missile"),
            "confidence_delta": 0.05,
            "feasibility": 4,
            "horizon": "near",
        },
        {
            "name": "失辐射等待反辐射巡飞弹",
            "type": "new_capability",
            "equipment_form": "Harop类长航时反辐射巡飞弹药、被动射频搜索组件、目标复核传感器和机动发射单元",
            "baseline_system": "IAI公开产品资料所示Harop长航时巡飞弹药及其猎歼和压制用途",
            "function": "在雷达间歇开机、关机转移和诱饵辐射条件下持续搜索并压制防空、电子战与远程探测节点",
            "capability_gap": "公开基线不能证明复杂诱饵、频率捷变和长时间静默条件下的目标真实性复核、失辐射等待与任务安全边界",
            "operational_mechanism": "被动搜索形成候选辐射源，目标失辐射后保持受限等待而不强行攻击，再以独立复核和授权边界决定继续监视、压制或中止",
            "military_value": "以持续反辐射猎歼削弱对手防空探测和火控链，为远程导弹及低空无人火力开辟进入窗口",
            "strike_countermeasure_value": "把一次性反辐射突击转化为跨越雷达关机窗口的时间学习和持续成本强加",
            "novelty": "围绕Harop类巡飞弹的失辐射等待与目标复核形成独立装备方向，不与AARGM或MALD功能强行复合",
            "development_path": "近期验证被动搜索、失辐射等待和安全中止，中期开展频率捷变、诱饵辐射与关机转移条件下的红蓝对抗试验",
            "evidence_keywords": ("harop", "harpy"),
            "confidence_delta": 0.04,
            "feasibility": 3,
            "horizon": "mid",
        },
        {
            "name": "低成本批量巡航效应器",
            "type": "new_capability",
            "equipment_form": "Barracuda-500M类固定构型、面向规模生产的低成本巡航效应器及地面发射接口",
            "baseline_system": "Anduril公开生产协议信息所示Surface-Launched Barracuda-500M巡航效应器",
            "function": "以可规模补充的巡航效应器对战役纵深固定和准固定节点实施多波次压制与毁伤",
            "capability_gap": "公开资料能够证明项目和生产方向，但不能证明单位有效毁伤成本、批产一致性、强扰突防质量和持续补充节奏",
            "operational_mechanism": "保持固定构型和明确任务边界，以共用发射与任务接口组织多波次投送，并用任务完成率、补充周期和单位有效毁伤成本约束规模化价值",
            "military_value": "开链低成本规模化纵深压制火力，减少高端远程弹药承担常规节点消耗任务的库存压力",
            "strike_countermeasure_value": "以工业补充速度和多波次到达改变对手昂贵拦截资源与我方巡航效应器之间的成本交换关系",
            "novelty": "从追求单弹全能转向固定构型、任务分工和可规模生产共同决定的经济学制胜",
            "development_path": "近期验证固定构型任务边界、发射接口和制造一致性，中期以代表性拦截与强扰环境评估单位有效毁伤成本和补充节奏",
            "evidence_keywords": ("barracuda", "famm"),
            "confidence_delta": 0.02,
            "feasibility": 3,
            "horizon": "mid",
        },
        {
            "name": "空射可消耗电子攻击压制效应器",
            "type": "new_capability",
            "equipment_form": "MALD-J类固定构型空射可消耗诱饵与电子攻击效应器及载机任务接口",
            "baseline_system": "RTX公开产品资料所示MALD空射诱饵和MALD-J干扰变型",
            "function": "在主攻武器进入前欺骗、干扰或压制防空探测与火控链，制造可被后续导弹和无人火力利用的突防窗口",
            "capability_gap": "公开资料可证明MALD-J干扰变型存在，但不能证明代表性防空体系下的压制范围、持续时间、任务协同增益和战损交换",
            "operational_mechanism": "由载机在防区外释放固定构型可消耗电子攻击效应器，按预装订任务边界实施诱骗和干扰，并与独立毁伤武器在接口层协同",
            "military_value": "以直接电子攻击压制削弱对手防空发现和火控质量，为JASSM-ER、PrSM及巡飞火力创造进入和补击窗口",
            "strike_countermeasure_value": "用可消耗电子攻击效应器迫使防空节点暴露、重配或消耗资源，降低高价值攻击平台的前出暴露",
            "novelty": "保持MALD-J诱饵与电子攻击的固定构型边界，不在同一弹体强行叠加反辐射末制导和毁伤战斗部",
            "development_path": "近期验证载机接口、任务边界和受控频谱效应，中期在代表性探测与火控链条件下评估压制窗口和后续武器增益",
            "evidence_keywords": ("mald", "adm-160", "decoy"),
            "confidence_delta": 0.03,
            "feasibility": 3,
            "horizon": "mid",
        },
        {
            "name": (
                "低成本反无人拦截弹"
                if defensive_focus
                else (
                    "低空巡飞猎歼弹药"
                    if offensive_low_altitude_family == "switchblade"
                    else "低空可消耗察打一体无人机"
                )
            ),
            "type": "new_capability",
            "equipment_form": (
                "Coyote类低成本动能拦截弹、反无人火控接口和机动发射单元"
                if defensive_focus
                else (
                    "Switchblade 600类筒式发射低空巡飞猎歼弹药、EO/IR任务载荷和地面任务控制单元"
                    if offensive_low_altitude_family == "switchblade"
                    else "Launched Effects类可由空中或地面平台释放的低空可消耗察打一体无人机"
                )
            ),
            "baseline_system": (
                "公开产品资料所示Coyote类反无人机物理拦截装备"
                if defensive_focus
                else (
                    "AeroVironment公开产品资料所示Switchblade 600筒式发射巡飞弹药"
                    if offensive_low_altitude_family == "switchblade"
                    else "美国陆军公开预算和试验信息中的Launched Effects与低空察打无人装备方向"
                )
            ),
            "function": (
                "对低慢小无人机和多方向来袭目标实施低成本物理拦截"
                if defensive_focus
                else "前出搜索、确认并打击短时暴露的低空和近纵深目标，在通信受限时按任务边界继续完成察打闭环"
            ),
            "capability_gap": (
                "面对低慢小蜂群和多方向饱和来袭时，现役体系存在成本失配、持续射击和战损接替不足"
                if defensive_focus
                else "公开方向不能证明强干扰、低空遮蔽和高损耗条件下的目标复核、任务续接、载荷效应和快速补充质量"
            ),
            "operational_mechanism": (
                "由分布式探测保持航迹，再由低成本拦截弹对确认目标实施物理拦截并按剩余弹量重分配射界"
                if defensive_focus
                else "释放平台在威胁区外投送低空可消耗无人机，无人机以本地目标摘要和任务边界完成搜索、复核、交战或中止，并回传最小任务结果"
            ),
            "military_value": (
                "保护机场、港口、指挥所和远程火力阵地，改善反无人交换比并维持关键节点持续作战"
                if defensive_focus
                else "开链前出低空察打和近纵深猎歼能力，缩短短时目标从发现到毁伤的闭环并减少高价值平台暴露"
            ),
            "strike_countermeasure_value": (
                "补链低空发现—识别—物理拦截，并改善昂贵防空弹对廉价无人机的成本失配"
                if defensive_focus
                else "以前出分布式低空存在压缩目标逃逸时间，并以可消耗平台吸收局部战损和反无人拦截消耗"
            ),
            "novelty": (
                "把反无人装备收缩为低成本物理拦截单一任务，不与进攻型无人火力混写"
                if defensive_focus
                else (
                    "在Switchblade 600公开筒射巡飞弹药边界内验证受扰低空猎歼、目标复核和安全中止，不外推为Launched Effects项目能力"
                    if offensive_low_altitude_family == "switchblade"
                    else "从后方发现后召唤火力转向由释放平台前送的可消耗低空察打节点，并以任务边界约束受限自主"
                )
            ),
            "development_path": (
                "近期完成火控与发射接口联试，中期开展多方向饱和来袭和持续交战验证"
                if defensive_focus
                else "近期完成释放接口、低空导航、目标复核和安全中止验证，中期开展强扰、高损耗和多层反无人拦截条件下的任务级试验"
            ),
            "evidence_keywords": (
                ("coyote", "roadrunner", "counter-uas")
                if defensive_focus
                else (
                    ("switchblade",)
                    if offensive_low_altitude_family == "switchblade"
                    else ("launched effects", "lasso", "low altitude stalking")
                )
            ),
            "confidence_delta": 0.01 if defensive_focus else 0.0,
            "feasibility": 3,
            "horizon": "mid",
        },
    ]

    directions: list[dict[str, Any]] = []
    bounded_confidence = max(0.0, min(1.0, float(confidence)))
    for position, spec in enumerate(specs, start=1):
        row = dict(spec)
        keywords = tuple(str(item) for item in row.pop("evidence_keywords", ()))
        confidence_delta = float(row.pop("confidence_delta", 0.0) or 0.0)
        direct_evidence_refs = ids_for(*keywords)
        direction_confidence = max(
            0.0,
            min(
                0.86,
                bounded_confidence
                + confidence_delta
                + min(0.02, 0.01 * len(direct_evidence_refs)),
            ),
        )
        row.update(
            {
                "priority": f"P{position}",
                "direct_evidence_refs": direct_evidence_refs,
                "derived_from": ["accepted-baseline-and-s4-s5-handoff"],
                "future_trigger": common_trigger,
                "adversary_adaptation": "机动分散、诱饵欺骗、电磁压制、频谱静默、低成本饱和和针对性拦截",
                "failure_boundary": common_boundary,
                "uncertainty_boundary": "装备级方向有公开类别证据支撑，具体型号、指标区间和联合作战增益仍待验证",
                "feasibility_basis": "存在可类比平台或分系统基础，但强对抗环境下的体系集成成熟度不得由单项技术成熟替代",
                "verification": common_verification,
                "foresight": common_trigger,
                "query_relevance": (
                    f"面向“{query}”的高烈度强干扰任务窗口，在目标信息稀疏、链路不稳定或导航受扰阶段，"
                    f"直接承担{row['military_value']}，不是一般通信、保障或工程建设方向"
                ),
                "confidence": round(direction_confidence, 4),
            }
        )
        if gap_basis:
            row["capability_gap"] = (
                f"{row['capability_gap']}；现有公开基线仅支持类别级判断：{gap_basis[:220]}"
            )
        target_scenario = f"“{query}”中的目标信息稀疏、链路间歇和导航受扰任务阶段"
        enabling_technologies = [
            item.strip()
            for item in str(row["equipment_form"]).replace("和", "、").split("、")
            if item.strip()
        ][:5]
        operational_process = [
            item.strip()
            for item in str(row["operational_mechanism"]).replace("，", "；").split("；")
            if item.strip()
        ][:6]
        operational_process = normalize_operational_process(
            operational_process,
            equipment_identity=row["equipment_form"],
        )
        verification_plan = normalize_verification_plan(
            row["verification"],
            equipment_identity=row["equipment_form"],
            failure_boundary=row["failure_boundary"],
        )
        winning_mechanism = (
            f"{row['novelty']}；相对{row['baseline_system']}，通过{row['strike_countermeasure_value']}"
            "改变时间、成本、平台、毁伤或体系交换关系"
        )
        portrait = build_capability_portrait(
            scenario=target_scenario,
            problem=row["capability_gap"],
            principle=row["novelty"],
            technologies=enabling_technologies,
            operational_concept=row["operational_mechanism"],
            operational_steps=operational_process,
            capability=row["function"],
            effect=row["military_value"],
            winning_mechanism=winning_mechanism,
            equipment_form=row["equipment_form"],
            baseline=row["baseline_system"],
            development_path=row["development_path"],
            failure_boundary=row["failure_boundary"],
            verification_plan=verification_plan,
        )
        row.update(
            {
                "target_scenario": target_scenario,
                "problem_statement": row["capability_gap"],
                "scientific_principle": row["novelty"],
                "enabling_technologies": enabling_technologies,
                "operational_concept": row["operational_mechanism"],
                "operational_process": operational_process,
                "capability_outcome": row["function"],
                "winning_mechanism": winning_mechanism,
                "verification_plan": verification_plan,
            }
        )
        row["capability_portrait"] = portrait
        directions.append(row)
    if evidence_rows:
        anchored = [item for item in directions if item["direct_evidence_refs"]]
        if len(anchored) >= 5:
            directions = anchored[:7]
            for position, item in enumerate(directions, start=1):
                item["priority"] = f"P{position}"
    return directions
