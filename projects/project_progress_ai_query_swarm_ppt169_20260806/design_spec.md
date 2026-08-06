<!-- ppt-master-schema: design-spec/v1 -->
# 项目阶段进展：AI Query、质量集群与动态蜂群 - Design Spec

## I. Project Information

| Item | Value |
| --- | --- |
| Project Name | 项目阶段进展：AI Query、质量集群与动态蜂群 |
| Canvas Format | PPT 16:9 (1280 × 720) |
| Page Count | 15 |
| Target Audience | 项目方管理层、业务与技术负责人；重点关注阶段成果是否可验证、能否形成可演示闭环。 |
| Communication Intent | 说明“需求 Query”是异步运行的选题发现服务：围绕母题发散与自动态势发散共用联网校验、结构化生成、质量门和草稿审核发布；再讲清质量集群与动态蜂群是同一条 S1–S6 制胜机理链的两种执行策略，并以真实约束、运行结果和前端闭环对齐项目方对正式装备需求论证的理解。 |
| Desired Audience Outcome | 项目方清楚了解已交付能力、前端可演示成果和已验证边界；能够按任务复杂度选择“固定稳定的快速收敛”或“残差触发的动态竞争收敛”。 |
| Core Message / Ask / Action | 项目已形成可配置的多智能体研究操作系统：AI Query 以双模式选题发现服务将任务入口标准化；质量集群与动态蜂群共享 S1–S6 制胜机理链、采用不同执行策略；角色合同、版本账本、专家盲评和报告模板使结果可治理、可追溯、可交付。 |
| Delivery Context | 项目方阶段汇报，建议 15—18 分钟主讲并现场展示前端工作台关键页面；会后作为进展留档材料。 |
| Artifact Afterlife | 用于项目阶段验收、技术沟通、后续优化任务对齐与演示留档。 |
| Reading Mode | balanced |
| Content Strategy | balanced default |
| Design Style | 专业蓝金、Swiss minimal 的项目简报；以“入口能力—共同主链—双策略—真实验证—下一步”的故事线推进。 |
| Formula Policy | text-only |
| AI Image Acquisition Path | not applicable |
| Generation Mode | continuous |
| Spec Refinement | disabled |
| Created Date | 2026-08-06 |

## II. Canvas Specification

| Property | Value |
| --- | --- |
| Format | PPT 16:9 |
| Dimensions | 1280 × 720 |
| viewBox | `0 0 1280 720` |
| Margins | 48 px outer safe margin |
| Content Area | 1184 × 624 px within safe area |

## III. Visual Theme

### Theme Style

- **Mode**: custom
- **Mode Behavior**: 按“异步 Query 选题发现双入口—共同 S1–S6 主链—两种执行策略—动态孵化工程化—真实验证—下一步”推进；每页结论先行并给出最少量可核查证据。Kimi K3 只作为架构思想启发，项目实现是自身的 `winning_swarm_dynamic_v2`。
- **Visual style**: swiss-minimal
- **Theme**: 专业蓝金项目简报
- **Tone**: 克制、可核查、工程化

### Color Scheme

| Role | HEX | Purpose |
| --- | --- | --- |
| Background | #F8FAFC | 页面主底色与留白 |
| Secondary background | #EAF0F7 | 浅色分区与截图衬底 |
| Primary | #0D2B55 | 标题、主结构线与核心结论 |
| Accent | #E89A22 | 关键数字、风险与需要对齐的行动点 |
| Secondary accent | #2B78B8 | 流程节点、次级数据与辅助强调 |
| Body text | #18212F | 正文与说明文字 |

## IV. Typography System

### Font Plan

| Role | Chinese | English | Fallback tail |
| --- | --- | --- | --- |
| Title | Microsoft YaHei | Arial | sans-serif |
| Body | Microsoft YaHei | Arial | sans-serif |
| Annotation | Microsoft YaHei | Arial | sans-serif |
| Lead | Microsoft YaHei | Arial | sans-serif |

- **Title stack**: Microsoft YaHei, Arial, sans-serif
- **Body stack**: Microsoft YaHei, Arial, sans-serif
- **Annotation stack**: Microsoft YaHei, Arial, sans-serif
- **Lead stack**: Microsoft YaHei, Arial, sans-serif

### Font Size Hierarchy

| Purpose | Anchor Size (px) |
| --- | ---: |
| Body | 24 |
| Title | 42 |
| Subtitle | 32 |
| Lead | 28 |
| Annotation | 18 |
| Footnote | 16 |

## V. Layout Principles

### Page Structure

- **Header area**: 左上使用页码、章节标签和结论型标题；标题下以短横线或一句话说明强化阅读路径。
- **Content area**: 保持 12 栏隐形网格；机制页使用路径/关系图，比较页使用高信息密度矩阵，演示页以完整截图为证据。
- **Footer area**: 页码、资料口径或“项目仓库真实运行记录”来源提示。

### Spacing Specification

| Element | Current Project |
| --- | --- |
| Safe margin | 48 px |
| Content block gap | 24 px |
| Icon-text gap | 10 px |

## VI. Icon Usage Specification

- **Primary bundled library**: tabler-outline
- **Stroke Width**: 2

| Purpose | Icon Path | Page |
| --- | --- | --- |
| Query/任务入口 | `icons/tabler-outline/search.svg` | P02-P03 |
| 集群节点与调度 | `icons/tabler-outline/git-fork.svg` | P04-P09 |
| 前端演示 | `icons/tabler-outline/layout-dashboard.svg` | P10 |
| 下一步行动 | `icons/tabler-outline/arrow-right.svg` | P15 |

## VIII. Image Resource List

| Filename | Dimensions | Ratio | Purpose | Type | Layout pattern | Crop Policy | Acquire Via | Status | Reference | text_policy | page_role |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| workbench_home_clean.png | 1253×705 | 1.78 | 展示 AI Query 自动生成和研究任务入口已进入工作台 | Product screenshot | #19 Image floating in whitespace with thin frame and caption | no-crop | user | Existing | 真实前端素材；P03 右侧证据截图 | n/a | local |
| interaction_view_clean.png | 755×712 | 1.06 | 展示任务交互与过程可追溯能力 | Product screenshot | #50 Tiled grid with equal cells | no-crop | user | Existing | 真实前端素材；P10 拼贴之一 | n/a | local |
| capability_view_clean.png | 755×712 | 1.06 | 展示能力画像的结构化输出 | Product screenshot | #50 Tiled grid with equal cells | no-crop | user | Existing | 真实前端素材；P10 拼贴之一 | n/a | local |
| winning_view_clean.png | 1265×712 | 1.78 | 展示动态蜂群和制胜机理结果视图 | Product screenshot | #50 Tiled grid with equal cells | no-crop | user | Existing | 真实前端素材；P10 宽幅证据截图 | n/a | local |
| frontend_query_generation_live.jpg | 1265×712 | 1.78 | 展示“围绕母题 / 自动态势”双模式及 Query 草稿库 | Product screenshot | #70 Image with thin colored matte frame | no-crop | user | Existing | 本次从真实工作台截取；P03、P12 使用 | n/a | local |
| frontend_s1_s6_live.jpg | 1265×712 | 1.78 | 展示真实任务的 S1–S6 输入包、共享资源与结果节点 | Product screenshot | #50 Tiled grid with equal cells | no-crop | user | Existing | 本次从真实工作台截取；P12 使用 | n/a | local |
| frontend_evidence_center_live.jpg | 1265×712 | 1.78 | 展示证据条目、来源地址、主张与 Agent 归属 | Product screenshot | #50 Tiled grid with equal cells | no-crop | user | Existing | 本次从真实工作台截取；P12 使用 | n/a | local |
| frontend_report_review_live.jpg | 1265×712 | 1.78 | 展示已完成任务的报告评审与阅读入口 | Product screenshot | #19 Image floating in whitespace with thin frame and caption | no-crop | user | Existing | 本次从真实工作台截取；P13 使用 | n/a | local |

## IX. Content Outline

### Part 1: 把研究入口变为可治理能力

#### Slide 01 - 从“能跑”到“可演示、可评测、可审计”

- **Audience move**: 从不确定项目是否只是原型 → 明确其已形成可演示、可评测、可审计的阶段闭环。
- **Layout**: 大面积留白中的超大“闭环”文字与三段式路径；右侧用深蓝几何平面承托三项能力标签。
- **Title**: 项目已进入可演示、可评测、可审计阶段
- **Core message**: AI Query、双策略蜂群、独立评审与可选报告已接入同一研究与交付链路。
- **Content**: 从任务入口到审计交付，关键能力已贯通：AI Query 自动生成形成可审核入口；质量集群以稳定约束快速探索；动态蜂群以候选账本、专家盲评和质量门收敛正式交付。
- **Visualization**: 三段闭环路径图。
- **Cover impact**: 用“可演示、可评测、可审计”三词构成排版海报。

#### Slide 02 - “需求 Query”的两种选题发现模式

- **Audience move**: 从“让模型一次吐几个标题” → 理解它是可不中断、可审核的异步选题发现服务；两种前端模式只是在定义问题边界的方式上不同。
- **Layout**: 左右并置两种选题模式，底部汇入同一条异步服务链，强调边界定义者与统一质量治理。
- **Title**: “需求 Query”不是标题生成器，而是异步运行的选题发现服务
- **Core message**: 围绕母题发散由用户定义课题边界；自动态势发散由系统定义领域边界、Agent 从公开态势和技术信号中挑选高价值切入点；二者共用联网校验、结构化生成、质量门和草稿审核发布。
- **Content**: 围绕母题发散：用户必填母题，可补预期角度、需求牵引、技术驱动和其他约束；系统从需求、技术、体系、颠覆与规模建设等视角拆解互不重复的子题，适合已有明确课题的系统展开。自动态势发散：无需用户母题，仅可选填领域、区域、技术或时间偏好；系统以装备需求自主发现母题为领域边界，发现能力缺口、技术机会、体系韧性、成本交换与工业化问题，适合前期机会扫描。共用链路为：异步任务→轻量联网校验→按 20 个覆盖槽位生成→质量/去重/来源校验→原子写入草稿库→人工审核发布→带入 Deep Research。联网来源仅为选题形成线索，不替代正式报告证据。
- **Visualization**: 两种问题边界定义方式汇入同一条异步选题服务链。

#### Slide 03 - Query 能力已进入工作台，可直接演示、可追溯、不中断

- **Audience move**: 从只听功能描述 → 看到真实前端入口及其背后的异步状态、结构化产物和可恢复治理闭环。
- **Layout**: 左侧用六步服务链讲清前端可观察的状态与后台动作；右侧保留完整工作台截图，底部以结构化结果和来源边界作证据说明。
- **Title**: 一次生成任务，经历联网校验、结构化生成与草稿审核，而非页面阻塞等待
- **Core message**: 前端只创建任务；独立 Query Worker 异步运行，用户离开页面不影响任务，失败可重试，只有整批通过校验才原子写入草稿库。
- **Content**: 调用 `POST /api/v1/query-library/generations` 创建任务后，页面显示排队、联网校验、Query 生成、保存中、完成或失败；独立 Worker 轮询领取任务。联网阶段约执行 3—5 个公开检索、最多保留 8 个实际访问的 HTTPS 来源，用户 URL 优先。系统按 20 个覆盖槽位生成 4/6/8/12/16/20 条 Query，单条执行质量、去重和来源校验；全部通过才原子写入草稿库。人工审核发布后回填 Deep Research，失败可由 `POST /generations/{generation_id}/retry` 重试。每条输出含 `query`、`coverage_slot`、`supplemental_information`、`generation_rationale` 和 `source_references`：标题保持简洁，研究边界、失效条件和预期装备输出写入补充信息。
- **Images**: frontend_query_generation_live.jpg

### Part 2: 一条 S1–S6 制胜机理链，两种执行策略

#### Slide 04 - 两种模式共享同一条 S1–S6 制胜机理链

- **Audience move**: 从把质量集群和动态蜂群理解为两套割裂系统 → 明确二者共享同一研究主链，仅在组织、孵化和恢复方式上不同。
- **Layout**: 一条从 S1 到 S6 的主干；上下以 Quality / Dynamic 两条策略带标注各自的执行风格。
- **Title**: 面对同一个难题，我们准备了两种“带队做研究”的办法
- **Core message**: 两种模式都沿着 S1–S6 把“看清问题—想出方案—拿证据核验—形成可交付结论”走完；区别只在于团队如何组织。
- **Content**: S1–S6 可以用大白话理解为：先看清对手和场景，再设计打法、寻找新机理和装备方向，核验证据与可行性，最后用验证方案把最有价值的方向组合成能力画像。质量集群像一支固定、经验成熟的专家小组，按既定节奏快速会诊；动态蜂群像项目遇到新疑点才临时请来的专项顾问，谁能补上关键短板就让谁加入。
- **Visualization**: S1–S6 统一主干与两条策略带。

#### Slide 05 - 质量集群：受控的专家小组并行评审

- **Audience move**: 从把质量集群理解为“简单多开 Agent” → 理解其是预算可控、可恢复、可审计的快速探索策略。
- **Layout**: 左侧为基线到 S6 能力画像的六步流程，右侧列出资源上限、恢复与候选保留规则。
- **Title**: 质量集群：先请一支固定专家小组，把方向摸得又快又稳
- **Core message**: 它把多人讨论装进可控的节奏里：先出几个方向，再分工补证据，最后只留下真正值得继续研究的少数方案。
- **Content**: 就像一次有章法的专家会诊：先有基线判断，再提出候选方向；检索、红队、架构、证据、成熟度和验证等角色分批补强；每一轮都有质量检查，不够有价值就不再加人。系统最多十二个实例、三波、六并发，每波保留检查点，遇到失败从断点恢复。这样避免“人越多、意见越乱”，快速收敛成二到四条较稳定的装备方向初稿。
- **Visualization**: 受控专家组的有界波次流程图。

#### Slide 06 - 动态蜂群：让 Mission Graph 按问题残差生长

- **Audience move**: 从将动态蜂群等同于“大规模并行” → 理解它是以残差触发、角色合同与候选账本治理的竞争收敛系统。
- **Layout**: 中央为会生长的 Mission Graph，左侧是 S1–S6 种子角色，右侧是残差触发、合并 / 拒绝 / 重基、盲评修复和 S6 组合收敛。
- **Title**: 动态蜂群：方案哪里卡住，就临时请哪一类专家来补关键一块
- **Core message**: 它不是一开始就把所有人叫来，而是让基础团队先做；只有发现关键缺口，才增加最需要的角色，并把每次补充都登记清楚。
- **Content**: 想象研究做到一半，发现证据不够、因果说不通、装备不够具体、对手会如何应对还没想清，或者缺少验证办法。系统才会临时请对应专项顾问加入，给清楚的任务和边界，做完就离场。每份新意见都必须写入候选账本，不能悄悄覆盖已有结论；要么合并、要么退回补充、要么要求按最新结论重做。动态蜂群因此更慢、更贵，但能把复杂课题的“漏项”逐项补上。
- **Visualization**: Mission Graph 生长与版本账本闭环图。

#### Slide 07 - Kimi K3 的借鉴是架构思想，项目的落地是受治理的动态孵化

- **Audience move**: 从误解为直接复刻外部产品 → 理解项目吸收的是“按任务状态临时生成最有价值能力”的架构思想，并完成了自身工程化约束。
- **Layout**: 左侧列出五个方法原则，右侧映射项目中的控制器、角色合同、隔离会话、版本账本、专家评审和有界回收。
- **Title**: 动态蜂群的灵感：不是“人海战术”，而是“问题出现才请对的人”
- **Core message**: 借鉴 Kimi K3 的核心不是照搬实现，而是把临时增援的权力交给统一调度，让每位新成员都对一个明确缺口负责。
- **Content**: 我们借鉴的原则很朴素：缺什么能力才补什么能力；新来的角色只做一件清楚的事；所有意见放到同一本账上比较；不要把相近方案硬凑平均分；谁能加入由总调度决定，而不是让子 Agent 自己扩招。项目把这些原则变成受治理的角色合同、隔离会话、版本账本、专家评审和任务完成后回收，实际执行模式是 `winning_swarm_dynamic_v2`。
- **Visualization**: 原则到工程实现的映射图。

#### Slide 08 - 真实运行对比：更快的初筛，与更强的正式收敛

- **Audience move**: 从只比较“谁更快” → 能按正式交付所需的质量、证据和审计状态选择策略。
- **Layout**: 左右两列策略卡，中间为取舍箭头，底部为同 Query 的真实运行指标。
- **Title**: 怎么选？先要方向选质量集群；要拿正式结论选动态蜂群
- **Core message**: 质量集群用更短时间帮我们把方向摸清；动态蜂群多花时间把漏项补齐、把相近方案拉开、把正式结论守住。
- **Content**: 同一 Query 的真实运行中，质量集群约十分钟完成十六次调用，快速得到六项画像，但审计状态仍是 limited；动态蜂群约三十一分钟、三十四次调用，最终达到百分之百来源绑定、L1 到 L3 通过和 approved。动态模式慢的原因不是无谓加人，而是增加了候选账本、独立评审和定向修复。结论很直接：前者适合快速筛方向，后者适合对外承担正式装备需求论证。
- **Visualization**: 数据驱动的对比矩阵。
- **Native-ready**: no

#### Slide 09 - 质量门与专家盲评，使“能生成”不等于“可发布”

- **Audience move**: 从认为多 Agent 天然保证质量 → 理解正式发布依赖明确的交付硬门、独立判断和定向修复。
- **Layout**: 上半为候选—账本—盲评—修复—S6 发布路径，下半为八维专家评审、阈值及 warning 升级为 hard gate 的对照。
- **Title**: 质量怎么提升？不让“看起来像答案”的方案直接变成结论
- **Core message**: 系统给每个候选安排独立复核：先看是否说得通、落得下、站得住，再决定通过、补一补还是挡在发布门外。
- **Content**: 评审专家不参与原始讨论，只看候选和有效证据，因此能更客观地发现问题。它会检查领域是否契合、装备是否具体、军事价值是否成立、因果是否连贯、证据是否可信以及工程上是否可行；综合分和关键项达标才放行。真实修复中，我们已经把“标题看起来很多、内容却重复”和“装备不够具体”从提示升级为硬门，因此质量不是靠最后一句承诺，而是靠每一步都能拦住不合格方案。
- **Visualization**: 质量门与专家评审的一体化流程图。

### Part 3: 前端交付、配置能力与下一步

#### Slide 10 - 前端工作台让研究过程与能力结果都可被直接看见

- **Audience move**: 从关注后台实现 → 确认项目方能在真实工作台直接看见任务过程与能力画像，而非只看到最终报告。
- **Layout**: 两张大尺寸真实截图并置，分别承载“过程可感知”和“能力可解释”；底部给出演示顺序。
- **Title**: 前端不只展示结果，也让研究过程和能力画像可被直接看见
- **Core message**: 实时交互与事件记录回答“研究怎么推进”，能力画像与卡片回答“研究得到了什么”。
- **Content**: 左侧真实工作台展示任务在执行过程中的实时交互与事件；右侧真实工作台展示形成后的能力画像与结构化卡片。项目方可从同一任务入口依次下钻过程、证据组织和能力结果；截图保持原始内容与比例。
- **Images**: interaction_view_clean.png, capability_view_clean.png

#### Slide 11 - 制胜结果也进入工作台，支持从结论回看机制与门控状态

- **Audience move**: 从只看到抽象“蜂群能力” → 看到制胜机理、候选结果与门控状态已经沉淀为可审阅的前端结果视图。
- **Layout**: 宽幅真实结果截图作为主视觉，右侧以三条演示提示说明看什么、怎么下钻、如何用于评审。
- **Title**: 不把结论藏在后台：制胜机理、结果与门控状态都进入工作台
- **Core message**: 前端把动态研究的最终结果转成项目方可浏览、可复核、可用于评审沟通的结果视图。
- **Content**: 真实结果页面集中呈现制胜机理与任务门控状态。现场可先从结果总览理解形成的装备方向，再回看相应 S 节点和过程信息；这使项目方获得的不只是一个结论，而是能够跟随研究过程检查结论如何形成的可视化入口。
- **Images**: winning_view_clean.png

#### Slide 12 - 真实前端闭环（中段）：从 S1–S6 推演到证据中心，过程可以逐层下钻

- **Audience move**: 从“只知道 Agent 在后台运行” → 看到任务、输入包、节点结果、支撑证据均有对应前端入口，过程可直接检视。
- **Layout**: 两张实时工作台截图左右并列；上方给出一条从推演到证据的阅读路径，底部说明同一任务在页面间保持上下文。
- **Title**: 从 S1–S6 推演到证据中心，研究过程在前端可逐层下钻
- **Core message**: 系统不是只展示最终结论，而是将 S1–S6 输入包、共享资源、Agent 结果节点，以及主张—来源—创建 Agent 等证据要素，放进同一任务视图中。
- **Content**: 左图来自真实 S1–S6 Agent 页面：可看到当前任务、研究路线、输入 Packet、证据索引、共享受控资源与六个专用 Agent 结果。右图来自同一任务的证据中心：每项证据保留支撑主张、创建 Agent、evidence ID、来源位置、质量评估和来源地址。项目方可沿“机制推演 → 证据核验”连续下钻，而不依赖口头说明。
- **Images**: frontend_s1_s6_live.jpg, frontend_evidence_center_live.jpg

#### Slide 13 - 真实前端闭环（交付）：从已完成任务进入报告评审，形成可阅读、可沟通的交付入口

- **Audience move**: 从“报告只是一份离线文件” → 看到已完成任务、任务状态与研究报告已在前端形成统一的交付与评审入口。
- **Layout**: 宽幅报告评审截图为主视觉，右侧给出从任务选择、报告阅读到复核下钻的三步交付说明。
- **Title**: 研究完成后，报告评审也在工作台中承接：从任务到交付不断线
- **Core message**: 项目把任务选择、完成状态、报告阅读与其它过程视图连在一起，使交付既可阅读，也可回到过程与证据复核。
- **Content**: 真实报告评审页面中，左侧保留已完成任务列表，右侧直接展示当前任务的研究报告；同一任务可随时切换至交互过程、证据中心、S1–S6 Agent 与能力画像。这样项目方获得的是“可读报告 + 可回看过程”的闭环交付，而不是脱离生成过程的一次性文档。
- **Images**: frontend_report_review_live.jpg

#### Slide 14 - 多运行模式与多报告模板，让不同任务选择合适的研究强度与交付形态

- **Audience move**: 从把系统理解为单一运行链路 → 理解项目已将研究强度和报告产物设计成可选择、可追溯的配置。
- **Layout**: 上半为四种执行 Profile 的选择带，下半为两种报告模板，中部以“任务配置 → 运行快照 → 可审计报告”连接。
- **Title**: 研究策略和报告表达均可配置，避免用同一种成本处理所有任务
- **Core message**: 项目支持传统固定编排、协同优化、质量集群和 Mission Graph 动态蜂群四类运行 Profile，并可选项目论证五章或三层九项报告模板。
- **Content**: `legacy_v1` 用于兼容回滚和对照；`optimized_v2` 用于普通任务；`swarm_quality_v1` 用于快速质量残差探索；`winning_swarm_dynamic_v2` 用于复杂正式论证。`project_argument_v1` 交付需求分析、项目画像、总体方案、关键技术、研制基础；`three_layer_nine_item` 交付需求挖掘、技术攻关、能力图像、效能贡献。配置随任务与运行快照保存。
- **Visualization**: Profile 选择—报告模板选择—可审计交付配置图。

#### Slide 15 - 下一阶段：质量不降级，效率可优化

- **Audience move**: 从看到已完成内容 → 与项目团队对齐后续优化的优先级与验收方向。
- **Layout**: 左右两条优化轨道汇入“质量不降级，效率可优化”。
- **Title**: 下一步：在不牺牲质量硬门的前提下，提升证据可信度与运行效率
- **Core message**: 保留“Quality 快速探索 + Dynamic 正式收敛”双策略，继续推进引用审计、候选去重与动态编排提速。
- **Content**: 证据可信度：增强 Claim—来源直接对应、正文可核查呈现、时效校验、冲突证据处理与专家复核。运行效率：减少同族重复候选、提前按装备族与验收变量去重、优化动态 Agent 编排。下一轮验收观察来源绑定、交付硬门、运行时长与前端闭环演示。
- **Visualization**: 双轨路线图。
- **Closing impact**: 以“质量不降级，效率可优化”为唯一离场信息。

## X. Speaker Notes Requirements

- **Filename**: match each SVG filename under `notes/`
- **Content**: 每页以结论开场，补充来源口径、转场和现场演示提示；真实对比数字说明其来自 2026-08-05 同 Query 运行记录，不外推为一般性能承诺。
- **Total duration**: 20 minutes
- **Notes style**: formal
- **Presentation purpose**: report, explain, align
