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
_REQUIRED_SKILLS = (DEEP_SKILL_SLUG, "equipment-research", "deep-research")
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
    for slug in (*_REQUIRED_SKILLS, *_unique_strings(active_skill_ids)):
        if slug in accessible_set and slug not in skills:
            skills.append(slug)

    knowledge_enabled = bool(payload.get("knowledge_enabled", True))
    if knowledge_enabled:
        if "knowledge-base" in accessible_set and "knowledge-base" not in skills:
            skills.append("knowledge-base")
    else:
        skills = [slug for slug in skills if slug != "knowledge-base"]

    configured_preloads = _unique_strings(agent_context.get("preload_skills"))
    preload_skills = [slug for slug in configured_preloads if slug in skills]
    for slug in (*_REQUIRED_SKILLS, "knowledge-base" if knowledge_enabled else ""):
        if slug and slug in skills and slug not in preload_skills:
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
    context = await get_session_research_context(db=db, user=user, session=session)
    payload = dict(session.payload or {})
    mode = normalize_deep_research_mode(research_mode)
    section = str(research_section or "").strip()[:64]
    rules = [
        "当前运行属于 equipment deep research 平台原生深研会话。",
        "延续原武器装备深研的方法：区分事实、推断和未知项，围绕作战场景、制胜机理、技术路径与能力画像形成证据链。",
        "本会话已启用公网检索能力。凡涉及公开论文、专利、标准、机构资料、技术现状、工程数据或时效性事实，"
        "必须优先调用 web_search，"
        "对关键结论使用至少两个独立来源交叉核验，并在答案中保留可点击的原始 URL；不得声称本次运行无公网检索能力。",
        "公网检索结果只是外部证据候选：优先政府、军队、标准组织、科研机构、原始论文和专利，明确区分已证实事实、合理推断与仍待验证项。",
        (
            "web_search 已在工具层完成有界重试、后端切换和熔断；若返回 status=degraded，"
            "当前 Agent 与 Subagent 必须停止公网重试和同义改写，优先调用一次 query_kbs 做跨库检索，"
            "再基于已有来源完成回答并标注具体证据缺口。不得以‘继续尝试’开启无界工具循环。"
        ),
        "需要读取关联任务、能力版本或研究产物时，优先调用 equipment_deep_context 工具，不要猜测内部数据。",
        "形成能力画像草案时保持原版本不可变，只能通过 save_equipment_capability_draft 新增待核验版本。",
        "用户可以输入深研命令：/diverge 表示重新开放发散正交假设，/challenge 表示对抗检验反例与失效边界，"
        "/synthesize 表示综合归纳已有方向，/memory 表示只读查看当前决策记忆中的候选方向、裁决与待追问，"
        "且不启动新的发散或议事，/card 表示使用已收敛方向形成五栏能力卡，/help 表示列出这些命令。",
    ]
    if mode == SECTION_DEEPEN_MODE:
        target = f"「{section}」栏目" if section else "用户当前指定的画像栏目或研究问题"
        rules.extend(
            [
                f"本轮研究模式为 section_deepen（深化当前装备），研究目标是{target}。",
                "必须保持当前装备身份、装备名称和核心任务定位不变；可以深化、拆解或修正制胜机理，但不得擅自改写为另一种武器装备，也不得输出其他装备候选清单。",
                "优先围绕研发该武器的关键技术卡点和工程痛点展开：分析卡点成因、指标耦合、系统集成难题，比较构型、材料、算法、接口、部署和保障等攻关路线及取舍。",
                "同步推演作战流程和制胜逻辑，说明关键技术如何转化为作战动作、体系能力与制胜优势，并把机理要求反推到技术实现。",
                "形成可直接修订画像栏目的具体结论；证据缺口、失效边界和验证动作仅在影响方案成立、路线选择或研发决策时补充，不得机械凑齐固定模板。",
                "只有用户显式切换为 new_weapon_diverge、明确要求发散新质武器，或发送 /diverge，"
                "才允许突破当前装备身份。",
            ]
        )
        if section == "装备与技术实现":
            rules.extend(
                [
                    "当前栏目启用技术攻关舱通用工程化契约：前序核验、反驳和概念纠偏只作为方案设计输入，"
                    "不得让最终成果再次退化为以纠错为主体的报告。",
                    "研究必须遵循七级因果链，前一级结论成为后一级输入，并保持双向可追溯："
                    "（1）能力目标——要形成什么能力，明确场景、对象、边界、指标与验收判据；"
                    "（2）装备总体设计——装备总体怎么设计，明确构型、分系统、功能、模式和接口；"
                    "（3）技术体系——主要依靠哪些技术，建立能力—分系统—核心/支撑/基础/部件技术映射；"
                    "（4）关键技术识别——哪些技术最关键，按瓶颈性、不可替代性、依赖传播和成熟度排序；"
                    "（5）突破难点——哪些地方最难突破，给出极限、冲突、根因、失效模式和突破判据；"
                    "（6）解决路径——有哪些解决路径，对候选路线比较原理、收益、依赖、代价、风险和决策门；"
                    "（7）具体实现——具体如何实现，落实原理、算法、结构、材料、器件、控制、软件、工艺、集成和试验。",
                    "当用户要求形成、汇总、定稿或交付研究方案时，正文必须依次使用上述七个一级标题；"
                    "不得跳过能力目标直接罗列技术，也不得把关键技术、突破难点和解决路径混写成一个术语清单。",
                    "七个主体都要服务一线研发执行，落实到分系统、输入输出接口、指标与预算、阶段任务包、"
                    "可验收交付物和通过判据；同时补齐信号/能量/控制链、样机阶段、WBS、试验矩阵、"
                    "里程碑与决策门、风险/FMEA/降级策略和30/60/90天启动包。",
                    "对缺少可靠依据的精确参数必须标注为‘工程假设/TBD’，给出预算或实测闭合方法；"
                    "不得用术语清单、泛化建议或伪造精确数值代替工程实现。",
                    "已有技术攻关任务书或纠偏报告时，最终研发方案应作为新的独立交付物保存，不得覆盖原交付物。",
                ]
            )
    else:
        rules.extend(
            [
                "本轮研究模式为 new_weapon_diverge（发散新质武器）。",
                "以关联 Query 场景及未来战争态势为核心问题空间，开放发散能够形成制胜优势、"
                "制衡对手的新质创新颠覆武器装备。",
                "现有装备目录、能力画像、参考武器和既有技术路线只是启发基线，不是候选边界；从任务链反转、作用机理、装备构型、交战窗口、成本交换和对手反适应等维度形成彼此正交的候选，再按作战价值、颠覆性与可行性收敛。",
                "先给出候选与可见取舍；用户明确确认方向或要求成卡后，才将新装备身份保存为待核验草案。",
            ]
        )
    if payload.get("knowledge_enabled", True):
        rules.append("需要外部或内部事实依据时可以检索本会话已授权知识库，并标明来源与证据缺口。")
    else:
        rules.append("本会话运行时已禁用知识库，不得声称检索了内部知识库。")
    if payload.get("subagents_enabled", True):
        rules.append("适合并行拆解或交叉核验时可以调用平台 Subagent，并在汇总前等待必要结果。")
    else:
        rules.append("本会话运行时已禁用 Subagent，不得委派子任务。")
    bound_name = str(payload.get("capability_name") or "").strip()
    bound_sections = payload.get("capability_sections") if isinstance(payload.get("capability_sections"), list) else []
    reference_weapons = payload.get("reference_weapons") if isinstance(payload.get("reference_weapons"), list) else []
    if bound_sections:
        if mode == SECTION_DEEPEN_MODE:
            rules.append(
                f"当前已锁定能力画像卡「{bound_name or '当前装备'}」及其栏目；只深化该装备，"
                "引用其他武器时只能用于证据对照，不得混淆或替换装备身份。"
            )
            rules.append("形成修订时明确列出本栏保留、补充、纠错和待核验内容；需要沉淀时以同一装备身份新增待核验版本。")
        else:
            rules.append(
                f"当前已注入能力画像卡「{bound_name or '当前装备'}」及所绑定栏目；"
                "它们是启发基线、待突破假设和对照坐标，不是新质装备候选边界。"
            )
    if reference_weapons:
        reference_names = "、".join(
            str(item.get("title") or item.get("primary_equipment_identity") or "").strip()
            for item in reference_weapons[:8]
            if isinstance(item, Mapping)
        )
        if mode == SECTION_DEEPEN_MODE:
            rules.append(f"参考武器「{reference_names}」仅用于技术、证据与对抗边界对照；不得据此更换当前装备身份。")
        elif bound_sections:
            rules.append(
                f"参考武器「{reference_names}」仅作为对照与启发基线；不得混淆装备身份，但可以从其边界反推正交的新质装备方向。"
            )
        else:
            rules.append(
                f"参考武器「{reference_names}」是本轮启发与对照基线，不是候选边界；"
                "应从其能力缺口和对手反适应出发继续开放发散。"
            )
    if focus.strip():
        rules.append(f"本轮研究焦点：{focus.strip()[:1600]}")
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
            "若本轮已经形成足以实质修改原能力卡的成熟结论，应在回答末尾用一句话询问用户是否"
            "基于本轮结论形成新的待核验能力卡；在用户明确确认前不得调用保存工具。不要每轮机械询问，"
            "只有结论足以更新至少一个 S6 栏目时才提出。若用户当前消息已经明确确认更新或成卡，"
            "则直接按正式 S6 五栏合同完成逐栏起草、自检并调用保存工具，无需再次询问。"
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
            _project_capability(item.to_dict())
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
        "run": _project_run(run) if run is not None else None,
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


def _project_run(run) -> dict[str, Any]:
    payload = dict(run.payload or {})
    projected_payload = {
        key: _bounded_value(payload[key], depth=0)
        for key in (
            "summary",
            "result",
            "research_focus",
            "selected_agent_ids",
            "discovery_branch",
            "capability_count",
        )
        if key in payload
    }
    return {
        "run_id": run.id,
        "topic": run.topic,
        "status": run.status,
        "research_route": run.research_route,
        "readonly": bool(run.readonly),
        "payload": projected_payload,
    }


def _project_capability(value: dict[str, Any]) -> dict[str, Any]:
    snapshot = value.get("snapshot") if isinstance(value.get("snapshot"), dict) else {}
    projected = {
        key: _bounded_value(snapshot[key], depth=0)
        for key in (
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
