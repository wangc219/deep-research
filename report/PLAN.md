# 以架构设计为主约束的实施方案：动态研究蓝图与自治能力编排

## 一、实施基线

本次改造以指定架构设计文档为唯一业务架构主约束：

- 支持“专家模式”和“智能模式”两种入口。
- S1-S6 是JS装备需求挖掘的思考能力，不是固定串行业务流程；应支持组合、跳步、并行、回溯和扩展。:codex-file-citation{path="/Users/wangchen/equipment research/基于多智能体协作的JS装备市场需求深度挖掘系统架构设计.docx" artifact_kind="document" page_number="1"}
- 真实支持 A-H 八类发现方向，以及无法命中时由元编排能力即时生成研究蓝图。:codex-file-citation{path="/Users/wangchen/equipment research/基于多智能体协作的JS装备市场需求深度挖掘系统架构设计.docx" artifact_kind="document" page_number="3"} :codex-file-citation{path="/Users/wangchen/equipment research/基于多智能体协作的JS装备市场需求深度挖掘系统架构设计.docx" artifact_kind="document" page_number="4"}
- 制胜机理采用 Tree-of-Warfare 图式推理，每个节点必须包含“认识、证据、置信度、下一步建议”，并由批判 Agent 决定通过、补证、回溯或扩展。:codex-file-citation{path="/Users/wangchen/equipment research/基于多智能体协作的JS装备市场需求深度挖掘系统架构设计.docx" artifact_kind="document" page_number="6"}
- 支持内循环、中循环、外循环和 L4 跨分支元循环，最终生成需求卡片、能力全景图和推理可回溯报告。:codex-file-citation{path="/Users/wangchen/equipment research/基于多智能体协作的JS装备市场需求深度挖掘系统架构设计.docx" artifact_kind="document" page_number="9"} :codex-file-citation{path="/Users/wangchen/equipment research/基于多智能体协作的JS装备市场需求深度挖掘系统架构设计.docx" artifact_kind="document" page_number="11"}

reference 项目的 OPC 自建、自营、自成长、nanobot skills、pi 会话与扩展、GenericAgent Supervisor/Morphling 只用于实现上述要求，不改变目标架构。

## 二、当前实现与目标架构的关键差距

1. 当前运行时只有三条真实路线；A-H 目前主要用于分类字段和 benchmark，D-H 未进入真实调度。
2. 当前计划图基本固定为“baseline map → reduce → winning → audit → report”，仍偏固定 workflow。
3. 当前 SixStepReasoner 默认串行生成 S1-S6，缺少节点级跳步、并行、回溯和动态插入。
4. 缺少文档要求的专家/智能双模式、背景假设树、场景发散、案例专用链和元编排。
5. 缺少独立的批判 Agent、反思 Agent、收敛融合层以及四层循环控制。
6. 当前 skill 集中配置在 YAML 中，Agent 不能按任务自主发现和渐进加载。
7. 当前九字段能力画像可作为需求卡片基础，但尚缺能力全景图、跨背景/跨场景聚类和完整 Tree-of-Warfare 回溯视图。
8. 当前装备、作战运用 Agent 被当成固定基线角色；目标应将其改造成可被不同分支按需调用的专业能力。

## 三、目标运行架构

### 1. 主控智能体升级为 Chief-Agent

Chief-Agent 只负责控制和决策，不替代专业研究：

- **需求解析 Skill**
  - 判定 `expert` 或 `intelligent` 模式。
  - 提取场景、领域、研究粒度、军兵种、作战域、时间范围和约束。
  - 识别用户明确问题与隐含探索空间。
- **发现方向判定 Skill**
  - 输出 A-H 多标签概率，而不是只选单一路线。
  - 支持一个主分支和多个候选分支。
- **研究蓝图生成 Skill**
  - 从分支模板、任务特征和现有能力目录合成动态研究图。
  - 决定需要哪些背景、场景、S1-S6 节点、案例链、技术链或仿真能力。
- **循环控制 Skill**
  - 根据批判、反思、证据缺口和收敛状态触发内、中、外、L4 循环。
- **能力经纪 Skill**
  - 从 Agent、skill、tool 目录选择能力。
  - 缺少能力时组合临时 Agent Blueprint，不能伪造覆盖。

### 2. 用动态 Research Blueprint 取代固定 workflow

新增 `ResearchBlueprint`，每次任务动态生成，至少包含：

- 运行模式及研究目标
- 主分支、候选分支及触发理由
- 背景假设与场景展开策略
- 能力节点及其输入输出契约
- 硬依赖、软依赖和可并行关系
- `required / optional / skipped / deep-focus` 节点属性
- 每个节点的 Agent、skills、tools 和预算
- 内、中、外、L4 循环策略
- 节点质量门和全局停止条件
- 输出契约和能力版本快照

调度器只执行“当前已满足依赖且质量门允许”的节点。节点、边和分支均可在运行中由结构化决策增加或关闭，但必须保留变更原因和审计事件。

### 3. S1-S6 落地为可组合的制胜机理能力

S1-S6 不全部做成长期独立 Agent，也不固化成六步流水线，采用“skill 优先、必要时升级为隔离 subagent”的方式：

| 能力 | 默认实现 | 升级为独立 subagent 的条件 |
|---|---|---|
| S1 对手分析 | 对手体系分析 skill + 装备/情报工具 | 多对手、多体系假设或需要独立深搜 |
| S2 作战运用审查 | 条令、战法、任务链分析 skill | 新战法生成、多个替代战法并行比较 |
| S3 突破口思考 | 反事实、TRIZ、效果链 skills | 需要并行生成多组候选突破方向 |
| S4 装备能力映射 | 能力-任务映射 skill + 知识图谱工具 | 映射关系复杂或涉及多个装备体系 |
| S5 装备现状分析 | 武器装备 Agent + 参数与成熟度工具 | 需要大规模型号对比或专项技术研究 |
| S6 能力图像综合 | 收敛融合 Agent + 排序/可视化工具 | 跨背景、跨场景、跨分支结果需融合 |

Subagent 创建仍遵循可拆分、隔离有收益、存在结构化汇总契约、预算允许四项条件。

### 4. Tree-of-Warfare 推理图

将当前 `WinningReasoningNode` 升级为 `WarfareReasoningNode`：

- `node_id`
- `semantic_stage`：S1-S6 或自定义节点
- `branch_id`
- `background_id`、`scenario_id`
- `recognition`
- `evidence_ids`、`claim_ids`
- `confidence`
- `assumptions`
- `next_action_suggestions`
- `parent_node_ids`
- `status`
- `iteration`
- `critic_verdict_id`
- `created_by`
- `capability_version_refs`

边类型支持：

- `depends_on`
- `supports`
- `contradicts`
- `refines`
- `backtracks_to`
- `derived_from`
- `cross_branch_triggers`

不能再用固定的 S1→S2→S3→S4→S5→S6 列表作为唯一执行模型。

### 5. 批判、反思与收敛

新增三个系统角色：

- **Critic Agent**
  - 节点级检查证据支撑、逻辑闭合、反证、创新性、可行性和安全边界。
  - 输出 `pass / supplement_search / revise / backtrack / branch / reject`。
  - 只产生评价和指令，不直接修改专业结论。

- **Reflection Agent**
  - 在背景、场景、分支或轮次完成后检查覆盖度、遗漏维度、同质化、证据空洞和认知偏差。
  - 决定是否需要新增背景、场景、观察视角或分支。

- **Convergence Agent**
  - 对跨背景、跨场景和跨分支成果执行聚类、去重、冲突保留、优先级排序。
  - 不以简单文本相似度合并，必须保留不同适用场景、指标边界和证据链。

最终审计 Agent 继续执行发布门控，与 Critic/Reflection 职责分离。

## 四、A-H 八类发现方向的真实运行策略

各分支配置为“蓝图种子”，只定义语义重点、建议能力和质量门，不定义不可改变的执行顺序。

| 分支 | 入口能力 | 默认重点 | 可跳过/弱化 | 专用质量门 |
|---|---|---|---|---|
| A 新战法发现 | 形势、场景、作战概念 | S2、S3 深化，多个战法候选并行 | S1 快速，S5 轻量 | 新战法必须与现有战法有实质差异，并经过效果与可行性验证 |
| B 传统能力缺口 | 场景、现有装备基线 | S4、S5 双向迭代 | S1-S3 可按任务压缩 | 每个差距必须同时关联场景压力、目标能力和现有能力证据 |
| C 局部战争案例 | 多语言案例检索 | 事实还原、决策点、因果链、跨案例规律 | 先不运行标准 S1-S2 | 事实、判断和未来类比必须分层；跨案例规律不少于两个独立案例 |
| D 技术驱动 | 技术雷达 | 技术潜力、成熟度、颠覆场景、S3/S4 | S1 跳过，S5 弱化 | 区分概念、原型、试验和工程可用状态 |
| E 对手动向 | 对手装备/演训/条令监测 | S1 深化、威胁效果、对冲需求 | 其他节点按需 | 动向必须有时间基线和异常变化证据 |
| F 体系对抗 | 红蓝体系建模 | 体系脆弱点、补链强链、体系级能力 | 单装备比较降级 | 明确体系节点、依赖、级联影响和反事实 |
| G 跨域融合 | 跨域映射矩阵 | 域间缝隙、跨域协同突破、接口能力 | S1/S2/S5 按需 | 每个空白必须说明涉及域、接口、信息流和协同条件 |
| H 非传统安全 | 新型威胁扫描 | 新对手画像、新场景、S3/S4 | S2/S5 弱化 | 显式标注历史证据不足、类比边界和不确定性 |

### 元编排

无法稳定映射 A-H 时：

1. 提取任务驱动源。
2. 形成所需能力清单。
3. 查询 Agent/skill/tool 能力目录。
4. LLM 生成候选 Blueprint。
5. 确定性校验器检查契约、依赖、权限、预算和输出完整性。
6. 缺能力时创建仅当前 run 可用的临时 Agent。
7. Blueprint 和临时 Agent 均写入运行快照，不自动进入正式能力库。

## 五、多重循环实现

### 1. 内循环

作用于单个 Tree-of-Warfare 节点：

- 证据不足时补充 DeepSearch。
- 存在冲突时搜索反证并修订置信度。
- 批判不通过时回到本节点或直接前置节点。
- 直到通过质量门、预算耗尽或转为受限结论。

### 2. 中循环

作用于同一场景下的观察视角：

- 更换电磁压制、资源受限、体系受损、有人无人协同等视角。
- 保留上一轮图分支，不覆盖原结论。
- 由 Reflection Agent 判断是否产生新认识；连续两轮无有效新增则停止。

### 3. 外循环

作用于背景假设与场景组合：

- 国际形势 Agent 生成 N 个有证据基础的背景假设。
- 场景 Agent 为每个背景生成 M 个场景。
- 不固定 N=3、M=2；由覆盖、差异度和预算共同确定。
- 独立组合并行，完成后进入收敛融合层。

### 4. L4 元循环

作用于发现分支之间：

- 新战法结果可触发传统能力缺口。
- 案例规律可触发技术驱动。
- 对手动向可触发体系对抗或跨域融合。
- L4 必须说明触发依据、预期新信息和预算，禁止无目标循环。
- 同一分支组合重复触发且无有效新增时自动终止。

新增 `LoopDirective`：

- `loop_type`
- `trigger`
- `source_node_or_branch`
- `target_node_or_branch`
- `required_new_information`
- `expected_value`
- `budget`
- `status`
- `stop_reason`

## 六、专业 Agent、skills 与 tools 配置

### 1. 长期专业 Agent

- Chief-Agent
- 国际形势 Agent
- 作战场景 Agent
- 制胜机理 Agent
- 案例研究 Agent
- 武器装备 Agent
- 作战运用 Agent
- Critic Agent
- Reflection Agent
- Convergence Agent
- Audit Agent
- Report Agent

D-H 所需技术雷达、对手监测、体系仿真、跨域映射和新型威胁扫描，初期作为专业 skills + 工具组合；只有在上下文隔离、长期记忆或独立研究循环确有必要时才晋升为长期 Agent。

### 2. 六类 skills

按照文档要求形成独立、按需加载的 skill 包：

- **深度搜索**：多源检索、递归查询扩展、多语言检索、来源质量、反证搜索。
- **深度研究**：长文理解、跨源融合、矛盾检测、假设生成、研究收敛。
- **知识操作**：JS知识、装备本体、战法/条令、能力-任务映射。
- **推演仿真**：场景压力测试、效果链模拟、体系依赖分析、蒙特卡洛接口。
- **认知工具**：反事实、类比、TRIZ、竞争假设、SWOT/PEST。
- **输出生成**：需求卡片、能力全景图、研究报告和审计摘要。

每个 skill 使用独立 `SKILL.md`，只在触发后加载正文；脚本、领域参考和模板分离存放。

### 3. 工具边界

确定性工具负责：

- 搜索、抓取、材料化和段落定位
- 知识图谱查询
- 装备参数归一与冲突保存
- 图节点和边写入
- 聚类、排序和可视化
- 仿真模型调用
- 预算、权限、检查点和审计

LLM Agent 负责语义判断、假设、类比、创新和研究决策。

仿真工具没有可靠参数或模型时，只能输出“定性压力测试”或“待验证估计”，不得仿造类似“提升60%”的精确结果。

## 七、领域对象和 API 改造

### 1. 输入契约

`ResearchProblem` 升级为：

- `run_mode: expert | intelligent`
- `topic`
- `expert_scope`
- `granularity`
- `service_branches`
- `warfare_domains`
- `preferred_discovery_branches`
- `exploration_constraints`
- `max_backgrounds`
- `max_scenarios_per_background`
- `loop_budget`
- `analyst_confirmed`

原有三条 `research_route` 保持兼容：

- `new_winning_mechanism` → A
- `traditional_gap` → B
- `war_case_learning` → C

### 2. 新增领域对象

- `ResearchIntent`
- `DiscoveryBranchHypothesis`
- `ResearchBlueprint`
- `BlueprintNode`
- `BackgroundHypothesis`
- `ScenarioHypothesis`
- `WarfareReasoningNode`
- `CriticAssessment`
- `ReflectionAssessment`
- `LoopDirective`
- `CaseTimeline`
- `CausalChain`
- `DemandCard`
- `CapabilityPanorama`
- `ConvergenceResult`

### 3. 输出契约

`DemandCard` 至少包含：

- 能力域
- 能力名称
- 装备形态或类别
- 关键功能
- 关键指标及区间
- 优先级
- 支撑背景和场景
- 来源制胜逻辑
- 当前能力与差距
- 体系依赖
- 技术成熟度
- 验证方法
- 风险与适用边界
- EvidenceCard/claim 引用
- 置信度

`CapabilityPanorama` 包含：

- 能力节点
- 场景、威胁、战法、效果、装备之间的关联边
- 新能力、升级能力和体系建设项分类
- 跨场景共性与场景专属能力
- 冲突、证据强弱和不确定性

新增查询接口：

- `GET /api/v1/runs/{id}/intent`
- `GET /api/v1/runs/{id}/blueprint`
- `GET /api/v1/runs/{id}/warfare-tree`
- `GET /api/v1/runs/{id}/loops`
- `GET /api/v1/runs/{id}/demand-cards`
- `GET /api/v1/runs/{id}/capability-panorama`
- `GET /api/v1/runs/{id}/critic-assessments`
- `GET /api/v1/runs/{id}/reflections`

现有 summary、capabilities、report、events 和 manifest 接口继续兼容。

## 八、实施阶段

### 阶段一：架构契约对齐

- 增加双运行模式和 A-H 正式枚举。
- 引入 ResearchIntent、ResearchBlueprint 和 BlueprintNode。
- 将固定计划图替换为动态 readiness graph。
- 保留三条旧路线兼容适配。
- 每个 run 固化 Blueprint、Agent、skill、tool 和模型版本。

完成标准：专家模式、智能模式和 A-H 均能生成可解释蓝图；未命中任务能生成通过校验的自定义蓝图。

### 阶段二：制胜机理图式执行

- 将 S1-S6 改为可选、可并行、可回溯能力节点。
- 建立 Tree-of-Warfare 数据模型。
- 增加 Critic Agent 和节点级质量门。
- 支持针对任意节点的搜索补证和恢复。
- 当前 L1/L2/L3 保留为发布质量层，不再代替 S1-S6 图式控制。

完成标准：同一任务中可观测到跳过、并行、回溯三种行为，且每个节点具备四项规定输出。

### 阶段三：循环系统与 A-C 主路径

- 实现内、中、外、L4 循环控制器。
- 完整实现 A、B、C 三条架构示例。
- 新增案例研究 Agent、时间线、决策点和因果链对象。
- 接入 Reflection 和 Convergence Agent。
- 将现有装备、作战运用 Agent 改为按需调用。

完成标准：文档中的传统缺口、新战法、案例经验三个示例都能从 API 主链产生对应蓝图、循环事件和交付物。

### 阶段四：D-H 与元编排

- 实现技术雷达、对手动向、体系对抗、跨域矩阵和非传统威胁 skills/tools。
- 为 D-H 配置蓝图种子、质量门和 benchmark。
- 实现动态能力发现和临时 Agent Blueprint。
- 对临时 Agent 执行权限交集、预算和输出契约校验。

完成标准：D-H 各有至少一条真实主链验收任务；未知任务可生成自定义蓝图而不是退回固定默认路线。

### 阶段五：知识、仿真和交付增强

- 接入本地JS知识、装备本体、战法条令和案例知识适配器。
- 建立统一 EvidenceCard 与 claim-level 支撑度。
- 提供定性压力测试和可插拔仿真接口。
- 生成需求卡片、能力全景图和可回溯报告。
- 工作台显示动态蓝图、Tree-of-Warfare、循环、批判和收敛过程。

完成标准：所有正式需求卡片均能回溯到场景、制胜节点、装备差距和证据。

### 阶段六：受控自成长

在架构主链验收后再引入 OPC 思想：

- 从重复 Recall、人工退回和 Critic 失败中提取能力缺口。
- Reflection 生成候选 skill 或 Agent Blueprint。
- 使用 A-H benchmark、历史回放和同预算 A/B 评估。
- 候选能力只能进入隔离区。
- 通过安全审计和人工批准后晋级。
- 每个版本可回滚，旧 run 始终使用原能力快照。

不得让自成长机制修改 S1-S6 语义、证据标准或架构发布门控。

## 九、架构级验收场景

### 双模式

- 专家模式严格围绕指定场景/领域研究，不擅自无限扩展。
- 智能模式能自主提出差异化背景、场景和研究焦点，并说明理由。

### 八分支

- A-H 各自命中正确分支和重点节点。
- 允许多分支并存。
- 未知问题触发元编排而非强塞入 A-C。

### 非固定流程

- A 分支深化 S2/S3，S1/S5 可轻量化。
- B 分支允许 S4/S5 双向反复。
- C 分支先执行案例链，再进入 S3-S6。
- D 分支可以跳过 S1。
- G 分支可以直接从跨域矩阵进入 S3/S4/S6。
- 运行记录必须证明节点选择来自 Blueprint，而非硬编码顺序。

### Tree-of-Warfare

- 每个节点均有认识、证据、置信度和下一步建议。
- 节点能够并行、产生竞争分支、被反证或回溯。
- Critic 不通过能返回精确目标节点。

### 多重循环

- 内循环补证。
- 中循环更换观察视角。
- 外循环展开多个背景和场景。
- L4 能从 A 触发 B、从 C 触发 D。
- 无新增信息时能够收敛停止。

### 交付物

- 需求卡片字段完整。
- 能力全景图存在且关系可追溯。
- 报告区分事实、推理、假设和限制。
- 未通过证据、确认或成熟度门控时只能发布待审或受限版本。

## 十、默认决策

- 架构设计优先级高于当前实现和 reference 项目。
- 不新增传统 BPM/workflow 引擎。
- A-H 是研究策略种子，不是八条固定流水线。
- S1-S6 是语义能力节点，不要求每次全部执行。
- L1/L2/L3 保留为质量与发布门控，不能与 S1-S6 混为同一层。
- 默认复用现有 Python、FastAPI、SQLAlchemy、Harness、EvidenceCard、事件流、checkpoint 和 benchmark。
- 自建、自营、自成长必须在权限、证据、预算、审计和人工晋级边界内运行。
