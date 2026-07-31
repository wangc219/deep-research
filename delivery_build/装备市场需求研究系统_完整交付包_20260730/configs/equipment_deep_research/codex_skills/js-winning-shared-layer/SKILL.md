---
name: js-winning-shared-layer
description: Codex CLI 制胜智能体共享方法与知识访问层，用于 S1-S6、批判、动态专用子 Agent 和 L1-L4 循环。
---

# JS 制胜智能体共享层

仅当系统提示明确要求使用 `$js-winning-shared-layer` 时启用。

## 权威顺序

1. `agent_runtime.dynamic_agent_contract` 或当前固定 Agent 角色契约。
2. `task_input.discovery_blueprint` 的 A-H/OTHER 路径、S1-S6 强度与循环预算。
3. `agent_runtime.skills` 中本回合激活的专用与共享 Skill。
4. `agent_runtime.knowledge_packs` 和 `task_input.knowledge_pack_catalog` 中允许访问的知识包。
5. `task_input.evidence_index`、结构化 Packet 和前序节点输出。

不得读取其他 Agent 原始会话，不得在工作区漫游寻找未授权知识，不得把知识包描述当作事实证据。

## Tree-of-Warfare 节点契约

每个 S1-S6 节点除专用字段外，必须输出：

- `recognition`：可审计结论，不包含隐藏思维过程；
- `evidence_refs`：输入中真实存在的 EvidenceCard 或 Packet ID；
- `confidence`：0 到 1，并与证据强度一致；
- `next_action`：`continue|parallel|backtrack|recall|stop`、目标步骤和理由。

低质量节点只修复当前节点；跨步骤断链从最早不完整节点回溯。达到循环上限或没有信息增益时停止并披露限制。

## 共享方法

- DeepSearch：分轨检索、递归扩展、反证查询、来源材料化。
- DeepResearch：跨源融合、竞争假设、冲突保留、适用边界。
- 推演：仅做任务级、能力级和防御性压力测试，不生成可执行攻击方案。
- 反事实与 TRIZ：改变关键前提、提取矛盾、生成多个可验证备选。
- 结构化交接：只传下游必需字段，保留证据、置信度、冲突和开放问题。

动态专用 Agent 还必须遵守 [动态子 Agent 契约](references/dynamic-subagents.md)；知识访问遵守 [知识包访问规则](references/knowledge-access.md)。

