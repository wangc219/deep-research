<!-- ppt-master-schema: design-spec/v1 -->
# JS装备市场需求深度挖掘系统甲方成果汇报 - Design Spec

## I. Project Information

| Item | Value |
| --- | --- |
| Project Name | JS装备市场需求深度挖掘系统甲方成果汇报 |
| Canvas Format | PPT 16:9（1280 × 720） |
| Page Count | 17 |
| Target Audience | 甲方项目负责人、业务领域专家、技术负责人及验收管理人员 |
| Communication Intent | 以成果汇报和验收说明为主，先证明项目已形成业务、工程与评测闭环，再突出多智能体协作、制胜 S1–S6 智能体功能、可审计推理和专业质量优势；下一阶段重点由功能闭环建设转向专业知识资产化、推演验证和持续研判运营 |
| Desired Audience Outcome | 甲方能够清晰判断项目完成度、核心特色和实际业务价值，认可真实盲评所验证的质量优势，并就专业知识底座、首批仿真验证场景、持续监测主题和专家协同治理达成共识 |
| Core Message / Ask / Action | JS装备市场需求深度挖掘系统的核心闭环已初步落地，真实专家盲评验证其在机理推演、能力映射和体系分析上较为显著优于对照方案；下一阶段重点优化智能体设计与协作编排、完善端到端业务执行流程，并持续完善 Benchmark 测试、Pairwise 盲评和模块消融实验 |
| Delivery Context | 甲方现场汇报约 15–20 分钟，有主讲和讨论环节 |
| Artifact Afterlife | 会后作为项目成果说明、阶段验收依据、试点决策材料和后续建设沟通底稿 |
| Reading Mode | balanced |
| Content Strategy | 允许将架构设计文档重组为结论先行的成果汇报叙事；保留全部关键事实与真实评测口径，优先采用系统真实截图、架构图、流程图和数据可视化，避免大段照搬原文 |
| Design Style | pyramid 结论先行叙事 + soft-rounded 现代柔和圆角风格；深海蓝与成果金色板，真实证据优先 |
| Formula Policy | text-only |
| AI Image Acquisition Path | api |
| Generation Mode | continuous |
| Spec Refinement | disabled |
| Created Date | 2026-07-22 |

## II. Canvas Specification

| Property | Value |
| --- | --- |
| Format | PPT 16:9 |
| Dimensions | 1280 × 720 |
| viewBox | `0 0 1280 720` |
| Margins | 40 px outer safe margin；截图页允许视觉载体延伸至 24 px，但文字仍留在安全区 |
| Content Area | x=40–1240，y=40–680；页脚证据线占底部 28 px |

## III. Visual Theme

### Theme Style

- **Mode**: pyramid
- **Visual style**: soft-rounded
- **Theme**: 深海蓝的系统可信度 × 成果金的验收亮点；以圆角载体、柔和分层与真实截图形成“研究成果工作台”视觉语言
- **Tone**: 正式、可信、技术清晰、结论先行；突出成果，同时清晰呈现证据可靠性补强方向

### Color Scheme

| Role | HEX | Purpose |
| --- | --- | --- |
| Background | #F7F9FC | 主页面浅色研究底 |
| Secondary background | #EAF0F7 | 卡片、分区和信息带 |
| Primary | #123B63 | 标题、架构主线、关键节点 |
| Accent | #D59A24 | 成果数字、胜出结论、决策重点 |
| Secondary accent | #2A7F9E | 智能体协作、证据链和辅助数据 |
| Body text | #17212B | 正文与数据标签 |
| Muted text | #5B6B7C | 注释、来源、次级说明 |
| Positive | #2E8B6D | 通过、完成、优势项 |
| Warning | #C87919 | 风险、耗时、待优化项 |
| Negative | #B94747 | 证据可靠性明显落后等关键风险 |
| Surface | #FFFFFF | 浮层卡片和截图承载面 |
| Grid | #D7E0EA | 细分隔线、坐标与结构线 |

### AI Image Strategy

- **Image Rendering**: flat
- **Visual**: 现代扁平几何插图，以圆角模块、证据流、智能体节点与闭环轨迹构成；无嵌入文字，所有中文标签由 SVG 叠加
- **Mood**: 克制、自信、面向复杂系统的协同感，类似一张友好而专业的研究指挥图

## IV. Typography System

### Font Plan

| Role | Chinese | English | Fallback tail |
| --- | --- | --- | --- |
| Title | Noto Serif CJK SC | Georgia | Songti SC, SimSun, serif |
| Body | Microsoft YaHei | Arial | PingFang SC, SimHei, sans-serif |
| Data | Microsoft YaHei | Arial | PingFang SC, sans-serif |
| Footnote | Microsoft YaHei | Arial | PingFang SC, sans-serif |

- **Title stack**: Georgia, "Noto Serif CJK SC", "Songti SC", SimSun, serif
- **Body stack**: Arial, "Microsoft YaHei", "PingFang SC", SimHei, sans-serif
- **Data stack**: Arial, "Microsoft YaHei", "PingFang SC", sans-serif
- **Footnote stack**: Arial, "Microsoft YaHei", "PingFang SC", sans-serif
- **Role rationale**: 保留用户确认的报告型衬线标题与无衬线正文组合；数据与脚注继续使用正文家族以确保密集图表可读。当前环境若缺少确认字体，使用已声明的中文安全替代，不改变标题/正文的角色关系。

### Font Size Hierarchy

| Purpose | Anchor Size (px) |
| --- | ---: |
| Body | 24 |
| Title | 42 |
| Section title (long conclusion) | 36 |
| Subtitle | 32 |
| Lead | 30 |
| Compact label | 21 |
| Medium metric | 38 |
| Annotation | 18 |
| Footnote | 14 |

## V. Layout Principles

### Page Structure

- **Header area**: 结论式标题位于顶部安全区，必要时配 1 行 takeaway；标题不是主题标签，而是本页判断。
- **Content area**: 以不对称主证据区为优先；截图、架构图和数据图承担主视觉，圆角卡片只用于分组和结论承载，避免全页等权卡片阵列。
- **Footer area**: 数据页和验收页保留来源/口径线与页码；风险数据必须标明日期和比较基准。

### Spacing Specification

| Element | Current Project |
| --- | --- |
| Safe margin | 40 px |
| Content block gap | 20–28 px |
| Icon-text gap | 10–14 px |

## VI. Icon Usage Specification

- **Primary bundled library**: tabler-outline
- **Stroke Width**: 2

| Purpose | Icon Path | Page |
| --- | --- | --- |
| 项目目标 | tabler-outline/target-arrow | P02, P03, P17 |
| 三条研究路线 | tabler-outline/route-2 | P03, P05 |
| 多智能体 | tabler-outline/robot | P05, P06, P07 |
| 协作角色 | tabler-outline/users-group | P06, P11 |
| 证据与质量 | tabler-outline/shield-check | P08, P09, P14 |
| 数据与队列 | tabler-outline/database | P06, P10 |
| 运行状态 | tabler-outline/activity | P10, P11, P14 |
| 动态分支 | tabler-outline/git-branch | P05, P08 |
| 检索与取证 | tabler-outline/search | P03, P09 |
| 验收产物 | tabler-outline/file-check | P09, P13, P14 |
| Benchmark | tabler-outline/chart-bar | P02, P15, P16 |
| 运行效率 | tabler-outline/clock | P16, P17 |
| 风险提示 | tabler-outline/alert-triangle | P02, P16, P17 |
| 下一阶段 | tabler-outline/rocket | P17 |
| 验收清单 | tabler-outline/checklist | P14 |
| 分层架构 | tabler-outline/layers-linked | P04, P09 |
| 体系关系 | tabler-outline/network | P04, P07 |
| 过程追溯 | tabler-outline/timeline | P08, P11 |

## VII. Visualization Reference List

| Page | Template | Path | Summary-quote (verbatim) | Usage |
| --- | --- | --- | --- | --- |
| P16 | stacked_bar_chart | templates/charts/stacked_bar_chart.svg | "Pick when each category splits into 2-4 internal parts and total still matters. Skip if only comparing totals (use column_chart)." | 将 8 个评测维度拆为“完整方法 / 平 / 通用 Agent”三段票型，突出七项优势与一项明显短板 |

- horizontal_bar_chart | rejected for P16: 只能表达单一总量，无法同时保留三段票型构成

## VIII. Image Resource List

| Filename | Dimensions | Ratio | Purpose | Type | Layout pattern | Crop Policy | Acquire Via | Status | Reference | text_policy | page_role |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| cover_multi_agent_closed_loop.png | 1672x941 | 1.78 | P01 封面主视觉，并在 P17 以低透明度回声式复用 | AI flat illustration | #1 Full-bleed background with floating title + #30 Flat semi-transparent rectangle overlay + #65 Image with NO text — labels added as native SVG | adaptive | ai | Generated | 扁平圆角的多智能体研究闭环：中心任务节点连接多类专业 Agent、证据流、质量门控和能力画像，右侧保留标题安静区，不出现文字、数字、标识或军事行动细节 | none | hero_page |
| workbench_home.png | 1253x705 | 1.78 | P10 研究指挥台真实界面 | Product screenshot | #19 Image floating in whitespace with thin frame and caption + #36 Drop shadow under image panel | no-crop | user | Existing | 完整展示任务列表、状态与 24 项完成任务，不裁切界面信息 | none | local |
| interaction_gate_overview_v2.jpg | 600x165 | 3.64 | P11 真实 L1–L4 门控循环总览 | Product screenshot | #19 Image floating in whitespace with thin frame and caption + #70 Image with thin colored matte frame | no-crop | user | Existing | 真实任务 run-eaae894d… 的循环总览，完整显示 L1 步骤门控、L2 因果复核、L3 残差回溯 1 次、L4 元循环 2 次 | none | local |
| interaction_recall_request_v2.jpg | 570x255 | 2.24 | P11 真实门控失败与定向再调事件链 | Product screenshot | #48 Side-by-side comparison + #70 Image with thin colored matte frame | no-crop | user | Existing | 真实显示 L1 completed: gate=False 与“综合置信度未达到门控，需要定向补充高置信证据” | none | local |
| interaction_recall_complete_v2.jpg | 570x255 | 2.24 | P11 真实再调返回与覆盖重算事件链 | Product screenshot | #48 Side-by-side comparison + #70 Image with thin colored matte frame | no-crop | user | Existing | 真实显示 recall completed and returned to L1，以及主控 Agent 合并再调结果、重新计算能力覆盖 | none | local |
| architecture_execution_overview.png | 1928x1632 | 1.18 | P12 架构执行总览真实界面 | Product screenshot | #38 Background image + annotation cards with bezier leader lines + #70 Image with thin colored matte frame | no-crop | user | Existing | 完整展示 A–H 发现蓝图、六个专用 Agent、L1–L4 循环门控及参与业务 Agent，四个说明卡置于截图外侧并准确指向对应区域 | none | local |
| capability_view.png | 755x712 | 1.06 | P13 能力成果与交付界面 | Product screenshot | #80 Side hero image + staggered evidence cards + #70 Image with thin colored matte frame | no-crop | user | Existing | 截图作为一侧主证据，另一侧展示成果交付矩阵，不裁切 | none | local |
| benchmark_results.png | 435x1280 | 0.34 | P16 Benchmark 真实结果界面取证 | Product screenshot | #18 Image as full-height sidebar column + #70 Image with thin colored matte frame | no-crop | user | Existing | 竖向完整展示真实评测结果界面，与可编辑票型图并列 | none | local |

## IX. Content Outline

### Part 1: 结论与项目价值

#### Slide 01 - 基于多智能体协作的 JS 装备市场需求深度挖掘系统

- **Audience move**: 从“这是一个架构设想”转变为“这是一个已有真实系统、真实产物和真实评测支撑的阶段成果”
- **Layout**: AI 主视觉全幅铺底，左侧/中部为多智能体闭环几何场景，右侧安静区承载标题；底部以三枚小标签提示“业务闭环 / 工程闭环 / 评测闭环”
- **Title**: 基于多智能体协作的 JS 装备市场需求深度挖掘系统
- **Core message**: 本项目已经形成可运行、可追溯、可评测的 JS 装备市场需求深度挖掘系统初版。
- **Content**: 项目名称作为主标题；副标题“项目阶段成果汇报”；小字“落地功能 · 工程验收 · Benchmark Baseline · 汇报日期”；日期值使用 PowerPoint 自动更新日期字段，根据打开或汇报当天自动刷新，不写死固定日期。
- **Images**: cover_multi_agent_closed_loop.png
- **Cover impact**: 以“从架构走向可审计运行”为核心冲突，采用“多智能体闭环全幅主视觉 + 右侧浮动标题”的高识别构图，避免普通标题页。

#### Slide 02 - 三类闭环与核心功能已落地，真实验收和专家盲评形成双重验证

- **Audience move**: 从零散功能认知转变为对项目完成度、优势和风险的统一判断
- **Layout**: 左侧一条由“业务—工程—评测”组成的弧形闭环，右侧两个大数字与一张核心功能矩阵；底部一句验收结论
- **Title**: 三类闭环与核心功能已落地，真实验收和专家盲评形成双重验证
- **Core message**: 项目已经具备可执行业务链、企业运行链、成果交付链和真实评测链，可用于甲方演示、工程复核与 Benchmark 对比验证。
- **Content**: “业务闭环：三路线、A–H 元编排、S1–S6”；“工程闭环：FastAPI + 持久化队列 + Worker + React 工作台”；“评测闭环：480 条案例资产 + 19 条专业 Query 真实盲评”。成果数字：`446 passed`；对通用 Agent `17胜 2平 0负`。核心功能：三路线 + A–H 动态编排、S1–S6 专业推理链、证据门控 + 交互审计、成果矩阵 + Manifest。
- **Visualization**: 三段闭环 + 验收数字 + 核心功能矩阵，不使用裸数字；每个指标均带比较或含义。

#### Slide 03 - 系统把“资料检索 + 人工归纳”升级为七阶段可追溯研究闭环

- **Audience move**: 从关注单点大模型生成转变为理解系统的端到端业务价值
- **Layout**: 横向七阶段柔和圆角流程，阶段间用箭头与证据回流线连接；下方用“输入—过程—交付”三段说明价值
- **Title**: 系统把“资料检索 + 人工归纳”升级为七阶段可追溯研究闭环
- **Core message**: 系统最终交付的不是装备清单，而是从任务背景到验证路径均可追溯的能力画像。
- **Content**: `任务解析 → 路径选择 → 多智能体研究 → 证据治理 → 制胜机理推理 → 能力画像 → 审计交付`。输入侧：公开、非操作性、任务级与能力级问题。交付侧：任务背景、作战效果、能力功能、性能约束、体系接口、装备形态、优先级、证据链与验证路径。
- **Visualization**: 自定义 SVG 流程图；末端能力画像向“证据治理”回连，体现验证而非一次性生成。

### Part 2: 核心架构与多智能体特色

#### Slide 04 - 项目适配架构贯通业务流程、Agent 协作、证据治理与成果交付

- **Audience move**: 从理解业务流程转变为看清系统分层、模块边界和工程可扩展性
- **Layout**: Codex 原生绘制四层可编辑架构图；左侧固定四层标签，右侧以一条主线路依次展开任务入口、三路线、A–H 分支网络、主控与专用 Agent、S1–S6、证据门控回路和成果交付
- **Title**: 项目适配架构贯通业务流程、Agent 协作、证据治理与成果交付
- **Core message**: 任务解析、路线编排、主控与专业 Agent、证据质量治理、企业运行和成果交付在同一架构中贯通，并保持可扩展、可约束、可复核。
- **Content**: 业务层负责任务解析、三路线、A–H 分支和研究蓝图；Agent 层包括主控 Agent、路线 Agent、S1–S6 专业 Agent，以及 Registry、Session、权限、预算、Wave、Checkpoint；证据层负责检索、材料化、评分、L1–L4 和审计；企业层负责 API、持久化队列、Worker、工作台、报告、成果矩阵、Trace 与 Manifest/SHA-256。
- **Visualization**: Codex 原生 SVG 项目架构图；用少量节点、清晰箭头与回溯曲线体现从任务入口到审计交付的业务闭环，全部文字、节点和线路可编辑。

#### Slide 05 - 三条已落地路线提供稳定执行入口，A–H 八分支提供目标架构扩展面

- **Audience move**: 从“系统只有固定流程”转变为理解稳定路线与动态发现分支并存的业务编排能力
- **Layout**: 上部三条主路线作为宽卡片，下部 A–H 八分支沿弧形轨道排布，中央是主控 Agent；用细线表现选择、补齐覆盖和差异化蓝图
- **Title**: 三条已落地路线提供稳定执行入口，A–H 八分支提供目标架构扩展面
- **Core message**: 系统既能以三条成熟路线稳定执行，也能根据任务主题、交互模式和分支覆盖动态生成研究蓝图。
- **Content**: 已落地路线：`新制胜机理`、`传统能力缺口`、`局部战争案例`。A–H：新战法、传统缺口、案例经验、技术驱动、对手动向、体系对抗、跨域融合、非传统安全。主控 Agent 根据主题和模式选取业务 Agent，并显式披露覆盖缺口。
- **Visualization**: 中心辐射式自定义结构图；三路线用 Primary，八分支用 Secondary accent，当前选中路径用 Accent。

#### Slide 06 - 动态 Agent Registry 与独立受控会话让协作可替换、可并发、可恢复

- **Audience move**: 从“多 Agent 等于多次调用”转变为理解受控协作 Harness 的工程内涵
- **Layout**: 左侧为动态 Registry 与角色池，中央为三道隔离边界，右侧为并发 Wave 与 Checkpoint；底部列出 map-reduce 和结构化交接
- **Title**: 动态 Agent Registry 与独立受控会话让协作可替换、可并发、可恢复
- **Core message**: 每个 Agent 都拥有独立上下文、工具权限、预算、Session、Checkpoint 和输出目录，编排器不写死角色。
- **Content**: `默认角色可全选 / 选子集 / 配置替换`；独立上下文投影与最小工具权限；有界并发 Wave；Subagent map-reduce；结构化 handoff；失败恢复与覆盖缺口显式呈现。
- **Visualization**: Registry → 隔离沙箱 → Wave → 汇聚结果的自定义 SVG 架构图。

#### Slide 07 - S1–S6 将“研究材料”逐级转化为可交付的制胜机理与能力画像

- **Audience move**: 从理解通用协作框架转变为看清本项目固化的专业推理链
- **Layout**: 六个不同宽度的连续模块沿上升弧线排列，终点为能力画像；每个模块只写职责关键词，下方给出链路产出
- **Title**: S1–S6 将“研究材料”逐级转化为可交付的制胜机理与能力画像
- **Core message**: 六类专业 Agent 把对手、运用、突破口、能力映射、现状差距和综合画像串成行业专用推理链，而非通用 Deep Research 套壳。
- **Content**: `S1 对手分析`；`S2 作战运用审查`；`S3 突破口思考`；`S4 装备能力映射`；`S5 装备现状与差距`；`S6 能力图像综合`。链路产出：规律、场景、因果机制、能力需求、指标边界、装备形态与验证建议。
- **Visualization**: 六节点递进链 + 体系网络背景线；用“研究材料 → 机理 → 能力”三段色阶强化转化关系。

#### Slide 08 - L1–L4 四级循环把补证、回溯和强度调整限制在可审计边界内

- **Audience move**: 从看到线性推理链转变为理解质量不足时系统如何定向纠偏
- **Layout**: 四层同心圆/螺旋路径，L1 在内、L4 在外；右侧列出触发条件与动作，底部强调有界调整规则
- **Title**: L1–L4 四级循环把补证、回溯和强度调整限制在可审计边界内
- **Core message**: 系统不是无限自我反思，而是按缺口触发分层、定向、有上限的补证与重编排。
- **Content**: `L1 内循环：单节点自检与补证`；`L2 中循环：相邻阶段回溯`；`L3 外循环：跨阶段质量门控`；`L4 元循环：收敛后有界复核，可调整最多两个 A–H 次分支和 S1–S6 执行强度`。非法调整由 Harness 拒绝并保留原蓝图。
- **Visualization**: 自定义同心反馈回路，非顺序流程；每层标注“触发—动作—边界”。

#### Slide 09 - 证据治理贯穿检索、材料化、引用和交付校验，结果可复核而非只可阅读

- **Audience move**: 从关注推理结果转变为认可系统对证据质量、数据安全和交付完整性的治理
- **Layout**: 左侧“来源进入正式支撑链”的门控漏斗，右侧“报告/需求卡/能力全景/推理追溯/Manifest”交付栈；中部用红色旁路表示低质量来源被拒绝
- **Title**: 证据治理贯穿检索、材料化、引用和交付校验，结果可复核而非只可阅读
- **Core message**: 只有通过网络安全、材料化和质量门控的公开来源才能进入正式证据链，最终交付还可通过 Manifest 与 SHA-256 校验。
- **Content**: SSRF 防护；页面正文简化与位置索引；材料化与质量评分；事实、推断、假设分离；低质量或材料化失败来源拒绝进入正式支撑；持久化 SSE 与断线重放；RBAC、最小权限和原始会话隔离；报告、需求卡片、能力全景、推理追溯、质量门控、验收报告、Manifest/SHA-256。
- **Visualization**: 门控漏斗 + 可校验交付栈。

### Part 3: 真实系统与交付成果

#### Slide 10 - 研究指挥台已承载真实任务管理与跨进程运行闭环

- **Audience move**: 从架构理解转变为看到真实可操作的企业工作台
- **Layout**: 大幅完整截图占据页面 70% 以上，顶部/侧边以三枚浮动指标卡标注“24 项完成任务 / 多任务并行槽位 / 持久化队列 + 独立 Worker”
- **Title**: 研究指挥台已承载真实任务管理与跨进程运行闭环
- **Core message**: 工作台已经覆盖研究创建、草稿、筛选、归档、执行历史与真实运行产物，不是静态演示页面。
- **Content**: FastAPI + SQLite/SQLAlchemy 持久化队列 + 独立 Worker + React/Vite；API 创建任务后不直接执行研究；Worker 跨进程领取并持久化状态；应用重启后仍可读取 summary、证据、S1–S6、能力画像、报告、trace 与 manifest。
- **Images**: workbench_home.png

#### Slide 11 - 372 条真实交互事件把门控、定向再调和返回节点完整展开

- **Audience move**: 从“后台在运行”转变为理解协作过程如何被观察、重放和审计
- **Layout**: 左侧显示真实 L1–L4 循环总览和运行指标，右侧上下两幅真实事件链截图，依次展示“L1 门控失败 → 定向再调”与“再调完成 → 返回 L1 → 覆盖重算”
- **Title**: 372 条真实交互事件把门控、定向再调和返回节点完整展开
- **Core message**: 持久化 SSE 既服务实时观察，也支持断线重放和事后审计，同时不暴露原始模型消息。
- **Content**: 真实任务 `run-eaae894d-8f02-4f2c-861c-be671b3bd7fb` 可查看 `372 条交互事件`、`22 张 EvidenceCard`、`6 / 6 个 S Agent`、`12 个推理节点` 与 `1 次真实 Recall`；审计链明确记录 `L1 completed: gate=False → recall_requested → recall_task_completed → returned to L1 → coverage_recomputed_after_recall`。
- **Images**: interaction_gate_overview_v2.jpg; interaction_recall_request_v2.jpg; interaction_recall_complete_v2.jpg

#### Slide 12 - 架构执行总览将 A–H 蓝图、S1–S6 Agent 与四层循环完整展开

- **Audience move**: 从架构图中的抽象模块转变为看到 A–H 发现蓝图、专用 Agent 和四层循环在真实前端中的完整执行状态
- **Layout**: 近方形截图按原始比例居中完整展示并占据页面主体，左右保留说明区；四个编号提示框置于截图外侧，以短折线和定位圆点分别指向顶部六阶段执行蓝图、中部 S1–S6 专用 Agent 卡片区、下部 L1–L4 循环门控区和最下方参与业务 Agent 区域，任何提示框不得覆盖截图有效内容
- **Title**: 架构执行总览将 A–H 蓝图、S1–S6 Agent 与四层循环完整展开
- **Core message**: 真实前端已经把发现蓝图、六个专用 Agent、循环门控状态和动态参与的业务 Agent 集中呈现，架构执行过程可查看、可定位、可回放。
- **Content**: 说明截图中真实可见的四项落地能力：`A–H 发现蓝图与六阶段执行状态`；`S1–S6 专用 Agent 6/6 完成`，包含对手分析、作战运用审查、突破口思考、装备能力映射、现状差距和能力图像综合；`L1–L4 循环门控`，展示步骤门控、因果复核、残差回溯和元循环的次数与最近状态；`本次参与的业务 Agent`，展示由主控 Agent 根据分支路径和当前输入动态选取的作战场景、国际形势、作战运用和武器装备等 Agent。
- **Images**: architecture_execution_overview.png

#### Slide 13 - 系统把研究结论沉淀为可评审、可追踪、可校验的成果交付包

- **Audience move**: 从看到推理过程转变为理解甲方最终能拿到什么、如何继续评审与验证
- **Layout**: 左侧真实能力成果截图为主视觉，右侧成果交付矩阵；底部强调“可评审 / 可回溯 / 可校验 / 可迭代”
- **Title**: 系统把研究结论沉淀为可评审、可追踪、可校验的成果交付包
- **Core message**: 系统把深度研究、证据治理和专业推理沉淀为甲方可直接使用的多形态成果交付包。
- **Content**: 深度报告、需求卡片、能力全景图、成果画像、推理追溯、证据索引、质量门控、交互审计、交付 Manifest。
- **Images**: capability_view.png

#### Slide 14 - 全量回归与三路线验收表明初版已达到可交付、可复核状态

- **Audience move**: 从产品界面印象转变为基于测试与交付记录判断工程成熟度
- **Layout**: 左侧以 `446 passed` 为大数字，右侧三条路线用状态条表示 completed / runtime_complete / release_ready / audit approved / formal evidence；底部列出构建与交付校验
- **Title**: 全量回归与三路线验收表明初版已达到可交付、可复核状态
- **Core message**: 2026-07-17 验收记录显示回归、生产构建、Compose 配置、代码检查和真实三路线闭环均已通过。
- **Content**: `446 passed`；Vite 生产构建通过；Compose 配置通过；本轮 Ruff 检查通过。三条路线均达到 `status=completed`、`runtime_complete=true`、`release_ready=true`、`audit_status=approved`、`formal_evidence_present=true`。代表性闭环：4 路基线 Agent、6 个推理节点、L1/L2/L3、2 项结构化成果画像、71 条交互事件、15/15 工具调用/结果、30 个 Manifest 文件。
- **Visualization**: 验收状态仪表板式信息图；每个数字均附口径和日期。

### Part 4: Benchmark 实证与下一阶段决策

#### Slide 15 - 正式 Benchmark 以约 100 条专家标注 Query 开展匿名 A/B Pairwise 盲评

- **Audience move**: 从把 480 条候选案例等同于正式全量测试，转变为认可“专家筛选、路径覆盖、匿名 Pairwise 盲评与低置信人工仲裁”的正式评测方案
- **Layout**: 上半区用四阶段横向漏斗展示“480 条候选题库 → 专家筛选与标注 → 约 100 条正式 Benchmark → A–H / OTHER 路径覆盖”；下半区左侧展示入选门槛，右侧用四步流程展示“识别路径 → 检查规定产物 → 九维 Pairwise 比较 → 输出胜者与仲裁标记”，底部明确排除简单事实问答和不可复核 Query
- **Title**: 正式 Benchmark：约 100 条专家标注 Query 采用 Pairwise 盲评
- **Core message**: 480 条保留为候选题库，不直接全部运行；正式 Benchmark 从中筛选约 100 条适合 Deep Research 的 Query，对同题匿名回答 A/B 开展九维 Pairwise 盲评，并对低置信或争议样本转人工仲裁。
- **Content**: 候选池 `480 条`，现有 A–H 每分支 60 条；正式集规模为`约 100 条`，最终数量以专家终审为准，并保留 A–H 及动态组合 `OTHER` 的路径覆盖。入选门槛包括：Deep Research 必要性（多源检索、跨源综合、机理或因果分析）、JS 装备业务相关性、专家标注完整性（分支、模式、预期输出、评分规则）、可复核证据包与安全边界。Pairwise 方法对同一 Query 的两个匿名回答进行比较：Judge 首先独立识别主路径和辅助路径，再检查路径规定产物的完整性，随后按九个维度判定 A、B 或 tie；其中任务完成、证据与事实、因果机理深度、军事运用价值、能力映射与需求质量五项核心维度各占 `15%`，前瞻新颖性占 `10%`，跨场景稳健性、不确定性与验证、沟通效率各占 `5%`。总体胜者不按篇幅或维度票数机械决定，只有核心质量实质相当才判 tie；总体置信度或路径置信度低于 `0.65`、引用需要外部核验、双方核心优势分化或疑似严重失败时标记人工仲裁。输出结构化 JSON，记录路径、胜者、置信度、九维结果、规定产物缺项、引用问题、严重失败和仲裁原因。排除简单事实问答、短检索即可回答、缺乏公开可核材料以及越界或不安全操作请求。
- **Visualization**: 四阶段筛选漏斗 + A–H / OTHER 路径覆盖矩阵 + Pairwise 四步评测流程；突出五项核心维度各 15% 和人工仲裁触发条件，约 100 为规划规模，不表达为已冻结的精确数量。
- **Native-ready**: no

#### Slide 16 - 真实专家盲评验证七项专业优势，证据维度需结合正文展示口径解释

- **Audience move**: 从项目自述转变为基于真实对照评测认可质量优势，同时避免把引用展示差异误判为底层证据不足
- **Layout**: 顶部两组胜负大数字；中部左侧为 8 维三段堆积条形图，右侧为完整 Benchmark 结果截图；底部用优势区与风险区并列总结
- **Title**: 真实专家盲评验证七项专业优势，证据维度需结合正文展示口径解释
- **Core message**: 对纯 LLM 19 胜 0 平 0 负，对通用 Codex Agent 17 胜 2 平 0 负；七项专业维度优势明确，证据维度票型主要反映正式证据在正文中的展示与引用可见性口径，不应直接解释为证据不足。
- **Content**: 19 条专业 Query，57/57 完成，2 名真实专家 Judge。对纯 LLM：`19胜 0平 0负，100%`。对通用 Agent：`17胜 2平 0负，94.74%，95% CI 86.84%–100%`。优势票型：机理深度 `69:2:1`、能力映射 `65:2:5`、军事价值 `65:6:1`、跨场景稳健性 `70:2:0`、前瞻新颖性 `62:10:0`。证据与事实可靠性票型为 `2:3:67`；结合报告声明“19 项正式证据”但正文未完整展开的实际情况，该结果应作为正文证据展示、评测输入口径和 Judge 可见信息校准项，而不是底层证据数量不足的结论。
- **Visualization**: 使用 stacked_bar_chart 模板语义生成 8 维横向三段堆积条形图；source values determine geometry；优势段使用 Positive，通用 Agent 优势段在证据可靠性行使用 Negative。
- **Native-ready**: yes
- **Images**: benchmark_results.png

#### Slide 17 - 下一阶段聚焦智能体编排、业务流程与 Benchmark 三项优化

- **Audience move**: 从认可阶段成果转变为清晰理解下一阶段只聚焦智能体、业务流程和评测体系三项优化重点
- **Layout**: 深色简洁收束页；顶部用一句话说明“现有闭环基础上持续优化”，主体用三张等宽大卡片展示“智能体设计与编排、业务执行流程、Benchmark 与消融实验”，每张卡片仅保留三项行动；底部用一条成果目标横幅收口
- **Title**: 下一阶段重点：智能体编排、业务流程与 Benchmark
- **Core message**: 下一阶段不扩散建设主题，重点优化智能体设计和协作编排、完善业务执行流程，并通过更完整的 Benchmark 与消融实验持续验证各模块贡献。
- **Content**: `01 智能体设计与编排`：进一步细化主控 Agent、专用 Agent、业务 Agent 和 S1–S6 的职责边界，优化分支选择、并行协同、动态路由、回溯与再调策略，完善 Agent 输入输出契约和协作编排配置。`02 业务执行流程完善`：围绕任务入口、三路线、A–H 分支、六步推理、证据门控和成果交付梳理端到端流程，补齐异常处理、人工介入、结果复核与状态回放，使前端展示、后台执行和业务规则保持一致。`03 Benchmark 与消融实验`：持续扩充专家标注、适合 Deep Research 的 Query，完善匿名 A/B Pairwise 盲评、置信度和人工仲裁机制；增加主控编排、专用 Agent、S1–S6、证据门控、Recall 和工具链等模块的消融 Baseline，量化各模块对质量和稳定性的贡献。
- **Visualization**: 三张编号大卡片，以机器人、流程线路和评测图标分别代表“智能体、流程、评测”；底部成果横幅写明“可配置编排 · 可复核流程 · 可量化评测”。
- **Images**: cover_multi_agent_closed_loop.png
- **Closing impact**: 让甲方只记住“下一阶段集中做好智能体编排、业务流程和 Benchmark 三件事”，以简洁明确的持续优化方向收束，而非展开新的复杂建设主题。

## X. Speaker Notes Requirements

- **Filename**: match each SVG filename under `notes/`
- **Content**: 每页第一句先说结论，再用 2–3 个事实解释；所有 Benchmark 数字在同一句中给出比较基准；数据页口头说明日期、样本量与真实专家盲评口径；风险页明确区分“已验证事实”和“下一阶段建议”。
- **Total duration**: 18 minutes
- **Notes style**: formal、conclusion-driven、适度互动；面向甲方专家时保留技术准确性，避免朗读页面全文
- **Presentation purpose**: report、explain、persuade、align、record and hand off
