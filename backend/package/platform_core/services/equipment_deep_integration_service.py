"""平台原生会话与装备深研领域能力之间的适配层。"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.agents.context import resolve_agent_resource_options
from platform_core.agents.presets import DEFAULT_RESEARCH_POLICY
from platform_core.permissions import has_global_business_access
from platform_core.repositories.agent_repository import AgentRepository
from platform_core.repositories.conversation_repository import ConversationRepository
from platform_core.repositories.equipment_research_repository import EquipmentResearchRepository
from platform_core.services.personal_resource_audit_service import audit_superadmin_personal_resource_write
from platform_core.storage.postgres.models_business import User
from platform_core.storage.postgres.models_equipment import EquipmentCapabilityVersion, EquipmentDeepSession
from platform_core.utils.datetime_utils import utc_now_naive

DEEP_AGENT_SLUG = "deep-research"
WEAPON_SCHEME_AGENT_SLUG = "weapon-equipment-scheme"
CAPABILITY_PORTRAIT_AGENT_SLUG = "equipment-capability-portrait"
DEEP_SESSION_SCHEMA_VERSION = "equipment-deep-native-v2"
DEEP_SKILL_SLUG = "equipment-deep-conversation"
_REQUIRED_SKILLS = (DEEP_SKILL_SLUG, "equipment-research", "deep-research", "academic-evidence")
_WORKSPACE_SKILLS = ("html-preview",)
SECTION_DEEPEN_MODE = "section_deepen"
NEW_WEAPON_DIVERGE_MODE = "new_weapon_diverge"
_DEEP_RESEARCH_MODES = {SECTION_DEEPEN_MODE, NEW_WEAPON_DIVERGE_MODE}
# ``agent_request_service`` intentionally caps a single run's hidden prompt
# append at 12k characters.  Keep the domain adapter on the same contract so
# a rich capability card can never turn a valid deep-research submission into
# a 422 before the model is invoked.
_MAX_SYSTEM_PROMPT_APPEND_CHARS = 12_000

# Deep-conversation drafts must use the same governed S6 portrait contract as
# the formal S6 pipeline.  Keep the contract at the persistence boundary so a
# prompt omission, model drift, or direct tool call cannot create a partial
# card that the capability page later mis-parses.
S6_PORTRAIT_MODULES: tuple[tuple[str, str], ...] = (
    ("overview", "概述"),
    ("technology_implementation", "装备与技术实现"),
    ("operational_process", "关键作战流程"),
    ("capability_effects", "形成能力与作战效果"),
    ("winning_logic", "制胜逻辑机理"),
)
S6_PORTRAIT_SOFT_TARGET_CHARS = 360
# 360–400 is an authoring target, not a transport limit. Persistence only
# rejects near-empty prose; the agent must repair ordinary short columns before
# calling the tool, while legacy concise cards can still be normalized safely.
S6_PORTRAIT_HARD_MIN_CHARS = 60
_S6_KEY_ALIASES: dict[str, tuple[str, ...]] = {
    "overview": ("overview", "problem_statement", "capability_gap"),
    "technology_implementation": (
        "technology_implementation",
        "technology",
        "scientific_principle",
        "technical_principle",
        "implementation_concept",
    ),
    "operational_process": ("operational_process", "operational_mechanism"),
    "capability_effects": (
        "capability_effects",
        "outcome",
        "capability_outcome",
        "direct_military_effects",
    ),
    "winning_logic": (
        "winning_logic",
        "winning_mechanism",
        "source_winning_logic",
    ),
}
_S6_LABEL_TO_KEY = {
    "概述": "overview",
    "装备与技术实现": "technology_implementation",
    "关键作战流程": "operational_process",
    "形成能力与作战效果": "capability_effects",
    "制胜逻辑机理与对抗边界": "winning_logic",
    "制胜逻辑机理": "winning_logic",
    "制胜逻辑": "winning_logic",
}
_S6_HEADING_RE = re.compile(
    r"(?m)^[ \t]*(?:[-*+]\s*)?(?:#{1,6}\s*)?"
    r"(?:[（(]?\d+[）).、]\s*)?"
    r"(?P<label>概述|装备与技术实现|关键作战流程|形成能力与作战效果|"
    r"制胜逻辑机理与对抗边界|制胜逻辑机理|制胜逻辑)"
    r"(?:\s*[（(][^\n）)]{1,24}[）)])?\s*[：:]\s*"
)


@dataclass(frozen=True)
class DeepConversationRequestBinding:
    """平台原生 Conversation 对应的装备深研运行绑定。

    Agent 请求服务只消费这份协议化结果，不需要知道装备领域表结构；装备
    深研适配层则集中负责身份校验、领域上下文和运行来源，避免各入口各自
    拼装一套近似但不一致的 Run。
    """

    source: str
    external_id: str
    origin_metadata: dict[str, Any]
    request_metadata: dict[str, Any]
    runtime_context_overrides: dict[str, Any]


async def resolve_native_conversation_request_binding(
    *,
    db: AsyncSession,
    user: User,
    conversation,
    agent,
    request_metadata: Mapping[str, Any] | None = None,
    runtime_context_overrides: Mapping[str, Any] | None = None,
    model_spec: str | None = None,
) -> DeepConversationRequestBinding | None:
    """识别并恢复平台原生深研 Conversation 的领域运行上下文。

    无论请求来自装备深研页还是通用原生聊天页，只要 Conversation 已绑定
    深研 Session，后续 AgentRun 都必须恢复同一来源身份、知识库/Subagent
    隔离规则和装备上下文。普通 Conversation 返回 ``None``，不产生耦合。
    """

    conversation_metadata = dict(getattr(conversation, "extra_metadata", None) or {})
    if conversation_metadata.get("source") != "equipment_deep_research":
        return None

    session_id = str(conversation_metadata.get("equipment_deep_session_id") or "").strip()
    if not session_id:
        raise HTTPException(status_code=409, detail="深研会话缺少领域绑定")

    session = await EquipmentResearchRepository(db).get_deep_session(session_id)
    if session is None:
        raise HTTPException(status_code=409, detail="深研会话领域记录不存在")
    if session.owner_uid != str(user.uid) or getattr(conversation, "uid", None) != str(user.uid):
        raise HTTPException(status_code=404, detail="深研对话不存在")

    payload = dict(session.payload or {})
    if str(payload.get("status") or "active").strip().lower() == "archived":
        raise HTTPException(status_code=409, detail="深研对话已归档，恢复后才能继续追问")
    if str(payload.get("thread_id") or "") != str(getattr(conversation, "thread_id", "")):
        raise HTTPException(status_code=409, detail="深研会话线程绑定不一致")
    if str(payload.get("agent_slug") or DEEP_AGENT_SLUG) != str(getattr(conversation, "agent_id", "")):
        raise HTTPException(status_code=409, detail="深研会话智能体绑定不一致")

    metadata = dict(request_metadata or {})
    focus = str(metadata.get("equipment_deep_focus") or payload.get("focus") or "").strip()
    research_mode = normalize_deep_research_mode(metadata.get("equipment_deep_mode") or payload.get("research_mode"))
    research_section = str(metadata.get("equipment_deep_section") or payload.get("research_section") or "").strip()[:64]
    create_artifact = bool(metadata.get("equipment_create_artifact", False))
    active_skill_ids = _unique_strings(
        metadata.get("equipment_active_skill_ids") or payload.get("active_skill_ids") or []
    )[:12]
    domain_overrides = await build_runtime_context_overrides(
        db=db,
        user=user,
        agent=agent,
        session=session,
        focus=focus,
        active_skill_ids=active_skill_ids,
        create_artifact=create_artifact,
        research_mode=research_mode,
        research_section=research_section,
    )
    resolved_overrides = _merge_deep_runtime_overrides(
        domain_overrides,
        runtime_context_overrides,
        payload=payload,
    )

    normalized_model_spec = str(model_spec or "").strip()
    if normalized_model_spec and payload.get("model_spec") != normalized_model_spec:
        # Conversation/AgentRun 是模型选择的运行事实；领域 Session 仅同步一份
        # 展示投影，统一随当前请求事务提交，不在适配层自行 commit。
        payload["model_spec"] = normalized_model_spec
        session.payload = payload
        session.updated_at = utc_now_naive()
    if payload.get("research_mode") != research_mode or payload.get("research_section") != research_section:
        payload["research_mode"] = research_mode
        payload["research_section"] = research_section
        session.payload = payload
        session.updated_at = utc_now_naive()

    return DeepConversationRequestBinding(
        source="equipment_deep_research",
        external_id=session.id,
        origin_metadata={
            "equipment_deep_session_id": session.id,
            "equipment_run_id": session.run_id,
            "equipment_deep_mode": research_mode,
            "equipment_deep_section": research_section,
        },
        request_metadata={
            "equipment_deep_session_id": session.id,
            "equipment_create_artifact": create_artifact,
            "equipment_deep_mode": research_mode,
            "equipment_deep_section": research_section,
        },
        runtime_context_overrides=resolved_overrides,
    )


async def resolve_deep_agent(
    *,
    db: AsyncSession,
    user: User,
    requested_slug: str | None,
):
    """解析深研会话 Agent；未指定时固定使用平台深度研究角色。"""
    repo = AgentRepository(db)
    slug = str(requested_slug or "").strip() or DEEP_AGENT_SLUG
    agent = await repo.get_visible_by_slug(slug=slug, user=user, kind="main")
    if agent is None:
        if slug == DEEP_AGENT_SLUG:
            raise HTTPException(status_code=503, detail="深研智能体尚未完成初始化")
        raise HTTPException(status_code=404, detail="深研智能体不存在或无权访问")
    return agent


async def build_runtime_context_overrides(
    *,
    db: AsyncSession,
    user: User,
    agent,
    session: EquipmentDeepSession,
    focus: str = "",
    active_skill_ids: Sequence[str] = (),
    create_artifact: bool = False,
    research_mode: str = SECTION_DEEPEN_MODE,
    research_section: str = "",
) -> dict[str, Any]:
    """把领域会话能力投影为单次 AgentRun 的受限运行时覆盖。"""
    payload = dict(session.payload or {})
    agent_context = dict((agent.config_json or {}).get("context") or {})
    options = await resolve_agent_resource_options({"skills"}, db=db, user=user)
    accessible_skills = [item["key"] for item in options.get("skills", [])]
    accessible_set = set(accessible_skills)

    configured_skills = agent_context.get("skills")
    skills = accessible_skills if configured_skills is None else _unique_strings(configured_skills)
    skills = [slug for slug in skills if slug in accessible_set]
    for slug in (*_REQUIRED_SKILLS, *_WORKSPACE_SKILLS, *_unique_strings(active_skill_ids)):
        if slug in accessible_set and slug not in skills:
            skills.append(slug)

    knowledge_enabled = bool(payload.get("knowledge_enabled", True))
    if knowledge_enabled:
        if "knowledge-base" in accessible_set and "knowledge-base" not in skills:
            skills.append("knowledge-base")
    else:
        skills = [slug for slug in skills if slug != "knowledge-base"]

    configured_preloads = _unique_strings(agent_context.get("preload_skills"))
    preload_skills = [DEEP_AGENT_SLUG] if DEEP_AGENT_SLUG in skills else []
    technology_cabin = str(research_section or "").strip() == "装备与技术实现"
    if technology_cabin:
        for slug in ("academic-evidence", "knowledge-base"):
            if slug in skills and slug not in preload_skills:
                preload_skills.append(slug)
    preload_skills.extend(
        slug
        for slug in configured_preloads
        if slug in skills and slug not in (*_REQUIRED_SKILLS, "knowledge-base") and slug not in preload_skills
    )
    # 方法论保留在可发现目录中，只预载用户明确选用的技能。
    for slug in _unique_strings(active_skill_ids):
        if slug in skills and slug not in preload_skills:
            preload_skills.append(slug)

    context_patch: dict[str, Any] = {
        "skills": skills,
        "preload_skills": preload_skills,
        "subagents_enabled": bool(payload.get("subagents_enabled", True)),
    }
    if knowledge_enabled:
        configured_knowledges = (
            payload.get("knowledge_ids") if "knowledge_ids" in payload else agent_context.get("knowledges")
        )
        if isinstance(configured_knowledges, list):
            context_patch["knowledges"] = _unique_strings(configured_knowledges)
    else:
        context_patch["knowledges"] = []

    system_context = await build_system_context(
        db=db,
        user=user,
        session=session,
        focus=focus,
        create_artifact=create_artifact,
        research_mode=research_mode,
        research_section=research_section,
    )
    return {"system_prompt_append": system_context, "context": context_patch}


async def build_system_context(
    *,
    db: AsyncSession,
    user: User,
    session: EquipmentDeepSession,
    focus: str = "",
    create_artifact: bool = False,
    research_mode: str = SECTION_DEEPEN_MODE,
    research_section: str = "",
) -> str:
    """构建不进入用户可见消息的装备深研系统上下文。"""
    context = await get_session_research_context(
        db=db,
        user=user,
        session=session,
        compact=True,
    )
    payload = dict(session.payload or {})
    mode = normalize_deep_research_mode(research_mode)
    section = str(research_section or "").strip()[:64]
    rules = [
        "当前运行属于 equipment deep research 平台原生深研会话。",
        "以用户当前问题为任务，以关联栏目为研究目标。自主判断问题、规划研究路径、选择工具并组织回答；"
        "先前预设或历史焦点中的固定步骤、章节和检查清单仅作参考，不是本轮必经流程。"
        "用户当前明确要求优先于历史焦点；问题可推进时直接研究，仅在关键歧义会改变结论时澄清。",
        "研究深度随问题需要调整：简单追问直接回答，复杂问题可拆解、补证、比较、反思并调整方向。"
        "不要求每轮写完整报告，不强制七级链、固定标题、路线数量或来源数量。"
        "技能和待办按需使用；需要外部证据时默认委派调研探索员，单一问题不强制拆分或并行。",
        "本会话已启用公网检索能力。需要核实公开事实、时效信息或取得新证据时按需检索；"
        "论文问题在 academic_search 可用时优先使用 AMiner，其他公开事实使用 web_search。"
        "技术机理、技术路线、研究进展和技术选型同样优先检索 AMiner 论文证据，"
        "可用中英文术语和互补角度联合检索，筛选后补齐摘要，再判断工程适用性。"
        "关键或有争议的结论按证据强度交叉核验，引用时保留可点击的原始 URL；"
        "区分事实、推断、假设与未知，不编造来源、实验数据或工具结果。",
        "web_search 返回 status=degraded 时停止重试和同义改写，使用其他可用来源继续，"
        "说明影响结论的证据缺口；不得开启无界工具循环。",
        "需要关联任务、能力版本或研究产物的详细信息时调用 equipment_deep_context；不猜测内部数据。",
        "本会话具备沙盒文件工具与持久化工作区。用户要求文档、数据表、图表、HTML 或代码时，"
        "实际生成文件，核验后调用 present_artifacts 交付。"
        "文件交付独立于能力画像草案，开关关闭时仍可生成、预览、编辑和下载研究文件；"
        "用户只要求文件时不调用 save_equipment_capability_draft。需要交互页面时按需读取 html-preview 技能。",
        "普通研究按问题选择表达形式；只有用户要求成卡时才读取 equipment-deep-conversation 技能中的"
        " S6 五栏合同，并通过 save_equipment_capability_draft 新增待核验版本，原始和正式版本不可覆盖。",
        "用户可用 /diverge 开放新方向、/challenge 检验反例、/synthesize 综合、/card 成卡、/help 查看命令。"
        "/memory 表示只读查看当前决策记忆中的候选方向、裁决与待追问，且不启动新的发散或议事。",
    ]
    bound_name = str(payload.get("capability_name") or "").strip()
    bound_sections = payload.get("capability_sections") if isinstance(payload.get("capability_sections"), list) else []
    if mode == SECTION_DEEPEN_MODE:
        target = f"「{section}」栏目" if section else "用户当前指定的画像栏目或研究问题"
        rules.append(f"本轮研究模式为 section_deepen（深化当前装备），研究目标是{target}。")
        if bound_name:
            rules.append(
                f"当前研究对象为「{bound_name}」，不得擅自改写为另一种武器装备。"
                "可以质疑原卡假设、纠正描述、探索替代实现；其他栏目是理解目标的背景，不要求逐栏展开。"
                "用户明确改变研究对象或要求发散时遵循新要求。"
            )
        if section == "装备与技术实现":
            source_plan = (
                "Open Web、已授权本地知识库与 AMiner 三源均可用"
                if bool(payload.get("knowledge_enabled", True))
                else "Open Web 与 AMiner 可用，本会话未启用本地知识库"
            )
            rules.append(
                "当前为技术攻关舱。对需要新证据的原理、路线、器件、工艺、成熟度或可行性问题，"
                f"实际执行联合检索：{source_plan}。Open Web 核验标准、原厂、工程实现和供应链；"
                "本地知识库复用已有装备材料与内部研究；AMiner 挖掘科学原理、关键论文和技术进展。"
                "将有效发现映射到具体装备/分系统、作用原理、可实现技术、工程约束和验证判据，"
                "不停留在论文摘要、资料清单或泛技术名词。"
            )
            rules.append(
                "若研究后半段暴露出关键机理、构型、接口或工程可行性存疑，"
                "必须回溯失效假设，比较可替代原理和装备架构；必要时重新构建新质武器装备，"
                "而不是继续修补原结论。用户要求形成方案时，最终交付装备研发技术方案，"
                "凡技术方案在推演中形成、重构或替换武器装备，必须采用正式S3/S4同等的生成聚焦方式：先从战场矛盾和敌方任务链断点出发，"
                "闭合具体装备本体、接敌关系、作用载体与机理、作用对象、可观察直接战果和敌方原有应对失配原因，收敛为能够改变交战关系的"
                "具体作战制胜新质武器，再展开总体构型、分系统、关键技术和研发计划；不得先形成抽象技术方案再给算法、平台、节点或体系架构套上武器名称。"
                "题名固定为《武器装备研发技术方案报告》，"
                "副题为‘面向研发人员 · 技术路线设计 · 关键问题攻关 · 工程实现’。"
                "先写需求牵引、总体设计、核心技术与关键攻关三条报告主线，再给出‘章节—核心内容—主要回答的问题’导航表。"
                "正文依次使用七章：1.项目概述与研发需求；2.总体技术方案；3.核心技术体系；4.关键技术攻关；"
                "5.技术实现方案；6.技术路线与研发计划；7.预期成果与应用价值。"
                "闭合总体构型、作用原理、分系统与接口、关键材料/器件/算法/工艺、"
                "原理样机、分级试验、量化判据、阶段决策门与备选路线；不以资料综述代替。"
            )
    else:
        rules.append(
            "本轮研究模式为 new_weapon_diverge（发散新质武器），围绕关联场景和未来战争态势"
            "探索具有制胜优势、制衡对手价值的新方向。现有装备目录、能力画像、参考武器和既有技术路线只是启发基线，"
            "不是候选边界；发散维度、比较方法和收敛时机由问题与发现决定。先明确军事需求、任务链断点和"
            "制胜矛盾，再把前沿原理或技术落到具体可研制装备本体。候选应在作用机理、装备构型、任务链位置或制胜关系上"
            "真实不同，不得用换名、换载荷、泛化智能化、技术名词堆叠或小幅参数升级冒充新质方向。重点方向按问题需要说明"
            "创新断点、关键技术、工程瓶颈、失效边界、最低成本反制和可证伪验证；公开事实、类比迁移、模型推断与待验证假设分开。"
            "当用户要求形成武器装备时，采用正式S3/S4同等的生成聚焦方式而非末端检查表：候选从构想起点就是可单独指认、研制、部署和试验的物理武器实体，"
            "能够直接打击、毁伤、压制、拦截或拒止具体作战对象。能力方向、算法、软件、数据平台、指挥节点、通信中继、保障设施、"
            "网络或泛化体系架构只能作为装备分系统或支撑条件，不能单独作为候选。创造候选时始终围绕‘战场矛盾—敌方当前做法及断点—"
            "具体装备本体—接敌关系—作用载体与机理—作用对象—可观察直接战果—敌方原有应对为何失配’，名称必须体现创新核心和"
            "可识别的具体武器身份。用户未指定数量时，先在内部比较至少三种不同装备架构，最终只交付1至3个真正成立且彼此正交的候选，宁缺毋滥。"
            "当用户明确要求经过调研形成、提出、设计或发散新质创新武器装备时，先完成强研究路径，把高价值发现提炼为"
            "真正改变未来作战制衡与打赢判断的开放生成上下文，并以实现证据和不可跨越边界约束，"
            "再直接生成聚焦候选；不得先自由堆概念后靠字段、"
            "检查表或引用事后修补，也不得把论文摘要或网页摘录拼接成装备方案。"
            "此类单轮强研究不创建或更新待办；多个正交制胜子问题就是执行计划。最终正文所在响应不得调用write_todos或其他工具；"
            "若工具循环后再次输出，必须重述完整正文，不得只返回‘以上正文’或摘要尾声。"
        )
    if payload.get("knowledge_enabled", True):
        if mode == SECTION_DEEPEN_MODE and section == "装备与技术实现":
            rules.append("技术攻关舱允许为支撑技术落地主动检索本会话已授权知识库，无需用户额外 @知识库；必须标明来源。")
        else:
            rules.append("仅本轮用户显式 @知识库时可以检索本会话已授权知识库，并标明来源。")
    else:
        rules.append("本会话运行时已禁用知识库，不得声称检索了内部知识库。")
    if payload.get("subagents_enabled", True):
        rules.append(DEFAULT_RESEARCH_POLICY)
        if mode == NEW_WEAPON_DIVERGE_MODE:
            rules.append(
                "本轮可用 Subagent。若用户要求经过调研形成、提出、设计或发散新质装备，"
                "围绕面向未来作战需求、形成制衡对手并赢得制胜优势的具体装备，默认一次并行委派3个正交、可由证据回答的制胜子问题："
                "对手体系关键依赖、任务链断点与具体作用对象；重写作战方式的接敌关系、直接战果与成本交换；支撑新制胜机理的前沿原理、"
                "作用载体、关键分系统、工程可行性与成熟度边界。复杂跨域任务若存在会改变装备身份或总体构型的独立高价值轴，再追加第4个"
                "调研探索员，重点核查对手反制、反反制、环境适应或体系韧性；不得用同义问题凑数量。也可按当前Query替换为更有价值的正交"
                "制胜入口，但不得按网页、论文、国内外等资料类型分工。每次委派写清待作出的装备生成判断、证据缺口和会改变装备身份、构型或"
                "技术路线的发现；调研必须改变未来作战制衡与打赢判断或解决候选实现问题；"
                "网页检索通常用1至2个required_terms锚定核心身份对象，避免把三个不同证据点强制同页共现；每个探索员至少争取2个直接相关的一手或高权威网页来源，"
                "优先政府/军队、标准、论文出版页和原厂，已有原始来源时不用聚合媒体或转载页代替，同一论文转载只算一个来源。涉及技术实现的子问题必须使用AMiner并读取拟引用论文完整摘要。"
                "每个探索员取得4至6条高价值发现即简洁交付，不写检索过程和重复背景；Websearch通常3至5次，AMiner通常1至2次互补主题发现、必要时1次标题校正，"
                "只读取1至3篇强相关论文完整摘要。等待结果后由主智能体按‘高价值发现—改变的制胜关系—约束的装备身份/构型/技术路线—证据边界’"
                "综合并提炼为生成上下文，再直接创造聚焦候选。"
                "综合时以实际交付的论文题目、摘要层级和来源为准；单个分支为空不得覆盖其他分支已取得的论文证据。含DSML、XML、"
                "tool_calls或invoke的可见协议文本不算有效交付。"
                "若全部探索员未取得完整摘要且技术实现仍是候选成立的关键，主智能体在生成前直接补做一轮简短AMiner检索，"
                "补证先做一次不带related_queries的简短topic检索；为空时用web_search查核心技术的论文/DOI并从权威出版页或DOI入口提取准确标题，"
                "再用academic_search(mode=title)校正并对命中的1至3篇强相关论文集中读取完整摘要。完成标题桥接前不得宣称零命中。"
            )
    else:
        rules.append("本会话运行时已禁用 Subagent，不得委派子任务。")
    if bound_sections:
        rules.append("关联卡片与参考材料是可核验、可修正的研究背景，不是必须照抄的结论或冻结的推理路径。")
    if focus.strip():
        rules.append(f"会话初始焦点（当前问题有新要求时以当前问题为准）：{focus.strip()[:1600]}")
    if create_artifact:
        rules.extend(
            [
                "用户要求本轮形成能力画像草案；结论成熟后调用 save_equipment_capability_draft 保存待核验版本。",
                "能力画像必须严格遵循正式 S6 五栏合同，只能按以下顺序和精确栏名成稿："
                "（1）概述；（2）装备与技术实现；（3）关键作战流程；"
                "（4）形成能力与作战效果；（5）制胜逻辑机理。",
                "成卡不是一次盲写：先按五栏分别起草，再逐栏检查是否闭合职责、长度是否接近目标、"
                "是否与其他栏重复；发现短栏或缺失因果时先补写，全部通过自检后再调用保存工具。",
                "五栏各自承担独立论证：概述闭合场景、对象、定位与变化；装备与技术实现说明主路径、"
                "备选路径、构型、分系统、关键部件和工程取舍；关键作战流程闭合主体、条件、动作、"
                "状态变化、接口和转段；形成能力与作战效果区分新增任务、直接战果、体系收益和可观察判据；"
                "制胜逻辑机理闭合旧规则、作用链、交换关系、对手经济反制及其新增代价。",
                "每栏以 360–400 个有效中文字为常规目标，复杂因果尚未闭合时可适当略多；"
                "禁止按字符硬切，也不能用其他栏或总字数抵消短栏。禁止能力分类前缀、额外第六栏、"
                "栏名后缀（如‘修订’）、重复栏目和跨栏复用同一段落。",
                "保存时必须同时在 structured_fields 中提交 capability_portrait_modules 与"
                " capability_card_draft；两者均使用 overview、technology_implementation、"
                "operational_process、capability_effects、winning_logic 五个键。保存入口会再次校验，"
                "缺栏、重复栏或近乎空白将拒绝入库；360–400 字属于生成阶段的软目标，不得机械截断或凑字。",
            ]
        )
    else:
        rules.append(
            "当前消息已经明确确认更新或成卡时直接按 S6 合同保存，无需再次询问；"
            "否则不自动保存能力卡，不要每轮机械询问是否成卡。"
        )

    prefix = "\n".join([*rules, "", "<equipment_research_context>"])
    suffix = "\n</equipment_research_context>"
    encoded = json.dumps(context, ensure_ascii=False, separators=(",", ":"), default=str)
    # Account for the newline inserted between the opening tag and payload.
    available = max(0, _MAX_SYSTEM_PROMPT_APPEND_CHARS - len(prefix) - len(suffix) - 1)
    if len(encoded) > available:
        encoded = encoded[: max(0, available - 1)] + ("…" if available else "")
    return f"{prefix}\n{encoded}{suffix}"


def normalize_deep_research_mode(value: Any) -> str:
    """把外部研究模式收敛到安全的双模式协议。"""
    normalized = str(value or "").strip().lower()
    return normalized if normalized in _DEEP_RESEARCH_MODES else SECTION_DEEPEN_MODE


async def get_session_research_context(
    *,
    db: AsyncSession,
    user: User,
    session: EquipmentDeepSession,
    compact: bool = False,
) -> dict[str, Any]:
    """读取深研会话可见的任务、能力版本、产物与分支来源。"""
    if session.owner_uid != str(user.uid) and not has_global_business_access(user):
        raise HTTPException(status_code=404, detail="深研对话不存在")

    repo = EquipmentResearchRepository(db)
    run = await repo.get_run(session.run_id) if session.run_id else None
    if (
        run is not None
        and run.owner_uid != str(user.uid)
        and not has_global_business_access(user)
        and not run.legacy_source_id
    ):
        run = None

    capabilities = []
    artifacts = []
    if run is not None:
        capabilities = [
            _project_capability(item.to_dict(), compact=compact)
            for item in await repo.list_capability_versions_for_run(
                owner_uid=str(run.owner_uid) if has_global_business_access(user) else str(user.uid),
                run_id=run.id,
                limit=12,
            )
        ]
        artifacts = [item.to_dict() for item in await repo.list_artifact_refs(run.id, limit=30)]

    payload = dict(session.payload or {})
    branch_context = await _branch_context(db=db, user=user, payload=payload)
    return {
        "schema_version": DEEP_SESSION_SCHEMA_VERSION,
        "session_id": session.id,
        "topic": str(payload.get("topic") or ""),
        "focus": str(payload.get("focus") or ""),
        "capability_name": str(payload.get("capability_name") or ""),
        "capability_card_key": str(payload.get("capability_card_key") or ""),
        "capability_sections": [
            {
                "label": str(item.get("label", "") or "").strip()[:64],
                "text": str(item.get("text", "") or "").strip()[:1200],
            }
            for item in (payload.get("capability_sections") or [])[:8]
            if isinstance(item, Mapping) and str(item.get("label", "") or "").strip()
        ],
        "reference_weapons": [
            {
                "hypothesis_id": str(item.get("hypothesis_id") or "")[:256],
                "title": str(item.get("title") or "")[:400],
                "primary_equipment_identity": str(item.get("primary_equipment_identity") or "")[:400],
                "equipment_forms": [
                    str(value)[:400] for value in (item.get("equipment_forms") or [])[:8] if str(value).strip()
                ],
                "overview": str(item.get("overview") or "")[:3000],
                "score": item.get("score"),
            }
            for item in (payload.get("reference_weapons") or [])[:8]
            if isinstance(item, Mapping) and str(item.get("hypothesis_id") or "").strip()
        ],
        "run": _project_run(run, compact=compact) if run is not None else None,
        "capability_versions": capabilities,
        "artifacts": artifacts,
        "branch_context": branch_context,
    }


def _clean_s6_module_text(value: Any) -> str:
    """Normalize one authored S6 column without truncating its argument."""

    text = str(value or "").strip()
    text = re.sub(r"^(?:[-*+]\s*)+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _parse_s6_portrait_text(value: Any) -> tuple[dict[str, str], list[str]]:
    """Parse canonical and legacy/suffixed headings, reporting duplicates."""

    text = str(value or "").strip()
    if not text:
        return {}, []
    matches = list(_S6_HEADING_RE.finditer(text))
    modules: dict[str, str] = {}
    duplicates: list[str] = []
    labels = dict(S6_PORTRAIT_MODULES)
    for index, match in enumerate(matches):
        key = _S6_LABEL_TO_KEY[match.group("label")]
        body = _clean_s6_module_text(
            text[match.end() : matches[index + 1].start() if index + 1 < len(matches) else len(text)]
        )
        if key in modules:
            duplicates.append(labels[key])
            continue
        if body:
            modules[key] = body
    return modules, duplicates


def _mapping_s6_modules(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    modules: dict[str, str] = {}
    for key, _label in S6_PORTRAIT_MODULES:
        for alias in _S6_KEY_ALIASES[key]:
            body = _clean_s6_module_text(value.get(alias))
            if body:
                modules[key] = body
                break
    return modules


def _s6_chinese_char_count(value: str) -> int:
    return len(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]", value))


def normalize_s6_capability_draft(
    *,
    capability_image: str,
    structured_fields: Mapping[str, Any] | None = None,
) -> tuple[str, dict[str, str], dict[str, Any]]:
    """Validate and normalize a deep-conversation draft to the formal S6 contract.

    Structured modules are accepted because agents may provide both transport
    forms. Missing structured values are filled from the prose card. The
    normalized result always owns the canonical headings and storage keys.
    """

    structured = dict(structured_fields or {})
    parsed, duplicates = _parse_s6_portrait_text(capability_image)
    if duplicates:
        raise HTTPException(
            status_code=422,
            detail="S6 能力画像存在重复栏目：" + "、".join(dict.fromkeys(duplicates)),
        )

    candidates = (
        structured.get("capability_portrait_modules"),
        structured.get("capability_card_draft"),
        structured,
    )
    modules: dict[str, str] = {}
    for candidate in candidates:
        for key, body in _mapping_s6_modules(candidate).items():
            modules.setdefault(key, body)
    for key, body in parsed.items():
        modules.setdefault(key, body)

    missing = [label for key, label in S6_PORTRAIT_MODULES if not modules.get(key)]
    if missing:
        raise HTTPException(
            status_code=422,
            detail="S6 能力画像必须包含完整五栏，缺少：" + "、".join(missing),
        )

    short = [
        f"{label}（{_s6_chinese_char_count(modules[key])}字）"
        for key, label in S6_PORTRAIT_MODULES
        if _s6_chinese_char_count(modules[key]) < S6_PORTRAIT_HARD_MIN_CHARS
    ]
    if short:
        raise HTTPException(
            status_code=422,
            detail=(
                "S6 能力画像栏目明显过短："
                + "、".join(short)
                + f"；每栏至少 {S6_PORTRAIT_HARD_MIN_CHARS} 个有效中文字，"
                + f"并以 {S6_PORTRAIT_SOFT_TARGET_CHARS}–400 字为常规目标"
            ),
        )

    normalized_modules = {key: modules[key] for key, _label in S6_PORTRAIT_MODULES}
    portrait = "\n".join(f"{label}：{normalized_modules[key]}" for key, label in S6_PORTRAIT_MODULES)
    normalized_structured = dict(structured)
    normalized_structured["capability_portrait_modules"] = dict(normalized_modules)
    normalized_structured["capability_card_draft"] = dict(normalized_modules)
    normalized_structured["s6_portrait_contract"] = {
        "version": "s6-five-column-v1",
        "labels": [label for _key, label in S6_PORTRAIT_MODULES],
        "soft_target_chinese_chars": [S6_PORTRAIT_SOFT_TARGET_CHARS, 400],
        "hard_min_chinese_chars": S6_PORTRAIT_HARD_MIN_CHARS,
    }
    normalized_structured["s6_portrait_quality"] = {
        "chinese_chars": {key: _s6_chinese_char_count(normalized_modules[key]) for key, _label in S6_PORTRAIT_MODULES},
        "below_soft_target": [
            key
            for key, _label in S6_PORTRAIT_MODULES
            if _s6_chinese_char_count(normalized_modules[key]) < S6_PORTRAIT_SOFT_TARGET_CHARS
        ],
    }
    return portrait, normalized_modules, normalized_structured


async def save_capability_draft(
    *,
    db: AsyncSession,
    user: User,
    session_id: str,
    name: str,
    capability_image: str,
    rationale: str = "",
    evidence_refs: Sequence[str] = (),
    structured_fields: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """从平台原生深研会话新增一条待核验能力画像版本。"""
    repo = EquipmentResearchRepository(db)
    session = await repo.get_deep_session(session_id)
    if session is None or (session.owner_uid != str(user.uid) and not has_global_business_access(user)):
        raise HTTPException(status_code=404, detail="深研对话不存在")
    normalized_name = str(name or "").strip()
    normalized_image = str(capability_image or "").strip()
    if not normalized_name or (not normalized_image and not structured_fields):
        raise HTTPException(status_code=422, detail="能力名称和能力画像不能为空")
    normalized_image, normalized_modules, normalized_structured = normalize_s6_capability_draft(
        capability_image=normalized_image,
        structured_fields=structured_fields,
    )

    resource_owner_uid = str(session.owner_uid)
    existing = (
        await repo.list_capability_versions_for_run(
            owner_uid=resource_owner_uid,
            run_id=session.run_id,
            limit=100,
        )
        if session.run_id
        else []
    )
    version_no = 1 + max(
        (int((item.snapshot or {}).get("version_no") or 0) for item in existing),
        default=0,
    )
    session_payload = dict(getattr(session, "payload", {}) or {})
    parent_capability_id = str(session_payload.get("capability_card_key") or "").strip()
    parent_capability_name = str(session_payload.get("capability_name") or "").strip()
    version = EquipmentCapabilityVersion(
        id=f"capver-{uuid4()}",
        project_id=session.project_id,
        owner_uid=resource_owner_uid,
        run_id=session.run_id,
        snapshot={
            "schema_version": "equipment-capability-draft-v2",
            "version_no": version_no,
            "status": "pending_verification",
            "source": "equipment_deep_research_conversation",
            "session_id": session.id,
            "parent_capability_id": parent_capability_id[:256],
            "parent_card_key": parent_capability_id[:256],
            "parent_capability_name": parent_capability_name[:400],
            "name": normalized_name[:400],
            "deep_capability_portrait": normalized_image[:24_000],
            "capability_image": normalized_image[:24_000],
            "capability_portrait_modules": normalized_modules,
            "capability_card_draft": dict(normalized_modules),
            "rationale": str(rationale or "").strip()[:6000],
            "evidence_refs": _unique_strings(evidence_refs)[:32],
            "structured_fields": _bounded_value(normalized_structured, depth=0),
        },
    )
    await repo.add_capability_version(version)
    await audit_superadmin_personal_resource_write(
        db,
        actor=user,
        action="create_draft",
        resource_type="capability_version",
        resource_id=version.id,
        owner_uid=resource_owner_uid,
    )
    await db.commit()
    return version.to_dict()


async def _branch_context(*, db: AsyncSession, user: User, payload: dict[str, Any]) -> dict[str, Any] | None:
    parent_session_id = str(payload.get("parent_session_id") or "").strip()
    if not parent_session_id:
        return None
    repo = EquipmentResearchRepository(db)
    parent = await repo.get_deep_session(parent_session_id)
    if parent is None or (parent.owner_uid != str(user.uid) and not has_global_business_access(user)):
        return None
    parent_thread_id = str((parent.payload or {}).get("thread_id") or "")
    conversation = await ConversationRepository(db).get_conversation_by_thread_id(parent_thread_id)
    transcript = []
    if conversation is not None and conversation.uid == str(parent.owner_uid):
        stop_at = str(payload.get("branch_from_message_id") or "")
        for item in await ConversationRepository(db).get_messages(conversation.id):
            if item.role in {"user", "assistant"} and str(item.content or "").strip():
                transcript.append(
                    {
                        "message_id": str(item.id),
                        "role": item.role,
                        "content": str(item.content)[:1200],
                    }
                )
            if stop_at and str(item.id) == stop_at:
                break
    return {
        "parent_session_id": parent_session_id,
        "from_message_id": str(payload.get("branch_from_message_id") or ""),
        "transcript": transcript[-12:],
    }


def _project_run(run, *, compact: bool = False) -> dict[str, Any]:
    payload = dict(run.payload or {})
    payload_keys = (
        "summary",
        "research_focus",
        "selected_agent_ids",
        "discovery_branch",
        "capability_count",
    ) if compact else (
        "summary",
        "result",
        "research_focus",
        "selected_agent_ids",
        "discovery_branch",
        "capability_count",
    )
    projected_payload = {
        key: _bounded_value(payload[key], depth=0)
        for key in payload_keys
        if key in payload
    }
    if compact and isinstance(payload.get("result"), Mapping):
        result = payload["result"]
        projected_payload["result"] = {
            key: _bounded_value(result[key], depth=0)
            for key in ("status", "route", "artifact_counts", "capability_count")
            if key in result
        }
    return {
        "run_id": run.id,
        "topic": run.topic,
        "status": run.status,
        "research_route": run.research_route,
        "readonly": bool(run.readonly),
        "payload": projected_payload,
    }


def _project_capability(value: dict[str, Any], *, compact: bool = False) -> dict[str, Any]:
    snapshot = value.get("snapshot") if isinstance(value.get("snapshot"), dict) else {}
    snapshot_keys = (
        "version_no",
        "status",
        "source",
        "name",
        "capability_name",
        "evidence_refs",
        "hypothesis_id",
        "card_binding_id",
    ) if compact else (
        "version_no",
        "status",
        "source",
        "name",
        "capability_name",
        "capability_image",
        "rationale",
        "evidence_refs",
        "hypothesis_id",
        "card_binding_id",
    )
    projected = {
        key: _bounded_value(snapshot[key], depth=0)
        for key in snapshot_keys
        if key in snapshot
    }
    return {
        "version_id": value.get("version_id"),
        "run_id": value.get("run_id"),
        "snapshot": projected,
        "created_at": value.get("created_at"),
    }


def _bounded_value(value: Any, *, depth: int) -> Any:
    if depth >= 3:
        return "[已截断]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:2400]
    if isinstance(value, Mapping):
        return {str(key)[:120]: _bounded_value(item, depth=depth + 1) for key, item in list(value.items())[:24]}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_bounded_value(item, depth=depth + 1) for item in list(value)[:24]]
    return str(value)[:800]


def _unique_strings(values: Any) -> list[str]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        return []
    return list(dict.fromkeys(str(item).strip() for item in values if str(item).strip()))


def _merge_deep_runtime_overrides(
    domain_overrides: Mapping[str, Any],
    requested_overrides: Mapping[str, Any] | None,
    *,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """合并本轮选择，同时保持深研会话的能力上限与系统上下文。"""
    merged = dict(domain_overrides)
    domain_context = dict(domain_overrides.get("context") or {})
    requested = dict(requested_overrides or {})
    requested_context = requested.get("context")
    if isinstance(requested_context, Mapping):
        requested_knowledges = requested_context.get("knowledges")
        if isinstance(requested_knowledges, list):
            selected = _unique_strings(requested_knowledges)
            session_scope = payload.get("knowledge_ids")
            if not bool(payload.get("knowledge_enabled", True)):
                selected = []
            elif isinstance(session_scope, list):
                allowed = set(_unique_strings(session_scope))
                selected = [item for item in selected if item in allowed]
            domain_context["knowledges"] = selected

        requested_skills = requested_context.get("skills")
        if isinstance(requested_skills, list):
            allowed_skills = set(_unique_strings(domain_context.get("skills")))
            domain_context["skills"] = [item for item in _unique_strings(requested_skills) if item in allowed_skills]

        requested_preloads = requested_context.get("preload_skills")
        if isinstance(requested_preloads, list):
            allowed_preloads = set(_unique_strings(domain_context.get("preload_skills")))
            domain_context["preload_skills"] = [
                item for item in _unique_strings(requested_preloads) if item in allowed_preloads
            ]

        if isinstance(requested_context.get("subagents_enabled"), bool):
            domain_context["subagents_enabled"] = bool(
                domain_context.get("subagents_enabled", True) and requested_context["subagents_enabled"]
            )
    merged["context"] = domain_context

    requested_prompt = requested.get("system_prompt_append")
    if isinstance(requested_prompt, str) and requested_prompt.strip():
        domain_prompt = str(domain_overrides.get("system_prompt_append") or "").rstrip()
        combined_prompt = (
            f"{domain_prompt}\n\n{requested_prompt.strip()}" if domain_prompt else requested_prompt.strip()
        )
        merged["system_prompt_append"] = combined_prompt[:_MAX_SYSTEM_PROMPT_APPEND_CHARS]
    return merged
