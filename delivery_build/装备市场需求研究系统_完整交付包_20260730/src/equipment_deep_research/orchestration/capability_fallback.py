"""Evidence-bounded S6 fallback portfolio for deadline finalization.

The fallback is intentionally equipment-first.  It is used only when the
independent S6 model cannot return a complete structured result before the
runtime deadline.  It never invents calibrated performance numbers or claims
that an unverified concept is already operational.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any


def _complete_text(value: str, limit: int = 600) -> str:
    text = " ".join(str(value).split())
    if len(text) <= limit:
        return text
    clipped = text[:limit]
    boundary = max(clipped.rfind(mark) for mark in ("。", "！", "？", ";", "；"))
    if boundary >= 300:
        return clipped[: boundary + 1]
    return clipped.rstrip("，、：: ") + "。"


def build_deadline_weapon_directions(
    *,
    topic: str,
    evidence_ids: Sequence[str] = (),
    confidence: float = 0.62,
    gap_basis: str = "",
) -> list[dict[str, Any]]:
    """Return six concrete, mutually distinct combat-equipment directions."""

    query = " ".join(str(topic or "").split())
    evidence = list(dict.fromkeys(str(item) for item in evidence_ids if str(item)))
    defensive_focus = any(
        term in query for term in ("防空", "反无人", "拦截", "要地防护", "低空防御")
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
            "name": "现役远程精确制导导弹抗扰再打击升级",
            "type": "upgrade",
            "equipment_form": "现役远程对陆/反舰精确制导导弹、弹上多模导航末制导组件和任务规划装置",
            "baseline_system": "现役依赖预规划目标、外部导航校正和任务链持续更新的远程精确制导导弹",
            "function": "在导航拒止、链路间歇和毁伤评估迟滞时保持对固定或准固定高价值目标的精确毁伤与再打击能力",
            "capability_gap": "现役弹药在强干扰、欺骗和目标信息过期条件下的精度保底、目标复核和再打击任务闭合不足",
            "operational_mechanism": "在任务准备阶段装订目标特征、禁打边界和备选航路，飞行阶段由惯导、地形/景象匹配和多模末制导交叉校验，打击后以低带宽摘要触发补打或中止",
            "military_value": "强链战役纵深精确毁伤和再打击闭环，使通信受限时仍能压制关键火力、电子战或保障节点",
            "strike_countermeasure_value": "降低对持续外部喂数的刚性依赖，缩短目标再次暴露后的火力重组周期",
            "novelty": "从单次命中参数升级转向断链条件下可保持、可复核、可再打击的任务闭环",
            "development_path": "近期完成现役弹上任务软件、多模导航和末制导接口改装，中期在欺骗、干扰和迟滞毁伤评估条件下开展体系级实弹验证",
            "upgrade_package": ["多模PNT与抗欺骗末制导", "任务边界装订与安全中止", "毁伤摘要回灌与再打击规划"],
            "combat_effect_uplift": "恢复断链条件下的远程精确毁伤与补打组织能力，效能增量须由对抗试验校准",
            "strike_chain_contribution": "强链发现—授权—发射—末端确认—毁伤评估—再打击链条",
            "upgrade_boundary": "若现役弹体计算、能源、导引头或任务接口余量不足，则停止增量改装并转入新弹研制",
            "feasibility": 4,
            "horizon": "near",
        },
        {
            "name": "可消耗低空无人突击集群压制毁伤系统",
            "type": "new_capability",
            "equipment_form": "低特征低空无人机、诱骗/电子压制载荷、轻型精确毁伤载荷和分布式机动发射单元",
            "baseline_system": "现役中小型无人机、巡飞弹、电子战载荷和战术火力单元",
            "function": "以可消耗异构无人机分担侦察、诱骗、压制和突击任务，在局部断链后按预设边界继续完成目标复核和毁伤",
            "capability_gap": "单平台难以同时承受低空突防、高损耗、诱饵识别和规模火力组织，且昂贵弹药交换比易被对手廉价拦截反转",
            "operational_mechanism": "多批次低空进入迫使对手防空和电子战节点开机暴露，蜂群按剩余载荷与目标可信度重分配诱骗、压制和毁伤角色",
            "military_value": "开链形成低成本规模压制和近纵深毁伤能力，持续消耗对手探测、拦截与值班资源",
            "strike_countermeasure_value": "通过成本交换反转和多点到达提高重点目标压制持续性，而不是依赖单架高价值平台",
            "novelty": "由性能制胜转向可消耗规模、任务重构和工业补充共同决定的经济学制胜",
            "development_path": "近期完成百架级数字编组和小规模实装联试，中期验证强扰、高损耗与快速补充条件下的任务完成率",
            "feasibility": 3,
            "horizon": "mid",
        },
        {
            "name": "长航时巡飞弹蜂群搜索猎歼武器系统",
            "type": "new_capability",
            "equipment_form": "长航时巡飞弹、被动/光电复合导引头、蜂群任务分配模块和机动发射补充单元",
            "baseline_system": "现役单发巡飞弹、战术无人侦察平台和发现后召唤火力模式",
            "function": "在任务空域持续待机，对短时暴露的机动火力、防空和电子战节点实施搜索、确认、压制与连续猎歼",
            "capability_gap": "传统发射—飞行—命中的线性链路响应慢，目标在外部火力到达前可能转移或重新隐蔽",
            "operational_mechanism": "让弹药先于目标存在，蜂群在低带宽条件下共享局部目标摘要，并由人在回路的预设交战边界约束搜索、认领、攻击或中止",
            "military_value": "压缩目标出现到毁伤的决策周期，形成持续拒止和时间敏感目标猎歼能力",
            "strike_countermeasure_value": "以长航时持续存在替代远距离临机召唤，降低目标信息保鲜和连续链路依赖",
            "novelty": "从平台发射逻辑转向持续存在的徘徊火力场，并把时间窗口转化为装备能力",
            "development_path": "近期验证长航时待机、目标类别过滤和安全中止，中期开展诱饵、静默机动和蜂群损耗条件下的任务压力试验",
            "feasibility": 3,
            "horizon": "mid",
        },
        {
            "name": "远程精确打击导弹多路径突防武器族",
            "type": "new_capability",
            "equipment_form": "模块化远程对陆/反舰导弹、多点机动发射单元、多模末制导组件和异构弹药任务规划系统",
            "baseline_system": "现役单一弹型、固定突防航路和集中式任务规划的远程导弹体系",
            "function": "围绕高价值固定、准固定和有限机动目标形成多点发射、多路径突防、异构效应组合和打击后再攻击",
            "capability_gap": "对手防空反导、诱饵和电子战适应后，单一弹型与单轴突防易被预测，远程火力难以持续形成有效毁伤",
            "operational_mechanism": "由目标可信度和拦截压力驱动不同射程、末段特征与效应载荷的多波次组合，分散拦截资源并依据毁伤摘要重规划后续波次",
            "military_value": "形成传统远程精打赛道的跨代突防与战役纵深毁伤优势，提高高价值目标压制和区域拒止韧性",
            "strike_countermeasure_value": "强链多点发射—多路径突防—末端确认—再打击闭环，迫使对手扩大昂贵拦截弹消耗",
            "novelty": "从单弹性能竞争转向导弹武器族、发射节点和多波次任务重规划的体系竞争",
            "development_path": "近期完成多弹型任务规划与半实物闭环，中期在复杂电磁和对抗拦截条件下开展体系级实弹验证",
            "feasibility": 3,
            "horizon": "mid",
        },
        {
            "name": "反辐射巡飞弹自主搜捕压制武器系统",
            "type": "new_capability",
            "equipment_form": "反辐射巡飞弹、宽带被动侦收导引头、光电复核组件和机动多联装发射单元",
            "baseline_system": "现役反辐射导弹、电子支援侦察平台和单次压制防空任务编组",
            "function": "在敌雷达间歇开机、频率捷变和诱饵辐射条件下持续搜索并压制防空、电子战与远程探测节点",
            "capability_gap": "现役反辐射武器对短时开机、关机转移和假辐射源的持续猎杀与目标复核能力不足",
            "operational_mechanism": "被动侦收先形成候选辐射源轨迹，巡飞待机跨越关机窗口，再由多谱段复核和人工授权边界决定压制、攻击或继续监视",
            "military_value": "以电子压制和节点毁伤开辟远域火力通道，持续削弱对手防空杀伤链和决策节奏",
            "strike_countermeasure_value": "把一次性反辐射突击转化为对雷达开关机节奏的持续猎歼和成本强加",
            "novelty": "将反辐射效应、长航时待机和目标复核融合为时间学习型压制武器",
            "development_path": "近期验证宽带被动测向、假辐射源识别和安全交战边界，中期开展关机转移与多诱饵红蓝对抗试验",
            "feasibility": 3,
            "horizon": "mid",
        },
        {
            "name": (
                "低成本拦截弹与定向能反无人猎歼系统"
                if defensive_focus
                else "空射低空隐身巡航导弹远域压制武器系统"
            ),
            "type": "new_capability",
            "equipment_form": (
                "低成本拦截弹、高能激光/高功率微波效应器、反无人火控雷达和机动武器站"
                if defensive_focus
                else "空射低空隐身巡航导弹、可更换任务载荷、多模末制导组件和有人/无人载机挂载接口"
            ),
            "baseline_system": (
                "现役近程防空、电子战反无人和弹炮结合要地防护系统"
                if defensive_focus
                else "现役空射巡航导弹、防区外打击平台和固定任务载荷体系"
            ),
            "function": (
                "按目标价值、来袭密度和单次拦截成本分配软杀伤、定向能和低成本动能拦截"
                if defensive_focus
                else "由有人或无人载机在防区外释放，依托低空低特征航路和模块化压制/毁伤载荷打击远域关键节点"
            ),
            "capability_gap": (
                "面对低慢小蜂群和多方向饱和来袭时，现役体系存在成本失配、持续射击和战损接替不足"
                if defensive_focus
                else "现役远域打击对高价值发射平台、持续链路和单一战斗部依赖较强，难以兼顾压制开窗与后续毁伤"
            ),
            "operational_mechanism": (
                "分布式探测保持航迹，先以软杀伤和定向能分流降效，再由低成本拦截弹猎歼漏网目标并动态重分配射界"
                if defensive_focus
                else "载机分布式接近并多点释放，弹上按预装订边界保持低空突防，在末段以多模识别选择电子压制或精确毁伤效应"
            ),
            "military_value": (
                "保护机场、港口、指挥所和远程火力阵地，改善反无人交换比并维持关键节点持续作战"
                if defensive_focus
                else "开辟防区外无人/有人协同的远域压制新赛道，为后续导弹和无人火力创造突防窗口"
            ),
            "strike_countermeasure_value": (
                "补链低空发现—识别—分层拦截并反转昂贵拦截弹对廉价无人机的成本劣势"
                if defensive_focus
                else "以多点空射、低空突防和新质压制载荷削弱对手预警、电子战与防空节点"
            ),
            "novelty": (
                "由单一拦截弹消耗转向成本感知的软硬杀伤协同"
                if defensive_focus
                else "从平台绑定的单一弹药转向可由有人/无人载机分布投送的模块化远域效应器"
            ),
            "development_path": (
                "近期完成多效应器火控接口联试，中期开展多方向饱和来袭和持续交战验证"
                if defensive_focus
                else "近期完成载荷模块、挂载接口和低空航路半实物验证，中期开展强扰与多层拦截条件下的体系级试验"
            ),
            "feasibility": 3,
            "horizon": "mid",
        },
    ]

    directions: list[dict[str, Any]] = []
    bounded_confidence = max(0.0, min(1.0, float(confidence)))
    for position, spec in enumerate(specs, start=1):
        row = dict(spec)
        row.update(
            {
                "priority": f"P{position}",
                "direct_evidence_refs": list(evidence),
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
                "confidence": bounded_confidence,
            }
        )
        if gap_basis:
            row["capability_gap"] = (
                f"{row['capability_gap']}；现有公开基线仅支持类别级判断：{gap_basis[:220]}"
            )
        portrait = (
            f"{row['name']}以{row['equipment_form']}为主要装备形态，面向“{query}”中的目标信息稀疏、"
            f"链路间歇和导航受扰阶段，直接承担{row['military_value']}。其作战运用概念是："
            f"{row['operational_mechanism']}。相对{row['baseline_system']}，重点补齐{row['capability_gap']}。"
            f"创新关系表现为{row['novelty']}；成熟度判断仅为{row['feasibility_basis']}。"
            f"对手可通过{row['adversary_adaptation']}反适应；{row['failure_boundary']}。"
            f"近期按{row['development_path']}推进，并以{common_verification}，未经校准不得承诺精确效能增量。"
        )
        row["capability_portrait"] = _complete_text(portrait, 600)
        directions.append(row)
    return directions
