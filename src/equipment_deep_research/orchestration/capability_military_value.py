from __future__ import annotations

from typing import Any, Mapping


_DIRECT_EFFECT_TERMS = (
    "打击",
    "猎歼",
    "歼灭",
    "拦截",
    "压制",
    "反制",
    "拒止",
    "威慑",
    "毁伤",
    "突防",
    "再打击",
    "火力",
    "火控",
    "猎获",
    "目标发现",
    "目标识别",
    "识别",
    "防护",
    "恢复",
    "压迫",
    "诱导",
    "再装填",
    "再战",
)

_EQUIPMENT_OBJECT_TERMS = (
    "导弹",
    "滑翔弹",
    "制导炸弹",
    "航空炸弹",
    "火箭弹",
    "雷达",
    "光电",
    "声呐",
    "无人",
    "无人僚机",
    "火控",
    "指挥",
    "C2",
    "ISR",
    "防空",
    "电子战",
    "舰",
    "艇",
    "机",
    "车",
    "平台",
    "节点",
    "系统",
    "载荷",
    "阵地",
    "拦截阵",
    "定向能",
    "激光武器",
    "高功率微波",
    "弹药",
    "拦截弹",
    "效应器",
    "发射单元",
    "终端",
)

_CONCRETE_WEAPON_TITLE_TERMS = (
    "导弹",
    "弹药",
    "巡飞弹",
    "滑翔弹",
    "制导炸弹",
    "航空炸弹",
    "火箭弹",
    "拦截弹",
    "鱼雷",
    "火炮",
    "无人机",
    "无人僚机",
    "无人艇",
    "无人潜航器",
    "火力车",
    "发射车",
    "发射单元",
    "拦截阵",
    "定向能",
    "激光武器",
    "高功率微波",
    "电子压制器",
    "效应器",
)

_GENERIC_DIRECTION_MARKERS = (
    "能力空白补位",
    "体系化快速制胜",
    "传统场景能力提升",
    "新作战样式适配",
    "体系贡献度",
)

_SUPPORT_ONLY_MARKERS = (
    "升级包",
    "套件",
    "保障包",
    "保障",
    "通信能力",
    "链路能力",
    "网关能力",
    "治理能力",
    "审计能力",
    "恢复装备族",
    "协同底座",
    "任务保持",
)


def _domain(topic: str) -> str:
    if any(term in topic for term in ("水下", "海底", "反水雷")):
        return "underwater"
    if any(term in topic for term in ("边境", "村镇", "丛林", "高原")):
        return "border"
    if any(term in topic for term in ("低空", "空情", "反无人")):
        return "low_altitude"
    if "无人协同" in topic or "无人集群" in topic:
        return "unmanned"
    if any(term in topic for term in ("通信", "链路", "低轨", "多源联通", "强扰")):
        return "contested_c2"
    if any(term in topic for term in ("补给", "维修", "保障", "基地支撑")):
        return "logistics"
    if any(term in topic for term in ("反介入", "岛链", "西太")):
        return "a2ad"
    if any(term in topic for term in ("边缘智能", "高消耗", "局部战争")):
        return "attrition"
    if any(term in topic for term in ("认知", "关键通道")):
        return "cognitive"
    if any(term in topic for term in ("南海", "南沙", "海上", "护航", "远海")):
        return "maritime"
    return "combined_arms"


_PROFILES: dict[str, dict[str, Any]] = {
    "underwater": {
        "new_name": "水下隐蔽目标多模态猎获与拦截指示能力",
        "upgrade_name": "现役水下光电/声呐节点弱目标猎获与反水雷处置升级",
        "new_form": "固定水下光电与声呐节点、磁异常传感器、机动UUV复核载荷和岸基拦截指示终端",
        "upgrade_form": "现役水下摄像/光学哨兵、声呐分类节点、边缘目标跟踪模块和反水雷任务终端",
        "baseline": "现役固定水下光电、声呐监视节点及反水雷UUV任务系统",
        "gap": "现役水下预警对浑浊、贴底慢速、诱饵和间歇目标的连续猎获、复核与拦截指示不足",
        "effect": "把弱线索转化为可供港防、反水雷和拦截力量使用的可信目标轨迹，压缩隐蔽接近窗口并提升清障与拒止效率",
        "mechanism": "以环境基线识别异常，以光电、声呐和磁异常交叉复核，再向港防火控或反水雷任务系统输出分级目标指示",
        "packages": ["低照与浑浊适配成像", "轨迹级异常识别", "声呐/UUV复核和拦截指示接口"],
    },
    "border": {
        "new_name": "边境低空渗透目标多源猎获与反无人压制引导能力",
        "upgrade_name": "现役边防雷达/光电节点低空目标猎获与反制火控升级",
        "new_form": "低空雷达、光电/红外、被动射频哨、短程无人侦察平台和反无人效应器协同任务系统",
        "upgrade_form": "现役边防雷达、光电塔、地面传感器、巡逻无人机和反无人火控终端",
        "baseline": "现役边防雷达、光电塔、固定视频节点和巡逻无人机任务系统",
        "gap": "现役边境感知难以把低空无人侦察、隐蔽渗透和诱饵线索快速转化为压制、拦截和通道封控任务",
        "effect": "缩短低空小目标与渗透分队从发现到压制处置的时间，提升关键通道反渗透、反无人拦截和前沿拒止威慑",
        "mechanism": "以固定节点建立常态基线，以无人机和被动射频补盲复核，并将可信目标直接推送反无人效应器与机动封控分队",
        "packages": ["低空多源探测融合", "边缘目标可信度与轨迹保持", "反无人火控和机动封控任务接口"],
    },
    "low_altitude": {
        "new_name": "近岸低空来袭目标分布式猎歼与要地拒止能力",
        "upgrade_name": "现役近程防空/反无人系统低慢小目标连续拦截升级",
        "new_form": "机动低空雷达、光电/射频探测哨、电子压制器、低成本拦截器和分布式火控节点",
        "upgrade_form": "现役近程防空、弹炮合一、反无人电子战和要地防护火控系统",
        "baseline": "现役近程防空、基地防护和反无人机分队任务系统",
        "gap": "现役要地防护对低慢小目标、诱饵与饱和来袭的持续发现、低成本拦截和战损接替不足",
        "effect": "提高低空目标连续猎获、软硬协同拦截和火力接替能力，保护指挥、机场、港口与火力节点并形成近岸拒止",
        "mechanism": "以分布式探测哨保持目标轨迹，按威胁和成本自动分配电子压制、近程火力与低成本拦截器，节点受损后由邻近单元接替",
        "packages": ["低慢小目标处理与敌我识别", "电子压制/弹炮/拦截弹火力分配", "战损后邻接火控与连续拦截"],
    },
    "unmanned": {
        "new_name": "断链无人集群自主猎歼与饱和突击协同能力",
        "upgrade_name": "现役无人平台分布式目标分配与协同攻击升级",
        "new_form": "异构无人机/无人艇任务群、边缘目标分配模块、协同突击载荷和有人监督火控终端",
        "upgrade_form": "现役无人机、无人艇、巡飞弹及其地面/舰载任务控制系统",
        "baseline": "现役无人平台及其任务控制、目标分配和载荷管理系统",
        "gap": "现役无人平台在断链、强扰和节点损失条件下难以保持目标分工、效应递进和协同攻击",
        "effect": "使无人集群在通信受压时仍能完成目标猎获、诱骗压制、饱和突击和重点目标毁伤，提高对高价值节点的反制与拒止效果",
        "mechanism": "预置任务边界与交战约束，由边缘节点根据目标价值、平台余量和损耗动态重组侦察、诱骗、压制和打击分队",
        "packages": ["断链任务包和目标分配", "异构平台协同攻击与载荷重构", "损耗后重组和有人监督火控"],
    },
    "contested_c2": {
        "new_name": "强扰断链条件分布式目标指示与连续火力协同能力",
        "upgrade_name": "现役战术指挥/火控系统抗扰任务授权与再打击升级",
        "new_form": "低特征分布式指挥火控节点、被动目标指示终端、低带宽任务包和机动火力接替单元",
        "upgrade_form": "现役战术指挥所、火控席位、ISR任务终端和多路径战术数据链",
        "baseline": "现役战术指挥、ISR目标指示、火力任务分发和战损回报系统",
        "gap": "现役体系在强干扰、节点毁伤和断续联网条件下难以维持目标指示、任务授权、火力协同与再次组织",
        "effect": "在中心节点受损和链路受压时保持关键目标指示、火力授权与再打击节奏，降低电子压制对打击歼灭和区域拒止的削弱",
        "mechanism": "把目标摘要、效应约束和授权条件压缩为可验证任务包，由分布式节点保存局部任务状态并接替火力分配与战损再组织",
        "packages": ["低带宽目标与火力任务包", "离线授权认证和局部火控接替", "多路径切换与战损后再打击重组"],
    },
    "logistics": {
        "new_name": "远海分散补给节点反袭扰拦截与火力再生能力",
        "upgrade_name": "现役补给舰/维修保障平台反无人拦截与战损再战升级",
        "new_form": "低特征分散补给节点、无人短驳平台、近区反无人/反小艇火力和弹药快速再装填单元",
        "upgrade_form": "现役补给舰、维修保障舰、前沿油弹节点及其近区防护和任务调度系统",
        "baseline": "现役补给舰、维修保障舰和前沿油弹/备件保障节点",
        "gap": "现役补给维修体系在低空袭扰、小艇威胁、远程打击和节点暴露条件下缺少自防拦截、分散续接与火力快速再生能力",
        "effect": "保护补给窗口和维修节点，缩短弹药、能源与关键装备恢复时间，使火力单元在受袭后保持再装填、再出动和持续压制能力",
        "mechanism": "把分散缓存、无人短驳、近区反无人拦截和战损维修排序组合成火力再生链，避免补给节点被打击后形成战役火力空窗",
        "packages": ["补给窗口低空/小艇探测拦截", "无人短驳与低特征分散缓存", "弹药再装填和战损装备快速再战"],
    },
    "a2ad": {
        "new_name": "岛链远程目标猎获与多域饱和打击协同能力",
        "upgrade_name": "现役岸舰远程火力系统抗毁目标指示与连续拒止升级",
        "new_form": "海空天电多源传感节点、远程反舰/对陆效应器、电子压制载荷和分布式火力任务系统",
        "upgrade_form": "现役岸基反舰导弹、舰载远程火力、海空ISR和联合火控系统",
        "baseline": "现役岸基反舰、舰载远程火力、海空ISR与联合指挥火控体系",
        "gap": "现役反介入体系在目标链受扰、前沿节点毁伤和对手分布式机动条件下的连续猎获、效应叠加和再打击不足",
        "effect": "保持对航母编队、远征基地和关键海空节点的远程目标猎获、电子压制与饱和打击能力，提升区域拒止和威慑可信度",
        "mechanism": "以多源传感交叉确认高价值目标，动态组合电子压制、诱骗和远程火力，并通过分布式节点维持打击后评估与再次攻击",
        "packages": ["抗欺骗远程目标融合", "电子压制与远程火力协同", "节点毁伤后的目标链接替和再打击"],
    },
    "attrition": {
        "new_name": "高消耗战场边缘自主目标猎获与火力重组能力",
        "upgrade_name": "现役侦察火控平台边缘识别、毁伤评估与再打击升级",
        "new_form": "可消耗无人侦察平台、边缘目标识别节点、低成本效应器和战损后火力重组终端",
        "upgrade_form": "现役营旅侦察无人机、火控终端、巡飞弹/精确弹药和毁伤评估系统",
        "baseline": "现役营旅侦察、火控、无人平台和毁伤评估任务系统",
        "gap": "现役体系在高损耗、强电磁和快速战法迭代条件下难以低成本持续完成目标猎获、毁伤评估和再次打击",
        "effect": "用可消耗侦察与边缘火控维持发现—打击—评估—再打击循环，提升对暴露目标的歼灭效率并降低高价值平台损耗",
        "mechanism": "将目标识别和火力排序前推到边缘节点，以可消耗平台持续补充传感与效应，并依据毁伤结果快速重组下一轮打击",
        "packages": ["边缘目标识别与火力排序", "可消耗无人侦察/效应平台", "毁伤评估回灌和再打击重组"],
    },
    "cognitive": {
        "new_name": "关键通道灰区目标识别、拦截阈值与威慑节奏控制能力",
        "upgrade_name": "现役海空监视系统异常目标猎获与拒止决策升级",
        "new_form": "海空目标可信度工作站、灰区行为识别模型、拦截阈值决策终端和威慑行动编排系统",
        "upgrade_form": "现役海空雷达、AIS/航迹融合、无人ISR和联合值班指挥系统",
        "baseline": "现役海空监视、航迹融合、异常告警和联合值班决策系统",
        "gap": "现役体系对灰区混编、航迹欺骗和低烈度越线的目标归因、拦截阈值与威慑节奏控制不足",
        "effect": "提高异常目标识别和行动归因可信度，支撑分级拦截、拒止展示与升级控制，压缩对手利用模糊空间实施试探的收益",
        "mechanism": "融合平台身份、航迹行为、频谱异常和任务背景，形成可解释的威胁等级，并将证据强度映射到跟监、驱离、拦截和威慑行动",
        "packages": ["异常航迹与混编行为识别", "证据可信度和拦截阈值评估", "拒止行动与威慑节奏编排"],
    },
    "maritime": {
        "new_name": "海空多源目标猎获、火力分配与拦截协同能力",
        "upgrade_name": "现役岸舰雷达/光电与火控系统远距识别和联合打击升级",
        "new_form": "岸舰雷达/光电、海空无人平台、电子支援载荷、联合火控终端和低成本拦截效应器",
        "upgrade_form": "现役岸基雷达、舰艇作战系统、海上巡逻机和近程防空/反无人火控系统",
        "baseline": "现役岸舰传感器、海上巡逻ISR、舰艇作战系统和近区防御火控体系",
        "gap": "现役海空协同对远距低特征目标、诱骗污染和多方向袭扰的连续识别、火力分配与低成本拦截不足",
        "effect": "缩短海空目标从发现到火力分配和拦截的时间，提升对无人机、小艇、暗船和远距威胁的猎歼、反制与海域拒止能力",
        "mechanism": "以岸舰机多源轨迹交叉验证目标身份，按威胁、射界和弹药成本分配电子压制、近区拦截与远程火力，并持续回灌毁伤评估",
        "packages": ["海空多源目标可信融合", "跨平台火力分配与交战排序", "低成本拦截和毁伤评估回灌"],
    },
    "combined_arms": {
        "new_name": "多域目标猎获、效应分配与持续打击协同能力",
        "upgrade_name": "现役侦察火控系统目标发现、反制与再打击升级",
        "new_form": "多源传感节点、联合火控终端、电子压制载荷和远近程效应器协同任务系统",
        "upgrade_form": "现役侦察预警、指挥火控、电子战和打击平台任务系统",
        "baseline": "现役侦察预警、指挥火控、电子战与打击平台体系",
        "gap": "现役体系对复杂目标的连续猎获、跨域效应分配和战损后再打击不足",
        "effect": "提升目标发现、火力分配、压制反制和持续打击能力，使分散平台能够围绕同一高价值目标形成可验证作战效果",
        "mechanism": "以多源目标可信度驱动效应器选择，并在节点损失和链路受压时保存任务状态、接替火力控制与组织再次打击",
        "packages": ["多源目标可信融合", "跨域效应分配和火力控制", "战损接替与再打击重组"],
    },
}


def military_capability_profile(topic: str, route: str = "") -> dict[str, Any]:
    del route
    return dict(_PROFILES[_domain(str(topic or ""))])


def needs_military_capability_rewrite(row: Mapping[str, Any]) -> bool:
    name = str(row.get("name", "")).strip()
    if not name:
        return True
    if any(marker in name for marker in _GENERIC_DIRECTION_MARKERS):
        return True
    if name.startswith(("方向一", "方向二", "方向三", "方向四", "方向五")):
        return True
    effect_count = sum(term in name for term in _DIRECT_EFFECT_TERMS)
    has_object = any(term.lower() in name.lower() for term in _EQUIPMENT_OBJECT_TERMS)
    if any(marker in name for marker in _SUPPORT_ONLY_MARKERS) and effect_count < 2:
        return True
    # A weapon title can be a valid equipment-development object without an
    # explicit effect verb.  ``岛链远程多模制导弹药`` is already more concrete
    # than the old A2/AD fallback slogan; rewriting it to a domain-wide
    # ``...协同能力`` regresses both specificity and the S6 title contract.
    if any(term in name for term in _CONCRETE_WEAPON_TITLE_TERMS) and not name.endswith(
        ("能力", "体系", "架构", "网络", "协同")
    ):
        return False
    if effect_count:
        return False
    if has_object and any(
        term in name
        for term in (
            "目标",
            "航迹",
            "战损",
            "蜂群",
            "低空",
            "水下",
            "电子战",
            "防空",
            "ISR",
            "C2",
            "欺骗",
            "诱骗",
        )
    ):
        return False
    return True


def _specialized_upgrade(
    original_name: str,
    default_name: str,
    default_form: str,
) -> tuple[str, str]:
    if any(term in original_name for term in ("反蜂群", "反规模化无人", "分层防护")):
        return (
            "现役近程防空/电子战系统反蜂群分层拦截升级",
            "现役近程防空、电子战、反无人火控和低成本拦截系统",
        )
    if any(term in original_name for term in ("再装订", "无人保障", "补给节点")):
        return (
            "现役无人作战平台弹药能源再装填与连续突击升级",
            "现役无人机/无人艇、任务载荷、弹药能源再装填和地面/舰载控制系统",
        )
    if any(term in original_name for term in ("C2", "COMMEX", "通信", "链路", "低轨")):
        return (
            "现役战术指挥/火控系统抗扰目标分配与再打击升级",
            "现役战术指挥所、无人任务控制站、ISR终端和多路径战术数据链",
        )
    if "价值评估" in original_name:
        return (
            "现役远程火力体系高价值目标排序与打击决策升级",
            "现役ISR融合、目标价值评估、远程火力任务规划和联合火控系统",
        )
    if any(term in original_name for term in ("快修", "快迭代", "侦察-评估")):
        return (
            "现役无人侦察/巡飞弹毁伤评估与快速再打击升级",
            "现役营连侦察无人机、巡飞弹、毁伤评估和快速再出动任务系统",
        )
    return default_name, default_form


def rewrite_capability_for_military_value(
    row: Mapping[str, Any],
    *,
    topic: str,
    route: str = "",
    force: bool = False,
) -> dict[str, Any]:
    result = dict(row)
    rewrite_name = needs_military_capability_rewrite(result)
    if not rewrite_name and not force:
        return result

    profile = military_capability_profile(topic, route)
    upgrade = str(result.get("capability_type", "")) == "upgrade"
    original_name = str(result.get("name", "")).strip()
    name = profile["upgrade_name" if upgrade else "new_name"]
    equipment_form = profile["upgrade_form" if upgrade else "new_form"]
    if force and not rewrite_name:
        name = original_name
        equipment_form = str(
            result.get("equipment_form") or result.get("equipment_category") or equipment_form
        )
    elif upgrade:
        name, equipment_form = _specialized_upgrade(
            original_name,
            str(name),
            str(equipment_form),
        )
    elif "保障与战损恢复" in original_name:
        name = "战损条件分布式火力再生与持续打击能力"
        equipment_form = "分布式弹药/能源节点、无人短驳平台、战损抢修单元和火力再出动控制终端"
    elif "C2" in original_name and "底座" in original_name:
        name = "强扰断链条件分布式目标指示与连续火力协同能力"
        equipment_form = "低特征分布式指挥火控节点、被动目标指示终端、低带宽任务包和机动火力接替单元"
    elif "战损再组织" in original_name:
        name = "低特征分布式火力节点战损接替与持续打击能力"
        equipment_form = "机动火力节点、低特征目标指示终端、战损接替控制器和快速再装填单元"
    effect = profile["effect"]
    mechanism = profile["mechanism"]
    gap = profile["gap"]
    original_gap = str(result.get("capability_gap", ""))
    if "；本次基线：" in original_gap:
        gap = f"{gap}；本次基线：{original_gap.split('；本次基线：', 1)[1]}"

    existing_source_logic = str(result.get("source_winning_logic", "")).strip()
    existing_mission_effect = str(
        result.get("mission_effect") or result.get("military_utility") or ""
    ).strip()
    existing_novelty = str(result.get("novelty", "")).strip()
    existing_foresight = str(result.get("foresight", "")).strip()
    existing_development_path = str(result.get("development_path", "")).strip()

    def has_direct_effect(value: str) -> bool:
        return any(term in value for term in _DIRECT_EFFECT_TERMS)

    mission_effect = (
        existing_mission_effect
        if has_direct_effect(existing_mission_effect)
        else effect
    )
    countermeasure = mechanism
    operational_mechanism = mechanism
    source_logic = existing_source_logic
    if not has_direct_effect(source_logic) or any(
        marker in source_logic for marker in _GENERIC_DIRECTION_MARKERS
    ):
        source_logic = "作战对象与失败窗口 → 目标猎获/火力分配断点 → 直接打击或反制效果 → 装备能力方向"

    result.update(
        {
            "name": name,
            "equipment_category": equipment_form,
            "equipment_form": equipment_form,
            "source_winning_logic": source_logic,
            "capability_gap": gap,
            "mission_effect": mission_effect,
            "military_utility": mission_effect,
            "strike_countermeasure_value": countermeasure,
            "operational_mechanism": operational_mechanism,
            "capability_image": f"形成{name}，以{equipment_form}为主要装备形态。{mechanism}。直接作战效果为：{effect}。",
            "novelty": existing_novelty
            or "把目标可信度、效应器选择、战损接替和再次攻击组织为同一任务机制，避免把支撑性通信、保障或接口单列为能力终点。",
            "foresight": existing_foresight
            or "面向未来3至10年低成本无人化、强电子对抗、节点猎杀和分布式作战演化，按对手反适应与失效注入结果滚动调整优先级。",
            "development_path": existing_development_path
            or "近期完成现役武器、无人平台、传感/火控与任务载荷改装，中期形成无人作战平台、导弹/弹药或拦截效应器样机并开展体系集成，最终通过实弹、红蓝对抗和失效注入验证；未达到任务级毁伤或反制门槛时转入新型号研制。",
        }
    )
    portrait = (
        f"面向“{topic}”，该方向不以一般体系补位、通信连续或保障可用作为最终目标，而以{name}作为装备建设终点。"
        f"决定性问题是：{gap.split('；本次基线：', 1)[0]}。武器装备发展落点由{equipment_form}构成，优先明确无人作战平台、导弹/弹药、拦截器或电子压制效应器的型号化路径。"
        f"其作战机理是{mechanism}。由此可直接{effect}。"
        "该方向应在危机升级、强扰断链、节点损失和高节奏对抗条件下验证，重点考察目标轨迹保持、火力任务送达、拦截或毁伤闭合、战损后接替和再次攻击组织；"
        "若只能改善信息连通、保障效率或界面互操作，却不能稳定提高目标发现、火力分配、拦截毁伤、压制反制或拒止威慑效果，则不得作为独立能力方向。"
        "公开证据只用于约束威胁趋势、装备基线和工程边界，具体性能阈值仍须通过仿真、半实物联试、红蓝对抗演训和失效注入校准。"
    )
    result["deep_capability_portrait"] = portrait

    if upgrade:
        result["baseline_system"] = str(result.get("baseline_system", "")).strip() or profile["baseline"]
        result["upgrade_package"] = list(profile["packages"])
        result["combat_effect_uplift"] = (
            str(result.get("combat_effect_uplift", "")).strip() or effect
        )
        result["strike_chain_contribution"] = (
            str(result.get("strike_chain_contribution", "")).strip() or mechanism
        )
        result["upgrade_boundary"] = str(result.get("upgrade_boundary", "")).strip() or (
            "现役平台余量、传感/火控接口和任务软件可承载时优先升级；若无法支撑目标级闭环、效应器接入或战损接替，则转入新装备研发。"
        )
    return result
