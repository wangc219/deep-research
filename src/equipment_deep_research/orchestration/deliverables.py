"""Branch-aware final delivery artifacts and narrative agent analysis."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
import re
from typing import Any

from equipment_deep_research.domain.models import CapabilityImageItem, to_plain
from equipment_deep_research.domain.store import DomainStore


BRANCH_DELIVERABLE_PROFILES: dict[str, dict[str, Any]] = {
    "A": {
        "name": "新战法发现",
        "required_sections": ["战法概念集", "装备能力需求图像", "关联装备形态建议"],
        "targets": {
            "tactic_concepts": 3,
            "tactic_combinations": 5,
            "capability_domains": 8,
            "capability_indicators": 30,
        },
        "product_keys": [
            "tactic_concepts",
            "tactic_combinations",
            "capability_domains",
            "capability_indicators",
            "equipment_forms",
        ],
    },
    "B": {
        "name": "传统能力缺口发现",
        "required_sections": ["需求卡片", "能力全景图", "深度研究报告（含推理链可回溯）"],
        "targets": {},
        "product_keys": ["demand_cards", "capability_panorama", "reasoning_traceability"],
    },
    "C": {
        "name": "局部战争案例经验",
        "required_sections": ["案例规律报告", "未来场景预测", "装备需求图像"],
        "targets": {
            "case_patterns": 6,
            "future_scenarios": 3,
            "emerging_equipment_categories": 4,
        },
        "product_keys": [
            "case_patterns",
            "future_scenarios",
            "emerging_equipment_categories",
        ],
    },
    # D–H 分支按架构文档"视情况综合考虑类似输出"：在各自专题章节之外，
    # 统一交付结构化"装备能力需求图像（需求卡片）"，与 A/B/C 的需求图像产物对齐。
    "D": {
        "name": "技术驱动发现",
        "required_sections": ["技术机会谱系", "成熟度与颠覆场景", "技术牵引装备形态", "装备能力需求图像（需求卡片）"],
        "targets": {},
        "product_keys": ["technology_opportunities", "future_scenarios", "equipment_forms", "demand_cards"],
    },
    "E": {
        "name": "对手动向牵引发现",
        "required_sections": ["对手变化规律", "威胁形成场景", "对冲能力与装备建议", "装备能力需求图像（需求卡片）"],
        "targets": {},
        "product_keys": ["threat_patterns", "future_scenarios", "capability_domains", "equipment_forms", "demand_cards"],
    },
    "F": {
        "name": "体系对抗博弈发现",
        "required_sections": ["体系脆弱性规律", "级联失效场景", "补链强链能力组合", "装备能力需求图像（需求卡片）"],
        "targets": {},
        "product_keys": ["system_vulnerabilities", "future_scenarios", "capability_domains", "equipment_forms", "demand_cards"],
    },
    "G": {
        "name": "跨域融合发现",
        "required_sections": ["跨域缝隙图谱", "协同模式组合", "接口与装备形态建议", "装备能力需求图像（需求卡片）"],
        "targets": {},
        "product_keys": ["cross_domain_gaps", "tactic_combinations", "capability_indicators", "equipment_forms", "demand_cards"],
    },
    "H": {
        "name": "非传统安全牵引",
        "required_sections": ["新型威胁画像", "高置信场景", "韧性与非致命装备需求", "装备能力需求图像（需求卡片）"],
        "targets": {},
        "product_keys": ["emerging_threat_profiles", "future_scenarios", "capability_domains", "equipment_forms", "demand_cards"],
    },
}

# 结构化交付产物：出现在分支 product_keys 中即注入对应对象并落盘为独立 JSON。
STRUCTURED_PRODUCT_KEYS = ("demand_cards", "capability_panorama", "reasoning_traceability")


REPORT_QUALITY_DIMENSIONS = {
    "领域属性符合性": "持续符合当前Query确定的具体军事装备领域；无人、低空、远程和精确打击仅在Query明确涉及时作为领域锚点，通信、C2、保障和工程只能作为具体武器装备的内部依赖。",
    "装备能力图像": "逐项保留动态组合中证据闭环的具体直接战斗武器，给出差异化指标画像、军事作战流程、直接战果和装备谱系位置；数量不设固定配额。",
    "制胜效能": "分别证明现役效能跃升、传统赛道跨代优势和新概念赛道开辟，并给出可校准效能方向。",
    "创新性": "说明相对现役基线改变的作战关系、对手反适应和失效边界，创新必须落实到具体装备。",
    "可实现性（成熟度）": "逐项给出核心技术点、成熟度、工程瓶颈、证据边界和验证条件，禁止把推断写成既成能力。",
}


BRANCH_REPORT_CONTRACTS: dict[str, dict[str, str]] = {
    "A": {
        "thesis": "从作战矛盾和制胜窗口出发，论证新战法如何改变发现、决策、机动、打击、评估和再组织链路，再把战法组合映射为能力域、指标和装备形态。",
        "military_test": "重点检验能否压缩对方反应窗口、扩大己方行动自由、形成多域协同打击或反制优势，并说明对手适应后机制是否仍成立。",
        "future_test": "区分近期可由现役体系组合形成的战法增量与中长期依赖新型平台、智能协同或任务网络的新机制。",
    },
    "B": {
        "thesis": "以现有任务链和装备基线为参照，定位在具体对抗条件下会导致任务失败或效能骤降的能力缺口，再论证升级与新研边界。",
        "military_test": "重点说明缺口如何削弱探测、指挥、突防、打击、抗毁、保障或持续作战能力，以及补齐后能够恢复哪一段任务效果。",
        "future_test": "避免把公开资料未覆盖等同于能力空白，结合成熟度、接口余量和未来威胁演化确定建设时序。",
    },
    "C": {
        "thesis": "从局部战争的具体条件、行动过程和结果中提炼因果规律，区分可迁移机制与特定战场偶然因素，再推演未来场景和装备需求。",
        "military_test": "重点解释装备与战法如何共同改变杀伤链、生存力、消耗交换、保障节奏和战场适应速度，而不是复述战例现象。",
        "future_test": "每项迁移判断都要给出适用前提、对手反适应、技术扩散和未来失效边界。",
    },
    "D": {
        "thesis": "从技术成熟度和可集成条件出发，证明技术如何改变任务机制与体系关系，再形成可验证的装备机会，而不是从技术名词直接跳到装备概念。",
        "military_test": "重点检验技术能否带来探测、决策、打击、抗扰、机动、保障或成本交换上的任务级跃迁。",
        "future_test": "明确技术成熟窗口、工程瓶颈、对抗性失效模式以及现役改装与全新装备形态的分界。",
    },
    "E": {
        "thesis": "沿对手能力形成链分析部署、训练、装备、组织和运用变化，判断其将如何重塑威胁场景，再反推可持续对冲能力。",
        "military_test": "重点说明己方如何降低对手侦察、决策、突防、打击或体系压制效果，并保持反制后的任务续接能力。",
        "future_test": "区分已形成威胁、正在形成能力和低置信预警信号，给出触发建设升级的观测指标。",
    },
    "F": {
        "thesis": "围绕体系节点、链路和资源依赖识别级联失效机理，论证补链、强链、替代链和快速重构能力如何改变体系对抗结果。",
        "military_test": "重点评估在关键节点受压、通信降级或保障中断时，体系能否维持打击、反制和任务闭环，而非追求单个平台峰值。",
        "future_test": "考虑对手绕开单点加固后的二次适应，验证能力组合是否具备分布式、可替换和动态重构特征。",
    },
    "G": {
        "thesis": "从跨域任务中的数据、时间、权限、接口和火力协同缝隙出发，证明融合机制如何把分散能力转化为联合任务效果。",
        "military_test": "重点说明跨域协同能否提高目标发现与处置连续性、缩短杀伤链并降低重复配置和协同摩擦。",
        "future_test": "明确异构协议、数据可信、低带宽、权限边界和多域降级运行条件下的可用范围。",
    },
    "H": {
        "thesis": "从新型威胁的扩散路径、任务冲击和治理约束出发，形成兼顾军事任务、韧性保障和非致命处置的装备能力需求。",
        "military_test": "重点说明能力如何保护关键任务、人员和基础设施，限制威胁扩散，并在规则约束下保持可控反制效果。",
        "future_test": "同步考虑威胁变异、技术滥用、法律伦理和军地协同边界，避免把短期应急手段固化为长期装备方向。",
    },
}


BRANCH_WRITER_OUTLINES: dict[str, dict[str, Any]] = {
    "A": {
        "title": "新作战战法发现深度研究报告",
        "target_chars": "5200-7600",
        # The target range is editorial guidance only. Complete arguments,
        # governed capability portraits and verification matrices must never
        # be shortened merely to satisfy a character budget.
        "hard_max_chars": 0,
        "sections": [
            "作战矛盾、制胜窗口与现有战法基线",
            "战法概念集：3种新战法",
            "战法组合：5种组合",
            "装备能力需求图像：8大能力域与30项能力指标",
            "关联装备形态、建设时序与验证边界",
        ],
        "mandatory_content": [
            "3种新战法逐项说明任务链机制、相对现有基线的实质变化、军事运用价值、对手反适应与证据边界",
            "5种战法组合逐项说明组合关系、适用场景、形成的打击/反制/拒止/威慑效果及失效条件",
            "8大能力域必须形成相互耦合的能力体系，不得只是技术名词并列",
            "30项能力指标必须分配到8个能力域，使用任务级、可验证口径，不得编造具体作战参数",
            "装备形态建议必须由战法和能力需求反推，并区分现役升级、近期新研和中长期预研",
        ],
    },
    "B": {
        "title": "传统能力缺口与武器装备能力需求深度研究报告",
        "target_chars": "4200-6500",
        "hard_max_chars": 0,
        "sections": [
            "现役任务链基线与决定性能力缺口",
            "武器装备能力需求卡片",
            "能力全景图与跨域耦合关系",
            "打击、反制、抗毁与持续作战价值",
            "建设优先序、推理链回溯与验证边界",
        ],
        "mandatory_content": [
            "需求卡片必须以与query直接匹配的具体待发展武器装备为主对象，优先形成无人作战平台、导弹/精确弹药、拦截弹、火炮、定向能或电子压制效应器等歼灭、打击、拒止和威慑装备；同时覆盖装备构型、关键指标、优先级、支撑场景和证据链",
            "能力全景图必须解释能力之间的依赖、替代、放大和共同失效关系，而非再次列卡片",
            "区分现役改装可补齐、需新装备形成和非装备措施约束，给出近期至中长期建设时序",
            "深度正文必须融合多源业务研判、六步效果链、能力映射和差距判断，保留反证与不确定性",
        ],
    },
    "C": {
        "title": "局部战争案例经验与未来装备需求深度研究报告",
        "target_chars": "5000-7200",
        "hard_max_chars": 0,
        "sections": [
            "战例事实边界、关键决策与因果链综合",
            "案例规律报告：6条核心规律",
            "未来场景预测：3类高置信场景",
            "装备需求图像：4大新兴装备类别",
            "迁移边界、对手适应与验证路径",
        ],
        "mandatory_content": [
            "6条规律逐项说明成立条件、行动机制、结果、跨案例共性、不可迁移因素和证据边界",
            "3类未来场景逐项说明触发信号、对抗形态演化、关键任务压力、军事价值、对手适应和置信度",
            "4大新兴装备类别必须由案例规律与未来场景共同反推，说明任务形态、能力组合、现役替代关系和验证路径",
            "不得把战例现象复述为规律，也不得把单一案例经验无条件外推到未来战争",
        ],
    },
    "D": {
        "title": "技术驱动与未来装备机会深度研究报告",
        "target_chars": "4200-6500",
        "hard_max_chars": 0,
        "sections": [
            "技术驱动源与任务机制变化",
            "技术机会谱系、成熟度与可集成条件",
            "颠覆场景、对抗失效与未来窗口",
            "技术牵引装备形态与能力需求卡片",
            "工程瓶颈、建设时序与验证路径",
        ],
        "mandatory_content": [
            "技术机会必须从任务链变化和体系关系变化中推导，不得把前沿技术名词直接包装成装备需求",
            "区分可由现役平台升级吸收、需要新研装备形成和只适合中长期预研的方向，并说明成熟窗口",
            "说明技术对探测、决策、打击、反制、抗扰、机动或保障效率的任务级增益及对手反适应后的失效模式",
            "装备建议按证据和成熟度收敛为少量优先方向，形成能力指标、工程瓶颈和可证伪验证路径",
        ],
    },
    "E": {
        "title": "对手动向牵引与对冲装备需求深度研究报告",
        "target_chars": "4200-6500",
        "hard_max_chars": 0,
        "sections": [
            "对手能力形成链与决定性变化",
            "威胁形成场景、预警信号与时间窗口",
            "对冲机理、反制窗口与制衡效果",
            "对冲能力需求图像与装备建议",
            "建设触发、升级阈值与验证边界",
        ],
        "mandatory_content": [
            "区分已经形成的能力、正在形成的能力和低置信预警信号，不得把计划、演示或单点部署等同成熟威胁",
            "沿对手侦察、决策、突防、打击和体系压制链定位可被削弱、延迟、欺骗或拒止的关键环节",
            "装备需求必须说明能够降低何种威胁效果、保持哪段任务续接能力以及对手二次适应后的剩余价值",
            "以可观测触发指标决定现役升级、新装备研制和预研储备的启动或降级时机",
        ],
    },
    "F": {
        "title": "体系对抗、级联失效与补链强链深度研究报告",
        "target_chars": "4200-6500",
        "hard_max_chars": 0,
        "sections": [
            "体系边界、关键节点与资源依赖链",
            "体系脆弱性规律与级联失效场景",
            "补链、强链、替代链与快速重构组合",
            "体系装备能力需求图像与需求卡片",
            "压力测试、建设优先序与验证边界",
        ],
        "mandatory_content": [
            "识别节点、链路、数据、权限、能源和保障之间的共同失效关系，不以单个平台峰值替代体系效果",
            "解释关键节点受压后如何导致感知、指挥、打击、反制或保障链级联退化，以及何种替代链能够止损",
            "能力组合必须体现分布式、可替换、可降级和动态重构机制，并考虑对手绕开加固点后的二次失效",
            "需求卡片和建设排序应由体系压力测试反推，明确近期补丁式升级与中长期体系重构边界",
        ],
    },
    "G": {
        "title": "跨域融合、接口闭合与联合任务效能深度研究报告",
        "target_chars": "4200-6500",
        "hard_max_chars": 0,
        "sections": [
            "跨域任务链与决定性协同缝隙",
            "协同模式组合与联合制胜机制",
            "数据、权限、接口与弱网运行条件",
            "接口装备形态与能力需求卡片",
            "降级运行、建设优先序与验证路径",
        ],
        "mandatory_content": [
            "从数据、时间、权限、接口和火力协同缝隙解释分散能力为何不能自动形成联合任务效果",
            "协同模式必须说明如何提高发现和处置连续性、缩短任务链、降低协同摩擦并保持受压后的任务续接",
            "明确异构协议、数据可信、跨密域释放、低带宽和权限限制下的最低可用机制与失效边界",
            "装备建议重点形成网关、任务网络、边缘节点或接口升级等少量方向，并用降级运行试验验证军事收益",
        ],
    },
    "H": {
        "title": "非传统安全威胁与韧性装备需求深度研究报告",
        "target_chars": "4200-6500",
        "hard_max_chars": 0,
        "sections": [
            "新型威胁画像、扩散路径与任务冲击",
            "高置信场景、触发信号与演化窗口",
            "关键任务、人员与基础设施韧性机制",
            "非致命反制与装备能力需求图像",
            "军地协同、规则约束与验证边界",
        ],
        "mandatory_content": [
            "威胁画像必须解释扩散机制、任务冲击和跨域耦合，不得只罗列风险类型",
            "场景预测应给出高置信触发信号、可能演化、关键任务压力和能力失效条件",
            "装备需求同时考虑保护关键任务、限制威胁扩散、恢复基础设施和实施可控非致命反制的实际效果",
            "明确法律伦理、技术滥用、军地协同和规则约束，避免将短期应急手段直接固化为长期装备方向",
        ],
    },
}


AGENT_LABELS = {
    "international_situation": "国际形势、威胁演化与预警信号",
    "combat_scenario": "作战场景、任务压力与关键窗口",
    "weapon_equipment": "装备基线、技术成熟度与能力差距",
    "operational_employment": "作战运用、任务链与体系协同",
    "case_research": "战例因果规律与迁移边界",
    "technology_radar": "技术机会、成熟度与颠覆潜力",
    "opponent_monitoring": "对手变化、能力形成与对冲需求",
    "system_confrontation": "体系依赖、级联脆弱性与补链强链",
    "cross_domain_fusion": "跨域缝隙、接口与协同条件",
    "nontraditional_security": "新型威胁、韧性需求与法律边界",
    "scenario_divergence": "候选场景、竞争假设与边界条件",
}


def branch_profile(branch: str) -> dict[str, Any]:
    return BRANCH_DELIVERABLE_PROFILES.get(branch, BRANCH_DELIVERABLE_PROFILES["A"])


def branch_report_contract(branch: str) -> dict[str, str]:
    return BRANCH_REPORT_CONTRACTS.get(branch, BRANCH_REPORT_CONTRACTS["A"])


def branch_writer_brief(branch: str) -> dict[str, Any]:
    profile = branch_profile(branch)
    outline = BRANCH_WRITER_OUTLINES.get(branch)
    if outline is None:
        outline = {
            "title": f"{profile['name']}深度研究报告",
            "target_chars": "2600-3800",
            "hard_max_chars": 0,
            "sections": list(profile["required_sections"]),
            "mandatory_content": [
                "按当前分支驱动源解释事实基线、因果机制、军事运用价值和未来演化",
                "把规律、场景、能力需求、指标与装备形态连接为连续论证，不得只罗列结构化字段",
                "数量只服从证据与分支产物，缺口必须披露，不得用同义改写凑数",
            ],
        }
    return {
        "branch": branch,
        "branch_name": profile["name"],
        "title": outline["title"],
        "target_chars": outline["target_chars"],
        "hard_max_chars": int(outline.get("hard_max_chars", 0) or 0),
        "required_sections": list(outline["sections"]),
        "mandatory_content": list(outline["mandatory_content"]),
        "target_counts": dict(profile.get("targets", {})),
        "report_contract": branch_report_contract(branch),
    }


def build_delivery_artifacts(
    *,
    topic: str,
    branch: str,
    blueprint: Mapping[str, Any] | None,
    store: DomainStore,
    convergence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    profile = branch_profile(branch)
    branch_products = _branch_products(store, convergence=convergence)
    if branch == "A":
        branch_products = _supplement_a_branch_products(
            branch_products,
            images=list(store.capability_images.values()),
        )
    elif branch in {"D", "E", "F", "G", "H"}:
        branch_products = _supplement_specialized_branch_products(
            branch,
            branch_products,
            images=list(store.capability_images.values()),
        )
    demand_cards = [_demand_card(image) for image in store.capability_images.values()]
    panorama = _capability_panorama(
        topic=topic,
        branch=branch,
        profile=profile,
        images=list(store.capability_images.values()),
        branch_products=branch_products,
    )
    traceability = _reasoning_traceability(store)
    branch_output = _branch_output(
        branch=branch,
        profile=profile,
        blueprint=blueprint or {},
        branch_products=branch_products,
        demand_cards=demand_cards,
        panorama=panorama,
        traceability=traceability,
    )
    return {
        "demand_cards": demand_cards,
        "capability_panorama": panorama,
        "reasoning_traceability": traceability,
        "branch_deliverables": branch_output,
        "branch_report_contract": branch_report_contract(branch),
        "branch_writer_brief": branch_writer_brief(branch),
        "intermediate_agent_analysis": render_intermediate_agent_analysis(
            topic=topic,
            branch=branch,
            store=store,
        ),
    }


_A_CAPABILITY_DOMAIN_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("战役纵深覆盖与远程投送", ("远程", "纵深", "射程", "防区外")),
    ("低空突防与任务区持续存在", ("低空", "巡飞", "驻留", "任务区")),
    ("精确制导与末段目标复核", ("精确", "末段", "光电", "导引", "复核")),
    ("受扰导航与断链任务自主", ("导航", "断链", "通信受限", "自主", "失联")),
    ("短时敏感目标猎歼与压制", ("短窗", "时间敏感", "猎歼", "反辐射", "压制")),
    ("直接毁伤与效果评估补杀", ("毁伤", "战斗部", "再打击", "补杀", "效果评估")),
    ("分布式发射与多轴规模齐射", ("分布式", "多轴", "齐射", "并发", "多联装")),
    ("低成本批产与库存补充韧性", ("低成本", "批产", "规模", "供应链", "补库", "库存")),
)


def _supplement_a_branch_products(
    products: Mapping[str, Any],
    *,
    images: list[CapabilityImageItem],
) -> dict[str, list[str]]:
    """Project a complete dynamic portfolio into the legacy A-branch envelope.

    Dynamic winning runs can produce a valid 5--7 item portfolio without the
    older ``branch_products`` wrapper.  This adapter derives only evaluation
    directions and prose already present in accepted capability images.  It
    does not create extra equipment candidates or performance claims.
    """

    merged = {
        str(key): _text_items(value, limit=80)
        for key, value in products.items()
    }
    accepted = [
        image
        for image in images
        if image.evidence_ids
        and image.name.strip()
        and image.operational_mechanism.strip()
    ]
    if not 5 <= len(accepted) <= 7:
        return merged

    corpus = " ".join(
        str(value)
        for image in accepted
        for value in (
            image.name,
            image.equipment_category,
            image.source_winning_logic,
            image.mission_effect,
            image.capability_gap,
            image.capability_image,
            image.deep_capability_portrait,
            image.equipment_form,
            image.operational_mechanism,
            image.development_path,
            image.combat_effect_uplift,
            image.strike_chain_contribution,
            " ".join(image.system_dependencies),
            " ".join(image.risk_boundaries),
        )
        if value
    )
    derived_domains = [
        label
        for label, markers in _A_CAPABILITY_DOMAIN_RULES
        if any(marker in corpus for marker in markers)
    ]
    if len(derived_domains) < 8:
        derived_domains.extend(
            image.equipment_category
            for image in accepted
            if image.equipment_category.strip()
        )

    supplements = {
        "tactic_concepts": [
            f"{image.name}：{image.source_winning_logic}"
            for image in accepted
            if image.source_winning_logic.strip()
        ][:3],
        "tactic_combinations": [
            f"{image.name}：{image.operational_mechanism}"
            + (
                f"；杀伤链贡献为{image.strike_chain_contribution}"
                if image.strike_chain_contribution.strip()
                else ""
            )
            for image in accepted
        ][:5],
        "capability_domains": _unique(derived_domains)[:8],
        "capability_indicators": [
            f"{image.name}—{dimension}"
            for image in accepted
            for dimension in (
                "覆盖或射程边界",
                "目标暴露至毁伤响应周期",
                "受扰自主与授权中止边界",
                "单位任务或单位有效毁伤成本",
                "并发波次与库存补充规模",
                "生存、抗扰与失效判据",
            )
        ][:30],
        "equipment_forms": [
            f"{image.name}：{image.equipment_form or image.equipment_category}"
            for image in accepted
        ],
    }
    for key, rows in supplements.items():
        merged[key] = _unique([*merged.get(key, []), *rows])
    return merged


def render_intermediate_agent_analysis(
    *, topic: str, branch: str, store: DomainStore
) -> str:
    lines: list[str] = []
    packets = [
        packet
        for packet in store.baseline_packets.values()
        if getattr(packet, "admission_status", "") != "rejected"
    ]
    if not packets:
        lines.extend(["当前没有可发布的专业研究结论。", ""])
        return "\n".join(lines)
    for packet in packets:
        label = AGENT_LABELS.get(packet.agent_id, packet.topic_focus or packet.agent_id)
        findings = _substantive_items(packet.findings, limit=8)
        dimensions = _analysis_dimension_sentences(packet.analysis_sections or packet.payload)[:4]
        limitations = _text_items(packet.limitations, limit=3)
        questions = _text_items(packet.open_questions, limit=3)
        lines.extend(
            [
                f"### {label}",
                "",
                f"综合现有研究结果，核心判断是：{_join_prose(findings, fallback=packet.handoff_summary)}",
                "",
                f"从作用机制和约束关系看，{_join_prose(dimensions, fallback='现有材料主要支持方向性判断，尚不足以形成更细的机制分解。')} 该判断以 {len(packet.evidence_ids)} 项已登记证据为边界，综合置信度为 {packet.confidence:.0%}。",
                "",
                f"对装备需求研判的直接启示是：{_substantive_implication(packet)}",
                "",
                f"反证与适用边界方面，{_join_prose(limitations, fallback='未登记独立反证；仍需在审计和场景压力测试中检查结论外推。')} 待继续回答的问题包括：{_join_prose(questions, fallback='无新增开放问题。')}",
                "",
                f"证据索引：{', '.join(packet.evidence_ids) or '无正式证据 ID'}。",
                "",
            ]
        )
    reasoning_groups = _reasoning_theme_groups(store)
    if reasoning_groups:
        lines.extend(["### 制胜逻辑、效果链与能力缺口", ""])
        for title, summaries in reasoning_groups:
            lines.extend(
                [
                    f"#### {title}",
                    "",
                    _join_prose(summaries, fallback="当前尚未形成可发布结论。"),
                    "",
                ]
            )
    lines.extend(
        [
            "### 跨专题综合判断",
            "",
            _cross_agent_synthesis(branch=branch, store=store),
            "",
        ]
    )
    return "\n".join(lines).strip() + "\n"


def branch_report_lines(branch_output: Mapping[str, Any]) -> list[str]:
    branch = str(branch_output.get("branch", "A"))
    profile = branch_profile(branch)
    contract = branch_report_contract(branch)
    products = branch_output.get("products", {})
    lines = [
        "## 3. 分支收敛产物与完成度",
        "",
        f"本轮按“{profile['name']}”输出契约收敛。以下内容只呈现有证据或有明确推断前提的成果；数量不足不会用泛化条目补齐，而会登记为交付缺口。",
        "",
        "### 分支论证主线",
        "",
        (
            f"{contract['thesis']}{contract['military_test']}{contract['future_test']}"
            "以下结论将这些要求写入具体事实、因果机制、装备选择和验证边界，"
            "不把军事价值、深度或前瞻性拆成脱离正文的标签。"
        ),
        "",
    ]
    for section in profile["required_sections"]:
        lines.append(f"### {section}")
        lines.append("")
        keys = _section_keys(str(branch_output.get("branch", "A")), section)
        values = [
            item
            for key in keys
            for item in _reportable_product_items(key, products.get(key))
        ]
        if values:
            for index, value in enumerate(values, start=1):
                lines.extend([f"**判断 {index}**　{value}", ""])
        else:
            lines.append("- 当前证据与专业研究结果尚未形成可发布条目，已列入后续定向补研。")
        lines.append("")
    completion = branch_output.get("completion", {})
    if completion:
        lines.extend(["### 定量交付门槛核对", ""])
        for key, row in completion.items():
            lines.append(
                f"- {key}：目标 {row.get('target', 0)}，已形成 {row.get('actual', 0)}，"
                f"状态为{'满足' if row.get('met') else '未满足'}。"
            )
        lines.append("")
    return lines


def _demand_card(image: CapabilityImageItem) -> dict[str, Any]:
    return {
        "card_id": f"card-{image.capability_id}",
        "capability_id": image.capability_id,
        "weapon_equipment": _weapon_equipment_card_name(image),
        "equipment_category": image.equipment_category,
        "equipment_configuration": image.equipment_form
        or image.equipment_category,
        "development_mode": (
            "现役武器装备升级"
            if image.capability_type == "upgrade"
            else "新研武器装备"
        ),
        "priority": image.priority,
        "key_indicators": _demand_card_indicators(image),
        "supporting_scenarios": [image.related_scenario],
        "evidence_chain": list(image.evidence_ids),
        "source_winning_logic": image.source_winning_logic,
        "mission_effect": image.mission_effect,
        "project_function": image.project_function,
        "capability_gap": image.capability_gap,
        "deep_capability_portrait": image.deep_capability_portrait or image.capability_image,
        "target_scenario": image.target_scenario or image.related_scenario,
        "problem_statement": image.problem_statement or image.capability_gap,
        "scientific_principle": image.scientific_principle,
        "enabling_technologies": list(image.enabling_technologies),
        "operational_concept": image.operational_concept or image.operational_mechanism,
        "operational_process": list(image.operational_process),
        "capability_outcome": image.capability_outcome or image.mission_effect,
        "winning_mechanism": image.winning_mechanism,
        "equipment_form": image.equipment_form,
        "operational_mechanism": image.operational_mechanism,
        "development_path": image.development_path,
        "baseline_system": image.baseline_system,
        "upgrade_package": list(image.upgrade_package),
        "combat_effect_uplift": image.combat_effect_uplift,
        "strike_chain_contribution": image.strike_chain_contribution,
        "upgrade_boundary": image.upgrade_boundary,
        "system_dependencies": list(image.system_dependencies),
        "risk_boundaries": list(image.risk_boundaries),
        "military_utility": image.military_utility,
        "strike_countermeasure_value": image.strike_countermeasure_value,
        "novelty": image.novelty,
        "foresight": image.foresight,
        "operational_constraints": list(image.operational_constraints),
        "evidence_basis": list(image.evidence_basis),
        "agent_contributions": list(image.agent_contributions),
        "reasoning_refs": list(image.reasoning_refs),
        "confidence": image.confidence,
    }


def _weapon_equipment_card_name(image: CapabilityImageItem) -> str:
    """Use the accepted model identity without locally reclassifying it."""

    name = str(image.name).strip()
    if name:
        return name
    configuration = image.equipment_form or image.equipment_category
    return str(configuration).strip()[:80]


def _demand_card_indicators(image: CapabilityImageItem) -> list[str]:
    """Extract auditable indicators without inventing weapon performance."""

    text = " ".join(
        item
        for item in (
            image.deep_capability_portrait,
            image.capability_image,
            image.development_path,
        )
        if item
    )
    matches = re.findall(
        r"(?:可证伪指标|验证指标|考核指标|通过条件)(?:包括|为|是)?[:：]?([^。；]+)",
        text,
    )
    indicators: list[str] = []
    for match in matches:
        indicators.extend(
            item.strip()
            for item in re.split(r"[、，,]", match)
            if item.strip()
        )
    return _unique(indicators)[:6]


def _supplement_specialized_branch_products(
    branch: str,
    products: Mapping[str, Any],
    *,
    images: list[CapabilityImageItem],
) -> dict[str, list[str]]:
    """Project accepted capability-image fields into D--H delivery slots.

    Dynamic winning runs converge directly on a reviewed equipment portfolio
    and may not retain the legacy L3 ``branch_products`` wrapper.  Reusing the
    accepted image fields prevents false zero-count gaps without inventing a
    new equipment direction, performance value, source, or conclusion.
    """

    merged = {
        str(key): _text_items(value, limit=80)
        for key, value in products.items()
    }

    def existing_or(key: str, values: Iterable[Any], *, limit: int = 60) -> None:
        if merged.get(key):
            return
        merged[key] = _unique(
            text
            for value in values
            for text in _text_items(value, limit=limit)
            if text
        )[:limit]

    forms = [image.equipment_form or image.equipment_category for image in images]
    scenarios = [
        image.foresight
        or next(iter(image.risk_boundaries), "")
        or image.related_scenario
        for image in images
    ]
    gaps = [image.capability_gap or image.problem_statement for image in images]
    capability_domains = [
        image.mission_effect
        or image.capability_outcome
        or image.equipment_category
        for image in images
    ]

    existing_or("equipment_forms", forms)
    if branch == "D":
        existing_or(
            "technology_opportunities",
            (image.enabling_technologies for image in images),
        )
        existing_or("future_scenarios", scenarios)
    elif branch == "E":
        existing_or("threat_patterns", gaps)
        existing_or("future_scenarios", scenarios)
        existing_or("capability_domains", capability_domains)
    elif branch == "F":
        existing_or("system_vulnerabilities", gaps)
        existing_or("future_scenarios", scenarios)
        existing_or("capability_domains", capability_domains)
    elif branch == "G":
        existing_or("cross_domain_gaps", gaps)
        existing_or(
            "tactic_combinations",
            (
                image.operational_concept
                or image.operational_mechanism
                or image.operational_process
                or image.source_winning_logic
                or image.mission_effect
                for image in images
            ),
        )
        existing_or(
            "capability_indicators",
            (_demand_card_indicators(image) for image in images),
        )
    elif branch == "H":
        existing_or("emerging_threat_profiles", gaps)
        existing_or("future_scenarios", scenarios)
        existing_or("capability_domains", capability_domains)
    return merged


def _capability_panorama(
    *,
    topic: str,
    branch: str,
    profile: Mapping[str, Any],
    images: list[CapabilityImageItem],
    branch_products: Mapping[str, Any],
) -> dict[str, Any]:
    domains: dict[str, dict[str, Any]] = {}
    for image in images:
        node = domains.setdefault(
            image.equipment_category,
            {
                "domain": image.equipment_category,
                "capability_ids": [],
                "indicators": [],
                "supporting_scenarios": [],
                "evidence_ids": [],
            },
        )
        node["capability_ids"].append(image.capability_id)
        node["supporting_scenarios"] = _unique([*node["supporting_scenarios"], image.related_scenario])
        node["evidence_ids"] = _unique([*node["evidence_ids"], *image.evidence_ids])
    declared_domains = _text_items(branch_products.get("capability_domains", []), limit=20)
    for domain in declared_domains:
        domains.setdefault(
            domain,
            {
                "domain": domain,
                "capability_ids": [],
                "indicators": [],
                "supporting_scenarios": [],
                "evidence_ids": [],
            },
        )
    declared_indicators = _text_items(branch_products.get("capability_indicators", []), limit=60)
    return {
        "topic": topic,
        "branch": branch,
        "branch_name": profile["name"],
        "domains": list(domains.values()),
        "cross_domain_indicators": declared_indicators,
        "equipment_forms": _text_items(branch_products.get("equipment_forms", []), limit=20),
        "target_counts": dict(profile.get("targets", {})),
        "actual_counts": {
            "capability_domains": len(domains),
            "capability_indicators": len(
                _unique([*declared_indicators, *[item for node in domains.values() for item in node["indicators"]]])
            ),
            "capability_items": len(images),
        },
    }


def _reasoning_traceability(store: DomainStore) -> dict[str, Any]:
    return {
        "reasoning_nodes": [to_plain(item) for item in store.reasoning_nodes.values()],
        "stage_outputs": [to_plain(item) for item in store.stage_outputs.values()],
        "agent_handoffs": [
            {
                "packet_id": item.packet_id,
                "agent_id": item.agent_id,
                "handoff_summary": item.handoff_summary,
                "evidence_ids": list(item.evidence_ids),
                "claim_ids": list(item.claim_ids),
                "confidence": item.confidence,
                "limitations": list(item.limitations),
                "open_questions": list(item.open_questions),
            }
            for item in store.baseline_packets.values()
        ],
        "trace_rule": "正式结论应由需求卡片回溯至能力画像、S1-S6节点、中间Agent Packet和EvidenceCard。",
    }


def _branch_output(
    *,
    branch: str,
    profile: Mapping[str, Any],
    blueprint: Mapping[str, Any],
    branch_products: Mapping[str, Any],
    demand_cards: list[dict[str, Any]],
    panorama: Mapping[str, Any],
    traceability: Mapping[str, Any],
) -> dict[str, Any]:
    products = {key: _text_items(branch_products.get(key, []), limit=60) for key in profile["product_keys"]}
    structured_products = {
        "demand_cards": demand_cards,
        "capability_panorama": panorama,
        "reasoning_traceability": traceability,
    }
    for key, value in structured_products.items():
        if key in profile["product_keys"]:
            products[key] = value
    actual_counts = {
        key: len(products.get(key, []))
        for key in profile.get("targets", {})
    }
    completion = {
        key: {"target": target, "actual": actual_counts.get(key, 0), "met": actual_counts.get(key, 0) >= target}
        for key, target in profile.get("targets", {}).items()
    }
    if not completion:
        completion = {
            key: {
                "target": 1,
                "actual": _product_count(key, products.get(key)),
                "met": _product_count(key, products.get(key)) >= 1,
            }
            for key in profile["product_keys"]
        }
    return {
        "branch": branch,
        "branch_name": profile["name"],
        "required_sections": list(profile["required_sections"]),
        "blueprint_required_outputs": list(blueprint.get("required_outputs", [])),
        "products": products,
        "report_quality_requirements": REPORT_QUALITY_DIMENSIONS,
        "report_contract": branch_report_contract(branch),
        "completion": completion,
        "delivery_status": "complete" if all(row["met"] for row in completion.values()) else "limited",
        "non_fabrication_rule": "未达到数量门槛时必须披露缺口，不得用同义改写或无证据条目凑数。",
    }


def _explicit_convergence_items(
    convergence: Mapping[str, Any] | None,
    *,
    markers: tuple[str, ...],
    limit: int,
) -> list[str]:
    """Read explicitly labelled branch products without inventing new rows."""

    if not isinstance(convergence, Mapping):
        return []
    rows: list[str] = []
    for value in convergence.get("cross_branch_links", []):
        text = str(value).strip()
        if not text or not any(marker in text for marker in markers):
            continue
        payload = re.split(r"[：:]", text, maxsplit=1)
        if len(payload) != 2:
            continue
        rows.extend(
            item.strip(" 。；;、")
            for item in re.split(r"[；;]", payload[1])
            if item.strip(" 。；;、")
        )
    return _unique(rows)[:limit]


def _branch_products(
    store: DomainStore,
    *,
    convergence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    candidates = [
        stage
        for stage in store.stage_outputs.values()
        if stage.layer == "L3"
        and isinstance(stage.outputs.get("branch_products"), Mapping)
    ]
    merged: dict[str, list[str]] = {}
    # The latest valid attempt owns keys it explicitly emits; keys omitted by a
    # targeted repair retain their most recent prior value.
    for stage in sorted(candidates, key=lambda item: (item.created_at, item.stage_id)):
        value = stage.outputs.get("branch_products", {})
        if not isinstance(value, Mapping):
            continue
        for key, rows in value.items():
            merged[str(key)] = _text_items(rows, limit=80)

    # Case Research owns the 6/3/4 branch packet. It is a first-class source for
    # delivery rather than merely raw material that S6 is expected to regenerate.
    for packet in store.baseline_packets.values():
        if packet.agent_id != "case_research" or packet.admission_status == "rejected":
            continue
        sections = packet.payload or packet.analysis_sections
        if not isinstance(sections, Mapping):
            continue
        case_mapping = {
            "case_patterns": ("case_patterns", "lessons", "cross_case_patterns"),
            "future_scenarios": (
                "future_scenarios",
                "future_scenario_mapping",
                "scenario_projections",
            ),
            "emerging_equipment_categories": (
                "emerging_equipment_categories",
                "equipment_needs",
                "equipment_categories",
            ),
        }
        for target, source_keys in case_mapping.items():
            for source_key in source_keys:
                values = _text_items(sections.get(source_key), limit=80)
                if values:
                    merged.setdefault(target, []).extend(values)
                    break
    convergence_products = {
        "future_scenarios": _explicit_convergence_items(
            convergence,
            markers=("三类未来高置信场景", "3类未来高置信场景"),
            limit=3,
        ),
        "emerging_equipment_categories": _explicit_convergence_items(
            convergence,
            markers=("四大新兴装备类别", "4大新兴装备类别"),
            limit=4,
        ),
    }
    for key, rows in convergence_products.items():
        if rows and not merged.get(key):
            merged[key] = list(rows)
    return {key: _unique(rows) for key, rows in merged.items()}


def _product_count(key: str, value: Any) -> int:
    if key == "capability_panorama" and isinstance(value, Mapping):
        return len(value.get("domains", []))
    if key == "reasoning_traceability" and isinstance(value, Mapping):
        return len(value.get("reasoning_nodes", []))
    if isinstance(value, Mapping):
        return int(bool(value))
    if isinstance(value, (list, tuple, set)):
        return len(value)
    return int(value not in (None, ""))


def _reportable_product_items(key: str, value: Any) -> list[str]:
    if key == "demand_cards" and isinstance(value, list):
        return [
            (
                f"{item.get('weapon_equipment', '待发展武器装备')}："
                f"按{item.get('development_mode', '装备发展')}实施，"
                f"面向{', '.join(item.get('supporting_scenarios', [])) or '目标场景'}，"
                f"重点形成{item.get('mission_effect') or item.get('deep_capability_portrait', '')}；"
                f"关键指标为{', '.join(item.get('key_indicators', [])) or '待验证'}，"
                f"优先级{item.get('priority', '待评估')}。"
            )
            for item in value[:20]
            if isinstance(item, Mapping)
        ]
    if key == "capability_panorama" and isinstance(value, Mapping):
        return [
            (
                f"{node.get('domain', '能力域')}：关联能力"
                f"{', '.join(node.get('capability_ids', [])) or '待补充'}，"
                f"指标包括{', '.join(node.get('indicators', [])) or '待补充'}，"
                f"支撑场景为{', '.join(node.get('supporting_scenarios', [])) or '待补充'}。"
            )
            for node in value.get("domains", [])[:20]
            if isinstance(node, Mapping)
        ]
    if key == "reasoning_traceability" and isinstance(value, Mapping):
        return [
            f"已形成{len(value.get('reasoning_nodes', []))}个制胜推理节点、"
            f"{len(value.get('agent_handoffs', []))}组专业研究结论和"
            f"{len(value.get('stage_outputs', []))}层门控结果，可从需求卡片回溯至证据。"
        ]
    return _text_items(value, limit=40)


def _analysis_dimension_sentences(value: Any) -> list[str]:
    if not isinstance(value, Mapping):
        return _text_items(value, limit=6)
    rows = []
    for key, item in list(value.items())[:10]:
        rendered = _join_prose(_text_items(item, limit=4), fallback="")
        if rendered:
            rows.append(f"在{key}维度，材料表明{rendered}")
    return rows


def _cross_agent_synthesis(*, branch: str, store: DomainStore) -> str:
    packets = list(store.baseline_packets.values())
    findings = _unique([item for packet in packets for item in _substantive_items(packet.findings, limit=5)])
    conflicts = _unique([item for packet in packets for item in _text_items(packet.limitations, limit=4)])
    scenarios = _unique(
        [
            str(value)
            for packet in packets
            for key, value in (packet.analysis_sections or packet.payload).items()
            if key in {"scenario_framework", "scenario_branches", "scenario_fit", "coa"}
        ]
    )
    return (
        f"跨专题研究结果共同指向：{_join_prose(findings, fallback='当前尚未形成稳定共识')}。"
        f"这些判断需要放回{branch_profile(branch)['name']}的任务链中理解，场景约束主要体现为"
        f"{_join_prose(scenarios, fallback='场景证据仍需补强')}。"
        f"当前最重要的反证和边界是{_join_prose(conflicts, fallback='公开资料不能替代仿真、试验和专家论证')}。"
        "结合S1对手解构、S2运用审查、S3突破口、S4能力映射、S5差距分析和S6综合排序，"
        "最终装备需求不应停留在技术名词罗列，而应同时说明任务效果、作用机制、体系接口、指标口径和验证路径。"
    )


def _reasoning_theme_groups(store: DomainStore) -> list[tuple[str, list[str]]]:
    by_step: dict[int, list[str]] = {}
    for node in store.reasoning_nodes.values():
        by_step.setdefault(node.step, []).append(node.summary)
    themes = [
        ("对手体系、任务约束与可利用窗口", [1, 2]),
        ("突破方向与效果传导机制", [3]),
        ("装备能力域、功能和指标边界", [4]),
        ("现状差距、优先序与建设取舍", [5]),
        ("综合能力画像与装备形态启示", [6]),
    ]
    return [
        (title, _unique([item for step in steps for item in by_step.get(step, [])]))
        for title, steps in themes
        if any(by_step.get(step) for step in steps)
    ]


def _substantive_implication(packet: Any) -> str:
    sections = packet.analysis_sections or packet.payload
    priority_keys = {
        "international_situation": ("threat_assessment", "warning_indicators", "scenario_drivers"),
        "combat_scenario": ("capability_pressure_points", "environment_constraints", "critical_timeline"),
        "weapon_equipment": ("capability_gaps", "upgrade_requirements", "new_equipment_requirements", "system_dependencies"),
        "operational_employment": ("equipment_function_requirements", "failure_modes", "force_coordination"),
        "case_research": ("case_patterns", "lessons", "transfer_boundaries"),
        "technology_radar": ("technology_opportunities", "technology_readiness", "disruptive_scenarios"),
        "opponent_monitoring": ("counter_requirements", "threat_effects", "warning_indicators"),
        "system_confrontation": ("critical_vulnerabilities", "reinforcement_directions", "cascading_failures"),
        "cross_domain_fusion": ("coordination_gaps", "fusion_requirements", "interface_dependencies"),
        "nontraditional_security": ("resilience_requirements", "nonlethal_requirements", "legal_ethical_limits"),
    }.get(packet.agent_id, ())
    values = (
        [
            item
            for key in priority_keys
            for item in _text_items(sections.get(key), limit=4)
        ]
        if isinstance(sections, Mapping)
        else []
    )
    if not values:
        values = _substantive_items(packet.findings, limit=4)
    return _join_prose(
        values,
        fallback="应把本专题揭示的任务压力转化为可度量能力、体系接口和验证条件。",
    )


def _substantive_items(value: Any, *, limit: int) -> list[str]:
    process_markers = ("Agent", "agent", "交接", "输出给下游", "仅消费", "结构化packet")
    return [
        item
        for item in _text_items(value, limit=limit * 2)
        if not any(marker in item for marker in process_markers)
    ][:limit]


def _section_keys(branch: str, section: str) -> list[str]:
    mapping = {
        "A": {
            "战法概念集": ["tactic_concepts", "tactic_combinations"],
            "装备能力需求图像": ["capability_domains", "capability_indicators"],
            "关联装备形态建议": ["equipment_forms"],
        },
        "B": {
            "需求卡片": ["demand_cards"],
            "能力全景图": ["capability_panorama"],
            "深度研究报告（含推理链可回溯）": ["reasoning_traceability"],
        },
        "C": {
            "案例规律报告": ["case_patterns"],
            "未来场景预测": ["future_scenarios"],
            "装备需求图像": ["emerging_equipment_categories"],
        },
        "D": {
            "技术机会谱系": ["technology_opportunities"],
            "成熟度与颠覆场景": ["future_scenarios"],
            "技术牵引装备形态": ["equipment_forms"],
            "装备能力需求图像（需求卡片）": ["demand_cards"],
        },
        "E": {
            "对手变化规律": ["threat_patterns"],
            "威胁形成场景": ["future_scenarios"],
            "对冲能力与装备建议": ["capability_domains", "equipment_forms"],
            "装备能力需求图像（需求卡片）": ["demand_cards"],
        },
        "F": {
            "体系脆弱性规律": ["system_vulnerabilities"],
            "级联失效场景": ["future_scenarios"],
            "补链强链能力组合": ["capability_domains", "equipment_forms"],
            "装备能力需求图像（需求卡片）": ["demand_cards"],
        },
        "G": {
            "跨域缝隙图谱": ["cross_domain_gaps"],
            "协同模式组合": ["tactic_combinations"],
            "接口与装备形态建议": ["capability_indicators", "equipment_forms"],
            "装备能力需求图像（需求卡片）": ["demand_cards"],
        },
        "H": {
            "新型威胁画像": ["emerging_threat_profiles"],
            "高置信场景": ["future_scenarios"],
            "韧性与非致命装备需求": ["capability_domains", "equipment_forms"],
            "装备能力需求图像（需求卡片）": ["demand_cards"],
        },
    }
    return mapping.get(branch, {}).get(section, branch_profile(branch)["product_keys"])


def _text_items(value: Any, *, limit: int) -> list[str]:
    if value in (None, "", [], {}):
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, Mapping):
        rendered = []
        for key, item in value.items():
            if item in (None, "", [], {}):
                continue
            rendered.append(f"{key}：{_compact_value(item)}")
        return rendered[:limit]
    if isinstance(value, Iterable):
        return [_compact_value(item) for item in list(value)[:limit] if _compact_value(item)]
    return [str(value)]


def _compact_value(value: Any) -> str:
    if isinstance(value, Mapping):
        return "；".join(f"{key}={_compact_value(item)}" for key, item in value.items() if item not in (None, "", [], {}))
    if isinstance(value, (list, tuple, set)):
        return "、".join(_compact_value(item) for item in value if _compact_value(item))
    return str(value).strip()


def _join_prose(values: list[str], *, fallback: str) -> str:
    rows = [item.rstrip("。；") for item in values if item.strip()]
    return "；".join(rows) + ("。" if rows else fallback)


def _unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(str(item).strip() for item in values if str(item).strip()))


__all__ = [
    "BRANCH_DELIVERABLE_PROFILES",
    "BRANCH_REPORT_CONTRACTS",
    "BRANCH_WRITER_OUTLINES",
    "STRUCTURED_PRODUCT_KEYS",
    "branch_profile",
    "branch_report_contract",
    "branch_writer_brief",
    "branch_report_lines",
    "build_delivery_artifacts",
    "render_intermediate_agent_analysis",
]
