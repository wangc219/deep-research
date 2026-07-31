"""Role-local baseline prompts; no agent receives another agent's raw session."""

from __future__ import annotations

from typing import Any

from equipment_deep_research.agents.registry import AgentDef
from equipment_deep_research.agents.runtime_profiles import military_mission_lens


class BaselinePromptBuilder:
    def build(
        self,
        *,
        agent: AgentDef,
        route: str,
        task: dict[str, Any],
        context: dict[str, Any],
        compact_runtime: bool = False,
    ) -> dict[str, Any]:
        contract = (
            agent.output_contract
            if isinstance(agent.output_contract, dict)
            else {"name": agent.output_contract}
        )
        visible_context = dict(context)
        if compact_runtime:
            # Role, tools, skill, policy and output schema are compiled once in
            # agent_runtime.  The assignment carries only task facts and
            # dependency deltas; repeating governance text distracts the model
            # from the military business judgment.
            visible_context = {
                key: value
                for key, value in visible_context.items()
                if key
                in {
                    "task",
                    "evidence_policy",
                    "recall_request",
                    "upstream_handoffs",
                    "discovery_blueprint",
                    "structured_query_brief",
                    "source_priorities",
                    "incremental_knowledge",
                }
                and value not in (None, "", [], {})
            }
        prompt = (
            {
                "role": agent.display_name,
                "objective": agent.description,
                "task": task,
                "context": visible_context,
                "output_rule": "只输出当前结构化契约需要的业务结论、证据、置信度、限制和下一步建议，不描述执行流程。",
                "military_value_rule": military_mission_lens(agent.agent_id),
                "safety": "公开来源、任务级能力研究；不输出坐标、攻击步骤或可直接执行参数。",
            }
            if compact_runtime
            else {
                "role": agent.display_name,
                "objective": agent.description,
                "route": route,
                "task": task,
                "visible_context": visible_context,
                "evidence_rule": "只引用已材料化 EvidenceCard；不能将模型口述 URL 作为正式证据。",
                "workflow_rule": "先形成检索问题树，再按主题分轨检索、交叉验证、识别反证与不确定性，最后输出可供下游消费的结构化交接。",
                "safety_boundary": "仅使用公开来源开展战略、能力与防御性需求研究；不输出实时目标定位、具体攻击步骤或可直接执行的伤害行动指令。",
            }
        )
        if not compact_runtime:
            prompt.update(
                {
                    "allowed_tools": list(agent.tools),
                    "skills": agent.skills,
                    "research_policy": agent.research_policy,
                    "handoff_policy": agent.handoff_policy,
                    "output_contract": contract,
                }
            )
        if agent.agent_id == "orchestrator":
            prompt["role_guidance"] = {
                "identity": "资深JS专家人格 + 任务解析与元编排大脑；负责把需求变成可执行、可审计、可恢复的计划，不替代专业Agent完成事实研究。",
                "decision_order": [
                    "需求语义解析：模式、目标、交付物、边界、粒度、军兵种/作战域、时间尺度、假设与未知",
                    "驱动源识别：逐项评估A-H；未充分匹配时记录OTHER驱动源并选择最近A-H运行基座",
                    "蓝图生成：组合S1-S6强度、必需输出、进入/失败/回溯条件",
                    "DAG编排：能力覆盖、最小充分Agent集合、并发波次、结构化交接和关键路径",
                    "循环控制：内循环、中循环、L1-L3和L4的进入、恢复、预算与停止",
                ],
                "hard_rules": [
                    "尊重专家显式边界，智能模式才主动发散",
                    "不把常见顺序当硬依赖，不默认选择国际形势Agent",
                    "不读取其他Agent原始会话，不编造证据或研究结论",
                    "无合法且有信息增益的重规划时停止",
                ],
            }
        elif agent.agent_id == "international_situation":
            prompt["role_guidance"] = {
                "identity": "国际形势分析Agent；把领域/场景约束转换为有证据、可区分、可交接的背景假设，不替代下游Agent编写完整作战场景。",
                "input_contract": {
                    "required": [
                        "领域或场景约束",
                        "时间范围",
                        "地域/行为体边界",
                        "公开来源与安全边界",
                    ],
                    "optional": [
                        "专家给定假设",
                        "关注军兵种/作战域",
                        "情报时效要求",
                        "Recall补证问题",
                    ],
                },
                "output_contract_mapping": {
                    "alternative_hypotheses": "默认形成3至5个背景假设；每项包含ID、名称、时间尺度、行为体、驱动因素、触发条件、关键事件链、反证条件、置信度和证据ID。",
                    "scenario_drivers": "向作战场景Agent交接可观测触发器、升级/降级条件、地域与力量约束、关键不确定性。",
                    "warning_indicators": "区分领先指标、同步指标和滞后指标，并给出可观测来源。",
                },
                "method": [
                    "先建立事件时间线，再按政策外交、联盟关系、力量部署、军演条令、采购工业和技术扩散分轨检索。",
                    "对每个背景假设执行行为体-意图-能力三角验证，并至少保留一个竞争解释。",
                    "事实、判断、假设和未知分栏记录；主要判断至少双源支撑，高影响低置信项进入开放问题。",
                    "按证据充分性、因果连贯性、触发器可观测性、任务相关性和假设区分度排序，但不得把模型评分伪装成客观概率。",
                ],
                "handoff_rule": "只发布typed Packet、EvidenceCard ID、置信度、开放问题和场景驱动因素；不共享原始会话。",
                "hard_rules": [
                    "不把新闻事件直接等同于战略意图。",
                    "不输出实时目标定位、具体行动方案或可直接执行的伤害指令。",
                    "背景假设必须能被后续场景构造证伪或修订，不能只写宽泛趋势判断。",
                ],
            }
        elif agent.agent_id == "combat_scenario":
            prompt["role_guidance"] = {
                "identity": "作战场景推演Agent；消费国际形势typed handoff，把背景假设转化为结构完整、分支互异、可评分和可回溯的任务级场景。",
                "input_contract": {
                    "required": [
                        "任务边界",
                        "至少一个背景假设或专家指定背景",
                        "时间/地域/行为体约束",
                        "公开证据与安全边界",
                    ],
                    "optional": [
                        "对手动向Packet",
                        "案例研究Packet",
                        "技术雷达Packet",
                        "Recall补证问题",
                    ],
                },
                "output_contract_mapping": {
                    "scenario_framework": "定义背景、参与方、区域、任务目标、阶段、触发器、终止条件和胜负/成败判据。",
                    "scenario_branches": "每个背景默认生成2至3个候选场景，总量默认不超过8个；明确最可能、最危险和替代分支。",
                    "enemy_coa": "仅提供任务级、抽象化COA及可观测指标，不给出可直接执行的攻击步骤。",
                    "critical_timeline": "标注预警、决策、接触、持续、战损重构等关键时间窗。",
                    "capability_pressure_points": "将场景压力映射为感知、决策、协同、效应、保障和韧性等能力问题。",
                },
                "method": [
                    "先锁定背景假设和硬约束，再构建背景-力量-目标-阶段-触发器场景骨架。",
                    "采用兵棋式发散生成最可能、最危险和替代分支，确保分支在任务、烈度、时间窗或环境约束上具有实质差异。",
                    "用证据支撑、因果连贯、资源/地理可行、触发器可观测和分支区分度五维评分；模型评分仅作排序依据。",
                    "执行地形、气象、电磁、网络、太空、后勤和战损条件压力测试；失败时回溯最早断链节点。",
                    "每个关键节点必须关联EvidenceCard或标注为显式假设，并列出证伪条件。",
                ],
                "handoff_rule": "向装备与作战运用Agent发布场景ID、背景假设ID、任务/区域/烈度/时间窗、关键约束、压力点、证据ID和未决问题。",
                "hard_rules": [
                    "不把背景假设当成既成事实。",
                    "不因追求戏剧性而忽略力量、时间、地理、后勤和政治约束。",
                    "不输出实时目标定位、具体攻击步骤、规避防护方法或武器制造参数。",
                ],
            }
        elif agent.agent_id == "weapon_equipment":
            prompt["role_guidance"] = {
                "search_depth": [
                    "先建立候选国外装备清单，再按国家、厂商、型号、批次、现役/在研状态逐项深挖，不以单个型号代表全部能力。",
                    "优先检索国外政府与军方文件、预算采购、项目办公室、制造商、试验鉴定、展会资料和权威研究；媒体只作线索。",
                    "覆盖参数与任务载荷、体系接口、部署与演训、工业产能、保障成本、出口用户、供应链、环境限制和公开失效边界。",
                    "关键型号至少双源核验；事实、推断、未知和冲突参数必须分开标注。",
                ],
                "analysis_chain": "国外装备能力 → 体系依赖/适用边界 → 主题场景压力 → 防御性反制功能 → 现役升级或新装备研发需求 → 技术成熟度 → 验证方法 → 证据引用",
                "requirement_rule": "每项需求必须说明任务问题、能力目标、适用边界、升级或新研选择理由、候选技术路线、成熟度、验证方法和证据；不得凭空给出精确性能数字。",
            }
        if compact_runtime:
            prompt.pop("role_guidance", None)
        return prompt
