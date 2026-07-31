# 主控 Agent 专用 Prompt、Tools 与 Skills 优化方案

## 1. 优化目标

依据《基于多智能体协作的 JS 装备市场需求深度挖掘系统架构设计》的业务流程，主控 Agent 不应只是“
## 2. 四项专用 Skill

| Skill ID | 核心职责 | 允许 Tool | 核心产物 |
| --- | --- | --- | --- |
| `requirement_semantics_analysis` | 解析模式、目标、交付物、边界、粒度、军兵种/作战域、时间尺度、假设和未知项 | `analyze_research_request` | 任务语义卡、研究问题树 |
| `discovery_driver_recognition` | 对 A-H 逐项评分；识别无法被 A-H 充分解释的 OTHER 驱动源 | `classify_discovery_drivers` | 驱动源评分、主次分支、未覆盖项、置信度 |
| `discovery_blueprint_generation` | 根据路径侧重组合 S1-S6；OTHER 时读取可用 Agent 能力即时生成蓝图 | `build_discovery_blueprint` | 动态能力标签、Agent、DAG 波次、S1-S6 强度、进入/失败/回溯条件 |
| `dag_loop_orchestration` | 最小充分 Agent 选择、能力覆盖、依赖 DAG、并发波次和内/中/外/L4 循环 | `plan_execution_waves`、`evaluate_loop_transition` | 能力覆盖矩阵、DAG、波次、预算、停止理由 |

## 3. Tool 设计原则

主控 Tool 应是“决策记录器和治理接口”，而不是宽泛的文本容器。每次调用都写入 `WorkingCheckpoint` 并保留审计 Trace。

### `analyze_research_request`

必填字段覆盖：交互模式、目标、交付物、约束、安全边界、粒度、作战域、时间尺度、假设、未知项和决策问题。

### `classify_discovery_drivers`

输出 A-H 各分支评分、主次驱动源、匹配信号、排除理由、`unmatched_driver` 和置信度。OTHER 不是固定第九分支：Codex CLI 读取当前注册表中的可用 Agent 能力，选择最接近的 A-H 作为运行基座，并即时生成 `custom_blueprint`。

### `build_discovery_blueprint`

输出运行路线、S1-S6 强度、Agent、必需产物、波次、依赖、循环策略、停止条件和 fallback。对新型任务，`custom_blueprint` 必须包含驱动源类型、必需能力标签、注册表内 Agent、依赖 DAG、波次、S1-S6 强度和停止条件。蓝图必须支持跳步、回溯和并行，不能机械串联六步。

### `plan_execution_waves`

输出 Agent DAG、结构化 handoff、并发度、关键路径、能力覆盖矩阵和预算。Agent 选择采用“最小但充分”原则。

### `evaluate_loop_transition`

输出循环层级、质量状态、信息增益、预算状态、下一动作、最早回溯节点、原因和停止理由。无信息增益、无合法重规划或达到上限时降级停止。

## 4. 主控 Prompt 决策顺序

```text
需求语义解析
  → A-H/OTHER 驱动源识别
  → S1-S6 动态蓝图
  → capability coverage
  → 最小充分 Agent 集合
  → DAG 与执行波次
  → 内/中/外/L4 循环和停止策略
```

关键约束：

- 专家模式尊重显式分支、Agent 和禁止边界；智能模式才主动发散。
- 分支判断基于任务语义与驱动源，不只依赖关键词数量。
- 不默认选择国际形势 Agent；只有任务确需态势、威胁或战略能力时才选择。
- 事实、用户假设、模型推断、冲突和未知分开表达。
- 主控只消费 Registry、结构化 Packet、coverage、checkpoint、trace 摘要和预算状态。
- 重规划必须有可执行变化和信息增益，否则停止。

## 5. 代码落点

- 专用、版本化 Prompt 与 JSON schema：`src/equipment_deep_research/agents/orchestrator_prompt.py`
- 主控 Agent、Tool allowlist 与 Skill 绑定：`configs/equipment_deep_research/agents.yaml`
- Skill 工作流、质量门控、预算与停止条件：`configs/equipment_deep_research/harness.yaml`
- Tool 注册与对象权限：`configs/equipment_deep_research/tools.yaml`、`src/equipment_deep_research/tools/domain_tools.py`
- Codex 项目 Skill 的主控专用规程：`configs/equipment_deep_research/codex_skills/js-equipment-agent-runtime/references/orchestrator.md`
- A-H/OTHER 蓝图审计字段：`src/equipment_deep_research/orchestration/blueprints.py`

## 6. 预期改进

- Prompt 从三个分散短指令收束为统一、版本化的主控契约；
- 驱动源识别与蓝图生成解耦，减少“先选分支再找理由”；
- 工具字段从宽泛数组升级为可审计业务字段；
- Skills 与架构图中的四项能力一一对应；
- OTHER 任务可以被识别并动态扩展，同时保持现有 A-H 运行时兼容；
- Agent 选择、DAG、循环和停止条件具备统一质量门控。
